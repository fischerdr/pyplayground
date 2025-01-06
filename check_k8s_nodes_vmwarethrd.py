import logging
import queue
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
from kubernetes import client, config
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)
file_handler = logging.FileHandler("vm_status_errors.log")
file_handler.setLevel(logging.ERROR)
file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

# Helper function to establish connection to VMware vCenter
def create_vcenter_connection(vcenter_host, username, password, disable_ssl):
    try:
        si = SmartConnect(host=vcenter_host, user=username, pwd=password, disableSslCertValidation=disable_ssl)
        return si
    except Exception as e:
        logger.error(f"Failed to connect to vCenter: {e}")
        return None

# Helper function to get VM details
def get_vm_details(vm):
    details = {
        "name": vm.name,
        "power_state": vm.runtime.powerState,
        "ip_address": vm.guest.ipAddress,
        "disks": [],
        "network_interfaces": []
    }

    # Get network interface information (MAC and IP addresses)
    if vm.guest.net:
        for nic in vm.guest.net:
            nic_info = {
                "mac_address": nic.macAddress,
                "ip_addresses": []
            }
            if nic.ipConfig and nic.ipConfig.ipAddress:
                for adr in nic.ipConfig.ipAddress:
                    ip_info = {
                        "ip_address": adr.ipAddress,
                        "prefix_length": adr.prefixLength
                    }
                    nic_info["ip_addresses"].append(ip_info)
            details["network_interfaces"].append(nic_info)

    # Get disk information
    for device in vm.config.hardware.device:
        if isinstance(device, vim.vm.device.VirtualDisk):
            details["disks"].append({
                "disk_label": device.deviceInfo.label,
                "disk_capacity_gb": device.capacityInKB / (1024 ** 2)  # Convert KB to GB
            })
    return details

# Cache VMs by name for faster lookup
def cache_vms(content):
    vm_cache = {}
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    for vm in container.view:
        vm_cache[vm.name] = vm
    container.Destroy()
    return vm_cache

# Optimized function to find a VM by name, with caching
def find_vm_by_name(vm_cache, vm_name):
    return vm_cache.get(vm_name, None)

# Thread worker function to process each node and add results to shared dictionary
def process_node(node, connection_pool, vcenter_host, vm_cache, results):
    node_name = node.metadata.name
    logger.info(f"\nProcessing node: {node_name}")

    # Get a vCenter connection from the pool
    try:
        si = connection_pool.get_nowait()
    except queue.Empty:
        logger.error("No vCenter connection available in the pool.")
        return

    # Ensure we return the connection to the pool
    try:
        vm = find_vm_by_name(vm_cache, node_name)
        if not vm:
            logger.error(f"VM for node {node_name} not found in vCenter.")
            return

        # Get VM details and add to results dictionary
        vm_details = get_vm_details(vm)
        results[node_name] = vm_details

    except Exception as e:
        logger.error(f"Failed to retrieve details for VM '{node_name}': {e}")

    finally:
        connection_pool.put(si)

@click.command()
@click.option('--vcenter_host', required=True, prompt="vCenter Host", help="The vCenter server host.")
@click.option('--username',  required=True, prompt="vCenter Username", help="The vCenter server username.")
@click.option('--password',  required=True, help="The vCenter server password.", hide_input=True, prompt="vCenter Password", default=None)
@click.option('--kubeconfig', default=None, help="Path to the kubeconfig file.")
@click.option('--node_search', default='', help="Optional substring to filter Kubernetes nodes by name.")
@click.option('--label_selector', default='', help="Optional label selector to filter Kubernetes nodes.")
@click.option('--disable_k8s_ssl', is_flag=True, help="Disable SSL verification for Kubernetes API.")
@click.option('--disable_vcenter_ssl', is_flag=True, help="Disable SSL verification for vCenter connection.")
@click.option('--threads', default=5, help="Number of threads for concurrent node processing.")
@click.option('--pool_size', default=5, help="Number of connections in the vCenter connection pool.")
@click.pass_context
def check_k8s_nodes(ctx, vcenter_host, username, password, kubeconfig, node_search, label_selector, disable_k8s_ssl, disable_vcenter_ssl, threads, pool_size):
    # If no options are provided, show the help message and exit
    if len(sys.argv) == 1:
        click.echo(ctx.get_help())
        ctx.exit()

    # If password is not provided, prompt for it securely
    if password is None:
        password = click.prompt("vCenter Password", hide_input=True)

    # Load Kubernetes configuration
    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
            logger.info(f"Using custom kubeconfig at {kubeconfig}")
        else:
            config.load_kube_config()
            logger.info("Using default kubeconfig")
        
        if disable_k8s_ssl:
            client.Configuration().verify_ssl = False
            logger.info("SSL verification disabled for Kubernetes API")
    except Exception as e:
        logger.error(f"Failed to load Kubernetes config: {e}")
        return

    k8s_api = client.CoreV1Api()
    
    # Set up the connection pool
    connection_pool = queue.Queue(maxsize=pool_size)
    for _ in range(pool_size):
        si = create_vcenter_connection(vcenter_host, username, password, disable_vcenter_ssl)
        if si:
            connection_pool.put(si)

    # Pre-fetch VM cache for quick lookup
    vm_cache = None
    if not connection_pool.empty():
        si = connection_pool.get()
        try:
            content = si.RetrieveContent()
            vm_cache = cache_vms(content)
            logger.info("Cached vCenter VMs for faster lookup.")
        finally:
            connection_pool.put(si)
    else:
        logger.error("Could not establish initial vCenter connection for VM caching.")
        return

    # Get the list of Kubernetes nodes, filtered by label selector and/or substring
    try:
        nodes = k8s_api.list_node(label_selector=label_selector).items
        if node_search:
            nodes = [node for node in nodes if node_search in node.metadata.name]
        logger.info(f"Found {len(nodes)} nodes matching search '{node_search}' and label selector '{label_selector}'.")
    except Exception as e:
        logger.error(f"Failed to retrieve nodes from Kubernetes: {e}")
        return

    # Dictionary to store VM information for each node
    results = {}

    # Process nodes with threading
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(process_node, node, connection_pool, vcenter_host, vm_cache, results) for node in nodes]
        for future in as_completed(futures):
            future.result()  # This will raise exceptions, if any, from the thread

    # Disconnect from vCenter
    while not connection_pool.empty():
        si = connection_pool.get()
        Disconnect(si)
    logger.info("\nFinished checking Kubernetes nodes and VM statuses.")

    # Print out all VM information at the end
    logger.info("\nVM Information for all processed nodes:")
    for node_name, vm_info in results.items():
        logger.info(f"\nNode: {node_name}")
        logger.info(f"  VM Name: {vm_info['name']}")
        logger.info(f"  Power State: {vm_info['power_state']}")
        logger.info(f"  IP Address: {vm_info['ip_address']}")
        logger.info("  Disks:")
        for disk in vm_info['disks']:
            logger.info(f"    {disk['disk_label']}: {disk['disk_capacity_gb']} GB")
        logger.info("  Network Interfaces:")
        for nic in vm_info['network_interfaces']:
            logger.info(f"    MAC Address: {nic['mac_address']}")
            for ip in nic['ip_addresses']:
                logger.info(f"      IP Address: {ip['ip_address']}")
                logger.info(f"      Prefix Length: {ip['prefix_length']}")

if __name__ == "__main__":
    check_k8s_nodes()
