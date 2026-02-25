#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prometheus Memory Metrics CLI.

A command-line interface for querying Prometheus in an OpenShift cluster for container
memory usage data, filtering for specific pods and containers, and exporting to CSV.

This CLI provides commands to:
    - Query Prometheus for container memory usage data
    - Filter results for specific pods and containers
    - Export data to CSV with configurable parameters
"""

import csv
import json
import logging
import os
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import click
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from pyplayground.utils.k8s_utils import exec_pod_command
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging
logger = get_logger(__name__)

# Configuration constants
DEFAULT_NAMESPACE = "px-backup"
DEFAULT_TARGET_PODS = [
    "px-backup-57cd656c76-ftpgf",
    "pxc-backup-mongodb-0",
    "pxc-backup-mongodb-1",
    "pxc-backup-mongodb-2",
]
DEFAULT_TARGET_CONTAINERS = ["mongodb", "px-backup"]
DEFAULT_OUTPUT_FILE = "memory_usage_filtered_flexible.csv"
PROMETHEUS_NAMESPACE = "openshift-monitoring"
PROMETHEUS_SELECTOR = "app.kubernetes.io/name=prometheus"
PROMETHEUS_PORT = "9090"
STEP_SECONDS = 3600  # 1 hour


def get_prometheus_pod() -> Optional[str]:
    """Get the Prometheus pod name from the openshift-monitoring namespace.

    Returns:
        Pod name if found, None otherwise
    """
    try:
        # Load kubeconfig
        config.load_kube_config()
        v1 = client.CoreV1Api()

        # Get pods with the prometheus label
        pods = v1.list_namespaced_pod(namespace=PROMETHEUS_NAMESPACE, label_selector=PROMETHEUS_SELECTOR)

        if pods.items:
            pod_name = pods.items[0].metadata.name
            logger.info(f"Found Prometheus pod: {pod_name}")
            return pod_name
        else:
            logger.error(f"No Prometheus pods found in namespace {PROMETHEUS_NAMESPACE}")
            return None

    except ApiException as e:
        logger.error(f"Kubernetes API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting Prometheus pod: {e}")
        return None


def build_prometheus_query(namespace: str, target_pods: List[str], target_containers: List[str]) -> str:
    """Build the Prometheus query for container memory usage.

    Args:
        namespace: Kubernetes namespace to query
        target_pods: List of pod names to filter for
        target_containers: List of container names to filter for

    Returns:
        URL-encoded Prometheus query
    """
    # Create pod pattern for regex match
    pod_pattern = "|".join(target_pods)

    # Build the query
    query = f'container_memory_usage_bytes{{namespace="{namespace}",pod=~"{pod_pattern}"}}'

    logger.debug(f"Prometheus query: {query}")
    return query


def get_time_range(days: int = 30) -> Tuple[int, int]:
    """Get the time range for the specified number of days.

    Args:
        days: Number of days to look back (default: 30)

    Returns:
        Tuple of (start_time, end_time) as Unix timestamps
    """
    end_time = int(datetime.now().timestamp())
    start_time = end_time - (days * 24 * 60 * 60)  # days ago

    logger.info(f"Time range: {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}")
    return start_time, end_time


def query_prometheus_via_k8s(prometheus_pod: str, query: str, start_time: int, end_time: int, step: int = STEP_SECONDS) -> Optional[Dict[str, Any]]:
    """Query Prometheus via Kubernetes library exec command.

    Args:
        prometheus_pod: Name of the Prometheus pod
        query: Prometheus query string
        start_time: Start time as Unix timestamp
        end_time: End time as Unix timestamp
        step: Step size in seconds for data points

    Returns:
        JSON response from Prometheus or None if failed
    """
    try:
        # Build the Prometheus API URL
        api_url = f"http://localhost:{PROMETHEUS_PORT}/api/v1/query_range"

        # URL encode the query
        encoded_query = urllib.parse.quote(query)

        # Build the full URL with parameters
        full_url = f"{api_url}?query={encoded_query}&start={start_time}&end={end_time}&step={step}"

        logger.info(f"Querying Prometheus: {full_url}")

        # Execute curl command inside the Prometheus pod using Kubernetes library
        exit_code, stdout_data, stderr_data = exec_pod_command(
            namespace=PROMETHEUS_NAMESPACE,
            pod_name=prometheus_pod,
            command=["curl", "-g", full_url],
        )

        if exit_code != 0:
            logger.error(f"curl command failed with exit code {exit_code}")
            logger.error(f"stderr: {stderr_data}")
            return None

        # Parse the JSON response
        try:
            response_data = json.loads(stdout_data)
            logger.info("Successfully retrieved data from Prometheus")
            return response_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response content: {stdout_data}")
            return None

    except Exception as e:
        logger.error(f"Error querying Prometheus: {e}")
        return None


def filter_and_process_data(response_data: Dict[str, Any], target_pods: List[str], target_containers: List[str]) -> List[Dict[str, Any]]:
    """Filter and process the Prometheus response data.

    Args:
        response_data: JSON response from Prometheus
        target_pods: List of pod names to filter for
        target_containers: List of container names to filter for

    Returns:
        List of processed data points
    """
    processed_data = []

    if "data" not in response_data or "result" not in response_data["data"]:
        logger.error("Invalid response format from Prometheus")
        return processed_data

    results = response_data["data"]["result"]
    logger.info(f"Processing {len(results)} result series from Prometheus")

    for result in results:
        if "metric" not in result or "values" not in result:
            logger.warning("Skipping result with missing metric or values")
            continue

        metric = result["metric"]
        pod = metric.get("pod", "")
        container = metric.get("container", "")

        # Check if pod is in target list
        pod_in_target = pod in target_pods

        # Check if container is in target list
        container_in_target = container in target_containers

        # Process if either pod or container is in target list (inclusive OR)
        if pod_in_target or container_in_target:
            logger.debug(f"Processing pod: {pod}, container: {container}")

            # Process each timestamp-value pair
            for timestamp, value in result["values"]:
                if timestamp and value and value != "null" and timestamp != "null":
                    try:
                        # Convert timestamp to readable format
                        readable_time = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")

                        # Convert memory from bytes to MB
                        memory_bytes = float(value)
                        memory_mb = round(memory_bytes / (1024 * 1024), 2)

                        processed_data.append(
                            {
                                "timestamp": readable_time,
                                "pod": pod,
                                "container": container,
                                "memory_bytes": str(int(memory_bytes)),
                                "formatted_memory_mb": str(memory_mb),
                            }
                        )

                    except (ValueError, TypeError) as e:
                        logger.warning(f"Skipping invalid data point: {e}")
                        continue
        else:
            logger.debug(f"Skipping pod: {pod}, container: {container} (not in target list)")

    logger.info(f"Processed {len(processed_data)} data points")
    return processed_data


def write_csv_file(data: List[Dict[str, Any]], output_file: str) -> bool:
    """Write the processed data to a CSV file.

    Args:
        data: List of processed data points
        output_file: Path to the output CSV file

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["timestamp", "pod", "container", "memory_bytes", "formatted_memory_mb"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            # Write header
            writer.writeheader()

            # Write data
            writer.writerows(data)

        logger.info(f"Data exported to {output_file}")
        logger.info(f"Rows written: {len(data)}")
        return True

    except Exception as e:
        logger.error(f"Failed to write CSV file: {e}")
        return False


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, verbose, debug):
    """Prometheus Memory Metrics CLI.

    A command-line interface for querying Prometheus in an OpenShift cluster
    for container memory usage data and exporting to CSV.
    """
    # Ensure that ctx.obj exists and is a dict
    ctx.ensure_object(dict)

    # Setup logging based on flags
    script_base_name = os.path.basename(__file__).replace(".py", "")
    if debug:
        log_level = logging.DEBUG
    elif verbose:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

    setup_logging(level=log_level, script_name=script_base_name)
    logger.info("Starting Prometheus Memory Metrics CLI")


@cli.command()
@click.option(
    "--namespace",
    "-n",
    default=DEFAULT_NAMESPACE,
    help=f"Kubernetes namespace to query (default: {DEFAULT_NAMESPACE})",
)
@click.option(
    "--pods",
    "-p",
    multiple=True,
    default=DEFAULT_TARGET_PODS,
    help="Target pod names (can be specified multiple times)",
)
@click.option(
    "--containers",
    "-c",
    multiple=True,
    default=DEFAULT_TARGET_CONTAINERS,
    help="Target container names (can be specified multiple times)",
)
@click.option(
    "--output",
    "-o",
    default=DEFAULT_OUTPUT_FILE,
    help=f"Output CSV file path (default: {DEFAULT_OUTPUT_FILE})",
)
@click.option("--days", "-d", default=30, type=int, help="Number of days to look back (default: 30)")
@click.option(
    "--step",
    "-s",
    default=3600,
    type=int,
    help="Step size in seconds for data points (default: 3600)",
)
@click.pass_context
def query(ctx, namespace, pods, containers, output, days, step):
    """Query Prometheus for container memory usage metrics.

    This command queries Prometheus in an OpenShift cluster for container memory
    usage data over the specified time range, filtering for specific pods and
    containers, and exports the data to a CSV file.
    """
    try:
        # Convert tuples to lists for consistency
        target_pods = list(pods) if pods else DEFAULT_TARGET_PODS
        target_containers = list(containers) if containers else DEFAULT_TARGET_CONTAINERS

        logger.info("Starting Prometheus memory metrics query")
        logger.info(f"Namespace: {namespace}")
        logger.info(f"Target pods: {target_pods}")
        logger.info(f"Target containers: {target_containers}")
        logger.info(f"Output file: {output}")
        logger.info(f"Days back: {days}")
        logger.info(f"Step seconds: {step}")

        # Step 1: Get Prometheus pod
        with click.progressbar(length=5, label="Querying Prometheus") as bar:
            click.echo("Step 1: Finding Prometheus pod...")
            prometheus_pod = get_prometheus_pod()
            if not prometheus_pod:
                raise click.ClickException("Failed to find Prometheus pod")
            bar.update(1)

            # Step 2: Build query and get time range
            click.echo("Step 2: Building query and time range...")
            query_str = build_prometheus_query(namespace, target_pods, target_containers)
            start_time, end_time = get_time_range(days)
            bar.update(1)

            # Step 3: Query Prometheus
            click.echo("Step 3: Querying Prometheus...")
            response_data = query_prometheus_via_k8s(prometheus_pod, query_str, start_time, end_time, step)
            if not response_data:
                raise click.ClickException("Failed to query Prometheus")
            bar.update(1)

            # Step 4: Process and filter data
            click.echo("Step 4: Processing and filtering data...")
            processed_data = filter_and_process_data(response_data, target_pods, target_containers)
            if not processed_data:
                raise click.ClickException("No data points found after filtering")
            bar.update(1)

            # Step 5: Write to CSV
            click.echo("Step 5: Writing data to CSV...")
            if not write_csv_file(processed_data, output):
                raise click.ClickException("Failed to write CSV file")
            bar.update(1)

        click.echo(f"✅ Successfully exported {len(processed_data)} records to {output}")

    except click.ClickException:
        raise
    except KeyboardInterrupt:
        click.echo("\n❌ Operation interrupted by user", err=True)
        raise click.Abort()
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command()
@click.option(
    "--namespace",
    "-n",
    default=PROMETHEUS_NAMESPACE,
    help=f"Namespace to search for Prometheus pod (default: {PROMETHEUS_NAMESPACE})",
)
def list_pods(namespace):
    """List available Prometheus pods in the cluster."""
    try:
        click.echo(f"Searching for Prometheus pods in namespace: {namespace}")
        prometheus_pod = get_prometheus_pod()
        if prometheus_pod:
            click.echo(f"✅ Found Prometheus pod: {prometheus_pod}")
        else:
            click.echo(f"❌ No Prometheus pods found in namespace {namespace}")
    except Exception as e:
        raise click.ClickException(f"Error listing pods: {e}")


@cli.command()
@click.option(
    "--namespace",
    "-n",
    default=DEFAULT_NAMESPACE,
    help=f"Namespace to query (default: {DEFAULT_NAMESPACE})",
)
def test_connection(namespace):
    """Test connection to Prometheus and Kubernetes cluster."""
    try:
        click.echo("Testing Kubernetes connection...")
        prometheus_pod = get_prometheus_pod()
        if not prometheus_pod:
            raise click.ClickException("Failed to find Prometheus pod")

        click.echo("✅ Kubernetes connection successful")
        click.echo(f"✅ Found Prometheus pod: {prometheus_pod}")

        # Test a simple query
        click.echo("Testing Prometheus query...")
        test_query = f'up{{namespace="{namespace}"}}'
        start_time, end_time = get_time_range(1)  # Last 1 day for test

        response_data = query_prometheus_via_k8s(prometheus_pod, test_query, start_time, end_time, 3600)
        if response_data:
            click.echo("✅ Prometheus query successful")
        else:
            raise click.ClickException("Failed to query Prometheus")

    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Connection test failed: {e}")


if __name__ == "__main__":
    cli()
