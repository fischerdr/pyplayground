import logging
import os

import click
import yaml
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_kube_config(initial_kubeconfig):
    """
    Load Kubernetes configuration from the specified kubeconfig file or the KUBECONFIG environment variable.

    Args:
        initial_kubeconfig (str): Path to the kubeconfig file to use.
    """
    try:
        if initial_kubeconfig:
            logger.info(f"Loading kubeconfig from file: {initial_kubeconfig}")
            config.load_kube_config(config_file=initial_kubeconfig)
        else:
            kubeconfig_env = os.environ.get("KUBECONFIG")
            if kubeconfig_env:
                logger.info(f"Loading kubeconfig from KUBECONFIG environment variable: {kubeconfig_env}")
                config.load_kube_config(config_file=kubeconfig_env)
            else:
                raise ValueError("No kubeconfig file provided and KUBECONFIG environment variable is not set.")
    except Exception as e:
        logger.error(f"Failed to load kubeconfig: {e}")
        raise

def ensure_namespace(namespace_name):
    """
    Ensure that the specified namespace exists. If not, create it.

    Args:
        namespace_name (str): Name of the namespace to ensure.
    """
    v1 = client.CoreV1Api()
    try:
        v1.read_namespace(name=namespace_name)
        logger.info(f"Namespace '{namespace_name}' already exists.")
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Namespace '{namespace_name}' not found. Creating it.")
            namespace = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))
            v1.create_namespace(namespace)
        else:
            raise

def ensure_service_account(namespace, service_account_name):
    """
    Ensure that the specified service account exists in the given namespace. If not, create it.

    Args:
        namespace (str): Name of the namespace.
        service_account_name (str): Name of the service account.
    """
    v1 = client.CoreV1Api()
    try:
        v1.read_namespaced_service_account(name=service_account_name, namespace=namespace)
        logger.info(f"Service account '{service_account_name}' already exists in namespace '{namespace}'.")
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Service account '{service_account_name}' not found. Creating it.")
            sa = client.V1ServiceAccount(metadata=client.V1ObjectMeta(name=service_account_name))
            v1.create_namespaced_service_account(namespace=namespace, body=sa)
        else:
            raise

def create_cluster_role():
    """
    Create a ClusterRole with the specified rules.

    Returns:
        client.V1ClusterRole: The ClusterRole object.
    """
    return client.V1ClusterRole(
        metadata=client.V1ObjectMeta(name="pxbackup-sa-clusterrolebinding"),
        rules=[
            client.V1PolicyRule(
                api_groups=["*"],
                resources=["*"],
                verbs=["get", "list", "create", "update", "delete"]
            )
        ]
    )

def create_role(namespace):
    """
    Create a Role with the specified rules.

    Args:
        namespace (str): Namespace for the Role.

    Returns:
        client.V1Role: The Role object.
    """
    return client.V1Role(
        metadata=client.V1ObjectMeta(name="pxbackup-sa-clusterrolebinding", namespace=namespace),
        rules=[
            client.V1PolicyRule(
                api_groups=["stork.libopenstorage.org"],
                resources=["*"],
                verbs=["*"]
            ),
            client.V1PolicyRule(
                api_groups=["*"],
                resources=["*"],
                verbs=["get", "list", "create", "update", "delete"]
            )
        ]
    )

def assign_roles(namespace, service_account_name):
    """
    Assign the ClusterRole and Role to the specified service account.

    Args:
        namespace (str): Namespace for the Role.
        service_account_name (str): Name of the service account.
    """
    rbac = client.RbacAuthorizationV1Api()

    # Create ClusterRole
    cluster_role = create_cluster_role()
    try:
        rbac.create_cluster_role(body=cluster_role)
        logger.info("ClusterRole 'pxbackup-sa-clusterrolebinding' created successfully.")
    except ApiException as e:
        if e.status == 409:  # Already exists
            logger.info("ClusterRole 'pxbackup-sa-clusterrolebinding' already exists.")
        else:
            raise

    # Create Role
    role = create_role(namespace)
    try:
        rbac.create_namespaced_role(namespace=namespace, body=role)
        logger.info("Role 'pxbackup-sa-clusterrolebinding' created successfully.")
    except ApiException as e:
        if e.status == 409:  # Already exists
            logger.info("Role 'pxbackup-sa-clusterrolebinding' already exists.")
        else:
            raise

    # Create ClusterRoleBinding
    cluster_role_binding_name = "pxbackup-sa-clusterrolebinding"
    try:
        rbac.read_cluster_role_binding(cluster_role_binding_name)
        logger.info(f"ClusterRoleBinding '{cluster_role_binding_name}' already exists.")
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Creating ClusterRoleBinding '{cluster_role_binding_name}'.")
            cluster_role_binding = client.V1ClusterRoleBinding(
                metadata=client.V1ObjectMeta(name=cluster_role_binding_name),
                subjects=[client.V1Subject(
                    kind="ServiceAccount",
                    name=service_account_name,
                    namespace=namespace
                )],
                role_ref=client.V1RoleRef(
                    kind="ClusterRole",
                    name="pxbackup-sa-clusterrolebinding",
                    api_group="rbac.authorization.k8s.io"
                )
            )
            rbac.create_cluster_role_binding(body=cluster_role_binding)
        else:
            raise

    # Create RoleBinding
    role_binding_name = "pxbackup-sa-rolebinding"
    try:
        rbac.read_namespaced_role_binding(name=role_binding_name, namespace=namespace)
        logger.info(f"RoleBinding '{role_binding_name}' already exists in namespace '{namespace}'.")
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Creating RoleBinding '{role_binding_name}'.")
            role_binding = client.V1RoleBinding(
                metadata=client.V1ObjectMeta(name=role_binding_name),
                subjects=[client.V1Subject(
                    kind="ServiceAccount",
                    name=service_account_name,
                    namespace=namespace
                )],
                role_ref=client.V1RoleRef(
                    kind="Role",
                    name="pxbackup-sa-clusterrolebinding",
                    api_group="rbac.authorization.k8s.io"
                )
            )
            rbac.create_namespaced_role_binding(namespace=namespace, body=role_binding)
        else:
            raise

def create_kubeconfig(namespace, service_account_name, output_dir):
    """
    Generate a kubeconfig file for the specified service account.

    Args:
        namespace (str): Namespace of the service account.
        service_account_name (str): Name of the service account.
        output_dir (str): Directory to save the kubeconfig file.
    """
    v1 = client.CoreV1Api()

    # Fetch the service account token secret
    secrets = v1.list_namespaced_secret(namespace=namespace)
    sa_secret = None
    for secret in secrets.items:
        if secret.metadata.annotations and \
           secret.metadata.annotations.get("kubernetes.io/service-account.name") == service_account_name:
            sa_secret = secret
            break

    if not sa_secret:
        raise Exception(f"No secret found for service account '{service_account_name}' in namespace '{namespace}'.")

    # Prepare kubeconfig
    token = sa_secret.data["token"]
    ca_cert = sa_secret.data["ca.crt"]
    server = config.list_kube_config_contexts()[1]["context"]["cluster"]

    kubeconfig = {
        "apiVersion": "v1",
        "clusters": [{
            "cluster": {
                "certificate-authority-data": ca_cert,
                "server": server
            },
            "name": server
        }],
        "contexts": [{
            "context": {
                "cluster": server,
                "user": service_account_name,
                "namespace": namespace
            },
            "name": service_account_name
        }],
        "current-context": service_account_name,
        "kind": "Config",
        "users": [{
            "name": service_account_name,
            "user": {
                "token": token
            }
        }]
    }

    output_path = os.path.join(output_dir, "kubeconfig.yaml")
    os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w") as f:
        yaml.dump(kubeconfig, f)

    logger.info(f"Kubeconfig file created at '{output_path}'.")

    return output_path

def test_kubeconfig(kubeconfig_path):
    """
    Test the connection using the generated kubeconfig by listing pods in the default namespace.

    Args:
        kubeconfig_path (str): Path to the kubeconfig file to test.

    Returns:
        bool: True if the connection test is successful, False otherwise.
    """
    try:
        config.load_kube_config(config_file=kubeconfig_path)

        # Perform a simple Kubernetes API request
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace="default")
        pod_names = [pod.metadata.name for pod in pods.items]
        logger.info(f"Connection successful! Retrieved pods in 'default' namespace: {pod_names}")

        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False

@click.command()
@click.option('--namespace', required=True, help="The namespace for the service account.")
@click.option('--service-account-name', required=True, help="The name of the service account.")
@click.option('--output-dir', required=True, help="Directory to save the generated kubeconfig.")
@click.option('--initial-kubeconfig', default=None, help="Path to the initial kubeconfig file (default: KUBECONFIG env var).")
def main(namespace, service_account_name, output_dir, initial_kubeconfig):
    """
    Main function to create namespace, service account, bind roles, generate kubeconfig, and test connection.

    Args:
        namespace (str): The namespace to create/use.
        service_account_name (str): The name of the service account to create/use.
        output_dir (str): Directory to save the generated kubeconfig.
        initial_kubeconfig (str): Path to the initial kubeconfig file.
    """
    load_kube_config(initial_kubeconfig)
    ensure_namespace(namespace)
    ensure_service_account(namespace, service_account_name)
    assign_roles(namespace, service_account_name)
    kubeconfig_path=create_kubeconfig(namespace, service_account_name, output_dir)
    
    # Test kubeconfig
    if test_kubeconfig(kubeconfig_path):
        logger.info("Kubeconfig connection test succeeded.")
    else:
        logger.error("Kubeconfig connection test failed.")
        
    logger.info("All operations completed successfully.")

if __name__ == "__main__":
    main()
