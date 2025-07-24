#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executes a command in a pod and returns the output."""
import json
import sys

import click
from kubernetes import client, config
from kubernetes.stream import stream


@click.command()
@click.option("--namespace", help="Namespace of the pod", required=True)
@click.option("--podname", help="Name of the pod", required=True)
@click.option("--command", help="Command to run in the pod", required=True)
def pod_exec_tty(namespace, podname, command):
    """Executes a command in a pod and returns the output."""
    # Load Kubernetes configuration
    config.load_kube_config()

    # Create a Kubernetes API client
    api = client.CoreV1Api()

    # Get the pod
    pod = api.read_namespaced_pod(namespace=namespace, name=podname)

    # Create a pseudo-terminal (pty) to interact with the pod
    exec_command = ["/bin/sh", "-c", command]
    try:
        exec_response = stream(
            api.connect_get_namespaced_pod_exec,
            name=podname,
            namespace=namespace,
            command=exec_command,
            container=pod.spec.containers[0].name,
            stdin=False,
            stdout=True,
            stderr=True,
            tty=False,
            _preload_content=False,  # This is key to getting raw output
        )

        output = ""  # Initialize an empty string to collect all stdout

        # If exec_response is a string, add it directly to output
        if isinstance(exec_response, str):
            output += exec_response
        else:
            # Handle streaming response
            while exec_response.is_open():
                exec_response.update(timeout=1)
                if exec_response.peek_stdout():
                    output += exec_response.read_stdout()
                if exec_response.peek_stderr():
                    print("STDERR:", file=sys.stderr)
                    print(exec_response.read_stderr(), file=sys.stderr)

        # After collecting all output, try to parse it as JSON
        try:
            json_obj = json.loads(output)
            print("JSON output:")
            print(json.dumps(json_obj, indent=2))
        except json.JSONDecodeError:
            # If it's not valid JSON, print as is
            print("Non-JSON output:")
            print(output)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    pod_exec_tty()
