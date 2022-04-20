#!/usr/bin/python3
# Proxmox-load-balancer Copyright (С) 2022 cvk98 (github.com/cvk98)

import sys
import requests
import urllib3
from time import sleep
from copy import deepcopy
from itertools import permutations

"""Proxmox node address and authorization information"""
server_url = "https://10.10.10.20:8006"
auth = {'username': "root@pam", 'password': "PASSWORD"}

"""Options"""
deviation = 0.03  # Permissible deviation from the average load of the balanced part of the cluster (10% for 0.05)
THRESHOLD = 0.9   # Dangerous loading threshold
LXC_MIGRATION = "OFF"  # Container migration (LXCs are rebooted during migration!!!)
migration_timeout = 1000  # For the future

"""List of exclusions"""
excluded_vms: tuple = ()  # Example: ('100',) or (100, 101, 102, 113, 125, 131)
excluded_nodes: tuple = ()  # Example: ('px-3',) or ('px-3', 'px-4', 'px-8', 'px-9')

GB = 1e+9
TB = 1e+12

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

payload = dict()  # PVEAuthCookie
header = dict()  # CSRFPreventionToken
sum_of_deviations: float = 0


class Cluster:
    def __init__(self, server: str):
        print("init при создании объекта Cluster")
        """Кластер"""
        self.server: str = server
        self.cl_name = self.cluster_name()
        """VMs and nodes"""
        self.cl_nodes: int = 0                      # Количество нод. Рассчитывается в Cluster.cluster_name
        self.cluster_information = {}               # Извлекается в Cluster.cluster_items
        self.cluster_items()
        self.included_nodes = {}                    # Балансируемые ноды
        self.cl_nodes: dict = self.cluster_hosts()  # Все ноды кластера
        self.cl_lxcs = set()                        # Определяются в Cluster.self.cluster_vms
        self.cl_vms_included: dict = {}             # Все VM и Lxc запущенные в балансируемом кластере
        self.cl_vms: dict = self.cluster_vms()      # Все VM и Lxc запущенные в кластере
        """RAM"""
        self.cl_mem_included: int = 0               # Занято памяти кластера в байтах для балансируемых нод
        self.cl_mem: int = 0                        # Занято памяти кластера в байтах
        self.cl_max_mem_included: int = 0           # Всего памяти кластера в байтах для балансируемых нод
        self.mem_load: float = 0                    # Загрузка ОЗУ кластера в %
        self.mem_load_included: float = 0           # Загрузка ОЗУ, балансируемой части кластера в %
        self.cl_max_mem: int = self.cluster_mem()   # Всего памяти кластера в байтах
        """CPU"""
        self.cl_cpu_load: float = 0                 # общая загрузка процессоров кластера от 0 до 1
        self.cl_cpu_load_include: float = 0         # общая загрузка процессоров кластера для балансируемых нод от 0 до 1
        self.cl_cpu_included: int = 0               # Всего ядер в кластере для балансируемых нод
        self.cl_cpu = self.cluster_cpu()            # Всего ядер в кластере
        """Others"""
        self.cluster_information = []
        self.show()

    def cluster_name(self):
        """Getting the cluster name and the number of nodes in it"""
        print("Запуск Cluster.cluster_name")
        name: str = ""
        url = f'{self.server}/api2/json/cluster/status'
        name_request = nr = requests.get(url, cookies=payload, verify=False)
        if name_request.ok:
            print(f'Информация о имени кластере получена. Код ответа: {nr.status_code}')
        else:
            print(f'Ошибка при выполнении {Cluster.cluster_name.__qualname__}')
            print(f'Не удалось получить информацию о кластере. Код ответа: {nr.status_code}. Причина: ({nr.reason})')
            sys.exit()
        temp = name_request.json()["data"]
        del name_request, nr
        for i in temp:
            if i["type"] == "cluster":
                name = i["name"]
                self.cl_nodes = i["nodes"]
        return name

    def cluster_items(self):
        """Collecting preliminary information about the cluster"""
        print("Запуск Cluster.cluster_items")
        url = f'{self.server}/api2/json/cluster/resources'
        print('Попытка получения информации о кластере...')
        resources_request = rr = requests.get(url, cookies=payload, verify=False)
        if resources_request.ok:
            print(f'Информация о кластере получена. Код ответа: {rr.status_code}')
        else:
            print(f'Ошибка при выполнении {Cluster.cluster_items.__qualname__}')
            print(f'Не удалось получить информацию о кластере. Код ответа: {rr.status_code}. Причина: ({rr.reason})')
            sys.exit()
        self.cluster_information = rr.json()['data']
        # print(self.cluster_information)
        del resources_request, rr

    def cluster_hosts(self):
        """Getting nodes from cluster resources"""
        print("Запуск Cluster.cluster_hosts")
        nodes_dict = {}
        temp = deepcopy(self.cluster_information)
        for item in temp:
            if item["type"] == "node":
                self.cluster_information.remove(item)
                item["cpu_used"] = round(item["maxcpu"] * item["cpu"], 2)  # Добавляем значение используемых ядер
                item["free_mem"] = item["maxmem"] - item["mem"]  # Добавляем значение свободной ОЗУ
                item["mem_load"] = item["mem"] / item["maxmem"]  # Добавляем значение свободной ОЗУ
                nodes_dict[item["node"]] = item
                if item["node"] not in excluded_nodes:
                    self.included_nodes[item["node"]] = item
        del temp
        return nodes_dict

    def cluster_vms(self):
        """Getting VM/Lxc from cluster resources"""
        print("Запуск Cluster.cluster_vms")
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
        print("Запуск Cluster.cluster_mem")
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
        print("Запуск Cluster.cluster_cpu")
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
        print("Запуск Cluster.show")
        print(f'Адрес сервера: {self.server}')
        print(f'Имя кластера: {self.cl_name}')
        print(f'Количество нод: {len(self.cl_nodes)}')
        print(f'Количество балансируемых нод: {len(self.cl_nodes) - len(excluded_nodes)}')
        print(f'Количество VM: {len(self.cl_vms)}')
        print(f'Количество балансируемых VM: {len(self.cl_vms_included)}')
        print(f'Общая ОЗУ кластера: {round(self.cl_max_mem / TB, 2)} TB. Загрузка {round((self.mem_load * 100), 2)}%')
        print(f'ОЗУ балансируемой части кластера: {round(self.cl_max_mem_included / TB, 2)} TB. Загрузка {round((self.mem_load_included * 100), 2)}%')
        print(f'Количество ядер CPU в кластере: {self.cl_cpu}, загрузка {round((self.cl_cpu_load * 100), 2)}%')
        print(f'Количество ядер балансируемой части кластере: {self.cl_cpu_included}, загрузка {round((self.cl_cpu_load_include * 100), 2)}%')


def authentication(server: str, data: dict):
    """Authentication and receipt of a token and ticket."""
    global payload, header
    url = f'{server}/api2/json/access/ticket'
    print('Попытка авторизации...')
    try:
        get_token = requests.post(url, data=data, verify=False)
    except Exception as e:
        print(f'Неверные настройки адреса или порта сервера: {e}')
        sys.exit()  # TODO Добавить отправку почты и логирование
    if get_token.ok:
        print(f'Успешная аутентификация. Код ответа: {get_token.status_code}')
    else:
        print(f'Ошибка при выполнении {authentication.__qualname__}')
        print(f'Аутентификация не прошла. Код ответа: {get_token.status_code}. Причина: {get_token.reason}')
        sys.exit()
    payload = {'PVEAuthCookie': (get_token.json()['data']['ticket'])}
    header = {'CSRFPreventionToken': (get_token.json()['data']['CSRFPreventionToken'])}


def cluster_load_verification(mem_load: float, cluster_obj: object) -> None:
    """Checking the RAM load of the balanced part of the cluster"""
    print("Запуск cluster_load_verification")
    if len(cluster_obj.cl_nodes) - len(excluded_nodes) == 1:
        print('It is impossible to balance one node!')
        sys.exit()
    assert 0 < mem_load < 1, 'The cluster RAM load should be in the range from 0 to 1'
    if mem_load >= THRESHOLD:
        print(f'Cluster RAM usage is too high {(round(cluster_obj.mem_load * 100, 2))}')
        print('It is not possible to safely balance the cluster')
        sys.exit()


def need_to_balance_checking(cluster_obj: object) -> bool:
    """Checking the need for balancing"""
    print("Запуск need_to_balance_checking")
    global sum_of_deviations
    nodes = cluster_obj.included_nodes
    average = cluster_obj.mem_load_included
    print(f'Average = {average}')
    for host, values in nodes.items():
        values["deviation"] = abs(values["mem_load"] - average)
        print(f'{host} deviation = {values["deviation"]}')
    sum_of_deviations = sum(values["deviation"] for values in nodes.values())
    for values in nodes.values():
        if values["deviation"] > deviation:
            return True
    else:
        return False


def temporary_dict(cluster_obj: object) -> object:
    """Preparation of information for subsequent processing"""
    print("Запуск temporary_dict")
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
    print("Запуск calculating")
    count = 0
    variants: list = []
    nodes = cluster_obj.included_nodes
    average = cluster_obj.mem_load_included
    for host in permutations(nodes, 2):
        # print(host)
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
                # pprint(variant)
                count += 1
    # pprint(sorted(variants, key=lambda last: last[-1]))
    print(f'Количество вариантов = {count}')
    return sorted(variants, key=lambda last: last[-1])


def vm_migration(variants: list, cluster_obj: object) -> None:
    """VM migration function from the suggested variants"""
    print("Запуск vm_migration")
    local_disk = None
    local_resources = None
    error_counter = 0
    for variant in variants:
        if error_counter > 2:
            sys.exit()  # TODO Добавить логирование и отправку сообщения
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
        if local_disk or local_resources:
            continue  # for variant in variants:
        else:
            job = requests.post(url, cookies=payload, headers=header, data=options, verify=False)
            if job.ok:
                print(f'Миграция VM {vm} с {donor} на {recipient}...')
                pid = job.json()['data']
            else:
                print(f'Ошибка при запросе миграции VM {vm} с {donor} на {recipient}. Проверьте запрос.')
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
                        print(f'{pid} - Завершена!')
                        status = False
                        break  # for _ in running_vms:
                    elif _['vmid'] == vm and _['status'] != 'running':  # TODO Отправить сообщение и таймаут
                        print(f'Что-то пошло не так во время миграции. Код ответа {request.status_code}')
                        sys.exit(1)
                else:
                    print(f'Миграция VM: {vm}... {timer} сек.')
            break  # for variant in variants:


def main():
    """The main body of the program"""
    authentication(server_url, auth)
    cluster = Cluster(server_url)
    cluster_load_verification(cluster.mem_load_included, cluster)
    need_to_balance = need_to_balance_checking(cluster)
    print(f'need_to_balance: {need_to_balance}')
    if need_to_balance:
        balance_cl = temporary_dict(cluster)
        sorted_variants = calculating(balance_cl, cluster)
        if sorted_variants:
            vm_migration(sorted_variants, cluster)
            print('Waiting 10 seconds for cluster information update')
            sleep(10)
    else:
        print('The cluster is balanced. Waiting 300 seconds.')
        sleep(300)


while True:
    main()
