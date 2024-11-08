import click
from kubernetes import client, config, stream
import os
import sys

@click.command()
@click.argument('pod_name')
@click.option('--namespace', '-n', default='default', help='Namespace of the pod')
@click.option('--env_var', '-e', multiple=True, help='Environment variable in the format VAR=VALUE')
@click.option('--command', '-c', required=True, help='Command to run in the pod')
@click.option('--kubeconfig', '-k', default=None, help='Path to the kubeconfig file')
@click.option('--container', '-c', default=None, help='Container name in the pod')
def exec_in_pod(pod_name, namespace, env_var, command, kubeconfig, container_name):
    """
    Connect to a Kubernetes pod, set environment variables, and run a command.
    """
    # Load Kubernetes configuration
    try:
        if kubeconfig:
            if not os.path.isfile(kubeconfig):
                click.echo(f"Error: Kubeconfig file '{kubeconfig}' does not exist.", err=True)
                sys.exit(1)
            config.load_kube_config(config_file=kubeconfig)
        else:
            # Attempt to load the default kubeconfig
            config.load_kube_config()
    except Exception as e:
        click.echo(f"Failed to load kubeconfig: {e}", err=True)
        sys.exit(1)
    
    # Initialize the API client
    v1 = client.CoreV1Api()
    
    # Parse environment variables into a dictionary format
    env_vars = {}
    for var in env_var:
        if '=' not in var:
            click.echo(f"Invalid environment variable format: '{var}'. Use VAR=VALUE.", err=True)
            sys.exit(1)
        key, value = var.split("=", 1)
        env_vars[key] = value
    
    # Create the command with environment variables
    if env_vars:
        env_command = ' && '.join([f'export {key}="{value}"' for key, value in env_vars.items()])
        full_command = f"{env_command} && {command}"
    else:
        full_command = command
    
    try:
        # Verify that the pod exists
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Determine the container to execute the command in
        # If multiple containers exist, you might want to add an option to specify the container
        if len(pod.spec.containers) > 1:
            click.echo(f"Pod '{pod_name}' has multiple containers. Please specify the container using an additional option.", err=True)
        
        container = container_name if container_name else pod.spec.containers[0].name
        
        # Execute command in the pod
        response = stream.stream(
            v1.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container=container,
            command=["/bin/sh", "-c", full_command],
            stderr=True, stdin=False, stdout=True, tty=False
        )
        click.echo("Command Output:\n" + response)
    except client.exceptions.ApiException as e:
        click.echo(f"API exception when executing command in pod: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)

if __name__ == '__main__':
    exec_in_pod()
