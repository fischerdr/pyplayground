import logging
import ssl

import click
from kubernetes import client, config
from pyVim.connect import Disconnect, SmartConnect, SmartConnectNoSSL
from pyVmomi import vim

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# Console handler for info level messages
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)
# File handler for errors
file_handler = logging.FileHandler("vm_status_errors.log")
file_handler.setLevel(logging.ERROR)
file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

# Helper function to establish connection to VMware vCenter
def connect_to_vcenter(vcenter_host, username, password, disable_ssl):
    try:
        if disable_ssl:
            si = SmartConnectNoSSL(host=vcenter_host, user=username, pwd=password)
        else:
            context = ssl.create_default_context()
            si = SmartConnect(host=vcenter_host, user=username, pwd=password, sslContext=context)
        return si
    except Exception as e:
        logger.error(f"Failed to connect to vCenter: {e}")
        return None

# Helper function to get VM details
def get_vm_details(vm, info_type="all"):
    details = {
        "name": vm.name,
        "power_state": vm.runtime.powerState,
        "ip_address": vm.guest.ipAddress,
        "disk_status": []
    }
    if info_type in ["all", "disk"]:
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                details["disk_status"].append({
                    "disk_label": device.deviceInfo.label,
                    "disk_capacity_gb": device.capacityInKB / (1024 ** 2)  # Convert KB to GB
                })
    return details

# Helper function to find a VM by name
def find_vm_by_name(content, vm_name):
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    for vm in container.view:
        if vm.name == vm_name:
            return vm
    return None

@click.command()
@click.option('--vcenter_host', prompt="vCenter Host", help="The vCenter server host.")
@click.option('--username', prompt="vCenter Username", help="The vCenter server username.")
@click.option('--password', help="The vCenter server password.", hide_input=True, prompt="vCenter Password", default=None)
@click.option('--kubeconfig', default=None, help="Path to the kubeconfig file.")
@click.option('--node_search', default='', help="Optional substring to filter Kubernetes nodes by name.")
@click.option('--label_selector', default='', help="Optional label selector to filter Kubernetes nodes.")
@click.option('--disable_k8s_ssl', is_flag=True, help="Disable SSL verification for Kubernetes API.")
@click.option('--disable_vcenter_ssl', is_flag=True, help="Disable SSL verification for vCenter connection.")
def check_k8s_nodes(vcenter_host, username, password, kubeconfig, node_search, label_selector, disable_k8s_ssl, disable_vcenter_ssl):
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
    
    # Connect to vCenter
    si = connect_to_vcenter(vcenter_host, username, password, disable_vcenter_ssl)
    if not si:
        logger.error("Could not connect to vCenter.")
        return
    content = si.RetrieveContent()

    # Get the list of Kubernetes nodes, filtered by label selector and/or substring
    try:
        nodes = k8s_api.list_node(label_selector=label_selector).items
        if node_search:
            nodes = [node for node in nodes if node_search in node.metadata.name]
        logger.info(f"Found {len(nodes)} nodes matching search '{node_search}' and label selector '{label_selector}'.")
    except Exception as e:
        logger.error(f"Failed to retrieve nodes from Kubernetes: {e}")
        Disconnect(si)
        return

    for node in nodes:
        node_name = node.metadata.name
        logger.info(f"\nNode: {node_name}")
        
        # Attempt to find the VM corresponding to this node
        try:
            vm = find_vm_by_name(content, node_name)
            if not vm:
                logger.error(f"VM for node {node_name} not found in vCenter.")
                continue

            # Get VM details
            vm_details = get_vm_details(vm)
            
            # Display VM details
            logger.info(f"  VM Name: {vm_details['name']}")
            logger.info(f"  Power State: {vm_details['power_state']}")
            logger.info(f"  IP Address: {vm_details['ip_address']}")
            
            logger.info("  Disks:")
            for disk in vm_details['disk_status']:
                logger.info(f"    {disk['disk_label']}: {disk['disk_capacity_gb']} GB")

        except Exception as e:
            logger.error(f"Failed to retrieve details for VM '{node_name}': {e}")

    # Disconnect from vCenter
    Disconnect(si)
    logger.info("\nFinished checking Kubernetes nodes and VM statuses.")

if __name__ == "__main__":
    check_k8s_nodes()
