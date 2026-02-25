#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executes a command in a pod and verifies the output."""
# import threading
from concurrent.futures import ThreadPoolExecutor

import click
from kubernetes import client, config

"""
Explanation of the Script:

    Arguments:
        --kubeconfig: Path to your kubeconfig file to connect to the Kubernetes cluster.
        --namespace: Namespace to search for pods.
        --label-selector: Label selector to filter the pods.
        --command: Command to execute on each selected pod.
        --threads: Number of threads to use for parallel execution (default is 5).

    Execution Logic:
        Loads the Kubernetes configuration from the specified kubeconfig.
        Connects to the Kubernetes API and lists pods in the provided namespace with the specified label selector.
        Uses a function to execute a shell command on each pod, utilizing Kubernetes API’s read_namespaced_pod_exec.
        Utilizes a thread pool to run commands on multiple pods in parallel.

    Results Dictionary:
        results dictionary is used to store the output from each pod, with pod names as keys and command outputs as values.

    Pass/Fail Grouping:
        pass_results stores pods where the output contains the specified pass_keyword.
        fail_results stores pods where the output does not contain pass_keyword.

    Pass/Fail Keyword:
        The --pass-keyword argument lets you define a keyword that indicates success. This keyword is used to determine if the command output should be marked as "pass" or "fail."

Usage Example

You can run the script as follows:

python script.py --kubeconfig ~/.kube/config --namespace my-namespace --label-selector app=myapp --command "ls /" --threads 10 --pass-keyword "bin"

This will run ls / on each pod and mark it as "pass" if the output contains "bin", grouping pods into passing and failing categories based on this condition. Adjust the command and pass/fail criteria as needed

"""


# Define the command-line interface
@click.command()
@click.option("--kubeconfig", type=click.Path(exists=True), help="Path to kubeconfig file", required=True)
@click.option("--namespace", help="Kubernetes namespace", required=True)
@click.option("--label-selector", help="Label selector to filter pods", required=True)
@click.option("--command", help="Command to run on each pod", required=True)
@click.option("--threads", default=5, help="Number of threads for parallel execution", show_default=True)
@click.option(
    "--pass-keyword",
    default="success",
    help="Keyword to consider command output as 'pass'",
    show_default=True,
)
def execute_on_pods(kubeconfig, namespace, label_selector, command, threads, pass_keyword):
    """Connect to the Kubernetes cluster, filter pods by namespace and label,run a command on each pod in parallel, and group results by pass/fail.

    Args:
        kubeconfig: Path to the kubeconfig file.
        namespace: Namespace to search for pods.
        label_selector: Label selector to filter the pods.
        command: Command to execute on each selected pod.
        threads: Number of threads to use for parallel execution.
        pass_keyword: Keyword to consider command output as 'pass'.

    Returns:
        None

    """
    # Load kubeconfig
    config.load_kube_config(config_file=kubeconfig)

    # Initialize Kubernetes API client
    v1 = client.CoreV1Api()

    # Dictionary to store results
    results = {}

    # Get list of pods matching the label selector in the specified namespace
    try:
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
    except client.exceptions.ApiException as e:
        click.echo(f"Error fetching pods: {e}")
        return

    # Function to execute command on each pod
    def run_command_on_pod(pod_name):
        try:
            response = v1.read_namespaced_pod_exec(
                pod_name,
                namespace,
                command=["/bin/sh", "-c", command],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            results[pod_name] = response
        except client.exceptions.ApiException as e:
            results[pod_name] = f"Error: {e}"

    # Multithreading execution
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(run_command_on_pod, pod.metadata.name) for pod in pods.items]
        for future in futures:
            future.result()  # Wait for all threads to complete

    # Group results into pass and fail based on pass_keyword presence in the output
    pass_results = {pod: output for pod, output in results.items() if pass_keyword in output}
    fail_results = {pod: output for pod, output in results.items() if pass_keyword not in output}

    # Display results
    click.echo("\nPASSING PODS:")
    for pod, output in pass_results.items():
        click.echo(f"{pod}:\n{output}")

    click.echo("\nFAILING PODS:")
    for pod, output in fail_results.items():
        click.echo(f"{pod}:\n{output}")


if __name__ == "__main__":
    execute_on_pods()
