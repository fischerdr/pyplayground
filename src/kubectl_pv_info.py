#!/usr/bin/env python3
"""
Script to list all PersistentVolumeClaims (PVCs) with their StorageClass and PersistentVolumes (PVs).

This script uses the Kubernetes API to gather information about storage resources in a cluster.
It provides details about PVCs, their associated StorageClasses, and PVs.
Date: 2025-01-27
"""

import logging
import sys
from typing import Dict, List

import click
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/kubectl_pv_info.log"),
    ],
)

logger = logging.getLogger(__name__)


def setup_kubernetes_client() -> None:
    """
    Initialize the Kubernetes client configuration.

    Attempts to load either in-cluster config or local kubeconfig.
    """
    try:
        config.load_incluster_config()
        logger.debug("Loaded in-cluster Kubernetes configuration")
    except config.ConfigException:
        try:
            config.load_kube_config()
            logger.debug("Loaded local Kubernetes configuration")
        except config.ConfigException as e:
            logger.error("Failed to load Kubernetes configuration: %s", str(e))
            sys.exit(1)


def get_storage_resources() -> tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Retrieve PVCs, PVs, and StorageClasses from the Kubernetes cluster.

    Returns:
        tuple: Contains lists of PVCs, PVs, and StorageClasses
    """
    v1 = client.CoreV1Api()
    storage_v1 = client.StorageV1Api()

    try:
        pvcs = v1.list_persistent_volume_claim_for_all_namespaces().items
        pvs = v1.list_persistent_volume().items
        storage_classes = storage_v1.list_storage_class().items

        logger.info("Successfully retrieved Kubernetes storage resources")
        return pvcs, pvs, storage_classes
    except ApiException as e:
        logger.error("Failed to retrieve Kubernetes resources: %s", str(e))
        sys.exit(1)


def format_storage_info(pvcs: List[Dict], pvs: List[Dict], storage_classes: List[Dict]) -> None:
    """
    Format and display storage information for all PVCs with their StorageClass and PV details.

    Args:
        pvcs: List of PersistentVolumeClaims
        pvs: List of PersistentVolumes
        storage_classes: List of StorageClasses
    """
    # Create lookup dictionary for PVs
    pv_dict = {pv.metadata.name: pv for pv in pvs}
    print("\nPersistentVolumeClaim Information:")
    print("-" * 100)
    print(
        f"{'NAMESPACE':<20} {'PVC NAME':<30} {'STORAGE CLASS':<20} "
        f"{'SIZE':<10} {'STATUS':<10} {'PV NAME':<20}"
    )
    print("-" * 100)

    for pvc in pvcs:
        namespace = pvc.metadata.namespace
        name = pvc.metadata.name
        storage_class = pvc.spec.storage_class_name or "default"
        size = pvc.spec.resources.requests.get("storage", "N/A")
        status = pvc.status.phase
        pv_name = pvc.spec.volume_name if pvc.spec.volume_name else "N/A"

        print(
            f"{namespace:<20} {name:<30} {storage_class:<20} "
            f"{size:<10} {status:<10} {pv_name:<20}"
        )

        if pv_name != "N/A" and pv_name in pv_dict:
            pv = pv_dict[pv_name]
            logger.debug("Found matching PV for PVC %s/%s: %s", namespace, name, pv_name)


@click.command()
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(debug: bool) -> None:
    """
    List all PVCs with their StorageClass and PV information in the Kubernetes cluster.

    This command provides a comprehensive view of storage resources in your cluster,
    including PVCs, their associated StorageClasses, and PV details.
    """
    if debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    logger.info("Starting Kubernetes storage information retrieval")
    setup_kubernetes_client()
    pvcs, pvs, storage_classes = get_storage_resources()
    format_storage_info(pvcs, pvs, storage_classes)
    logger.info("Completed storage information retrieval")


if __name__ == "__main__":
    main()
