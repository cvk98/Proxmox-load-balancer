#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Proxmox-load-balancer v0.6.4-betta Copyright (C) 2022 cvk98 (github.com/cvk98)

import sys
import requests
import urllib3
import yaml
import smtplib
import socket
from email.message import EmailMessage
from time import time
from time import sleep
from itertools import permutations
from copy import deepcopy
from loguru import logger
from collections import defaultdict

try:
    with open("config.yaml", "r", encoding='utf8') as yaml_file:
        cfg = yaml.safe_load(yaml_file)
except Exception as e:
    print(f'Error opening the configuration file: {e}')
    sys.exit(1)

"""Proxmox"""
server_url = f'https://{cfg["proxmox"]["url"]["ip"]}:{cfg["proxmox"]["url"]["port"]}'
auth = dict(cfg["proxmox"]["auth"])

"""Parameters"""
MEM_CONFIG_DEVIATION = MCD = cfg["parameters"]["mem_deviation"] / 100
THRESHOLD = cfg["parameters"]["threshold"] / 100
CPU_CONFIG_DEVIATION = CCD = cfg["parameters"]["cpu_deviation"] / 100
CPU_CONFIG_DEVIATION_DURATION_SECONDS = cfg["parameters"]["cpu_deviation_duration_seconds"]
LXC_MIGRATION = cfg["parameters"]["lxc_migration"]
MIGRATION_TIMEOUT = cfg["parameters"]["migration_timeout"]
ONLY_ON_MASTER = cfg["parameters"].get("only_on_master", False)

"""Exclusions"""
excluded_vms = []

for x in tuple(cfg["exclusions"]["vms"]):
    if isinstance(x, int):
        excluded_vms.append(x)
    elif "-" in x:
        r = tuple(x.split("-"))
        excluded_vms.extend(range(int(r[0]), int(r[1]) + 1))
    else:
        excluded_vms.append(int(x))

excluded_nodes = tuple(cfg["exclusions"]["nodes"])


"""Mail"""
send_on = cfg["mail"]["sending"]

"""Loguru"""
logger.remove()
# For Linux service
logger.add(sys.stdout, format="{level} | {message}", level=cfg["logging_level"])

# For Windows and linux window mode (you can change sys.stdout to "file.log")
# logger.add(sys.stdout,
#            colorize=True,
#            format="<green>{time:YYYY-MM-DD at HH:mm:ss}</green> | "
#                   "<level>{level}</level> | "
#                   "<level>{message}</level>",
#            level=cfg["logging_level"])

"""Constants"""
GB = cfg["Gigabyte"]
TB = cfg["Terabyte"]

logger.info("START ***Load-balancer!***")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

"""Globals"""
payload = dict()  # PVEAuthCookie
header = dict()  # CSRFPreventionToken
mem_sum_of_deviations: float = 0
cpu_sum_of_deviations: float = 0
cpu_sliding_windows = defaultdict(lambda: None)


class Cluster:
    def __init__(self, server: str):
        logger.debug("init when creating a Cluster object")
        """Cluster"""
        self.server: str = server
        self.cl_name = self.cluster_name()
        self.master_node: str = ""
        self.quorate: bool = False
        """VMs and nodes"""
        self.cl_nodes: int = 0                      # The number of nodes. Calculated in Cluster.cluster_name
        self.cluster_information = {}               # Retrieved in Cluster.cluster_items
        self.cluster_items()
        self.included_nodes = {}                    # Balanced nodes
        self.cl_nodes: dict = self.cluster_hosts()  # All cluster nodes
        self.cl_lxcs = set()                        # Defined in Cluster.self.cluster_vms
        self.cl_vms_included: dict = {}             # All VMs and LXC are running in a balanced cluster
        self.cl_vms: dict = self.cluster_vms()      # All VMs and Lxc are running in the cluster
        """RAM"""
        self.cl_mem_included: int = 0               # Cluster memory used in bytes for balanced nodes
        self.cl_mem: int = 0                        # Cluster memory used in bytes
        self.cl_max_mem_included: int = 0           # Total cluster memory in bytes for balanced nodes
        self.mem_load: float = 0                    # Loading the cluster RAM in %
        self.mem_load_included: float = 0           # Loading RAM, the balanced part of the cluster in %
        self.cl_max_mem: int = self.cluster_mem()   # Total cluster memory in bytes
        """CPU"""
        self.cl_cpu_load: float = 0                 # Total load of cluster processors from 0 to 1
        self.cl_cpu_load_include: float = 0         # Total load of cluster processors for balanced nodes from 0 to 1
        self.cl_cpu_included: int = 0               # Total cores in a cluster for balanced nodes
        self.cl_cpu = self.cluster_cpu()            # Total cores in the cluster
        """Others"""
        self.cluster_information = []
        # self.show()

    def cluster_name(self):
        """Getting the cluster name and the number of nodes in it"""
        logger.debug("Starting Cluster.cluster_name")
        name: str = ""
        url = f'{self.server}/api2/json/cluster/status'
        name_request = nr = requests.get(url, cookies=payload, verify=False)
        if name_request.ok:
            logger.debug(f'Information about the cluster name has been received. Response code: {nr.status_code}')
        else:
            logger.warning(f'Execution error {Cluster.cluster_name.__qualname__}')
            logger.warning(f'Could not get information about the cluster. Response code: {nr.status_code}. Reason: ({nr.reason})')
            sys.exit(0)
        temp = name_request.json()["data"]
        del name_request, nr
        for i in temp:
            if i["type"] == "cluster":
                name = i["name"]
                self.cl_nodes = i["nodes"]
        return name

    def cluster_items(self):
        """Collecting preliminary information about the cluster"""
        logger.debug("Launching Cluster.cluster_items")
        url = f'{self.server}/api2/json/cluster/resources'
        logger.debug('Attempt to get information about the cluster...')
        resources_request = rr = requests.get(url, cookies=payload, verify=False)
        if resources_request.ok:
            logger.debug(f'Information about the cluster has been received. Response code: {rr.status_code}')
        else:
            logger.warning(f'Execution error {Cluster.cluster_items.__qualname__}')
            logger.warning(f'Could not get information about the cluster. Response code: {rr.status_code}. Reason: ({rr.reason})')
            sys.exit(0)
        self.cluster_information = rr.json()['data']
        del resources_request, rr

    def cluster_hosts(self):
        """Getting nodes from cluster resources"""
        logger.debug("Launching Cluster.cluster_hosts")
        nodes_dict = {}

        # Find out which node is the current cluster master
        url = f'{self.server}/api2/json/cluster/ha/status/manager_status'
        logger.debug('Attempt to get information about the cluster HA manager...')
        resources_request = rr = requests.get(url, cookies=payload, verify=False)
        if resources_request.ok:
            logger.debug(f'Information about the cluster HA Manager has been received. Response code: {rr.status_code}')
        else:
            logger.warning(f'Execution error {Cluster.cluster_items.__qualname__}')
            logger.warning(
                f'Could not get information about the HA cluster manager. Response code: {rr.status_code}. Reason: ({rr.reason})')
            sys.exit(0)

        self.master_node = rr.json()['data']['manager_status']['master_node']
        self.quorate = (rr.json()['data']['quorum']['quorate'] == "1")
        if not self.quorate:
            # This is probably an error condition that should cause a "try again later"
            logger.warning(f'Quorum is currently not quorate!')

        temp = deepcopy(self.cluster_information)
        for item in temp:
            if item["type"] == "node":
                self.cluster_information.remove(item)
                if item["status"] != "online":                              # Ignore nodes that are not online
                    continue
                item["cpu_used"] = round(item["maxcpu"] * item["cpu"], 2)   # Adding the value of the cores used
                item["free_mem"] = item["maxmem"] - item["mem"]             # Adding the value of free RAM
                item["mem_load"] = item["mem"] / item["maxmem"]             # Adding the RAM load value
                item["is_master"] = (item["node"] == self.master_node)      # Flagging the current master node
                nodes_dict[item["node"]] = item

                if item["node"] not in excluded_nodes:
                    self.included_nodes[item["node"]] = item
        del temp
        return nodes_dict

    def cluster_vms(self):
        """Getting VM/Lxc from cluster resources"""
        logger.debug("Launching Cluster.cluster_vms")
        vms_dict = {}
        temp = deepcopy(self.cluster_information)
        for item in temp:
            if item["type"] == "qemu" and item["status"] == "running":
                vms_dict[item["vmid"]] = item
                if item["node"] not in excluded_nodes and item["vmid"] not in excluded_vms:
                    self.cl_vms_included[item["vmid"]] = item
                self.cluster_information.remove(item)
            elif item["type"] == "lxc" and item["status"] == "running":
                vms_dict[item["vmid"]] = item
                self.cl_lxcs.add(item["vmid"])
                if item["node"] not in excluded_nodes and item["vmid"] not in excluded_vms:
                    self.cl_vms_included[item["vmid"]] = item
                self.cluster_information.remove(item)
        del temp
        return vms_dict

    def cluster_mem(self):
        """Calculating RAM usage from cluster resources"""
        logger.debug("Launching Cluster.cluster_membership")
        cl_max_mem = 0
        cl_used_mem = 0
        for node, sources in self.cl_nodes.items():
            if sources["node"] not in excluded_nodes:
                self.cl_max_mem_included += sources["maxmem"]
                self.cl_mem_included += sources["mem"]
            else:
                cl_max_mem += sources["maxmem"]
                cl_used_mem += sources["mem"]
        cl_max_mem += self.cl_max_mem_included
        cl_used_mem += self.cl_mem_included
        self.cl_mem = cl_used_mem + self.cl_mem_included
        self.mem_load = cl_used_mem / cl_max_mem
        self.mem_load_included = self.cl_mem_included / self.cl_max_mem_included
        return cl_max_mem

    def cluster_cpu(self):
        """Calculating CPU usage from cluster resources"""
        logger.debug("Launching Cluster.cluster_cpu")
        cl_cpu_used: float = 0
        cl_cpu_used_included: float = 0
        cl_max_cpu: int = 0
        for host, sources in self.cl_nodes.items():
            if sources["node"] not in excluded_nodes:
                self.cl_cpu_included += sources["maxcpu"]
                cl_cpu_used_included += sources["cpu_used"]
            else:
                cl_max_cpu += sources["maxcpu"]
                cl_cpu_used += sources["cpu_used"]
        cl_max_cpu += self.cl_cpu_included
        cl_cpu_used += cl_cpu_used_included
        self.cl_cpu_load = cl_cpu_used / cl_max_cpu
        self.cl_cpu_load_include = cl_cpu_used_included / self.cl_cpu_included
        return cl_max_cpu

    def show(self):
        """Cluster summary"""
        logger.debug("Launching Cluster.show")
        print(f'Server address: {self.server}')
        print(f'Cluster name: {self.cl_name}')
        print(f'Number of nodes: {len(self.cl_nodes)}')
        print(f'Number of balanced nodes: {len(self.cl_nodes) - len(excluded_nodes)}')
        print(f'Number of VMs: {len(self.cl_vms)}')
        print(f'Number of VMs being balanced: {len(self.cl_vms_included)}')
        print(f'Shared cluster RAM: {round(self.cl_max_mem / TB, 2)} TB. Loading {round((self.mem_load * 100), 2)}%')
        print(f'RAM of the balanced part of the cluster: {round(self.cl_max_mem_included / TB, 2)} TB. Loading {round((self.mem_load_included * 100), 2)}%')
        print(f'Number of CPU cores in the cluster: {self.cl_cpu}, loading {round((self.cl_cpu_load * 100), 2)}%')
        print(f'The number of cores of the balanced part of the cluster: {self.cl_cpu_included}, loading {round((self.cl_cpu_load_include * 100), 2)}%')


def authentication(server: str, data: dict):
    """Authentication and receipt of a token and ticket."""
    global payload, header
    url = f'{server}/api2/json/access/ticket'
    logger.debug('Authorization attempt...')
    try:
        get_token = requests.post(url, data=data, verify=False)
    except Exception as exc:
        message = f'Incorrect server address or port settings: {exc}'
        logger.exception(message)
        send_mail(f'Proxmox node ({server_url}) is unavailable. Network or settings problem')
        sys.exit(1)
    if get_token.ok:
        logger.debug(f'Successful authentication. Response code: {get_token.status_code}')
    else:
        logger.debug(f'Execution error {authentication.__qualname__}')
        logger.error(f'Authentication failed. Response code: {get_token.status_code}. Reason: {get_token.reason}')
        sys.exit(1)
    payload = {'PVEAuthCookie': (get_token.json()['data']['ticket'])}
    header = {'CSRFPreventionToken': (get_token.json()['data']['CSRFPreventionToken'])}


def cluster_load_verification(mem_load: float, cluster_obj: Cluster) -> None:
    """Checking the RAM load of the balanced part of the cluster"""
    logger.debug("Starting cluster_load_verification")
    if len(cluster_obj.cl_nodes) - len(excluded_nodes) == 1:
        logger.error('It is impossible to balance one node!')
        sys.exit(1)
    assert 0 < mem_load < 1, 'The cluster RAM load should be in the range from 0 to 1'
    if mem_load >= THRESHOLD:
        logger.warning(f'Cluster RAM usage is too high {(round(cluster_obj.mem_load * 100, 2))}')
        logger.warning('It is not possible to safely balance the cluster')
        sys.exit(1)


def calculate_sum_of_deviations(cluster_obj: Cluster) -> None:
    """Calculation of the sum of deviations for RAM and CPU"""
    logger.debug("Starting calculate_sum_of_deviations")
    global mem_sum_of_deviations, cpu_sum_of_deviations
    nodes = cluster_obj.included_nodes
    mem_average = cluster_obj.mem_load_included
    cpu_average = cluster_obj.cl_cpu_load_include
    for host, values in nodes.items():
        values["mem_deviation"] = abs(values["mem_load"] - mem_average)
    for host, values in nodes.items():
        values["cpu_deviation"] = abs(values["cpu"] - cpu_average)
    mem_sum_of_deviations = sum(values["mem_deviation"] for values in nodes.values())
    cpu_sum_of_deviations = sum(values["cpu_deviation"] for values in nodes.values())


def need_to_balance_mem_checking(cluster_obj: Cluster) -> bool:
    """Checking the RAM load of the balanced part of the cluster"""
    logger.debug("Starting cluster_load_verification")
    nodes = cluster_obj.included_nodes
    for values in nodes.values():
        if values["mem_deviation"] > MEM_CONFIG_DEVIATION:
            return True
    else:
        return False


def need_to_balance_cpu_checking(cluster_obj: Cluster) -> bool:
    """Checking the need for balancing about CPU"""
    logger.debug("Starting need_to_balance_cpu_checking")
    nodes = cluster_obj.included_nodes
    cpu_average = cluster_obj.cl_cpu_load_include
    for host, values in nodes.items():
        if values["cpu_deviation"] > CPU_CONFIG_DEVIATION:
            sign = values["cpu"] > cpu_average
            if cpu_sliding_windows[host] is None:
                cpu_sliding_windows[host] = (time(), sign)
            elif cpu_sliding_windows[host][1] != sign:
                cpu_sliding_windows[host] = (time(), sign)
            elif time() - cpu_sliding_windows[host][0] > CPU_CONFIG_DEVIATION_DURATION_SECONDS:
                return True
        else:
            cpu_sliding_windows[host] = None
    else:
        return False


def temporary_dict(cluster_obj: Cluster) -> object:
    """Preparation of information for subsequent processing"""
    logger.debug("Running temporary_dict")
    obj = {}
    vm_dict = cluster_obj.cl_vms_included
    if not LXC_MIGRATION:
        for lxc in cluster_obj.cl_lxcs:
            del vm_dict[lxc]
    for host in cluster_obj.included_nodes:
        hosts = {}
        for vm, value in vm_dict.items():
            if value["node"] == host:
                hosts[vm] = value
        obj[host] = hosts
    return obj


def calculating(hosts: object, cluster_obj: Cluster) -> list:
    """The function of selecting the optimal VM migration options for the cluster balance"""
    logger.debug("Starting calculating")
    variants: list = []
    nodes = cluster_obj.included_nodes
    mem_average = cluster_obj.mem_load_included
    cpu_average = cluster_obj.cl_cpu_load_include
    for host in permutations(nodes, 2):
        cpu_part_of_deviation = sum(values["cpu_deviation"] if node not in host else 0 for node, values in nodes.items())
        mem_part_of_deviation = sum(values["mem_deviation"] if node not in host else 0 for node, values in nodes.items())
        for vm in hosts[host[0]].values():
            h0_mem_load = (nodes[host[0]]["mem"] - vm["mem"]) / nodes[host[0]]["maxmem"]
            h0_mem_deviation = h0_mem_load - mem_average if h0_mem_load > mem_average else mem_average - h0_mem_load
            h1_mem_load = (nodes[host[1]]["mem"] + vm["mem"]) / nodes[host[1]]["maxmem"]
            h1_mem_deviation = h1_mem_load - mem_average if h1_mem_load > mem_average else mem_average - h1_mem_load
            mem_temp_full_deviation = mem_part_of_deviation + h0_mem_deviation + h1_mem_deviation
            vm["cpu_used"] = round(vm["maxcpu"] * vm["cpu"], 2)
            h0_cpu_load = (nodes[host[0]]["cpu_used"] - vm["cpu_used"]) / nodes[host[0]]["maxcpu"]
            h0_cpu_deviation = h0_cpu_load - cpu_average if h0_cpu_load > cpu_average else cpu_average - h0_cpu_load
            h1_cpu_load = (nodes[host[1]]["cpu_used"] + vm["cpu_used"]) / nodes[host[1]]["maxcpu"]
            h1_cpu_deviation = h1_cpu_load - cpu_average if h1_cpu_load > cpu_average else cpu_average - h1_cpu_load
            cpu_temp_full_deviation = cpu_part_of_deviation + h0_cpu_deviation + h1_cpu_deviation
            if mem_temp_full_deviation < mem_sum_of_deviations and cpu_temp_full_deviation < cpu_sum_of_deviations:
                score = mem_temp_full_deviation / mem_sum_of_deviations
                score += cpu_temp_full_deviation / cpu_sum_of_deviations
                variant = (host[0], host[1], vm["vmid"], score)
                variants.append(variant)
    logger.info(f'Number of options = {len(variants)}')
    return sorted(variants, key=lambda last: last[-1])


def vm_migration(variants: list, cluster_obj: object) -> None:
    """VM migration function from the suggested variants"""
    logger.debug("Starting vm_migration")
    local_disk = None
    local_resources = None
    clo = cluster_obj
    error_counter = 0
    problems: list = []
    for variant in variants:
        if error_counter > 2:
            logger.exception(f'The number of migration errors has reached {error_counter} pieces.')
            send_mail(f'Problems occurred during VM:{problems} migration. Check the VM status')
            sys.exit(1)
        donor, recipient, vm = variant[:3]
        logger.debug(f'VM:{vm} migration from {donor} to {recipient}')
        if vm in cluster_obj.cl_lxcs:
            options = {'target': recipient, 'restart': 1}
            url = f'{cluster_obj.server}/api2/json/nodes/{donor}/lxc/{vm}/migrate'
        else:
            options = {'target': recipient, 'online': 1}
            url = f'{cluster_obj.server}/api2/json/nodes/{donor}/qemu/{vm}/migrate'
            check_request = requests.get(url, cookies=payload, verify=False)
            local_disk = (check_request.json()['data']['local_disks'])
            local_resources = (check_request.json()['data']['local_resources'])
        if local_disk or local_resources:
            logger.debug(f'The VM:{vm} has {local_disk if local_disk else local_resources if local_resources else ""}')
            # local_disk & Local_resource need to be reset after the check (if we start with a unmovable VM, the rest are never tested)
            local_disk = None
            local_resources = None
            continue  # for variant in variants:
        else:
            # request migration
            job = requests.post(url, cookies=payload, headers=header, data=options, verify=False)
            if job.ok:
                logger.info(f'Migration VM:{vm} ({round(clo.cl_vms[vm]["mem"] / GB, 2)} GB mem) from {donor} to {recipient}...')
                pid = job.json()['data']
                error_counter -= 1
            else:
                logger.warning(f'Error when requesting migration VM {vm} from {donor} to {recipient}. Check the request.')
                error_counter += 1
                problems.append(vm)
                continue  # for variant in variants:
            status = True
            timer: int = 0
            while status: # confirm the migration is done
                timer += 10
                sleep(10)
                if vm in cluster_obj.cl_lxcs:
                    url = f'{cluster_obj.server}/api2/json/nodes/{recipient}/lxc'
                else:
                    url = f'{cluster_obj.server}/api2/json/nodes/{recipient}/qemu'
                request = requests.get(url, cookies=payload, verify=False)
                recipient_vms = request.json()['data']
                for _ in recipient_vms:
                    if int(_['vmid']) == vm and _['status'] == 'running':
                        logger.info(f'{pid} - Completed!')
                        sleep(10)
                        if vm in cluster_obj.cl_vms:
                            url = f'{cluster_obj.server}/api2/json/nodes/{recipient}/qemu/{vm}/status/resume'
                            request = requests.post(url, cookies=payload, headers=header, verify=False)
                            logger.debug(f'Resuming {vm} after {pid}: {request.ok}')
                        status = False
                        break  # for _ in recipient_vms:
                    elif _['vmid'] == vm and _['status'] != 'running':
                        send_mail(f'Problems occurred during VM:{vm} migration. Check the VM status')
                        logger.exception(f'Something went wrong during the migration. Response code{request.status_code}')
                        sys.exit(1)
                    else:
                        logger.info(f'VM Migration: {vm}... {timer} sec.')
            break  # for variant in variants:


def send_mail(message: str):
    if send_on:
        logger.debug("Starting send_mail")
        email_content = message
        msg = EmailMessage()
        msg.set_payload(email_content)
        msg['Subject'] = cfg["mail"]["message_subject"]
        msg['From'] = cfg["mail"]["from"]
        msg['To'] = cfg["mail"]["to"]
        login: str = cfg["mail"]["login"]
        password: str = cfg["mail"]["password"]
        s = smtplib.SMTP(f'{cfg["mail"]["server"]["address"]}:{cfg["mail"]["server"]["port"]}')
        encryption = cfg["mail"]["ssl_tls"]
        if encryption:
            s.starttls()
        try:
            s.login(login, password)
            s.sendmail(msg['From'], [msg['To']], msg.as_string())
            logger.trace('Notification sent')
        except Exception as exc:
            logger.debug(f'Problem when sending an email: {exc}')
            logger.exception(f'The message has not been sent. Check the SMTP settings')
        finally:
            s.quit()
    else:
        pass


def main():
    """The main body of the program"""
    authentication(server_url, auth)
    cluster = Cluster(server_url)
    if ONLY_ON_MASTER:
        hostname = socket.gethostname()
        master = cluster.master_node
        if hostname != master:
            logger.info(
                f'This server ({hostname}) is not the current cluster master, {master} is. Waiting 300 seconds.')
            sleep(300)
            return
    cluster_load_verification(cluster.mem_load_included, cluster)
    calculate_sum_of_deviations(cluster)
    need_to_balance_cpu = need_to_balance_cpu_checking(cluster)
    need_to_balance_mem = need_to_balance_mem_checking(cluster)
    logger.info(f'Need to balance (CPU): {need_to_balance_cpu}')
    logger.info(f'Need to balance (MEM): {need_to_balance_mem}')
    if need_to_balance_cpu or need_to_balance_mem:
        balance_cl = temporary_dict(cluster)
        sorted_variants = calculating(balance_cl, cluster)
        if sorted_variants:
            vm_migration(sorted_variants, cluster)
            logger.info('Waiting 10 seconds for cluster information update')
            sleep(10)
        else:
            sleep(60)
            pass  # TODO Aggressive algorithm
    else:
        logger.info('The cluster is balanced. Waiting 300 seconds.')
        sleep(300)


while True:
    main()
