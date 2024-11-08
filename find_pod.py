import click
from kubernetes import client, config

def get_pod_info(pod_name):
    # Load Kubernetes configuration
    config.load_kube_config()
    
    # Initialize the API clients
    v1 = client.CoreV1Api()
    
    # Search for the pod across all namespaces
    pods = v1.list_pod_for_all_namespaces(watch=False)
    for pod in pods.items:
        if pod.metadata.name == pod_name:
            node_name = pod.spec.node_name
            pod_ip = pod.status.pod_ip
            namespace = pod.metadata.namespace
            
            # Get the external IP address of the node
            node = v1.read_node(node_name)
            external_ip = None
            for address in node.status.addresses:
                if address.type == "ExternalIP":
                    external_ip = address.address
                    break
            
            return {
                "namespace": namespace,
                "node_name": node_name,
                "pod_ip": pod_ip,
                "node_external_ip": external_ip
            }
    return None

@click.command()
@click.argument('pod_name')
def find_pod(pod_name):
    """Search for a pod by name and display the node, pod IP, and node external IP address where it is running."""
    pod_info = get_pod_info(pod_name)
    
    if pod_info:
        print(f"Pod '{pod_name}' is running in namespace '{pod_info['namespace']}'")
        print(f"Node: {pod_info['node_name']}")
        print(f"Pod IP: {pod_info['pod_ip']}")
        if pod_info['node_external_ip']:
            print(f"Node External IP: {pod_info['node_external_ip']}")
        else:
            print("Node External IP: Not available")
    else:
        print(f"Pod '{pod_name}' not found in any namespace.")

if __name__ == '__main__':
    find_pod()
