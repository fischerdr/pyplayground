from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


def get_all_api_resources_and_crds():
    """
    Fetches all API resources and CRDs available in the Kubernetes cluster.

    Returns:
        dict: A dictionary with two keys:
            - "api_resources": List of API resources.
            - "crds": List of Custom Resource Definitions.
    """
    # Load kubeconfig (default location is ~/.kube/config or in-cluster configuration)
    config.load_kube_config()

    api_client = client.ApiClient()
    api_resources = []
    crds = []

    try:
        # Get available API groups and versions
        api_groups = api_client.call_api("/apis", "GET", response_type="object")
        for group in api_groups[0]["groups"]:
            for version in group["versions"]:
                group_version = version["groupVersion"]
                try:
                    # Fetch resources for each API group/version
                    resources = api_client.call_api(
                        f"/apis/{group_version}", "GET", response_type="object"
                    )
                    api_resources.append(
                        {"group_version": group_version, "resources": resources[0]["resources"]}
                    )
                except ApiException as e:
                    print(f"Could not fetch resources for {group_version}: {e}")

        # Fetch CRDs
        crd_api = client.ApiextensionsV1Api(api_client)
        crds_list = crd_api.list_custom_resource_definition().items
        for crd in crds_list:
            crds.append(
                {
                    "name": crd.metadata.name,
                    "group": crd.spec.group,
                    "versions": [version.name for version in crd.spec.versions],
                    "scope": crd.spec.scope,
                    "kind": crd.spec.names.kind,
                }
            )
    except ApiException as e:
        print(f"Failed to fetch API resources or CRDs: {e}")

    return {"api_resources": api_resources, "crds": crds}


# Example usage
if __name__ == "__main__":
    result = get_all_api_resources_and_crds()
    print("API Resources:")
    for resource in result["api_resources"]:
        print(resource)
    print("\nCustom Resource Definitions:")
    for crd in result["crds"]:
        print(crd)
