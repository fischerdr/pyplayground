import sys

import click
from kubernetes import client, config


@click.command()
@click.option('--namespace', help='Namespace of the pod', required=True)
@click.option('--podname', help='Name of the pod', required=True)
@click.option('--command', help='Command to run in the pod', required=True)
def pod_exec_tty(namespace, podname, command):
    # Load Kubernetes configuration
    config.load_kube_config()

    # Create a Kubernetes API client
    api = client.CoreV1Api()

    # Get the pod
    pod = api.read_namespaced_pod(namespace=namespace, name=podname)

    # Create a pseudo-terminal (pty) to interact with the pod
    exec_command = ['/bin/sh', '-c', command]
    exec_api = client.CoreV1Api()
    exec_response = exec_api.connect_get_namespaced_pod_exec(
        namespace=namespace,
        name=podname,
        command=exec_command,
        container=pod.spec.containers[0].name,
        stdin=True,
        stdout=True,
        stderr=True,
        tty=True
    )

    # Handle the exec response
    while exec_response.is_open():
        exec_response.update(timeout=1)
        if exec_response.peek_stdout():
            print(exec_response.read_stdout())
        if exec_response.peek_stderr():
            print(exec_response.read_stderr(), file=sys.stderr)

if __name__ == '__main__':
    pod_exec_tty()