from kubernetes import client, config
from kubernetes.client.rest import ApiException


def get_k8s_client():
    """Loads the Kubernetes configuration and returns a Kubernetes API client."""
    try:
        # Load the kube config from the default location (or in-cluster if running in Kubernetes)
        config.load_kube_config()  # For local development
    except Exception as e:
        print(f"Error loading Kubernetes config: {e}")
        return None
    return client.CoreV1Api()  # Use CoreV1Api for namespace operations

def list_namespaces(api_client):
    """Lists all namespaces in the cluster."""
    try:
        namespaces = api_client.list_namespace()
        return namespaces.items
    except ApiException as e:
        print(f"Error fetching namespaces: {e}")
        return []

def list_crds(api_client):
    """Lists all Custom Resource Definitions (CRDs) in the cluster."""
    try:
        crd_api = client.ApiextensionsV1Api()
        crds = crd_api.list_custom_resource_definition()
        return crds.items
    except ApiException as e:
        print(f"Error fetching CRDs: {e}")
        return []

def get_resources_for_crd(api_client, crd, namespace):
    """Returns instances of a given CRD in the specified namespace."""
    try:
        # Extract group, version, and plural from the CRD spec
        api_group = crd.spec.group
        api_version = crd.spec.versions
        plural = crd.spec.names.plural
        
        # Fetch the resources (instances) for the CRD using the CustomObjectsApi
        custom_api = client.CustomObjectsApi()

        # Fetch resources for the given namespace
        resources = custom_api.list_namespaced_custom_object(
            group=api_group,
            version=api_version,
            namespace=namespace,  # Specify the current namespace
            plural=plural
        )
        return resources.get("items", [])
    except ApiException as e:
        if e.status != 404:  # Log only non-404 errors
            print(f"Error fetching resources for CRD {crd.metadata.name} in namespace {namespace}: {e}")
        return []

def find_known_and_unknown_crds(api_client):
    """Finds known and unknown CRDs across all namespaces."""
    namespaces = list_namespaces(api_client)
    crds = list_crds(api_client)
    
    if not crds:
        print("No CRDs found.")
        return
    if not namespaces:
        print("No namespaces found.")
        return

    for crd in crds:
        print(f"CRD: {crd.spec.names.plural}")
        
        # Check for instances of the CRD in all namespaces
        found_instances = False
        for namespace in namespaces:
            resources = get_resources_for_crd(api_client, crd, namespace.metadata.name)
            
            if resources:
                print(f"  - Namespace {namespace.metadata.name}: Known CRD with {len(resources)} instances")
                found_instances = True
            else:
                print(f"  - Namespace {namespace.metadata.name}: Unknown CRD with no instances")
        
        if not found_instances:
            print(f"  - No instances found in any namespace for CRD: {crd.metadata.name}")

def main():
    api_client = get_k8s_client()
    if api_client:
        find_known_and_unknown_crds(api_client)

if __name__ == "__main__":
    main()
