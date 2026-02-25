#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""This script is used to balance the namespaces across the label values by resource count.

This script is not intended for production use.

Usage:
    pxbkup_nsbyrcsr.py --kubeconfig <path_to_kubeconfig> --exclude <namespace1> <namespace2>

Example:
    pxbkup_nsbyrcsr.py --kubeconfig ~/.kube/config --exclude default
"""
import os
import re

import click
from kubernetes import client, config
from kubernetes.client.rest import ApiException


def load_k8s_config(kubeconfig_path=None):
    """Load Kubernetes configuration from a kubeconfig file."""
    if kubeconfig_path:
        config.load_kube_config(kubeconfig_path)
    else:
        config.load_kube_config(os.environ.get("KUBECONFIG"))


def get_namespaces(exclude_regex=None):
    """Get namespaces in the cluster."""
    v1 = client.CoreV1Api()
    namespaces = v1.list_namespace()
    filtered_namespaces = []

    for ns in namespaces.items:
        if exclude_regex and re.match(exclude_regex, ns.metadata.name):
            continue
        filtered_namespaces.append(ns.metadata.name)

    return filtered_namespaces


def get_labels_for_namespace(namespace):
    """Get labels for a namespace."""
    v1 = client.CoreV1Api()
    try:
        ns = v1.read_namespace(namespace)
        return ns.metadata.labels or {}
    except ApiException as e:
        print(f"Failed to get labels for namespace {namespace}: {e}")
        return {}


def count_crd_instances(crds, namespace):
    """Count instances of a CRD in a given namespace."""
    crd_client = client.CustomObjectsApi()
    try:
        group = crds.spec.group
        version = crds.spec.versions[0].name
        plural = crds.spec.names.plural
        instances = crd_client.list_namespaced_custom_object(
            group=group,  # Replace with the group of your CRDs
            version=version,  # Replace with the version of your CRDs
            namespace=namespace,
            plural=plural,  # Plural name of the CRD
        )
        return len(instances.get("items", []))
    except ApiException as e:
        if e.status != 404:  # Log only non-404 errors
            print(f"Failed to count CRD instances for {crds.spec.names.plural} in namespace {namespace}: {e}")
        return 0


def get_crds():
    """Get all CRDs in the cluster."""
    crd_client = client.ApiextensionsV1Api()
    crds = crd_client.list_custom_resource_definition().items
    return crds


def process_namespaces(namespaces, exclude_regex=None):
    """Process namespaces and their labels."""
    label_values = ["4am", "8am", "12pm", "4pm", "8pm", "12am"]
    grouped_data = {}

    for ns in namespaces:
        labels = get_labels_for_namespace(ns)

        # Check for relevant labels
        for label, value in labels.items():
            if label.startswith("storage/pxbackup.kubernetes.io") or label.startswith("resources/pxbackup.kubernetes.io") or label.startswith("all/pxbackup.kubernetes.io"):
                if value in label_values:
                    if label not in grouped_data:
                        grouped_data[label] = {value: {"count": 0, "namespaces": []}}

                    # Add namespace and increment count
                    grouped_data[label][value]["count"] += get_namespace_count(ns)
                    grouped_data[label][value]["namespaces"].append(ns)

    return grouped_data


def get_namespace_count(namespace):
    """Process namespaces and count CRD instances (total instances per namespace)."""
    namespace_count = 0
    crds = get_crds()  # Get the list of CRDs in the cluster
    total_crd_instances = 0
    for crd in crds:
        total_crd_instances += count_crd_instances(crd, namespace)
    namespace_count = total_crd_instances
    return namespace_count


def process_namespace_counts(namespaces):
    """Process namespaces and count CRD instances (total instances per namespace)."""
    namespace_counts = {}
    crds = get_crds()  # Get the list of CRDs in the cluster

    for ns in namespaces:
        total_crd_instances = 0
        for crd in crds:
            total_crd_instances += count_crd_instances(crd, ns)
        namespace_counts[ns] = total_crd_instances

    return namespace_counts


def distribute_input_keys(input_dict):
    """Evenly distribute keys from the input dictionary into six groups based on their 'count' values.

    Args:
        input_dict (dict): A dictionary where each key contains a nested dictionary with a 'count' key.

    Returns:
        dict: A dictionary with specified keys ('4am', '8am', '12pm', '4pm', '8pm', '12am')
              containing evenly distributed input keys and their totals.
        int: The total count of all 'count' values from the input dictionary.
    """
    # Ensure all keys in the input dictionary have a 'count' key
    for key, value in input_dict.items():
        if not isinstance(value, dict) or "count" not in value:
            raise ValueError(f"Each key in the input dictionary must contain a nested 'count' key. Problem with key: {key}")

    # Calculate the total count across all input counts
    total_count = sum(value["count"] for value in input_dict.values())

    # Sort the input dictionary by the 'count' values (descending order)
    sorted_items = sorted(input_dict.items(), key=lambda x: x[1]["count"], reverse=True)

    # Initialize the six groups with custom keys
    group_labels = ["4am", "8am", "12pm", "4pm", "8pm", "12am"]
    groups = {label: {"keys": [], "total_count": 0} for label in group_labels}

    # Distribute keys into groups to balance the total count
    for key, value in sorted_items:
        # Find the group with the smallest current count
        smallest_group = min(groups.values(), key=lambda x: x["total_count"])
        # Add the key to that group
        for group_label, group_data in groups.items():
            if group_data == smallest_group:
                group_data["keys"].append(key)
                group_data["total_count"] += value["count"]
                break

    # Prepare the output dictionary
    output_dict = {label: {"keys": data["keys"], "total_count": data["total_count"]} for label, data in groups.items()}
    return output_dict, total_count


# Function to split namespaces evenly across the values of 'all/pxbackup.kubernetes.io'
def split_namespaces_evenly_by_value(namespaces, label="all/pxbackup.kubernetes.io", label_values=None):
    """Split namespaces evenly across the values of 'all/pxbackup.kubernetes.io' label."""
    label_values = label_values or ["4am", "8am", "12pm", "4pm", "8pm", "12am"]

    # Create an empty dictionary to hold the grouped namespaces by label values
    evenly_grouped = {value: [] for value in label_values}

    # Gather namespaces with the label 'all/pxbackup.kubernetes.io'
    for ns in namespaces:
        labels = get_labels_for_namespace(ns)
        if label in labels:
            value = labels[label]
            if value in label_values:
                evenly_grouped[value].append(ns)

    # Split namespaces evenly across values
    all_namespaces = []
    for value, namespaces_list in evenly_grouped.items():
        all_namespaces.extend(namespaces_list)

    # Now we distribute these namespaces evenly across the label values
    value_count = len(label_values)
    namespace_chunks = [all_namespaces[i::value_count] for i in range(value_count)]

    # Assign the evenly distributed namespaces back into the group
    evenly_distributed = {}
    for idx, value in enumerate(label_values):
        evenly_distributed[value] = namespace_chunks[idx]

    return evenly_distributed


# Function to split unassigned namespaces evenly into a new group by label and values
def split_unassigned_namespaces_evenly(namespaces, label_values=None):
    """Split unassigned namespaces evenly across the values of labels.

    Args:
        namespaces (list): A list of namespaces to split.
        label_values (list): A list of label values to split the namespaces across.

    Returns:
        dict: A dictionary with the label values as keys and the namespaces as values.

    EXAMPLE label values:
    storage/pxbackup.kubernetes.io, resources/pxbackup.kubernetes.io, and all/pxbackup.kubernetes.io.
    """
    label_values = label_values or ["4am", "8am", "12pm", "4pm", "8pm", "12am"]

    # Identify unassigned namespaces (those without one of the three labels)
    unassigned_namespaces = []
    for ns in namespaces:
        labels = get_labels_for_namespace(ns)
        if not any(
            label in labels
            for label in [
                "storage/pxbackup.kubernetes.io",
                "resources/pxbackup.kubernetes.io",
                "all/pxbackup.kubernetes.io",
            ]
        ):
            unassigned_namespaces.append(ns)

    # Now distribute these unassigned namespaces evenly across the label values
    evenly_distributed = {value: [] for value in label_values}

    # Split unassigned namespaces evenly into groups
    unassigned_chunked = [unassigned_namespaces[i :: len(label_values)] for i in range(len(label_values))]

    for idx, value in enumerate(label_values):
        evenly_distributed[value].extend(unassigned_chunked[idx])

    return evenly_distributed


def display_grouped_data(grouped_data):
    """Function to display grouped results (labels, values, counts, namespaces)."""
    print("\n--- Grouped Data: Labels, Values, Counts, and Namespaces ---")
    for label, values in grouped_data.items():
        print(f"Label: {label}")
        for value, data in values.items():
            # Display count of namespaces for each value
            namespace_count = len(data["namespaces"])
            print(f"  Value: {value}")
            print(f"    Namespace Count: {namespace_count}")
            print(f"    Count: {data['count']}")
            print(f"    Namespaces: {', '.join(data['namespaces'])}")
            print()


def display_namespace_counts(namespace_counts):
    """Function to display CRD count group (namespaces and total CRD instances)."""
    print("\n--- Namespace Count Group: Namespaces and Total CRD Instances ---")
    for namespace, crd_count in namespace_counts.items():
        print(f"Namespace: {namespace}, Total CRD Instances: {crd_count}")


def display_evenly_distributed_namespaces(evenly_distributed):
    """Function to display the evenly distributed namespaces by label value."""
    print("\n--- Evenly Distributed Namespaces by Label Value ---")
    for value, namespaces in evenly_distributed.items():
        print(f"Value: {value}")
        print(f"  Number of Namespaces: {len(namespaces)}")
        print(f"  Namespaces: {', '.join(namespaces)}")
        print()


def display_unassigned_namespaces(evenly_distributed):
    """Function to display the evenly distributed unassigned namespaces by label value."""
    print("\n--- Evenly Distributed Unassigned Namespaces by Label Value ---")
    for value, namespaces in evenly_distributed.items():
        print(f"Value: {value}")
        print(f"  Number of Namespaces: {len(namespaces)}")
        print(f"  Namespaces: {', '.join(namespaces)}")
        print()


# Updated main function to process and display unassigned namespaces
@click.command()
@click.option("--kubeconfig", default=None, help="Path to kubeconfig file.")
@click.option("--exclude-namespaces", default=None, help="Regex to exclude namespaces.")
def main(kubeconfig, exclude_namespaces):
    """Main function to process and display unassigned namespaces."""
    # Load Kubernetes configuration
    load_k8s_config(kubeconfig)

    # Get namespaces, optionally excluding based on regex
    namespaces = get_namespaces(exclude_namespaces)

    # Process namespaces for label-based grouping (label, value, counts, namespaces)
    grouped_data = process_namespaces(namespaces, exclude_namespaces)

    # Process namespaces for CRD instance counts (total instances per namespace)
    namespace_counts = process_namespace_counts(namespaces)

    # Split namespaces evenly by the value of 'all/pxbackup.kubernetes.io' label
    evenly_distributed = split_namespaces_evenly_by_value(namespaces)

    # Split unassigned namespaces evenly by label values
    unassigned_distributed = split_unassigned_namespaces_evenly(namespaces)

    # Display grouped data by labels, values, counts, and namespaces
    display_grouped_data(grouped_data)

    # Display namespace count group (namespaces and total CRD instances)
    display_namespace_counts(namespace_counts)

    # Display the evenly distributed namespaces
    display_evenly_distributed_namespaces(evenly_distributed)

    # Display the evenly distributed unassigned namespaces
    display_unassigned_namespaces(unassigned_distributed)


if __name__ == "__main__":
    main()
