#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Proxmox-load-balancer v0.4.2-betta Copyright (C) 2022 cvk98 (github.com/cvk98)

import sys
import requests
import urllib3
import yaml
from time import sleep
from itertools import permutations
from copy import deepcopy
from loguru import logger

try:
    with open("config.yaml", "r", encoding='utf8') as yaml_file:
        cfg = yaml.safe_load(yaml_file)
except Exception as e:
    logger.exception(f'Error opening the configuration file: {e}')
    sys.exit(1)  # TODO Add mail sending

"""Proxmox"""
server_url = f'https://{cfg["proxmox"]["url"]["ip"]}:{cfg["proxmox"]["url"]["port"]}'
auth = dict(cfg["proxmox"]["auth"])

"""Parameters"""
DEVIATION = cfg["parameters"]["deviation"] / 200
THRESHOLD = cfg["parameters"]["threshold"] / 100
LXC_MIGRATION = cfg["parameters"]["lxc_migration"]
MIGRATION_TIMEOUT = cfg["parameters"]["migration_timeout"]

"""Exclusions"""
excluded_vms = tuple(cfg["exclusions"]["vms"])
excluded_nodes = tuple(cfg["exclusions"]["nodes"])


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

GB = cfg["Gigabyte"]
TB = cfg["Terabyte"]

logger.info("START ***Load-balancer!***")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

payload = dict()  # PVEAuthCookie
header = dict()  # CSRFPreventionToken
sum_of_deviations: float = 0


class Cluster:
    def __init__(self, server: str):
        logger.debug("init when creating a Cluster object")
        """Cluster"""
        self.server: str = server
        self.cl_name = self.cluster_name()
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
        temp = deepcopy(self.cluster_information)
        for item in temp:
            if item["type"] == "node":
                self.cluster_information.remove(item)
                item["cpu_used"] = round(item["maxcpu"] * item["cpu"], 2)   # Adding the value of the cores used
                item["free_mem"] = item["maxmem"] - item["mem"]             # Adding the value of free RAM
                item["mem_load"] = item["mem"] / item["maxmem"]             # Adding the RAM load value
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
    except Exception as e:
        logger.exception(f'Incorrect server address or port settings: {e}')
        sys.exit(1)  # TODO Add mail sending
    if get_token.ok:
        logger.debug(f'Successful authentication. Response code: {get_token.status_code}')
    else:
        logger.debug(f'Execution error {authentication.__qualname__}')
        logger.error(f'Authentication failed. Response code: {get_token.status_code}. Reason: {get_token.reason}')
        sys.exit(1)
    payload = {'PVEAuthCookie': (get_token.json()['data']['ticket'])}
    header = {'CSRFPreventionToken': (get_token.json()['data']['CSRFPreventionToken'])}


def cluster_load_verification(mem_load: float, cluster_obj: object) -> None:
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


def need_to_balance_checking(cluster_obj: object) -> bool:
    """Checking the need for balancing"""
    logger.debug("Starting need_to_balance_checking")
    global sum_of_deviations
    nodes = cluster_obj.included_nodes
    average = cluster_obj.mem_load_included
    for host, values in nodes.items():
        values["deviation"] = abs(values["mem_load"] - average)
    sum_of_deviations = sum(values["deviation"] for values in nodes.values())
    for values in nodes.values():
        if values["deviation"] > DEVIATION:
            return True
    else:
        return False


# TODO Переписать
def temporary_dict(cluster_obj: object) -> object:
    """Preparation of information for subsequent processing"""
    logger.debug("Running temporary_dict")
    obj = {}
    vm_dict = cluster_obj.cl_vms_included
    if LXC_MIGRATION != "ON" or "on":
        for lxc in cluster_obj.cl_lxcs:
            del vm_dict[lxc]
    for host in cluster_obj.included_nodes:
        hosts = {}
        for vm, value in vm_dict.items():
            if value["node"] == host:
                hosts[vm] = value
        obj[host] = hosts
    return obj


def calculating(hosts: object, cluster_obj: object) -> list:
    """The function of selecting the optimal VM migration options for the cluster balance"""
    logger.debug("Starting calculating")
    count = 0
    variants: list = []
    nodes = cluster_obj.included_nodes
    average = cluster_obj.mem_load_included
    for host in permutations(nodes, 2):
        part_of_deviation = sum(values["deviation"] if node not in host else 0 for node, values in nodes.items())
        for vm in hosts[host[0]].values():
            h0_mem_load = (nodes[host[0]]["mem"] - vm["mem"]) / nodes[host[0]]["maxmem"]
            h0_deviation = h0_mem_load - average if h0_mem_load > average else average - h0_mem_load
            h1_mem_load = (nodes[host[1]]["mem"] + vm["mem"]) / nodes[host[1]]["maxmem"]
            h1_deviation = h1_mem_load - average if h1_mem_load > average else average - h1_mem_load
            temp_full_deviation = part_of_deviation + h0_deviation + h1_deviation
            if temp_full_deviation < sum_of_deviations:
                variant = (host[0], host[1], vm["vmid"], temp_full_deviation)
                variants.append(variant)
                count += 1
    logger.info(f'Number of options = {count}')
    return sorted(variants, key=lambda last: last[-1])


def vm_migration(variants: list, cluster_obj: object) -> None:
    """VM migration function from the suggested variants"""
    logger.debug("Starting vm_migration")
    local_disk = None
    local_resources = None
    clo = cluster_obj
    error_counter = 0
    for variant in variants:
        if error_counter > 2:
            logger.exception(f'The number of migration errors has reached {error_counter} pieces.')
            sys.exit(1)  # TODO Add logging and message sending
        donor, recipient, vm = variant[:3]
        if vm in cluster_obj.cl_lxcs:
            options = {'target': recipient, 'restart': 1}
            url = f'{cluster_obj.server}/api2/json/nodes/{donor}/lxc/{vm}/migrate'
        else:
            options = {'target': recipient, 'online': 1}
            url = f'{cluster_obj.server}/api2/json/nodes/{donor}/qemu/{vm}/migrate'
            check_request = requests.get(url, cookies=payload, verify=False)
            local_disk = (check_request.json()['data']['local_disks'])
            local_resources = (check_request.json()['data']['local_resources'])
        if local_disk or local_resources:  # TODO Logging
            continue  # for variant in variants:
        else:
            job = requests.post(url, cookies=payload, headers=header, data=options, verify=False)
            if job.ok:
                logger.info(f'Migration VM:{vm} ({round(clo.cl_vms[vm]["mem"] / GB, 2)} GB) from {donor} to {recipient}...')
                pid = job.json()['data']
                error_counter -= 1
            else:
                logger.warning(f'Error when requesting migration VM {vm} from {donor} to {recipient}. Check the request.')
                error_counter += 1
                continue  # for variant in variants:
            status = True
            timer: int = 0
            while status:
                timer += 10
                sleep(10)
                url = f'{cluster_obj.server}/api2/json/nodes/{recipient}/qemu'
                request = requests.get(url, cookies=payload, verify=False)
                running_vms = request.json()['data']
                for _ in running_vms:
                    if _['vmid'] == vm and _['status'] == 'running':
                        logger.info(f'{pid} - Completed!')
                        status = False
                        break  # for _ in running_vms:
                    elif _['vmid'] == vm and _['status'] != 'running':  # TODO Send Message and Timeout
                        logger.exception(f'Something went wrong during the migration. Response code{request.status_code}')
                        sys.exit(1)
                else:
                    logger.info(f'VM Migration: {vm}... {timer} sec.')
            break  # for variant in variants:


def main():
    """The main body of the program"""
    authentication(server_url, auth)
    cluster = Cluster(server_url)
    cluster_load_verification(cluster.mem_load_included, cluster)
    need_to_balance = need_to_balance_checking(cluster)
    logger.info(f'Need to balance: {need_to_balance}')
    if need_to_balance:
        balance_cl = temporary_dict(cluster)
        sorted_variants = calculating(balance_cl, cluster)
        if sorted_variants:
            vm_migration(sorted_variants, cluster)
            logger.info('Waiting 10 seconds for cluster information update')
            sleep(10)
    else:
        logger.info('The cluster is balanced. Waiting 300 seconds.')
        sleep(300)


while True:
    main()
