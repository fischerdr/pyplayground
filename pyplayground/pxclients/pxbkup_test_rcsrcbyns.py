#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""This is a quick test script to balance the namespaces across the label values by resource count.

This script is not intended for production use.

Usage:
    pxbkup_test_rcsrcbyns.py --kubeconfig <path_to_kubeconfig> --exclude <namespace1> <namespace2>

Example:
    pxbkup_test_rcsrcbyns.py --kubeconfig ~/.kube/config --exclude default

"""

import json
import logging
import os

import click
from kubernetes import client, config

# Configure logging
logging.basicConfig(
    filename="kube_namespace_manager.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Hardcoded label keys and values
LABEL_KEYS = [
    "storage/pxbackup.kubernetes.io",
    "resources/pxbackup.kubernetes.io",
    "all/pxbackup.kubernetes.io",
]
LABEL_VALUES = ["4am", "8am", "12pm", "4pm", "8pm", "12am"]


# Load Kubernetes configuration
def load_kube_config(kubeconfig_path):
    """Load Kubernetes configuration from a kubeconfig file."""
    try:
        if kubeconfig_path:
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            config.load_kube_config()
    except Exception as e:
        logger.error(f"Error loading kubeconfig: {e}")
        raise


# Get namespace data
def get_namespace_data(excluded_namespaces):  # noqa: C901
    """Get namespace data from the cluster."""
    try:
        api = client.CustomObjectsApi()
        core_v1 = client.CoreV1Api()
        crd_api = client.ApiextensionsV1Api()

        # Get all CRDs in the cluster
        crds = crd_api.list_custom_resource_definition().items

        # Initialize data structure
        namespace_data = {
            label_key: {
                label_value: {"namespaces": [], "total_resource_count": 0}
                for label_value in LABEL_VALUES
            }
            for label_key in LABEL_KEYS
        }
        unassigned_data = {"namespaces": [], "total_resource_count": 0}

        # Fetch all namespaces
        for ns in core_v1.list_namespace().items:
            name = ns.metadata.name

            # Exclude namespaces explicitly mentioned
            if name in excluded_namespaces:
                continue

            # Check namespace labels
            ns_labels = ns.metadata.labels or {}
            assigned_label_key = None
            assigned_label_value = None

            for label_key in LABEL_KEYS:
                if ns_labels.get(label_key) in LABEL_VALUES:
                    assigned_label_key = label_key
                    assigned_label_value = ns_labels[label_key]
                    break

            resource_count = 0

            # Count CRD instances in the namespace
            for crd in crds:
                group = crd.spec.group
                version = crd.spec.versions[0].name
                plural = crd.spec.names.plural

                try:
                    resources = api.list_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=name,
                        plural=plural,
                    )
                    resource_count += len(resources["items"])
                except client.exceptions.ApiException as e:
                    if e.status != 404:  # Log only non-404 errors
                        logger.error(f"Error fetching CRD {plural} in namespace {name}: {e}")

            if assigned_label_key and assigned_label_value:
                namespace_data[assigned_label_key][assigned_label_value]["namespaces"].append(name)
                namespace_data[assigned_label_key][assigned_label_value][
                    "total_resource_count"
                ] += resource_count
            else:
                unassigned_data["namespaces"].append(name)
                unassigned_data["total_resource_count"] += resource_count

        # Balance namespaces across label values by resource count
        for label_key in LABEL_KEYS:
            all_namespaces = []
            for label_value in LABEL_VALUES:
                print(namespace_data[label_key][label_value]["namespaces"])
                all_namespaces.extend(namespace_data[label_key][label_value]["namespaces"])

            # Sort all namespaces by their resource count (descending)
            all_namespaces.sort(key=lambda x: x["resource_count"], reverse=True)

            # Distribute namespaces across label values
            balanced_namespaces = {label_value: [] for label_value in LABEL_VALUES}
            for ns in all_namespaces:
                # Find the label value with the least total resources
                min_label_value = min(
                    LABEL_VALUES,
                    key=lambda lv: sum(ns["resource_count"] for ns in balanced_namespaces[lv]),
                )
                balanced_namespaces[min_label_value].append(ns)

            # Update the data with balanced namespaces
            for label_value in LABEL_VALUES:
                namespace_data[label_key][label_value]["namespaces"] = [
                    ns["name"] for ns in balanced_namespaces[label_value]
                ]
                namespace_data[label_key][label_value]["total_resource_count"] = sum(
                    ns["resource_count"] for ns in balanced_namespaces[label_value]
                )

        return namespace_data, unassigned_data

    except Exception as e:
        logger.error(f"Error gathering namespace data: {e} - line {e.__traceback__.tb_lineno}")
        raise  # Re-raise the exception for further handling if needed
    finally:
        logger.info("Completed namespace data collection.")


@click.command()
@click.option(
    "--kubeconfig",
    default=None,
    help="Path to kubeconfig file. Uses the KUBECONFIG environment variable if not provided.",
)
@click.option(
    "--exclude",
    multiple=True,
    default=[],
    help="Namespaces to exclude from the analysis. Can be specified multiple times.",
)
def main(kubeconfig, exclude):
    """Main function to execute the script."""
    try:
        # Load Kubernetes configuration
        kubeconfig_path = kubeconfig or os.getenv("KUBECONFIG")
        load_kube_config(kubeconfig_path)

        # Get namespace data
        excluded_namespaces = set(exclude)
        namespace_data, unassigned_data = get_namespace_data(excluded_namespaces)

        # Add unassigned group to the output
        output = {"namespace_data": namespace_data, "unassigned": unassigned_data}

        # Print output as JSON
        print(json.dumps(output, indent=4))

    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        click.echo("An error occurred. Check the log file for details.", err=True)


if __name__ == "__main__":
    main()
