from concurrent.futures import ThreadPoolExecutor, as_completed

from kubernetes import client, config


def count_ns_resources_for_ns(ns, c_core, c_apps, c_batch, c_custom):
    """
    Helper function to count resources for a single namespace.
    
    :param ns: Namespace to query
    :param c_core: CoreV1Api client
    :param c_apps: AppsV1Api client
    :param c_batch: BatchV1Api client
    :param c_custom: CustomObjectsApi client
    :return: Dictionary with namespace as key and count of resources
    """
    # Standard resources
    std_res = {
        "pods": c_core.list_namespaced_pod(ns).items,
        "svc": c_core.list_namespaced_service(ns).items,
        "cm": c_core.list_namespaced_config_map(ns).items,
        "sec": c_core.list_namespaced_secret(ns).items,
        "pvc": c_core.list_namespaced_persistent_volume_claim(ns).items,
        "deploy": c_apps.list_namespaced_deployment(ns).items,
        "sts": c_apps.list_namespaced_stateful_set(ns).items,
        "ds": c_apps.list_namespaced_daemon_set(ns).items,
        "jobs": c_batch.list_namespaced_job(ns).items,
        "cron": c_batch.list_namespaced_cron_job(ns).items,
    }

    # Custom resources (CRDs)
    crds = {}
    try:
        # Get CRD definitions
        crd_defs = c_custom.list_cluster_custom_object(
            group="apiextensions.k8s.io", version="v1", plural="customresourcedefinitions"
        )

        # Query for CRD instances in the namespace
        for crd in crd_defs.get("items", []):
            grp = crd["spec"]["group"]
            ver = crd["spec"]["versions"][0]["name"]
            pl = crd["spec"]["names"]["plural"]
            try:
                crd_items = c_custom.list_namespaced_custom_object(
                    group=grp, version=ver, namespace=ns, plural=pl
                )
                crds[crd["spec"]["names"]["kind"]] = crd_items.get("items", [])
            except client.exceptions.ApiException:
                crds[crd["spec"]["names"]["kind"]] = []  # Empty or inaccessible CRDs
    except client.exceptions.ApiException as e:
        print(f"Error fetching CRDs for namespace {ns}: {e}")

    # Count resources and CRDs
    std_count = sum(len(items) for items in std_res.values())
    crd_count = sum(len(items) for items in crds.values())
    total_count = std_count + crd_count

    return {ns: {"count": total_count}}

def count_all_ns_resources():
    """
    Count all standard resources and CRDs grouped by namespace using threading for parallel processing.
    
    :return: A dictionary with namespaces as keys and resource counts as values.
    """
    # Load kubeconfig
    config.load_kube_config()

    # Initialize API clients
    c_core = client.CoreV1Api()
    c_apps = client.AppsV1Api()
    c_batch = client.BatchV1Api()
    c_custom = client.CustomObjectsApi()

    # List all namespaces
    ns_list = [ns.metadata.name for ns in c_core.list_namespace().items]

    # Results dictionary
    res = {}

    # Use ThreadPoolExecutor to parallelize requests across namespaces
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit jobs for each namespace
        futures = {executor.submit(count_ns_resources_for_ns, ns, c_core, c_apps, c_batch, c_custom): ns for ns in ns_list}
        
        # Collect results as they complete
        for future in as_completed(futures):
            ns_data = future.result()
            res.update(ns_data)

    return res


# Example usage:
if __name__ == "__main__":
    counts = count_all_ns_resources()
    for ns, data in counts.items():
        print(f"Namespace: {ns}, Total Resources: {data['count']}")
