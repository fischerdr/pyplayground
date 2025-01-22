from kubernetes import client, config


def count_resources_by_namespace():
    """
    Count all standard resources and custom resources (CRDs) grouped by namespace.

    :return: A dictionary with namespaces as keys and resource counts as values.
    """
    # Load kubeconfig
    config.load_kube_config()

    # Initialize API clients
    api_core = client.CoreV1Api()
    api_apps = client.AppsV1Api()
    api_batch = client.BatchV1Api()
    api_custom = client.CustomObjectsApi()

    # List all namespaces
    namespaces = [ns.metadata.name for ns in api_core.list_namespace().items]

    # Initialize results
    results = {}

    for namespace in namespaces:
        # Fetch standard resources
        resources = {
            "pods": api_core.list_namespaced_pod(namespace).items,
            "services": api_core.list_namespaced_service(namespace).items,
            "config_maps": api_core.list_namespaced_config_map(namespace).items,
            "secrets": api_core.list_namespaced_secret(namespace).items,
            "persistent_volume_claims": api_core.list_namespaced_persistent_volume_claim(
                namespace
            ).items,
            "deployments": api_apps.list_namespaced_deployment(namespace).items,
            "stateful_sets": api_apps.list_namespaced_stateful_set(namespace).items,
            "daemon_sets": api_apps.list_namespaced_daemon_set(namespace).items,
            "jobs": api_batch.list_namespaced_job(namespace).items,
            "cron_jobs": api_batch.list_namespaced_cron_job(namespace).items,
        }

        # Fetch CRDs
        crds = {}
        try:
            # List all CRD definitions in the cluster
            crd_definitions = api_custom.list_cluster_custom_object(
                group="apiextensions.k8s.io", version="v1", plural="customresourcedefinitions"
            )

            # Query for instances of each CRD in the specified namespace
            for crd in crd_definitions.get("items", []):
                group = crd["spec"]["group"]
                version = crd["spec"]["versions"][0]["name"]
                plural = crd["spec"]["names"]["plural"]
                try:
                    crd_instances = api_custom.list_namespaced_custom_object(
                        group=group, version=version, namespace=namespace, plural=plural
                    )
                    crds[crd["spec"]["names"]["kind"]] = crd_instances.get("items", [])
                except client.exceptions.ApiException:
                    crds[crd["spec"]["names"]["kind"]] = []  # Handle inaccessible or empty CRDs
        except client.exceptions.ApiException as e:
            print(f"Error fetching CRDs: {e}")

        # Count resources and CRDs
        standard_count = sum(len(items) for items in resources.values())
        crd_count = sum(len(items) for items in crds.values())
        total_count = standard_count + crd_count

        # Store results
        results[namespace] = {"count": total_count}

    return results


# Example usage:
if __name__ == "__main__":
    resource_counts = count_resources_by_namespace()
    for namespace, data in resource_counts.items():
        print(f"Namespace: {namespace}, Total Resources: {data['count']}")
