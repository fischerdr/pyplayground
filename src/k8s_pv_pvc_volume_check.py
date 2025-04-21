#!/usr/bin/env python3
"""Kubernetes PV and PVC Storage Type Analyzer.

This script analyzes PVs and PVCs in the cluster and categorizes namespaces based on their
storage types (NFS vs non-NFS). It provides a clear overview of which namespaces use
different storage types.
"""

import logging
import os
from typing import Dict, List, Set, Tuple

import click  # Import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.table import Table

from utils.k8s_utils import load_kube_config_auto  # Import k8s util
from utils.logging_utils import get_logger, setup_logging  # Import logging utils

console = Console()


class K8sStorageAnalyzer:
    """Analyzes Kubernetes storage resources and categorizes namespaces by storage type."""

    def __init__(self):
        """Initialize the Kubernetes Storage Analyzer. Assumes K8s config is loaded."""
        self.logger = get_logger(__name__)  # Use get_logger from utils
        # Initialize k8s client directly, assuming config is loaded before instantiation
        try:
            self.core_v1 = client.CoreV1Api()
            self.logger.debug("Kubernetes CoreV1Api client initialized.")
        except Exception as e:
            self.logger.error(f"Failed to initialize Kubernetes client: {e}")
            # Raising here might be better handled in the main function
            raise RuntimeError(f"Kubernetes client initialization failed: {e}")

    def get_all_pvs(self) -> List[Dict]:
        """Get all PersistentVolumes in the cluster.

        Returns:
            List of PV dictionaries.
        """
        try:
            self.logger.debug("Fetching all PersistentVolumes.")
            pvs = self.core_v1.list_persistent_volume()
            self.logger.info(f"Found {len(pvs.items)} PersistentVolumes.")
            return [pv.to_dict() for pv in pvs.items]
        except ApiException as e:
            self.logger.error(f"Failed to get PVs: {e.status} - {e.reason}")
            console.print(f"[bold red]API Error:[/bold red] Could not list PVs. Reason: {e.reason}")
            return []
        except Exception as e:
            self.logger.exception(f"Unexpected error getting PVs: {e}")
            console.print(f"[bold red]Error:[/bold red] Unexpected error listing PVs: {e}")
            return []

    def get_all_pvcs(self) -> List[Dict]:
        """Get all PersistentVolumeClaims in the cluster.

        Returns:
            List of PVC dictionaries.
        """
        try:
            self.logger.debug("Fetching all PersistentVolumeClaims.")
            pvcs = self.core_v1.list_persistent_volume_claim_for_all_namespaces()
            self.logger.info(
                f"Found {len(pvcs.items)} PersistentVolumeClaims across all namespaces."
            )
            return [pvc.to_dict() for pvc in pvcs.items]
        except ApiException as e:
            self.logger.error(f"Failed to get PVCs: {e.status} - {e.reason}")
            console.print(
                f"[bold red]API Error:[/bold red] Could not list PVCs. Reason: {e.reason}"
            )
            return []
        except Exception as e:
            self.logger.exception(f"Unexpected error getting PVCs: {e}")
            console.print(f"[bold red]Error:[/bold red] Unexpected error listing PVCs: {e}")
            return []

    def get_all_namespaces(self) -> List[Dict]:
        """Get all namespaces in the cluster.

        Returns:
            List of namespace dictionaries.
        """
        try:
            self.logger.debug("Fetching all Namespaces.")
            namespaces = self.core_v1.list_namespace()
            self.logger.info(f"Found {len(namespaces.items)} Namespaces.")
            return [ns.to_dict() for ns in namespaces.items]
        except ApiException as e:
            self.logger.error(f"Failed to get namespaces: {e.status} - {e.reason}")
            console.print(
                f"[bold red]API Error:[/bold red] Could not list Namespaces. Reason: {e.reason}"
            )
            return []
        except Exception as e:
            self.logger.exception(f"Unexpected error getting Namespaces: {e}")
            console.print(f"[bold red]Error:[/bold red] Unexpected error listing Namespaces: {e}")
            return []

    def _is_nfs_pv(self, pv: Dict) -> bool:
        """Check if a PV is NFS type.

        Args:
            pv: PersistentVolume dictionary.

        Returns:
            True if the PV is NFS type, False otherwise.
        """
        is_nfs = pv.get("spec", {}).get("nfs") is not None
        self.logger.debug(f"PV '{pv.get('metadata', {}).get('name', 'N/A')}' is NFS: {is_nfs}")
        return is_nfs

    def _build_pv_type_map(self, pvs: List[Dict]) -> Dict[str, bool]:
        """Build a map of PV name to its NFS status.

        Args:
            pvs: List of PV dictionaries.

        Returns:
            Dictionary mapping PV name (str) to NFS status (bool).
        """
        pv_type_map = {
            pv["metadata"]["name"]: self._is_nfs_pv(pv)
            for pv in pvs
            if "metadata" in pv and "name" in pv["metadata"]
        }
        self.logger.debug(f"Built PV type map for {len(pv_type_map)} PVs.")
        return pv_type_map

    def _calculate_namespace_storage(
        self, pvcs: List[Dict], pv_type_map: Dict[str, bool]
    ) -> Dict[str, Dict[str, bool]]:
        """Calculate storage types used per namespace based on PVCs.

        Args:
            pvcs: List of PVC dictionaries.
            pv_type_map: Dictionary mapping PV name to NFS status.

        Returns:
            Dictionary mapping namespace name to its storage types ({'nfs': bool, 'non_nfs': bool}).
        """
        namespace_storage: Dict[str, Dict[str, bool]] = {}
        for pvc in pvcs:
            namespace = pvc.get("metadata", {}).get("namespace")
            pv_name = pvc.get("spec", {}).get("volume_name")

            if not namespace:
                self.logger.warning(
                    f"Skipping PVC with missing namespace: {pvc.get('metadata', {}).get('name', 'N/A')}"
                )
                continue

            if pv_name and pv_name in pv_type_map:
                if namespace not in namespace_storage:
                    namespace_storage[namespace] = {"nfs": False, "non_nfs": False}

                if pv_type_map[pv_name]:  # If the PV is NFS
                    if not namespace_storage[namespace]["nfs"]:
                        self.logger.debug(
                            f"Namespace '{namespace}' uses NFS storage (via PVC '{pvc.get('metadata', {}).get('name')}' -> PV '{pv_name}')."
                        )
                        namespace_storage[namespace]["nfs"] = True
                else:  # If the PV is non-NFS
                    if not namespace_storage[namespace]["non_nfs"]:
                        self.logger.debug(
                            f"Namespace '{namespace}' uses non-NFS storage (via PVC '{pvc.get('metadata', {}).get('name')}' -> PV '{pv_name}')."
                        )
                        namespace_storage[namespace]["non_nfs"] = True
            elif pv_name:
                # PVC is bound but PV not found in our list (could be timing or error in get_pvs)
                self.logger.warning(
                    f"PVC '{namespace}/{pvc.get('metadata', {}).get('name')}' references PV '{pv_name}' which was not found."
                )
            else:
                # PVC is not bound or has no volumeName yet
                pvc_status = pvc.get("status", {}).get("phase", "Unknown")
                self.logger.debug(
                    f"PVC '{namespace}/{pvc.get('metadata', {}).get('name')}' is in phase '{pvc_status}' and has no volumeName."
                )
        return namespace_storage

    def _categorize_namespaces(
        self, namespace_storage: Dict[str, Dict[str, bool]], all_namespaces: List[Dict]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """Categorize namespaces into storage type groups.

        Args:
            namespace_storage: Dictionary mapping namespace to its calculated storage types.
            all_namespaces: List of all namespace dictionaries from the cluster.

        Returns:
            Tuple of sets: (only_non_nfs, only_nfs, mixed).
        """
        only_non_nfs = set()
        only_nfs = set()
        mixed = set()

        all_namespace_names = {
            ns.get("metadata", {}).get("name")
            for ns in all_namespaces
            if ns.get("metadata", {}).get("name")
        }

        for ns_name in all_namespace_names:
            storage_types = namespace_storage.get(ns_name)
            if storage_types:
                if storage_types["nfs"] and storage_types["non_nfs"]:
                    mixed.add(ns_name)
                    self.logger.debug(f"Categorized namespace '{ns_name}' as Mixed.")
                elif storage_types["nfs"]:
                    only_nfs.add(ns_name)
                    self.logger.debug(f"Categorized namespace '{ns_name}' as NFS Only.")
                elif storage_types["non_nfs"]:
                    only_non_nfs.add(ns_name)
                    self.logger.debug(f"Categorized namespace '{ns_name}' as Non-NFS Only.")
            else:
                # Namespaces without any bound PVCs using known PVs are ignored for categorization.
                self.logger.debug(f"Namespace '{ns_name}' has no associated PVCs using known PVs.")

        self.logger.info(
            f"Storage type analysis complete. Non-NFS: {len(only_non_nfs)}, NFS: {len(only_nfs)}, Mixed: {len(mixed)}."
        )
        return only_non_nfs, only_nfs, mixed

    def get_namespace_storage_types(self) -> Tuple[Set[str], Set[str], Set[str]]:
        """Fetch data and categorize namespaces based on their storage types.

        Returns:
            Tuple of sets containing:
            - Namespaces with only non-NFS storage
            - Namespaces with only NFS storage
            - Namespaces with both NFS and non-NFS storage
        """
        self.logger.info("Starting analysis of namespace storage types...")
        pvs = self.get_all_pvs()
        pvcs = self.get_all_pvcs()
        all_namespaces = self.get_all_namespaces()

        if not pvs:
            self.logger.warning("No PVs found. Cannot determine storage types accurately.")
            return set(), set(), set()
        if not pvcs:
            self.logger.info("No PVCs found. No namespaces are actively using persistent storage.")
            return set(), set(), set()
        if not all_namespaces:
            self.logger.warning("No namespaces found in the cluster.")
            return set(), set(), set()

        pv_type_map = self._build_pv_type_map(pvs)
        namespace_storage = self._calculate_namespace_storage(pvcs, pv_type_map)
        only_non_nfs, only_nfs, mixed = self._categorize_namespaces(
            namespace_storage, all_namespaces
        )

        return only_non_nfs, only_nfs, mixed

    def display_results(self) -> None:
        """Display the analysis results in a formatted table."""
        try:
            only_non_nfs, only_nfs, mixed = self.get_namespace_storage_types()

            # Create and display the table
            table = Table(
                title="Namespace Storage Type Analysis (Based on PV/PVCs)", title_style="bold blue"
            )
            table.add_column("Category", style="cyan", no_wrap=True, justify="right")
            table.add_column("Namespaces", style="green")
            table.add_column("Count", style="magenta", justify="right")

            # Add rows for each category
            table.add_row(
                "Non-NFS Only",
                "\n".join(sorted(only_non_nfs)) if only_non_nfs else "[dim]None[/dim]",
                str(len(only_non_nfs)),
            )
            table.add_row(
                "NFS Only",
                "\n".join(sorted(only_nfs)) if only_nfs else "[dim]None[/dim]",
                str(len(only_nfs)),
            )
            table.add_row(
                "Mixed (NFS & Non-NFS)",
                "\n".join(sorted(mixed)) if mixed else "[dim]None[/dim]",
                str(len(mixed)),
            )

            # Display the table
            console.print()
            console.print(table)
            console.print()

        except Exception as e:
            self.logger.exception("An error occurred during result display.")
            console.print(f"[bold red]Error displaying results:[/bold red] {e}")


@click.command()
@click.option(
    "--kubeconfig",
    required=True,
    type=click.Path(exists=True, dir_okay=False),  # Ensure file exists
    help="Path to kubeconfig file.",
    envvar="KUBECONFIG",  # Allow setting via KUBECONFIG env var
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(kubeconfig: str, debug: bool):
    """Analyze and categorize namespaces based on their storage types (NFS vs non-NFS)."""
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    # Use setup_logging from utils
    setup_logging(level=log_level, script_name=script_base_name)
    logger = get_logger(__name__)  # Get logger instance after setup

    logger.info("Starting Kubernetes Storage Analyzer script.")

    # Load Kubernetes configuration using util
    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error:[/bold red] Could not load Kubernetes configuration.")
        # No need for sys.exit, Click handles exit on error implicitly if needed,
        # or we just return here.
        return

    try:
        # Initialize and run the analyzer
        analyzer = K8sStorageAnalyzer()
        analyzer.display_results()
        logger.info("Kubernetes Storage Analyzer script finished successfully.")
    except RuntimeError as e:  # Catch initialization errors
        console.print(f"[bold red]Initialization Error:[/bold red] {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred during analysis.")
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
