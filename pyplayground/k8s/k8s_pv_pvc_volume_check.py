#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kubernetes PV/PVC Volume Type Analysis Script.

This script analyzes PersistentVolumes and PersistentVolumeClaims in a Kubernetes cluster
to categorize namespaces based on their storage types (NFS-only, Non-NFS only, or Mixed).
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Set, Tuple

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich import box
from rich.console import Console
from rich.table import Table

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from pyplayground.utils.k8s_utils import load_kube_config_auto
from pyplayground.utils.logging_utils import get_logger, get_project_root, setup_logging

# Get the project root directory
PROJECT_ROOT = get_project_root()
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tmp")

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
            self.logger.info(f"Found {len(pvcs.items)} PersistentVolumeClaims across all namespaces.")
            return [pvc.to_dict() for pvc in pvcs.items]
        except ApiException as e:
            self.logger.error(f"Failed to get PVCs: {e.status} - {e.reason}")
            console.print(f"[bold red]API Error:[/bold red] Could not list PVCs. Reason: {e.reason}")
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
            console.print(f"[bold red]API Error:[/bold red] Could not list Namespaces. Reason: {e.reason}")
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
        pv_type_map = {pv["metadata"]["name"]: self._is_nfs_pv(pv) for pv in pvs if "metadata" in pv and "name" in pv["metadata"]}
        self.logger.debug(f"Built PV type map for {len(pv_type_map)} PVs.")
        return pv_type_map

    def _calculate_namespace_storage(self, pvcs: List[Dict], pv_type_map: Dict[str, bool]) -> Dict[str, Dict[str, bool]]:
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
                self.logger.warning(f"Skipping PVC with missing namespace: {pvc.get('metadata', {}).get('name', 'N/A')}")
                continue

            if pv_name and pv_name in pv_type_map:
                if namespace not in namespace_storage:
                    namespace_storage[namespace] = {"nfs": False, "non_nfs": False}

                if pv_type_map[pv_name]:  # If the PV is NFS
                    if not namespace_storage[namespace]["nfs"]:
                        self.logger.debug(f"Namespace '{namespace}' uses NFS storage (via PVC '{pvc.get('metadata', {}).get('name')}' -> PV '{pv_name}').")
                        namespace_storage[namespace]["nfs"] = True
                else:  # If the PV is non-NFS
                    if not namespace_storage[namespace]["non_nfs"]:
                        self.logger.debug(f"Namespace '{namespace}' uses non-NFS storage (via PVC '{pvc.get('metadata', {}).get('name')}' -> PV '{pv_name}').")
                        namespace_storage[namespace]["non_nfs"] = True
            elif pv_name:
                # PVC is bound but PV not found in our list (could be timing or error in get_pvs)
                self.logger.warning(f"PVC '{namespace}/{pvc.get('metadata', {}).get('name')}' references PV '{pv_name}' which was not found.")
            else:
                # PVC is not bound or has no volumeName yet
                pvc_status = pvc.get("status", {}).get("phase", "Unknown")
                self.logger.debug(f"PVC '{namespace}/{pvc.get('metadata', {}).get('name')}' is in phase '{pvc_status}' and has no volumeName.")
        return namespace_storage

    def _categorize_namespaces(self, namespace_storage: Dict[str, Dict[str, bool]], all_namespaces: List[Dict]) -> Tuple[Set[str], Set[str], Set[str]]:
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

        all_namespace_names = {ns.get("metadata", {}).get("name") for ns in all_namespaces if ns.get("metadata", {}).get("name")}

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

        self.logger.info(f"Storage type analysis complete. Non-NFS: {len(only_non_nfs)}, NFS: {len(only_nfs)}, Mixed: {len(mixed)}.")
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
        only_non_nfs, only_nfs, mixed = self._categorize_namespaces(namespace_storage, all_namespaces)

        return only_non_nfs, only_nfs, mixed

    def _display_console_output(self, only_non_nfs: Set[str], only_nfs: Set[str], mixed: Set[str]) -> None:
        """Display the analysis results in a formatted table to the console."""
        # Get terminal width and calculate column width
        terminal_width = console.width
        namespace_col_width = terminal_width // 3
        self.logger.debug(f"Terminal width: {terminal_width}, calculated namespace column width: {namespace_col_width}")

        # Create and display the table
        table = Table(
            title="Namespace Storage Type Analysis (Based on PV/PVCs)",
            title_style="bold blue",
            show_lines=True,  # Add row separators
            box=box.ASCII,
        )
        table.add_column("Category", style="cyan", no_wrap=True, justify="right")
        # Set calculated width for the Namespaces column
        table.add_column("Namespaces", style="green", width=namespace_col_width)
        table.add_column("Count", style="magenta", justify="right")

        # Add rows for each category, joining namespaces with commas
        table.add_row(
            "Non-NFS Only",
            ", ".join(sorted(only_non_nfs)) if only_non_nfs else "[dim]None[/dim]",
            str(len(only_non_nfs)),
        )
        table.add_row(
            "NFS Only",
            ", ".join(sorted(only_nfs)) if only_nfs else "[dim]None[/dim]",
            str(len(only_nfs)),
        )
        table.add_row(
            "Mixed (NFS & Non-NFS)",
            ", ".join(sorted(mixed)) if mixed else "[dim]None[/dim]",
            str(len(mixed)),
        )

        # Display the table
        console.print()
        console.print(table)
        console.print()

    def _write_json_output(
        self,
        only_non_nfs: Set[str],
        only_nfs: Set[str],
        mixed: Set[str],
        output_dir: str,
        script_base_name: str,
    ) -> None:
        """Write the analysis results to a JSON file."""
        output_data = {
            "non_nfs_only": sorted(list(only_non_nfs)),
            "nfs_only": sorted(list(only_nfs)),
            "mixed": sorted(list(mixed)),
            "counts": {
                "non_nfs_only": len(only_non_nfs),
                "nfs_only": len(only_nfs),
                "mixed": len(mixed),
            },
        }
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{script_base_name}_output_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2)
            self.logger.info(f"JSON output saved to: {filepath}")
            console.print(f"[green]JSON output saved to:[/green] {filepath}")
        except IOError as e:
            self.logger.error(f"Failed to write JSON output to {filepath}: {e}")
            console.print(f"[bold red]Error:[/bold red] Could not write JSON file to {filepath}. Reason: {e}")
        except Exception as e:
            self.logger.exception(f"Unexpected error writing JSON output: {e}")
            console.print(f"[bold red]Error:[/bold red] Unexpected error writing JSON file: {e}")

    def _write_csv_output(
        self,
        only_non_nfs: Set[str],
        only_nfs: Set[str],
        mixed: Set[str],
        output_dir: str,
        script_base_name: str,
    ) -> None:
        """Write the analysis results to a CSV file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{script_base_name}_output_{timestamp}.csv"
        filepath = os.path.join(output_dir, filename)

        rows = []
        for ns in sorted(only_non_nfs):
            rows.append({"namespace": ns, "category": "Non-NFS Only"})
        for ns in sorted(only_nfs):
            rows.append({"namespace": ns, "category": "NFS Only"})
        for ns in sorted(mixed):
            rows.append({"namespace": ns, "category": "Mixed (NFS & Non-NFS)"})

        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
                if rows:  # Only write header if there is data
                    fieldnames = list(rows[0].keys())  # Get headers from first row
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    # Write only header if no data
                    writer = csv.writer(csvfile)
                    writer.writerow(["namespace", "category"])  # Default header

            self.logger.info(f"CSV output saved to: {filepath}")
            console.print(f"[green]CSV output saved to:[/green] {filepath}")
        except IOError as e:
            self.logger.error(f"Failed to write CSV output to {filepath}: {e}")
            console.print(f"[bold red]Error:[/bold red] Could not write CSV file to {filepath}. Reason: {e}")
        except Exception as e:
            self.logger.exception(f"Unexpected error writing CSV output: {e}")
            console.print(f"[bold red]Error:[/bold red] Unexpected error writing CSV file: {e}")

    def process_and_output(self, output_format: str, output_dir: str, script_base_name: str) -> None:
        """Get storage types and output results based on the specified format."""
        try:
            only_non_nfs, only_nfs, mixed = self.get_namespace_storage_types()

            if output_format == "json":
                self._write_json_output(only_non_nfs, only_nfs, mixed, output_dir, script_base_name)
            elif output_format == "csv":
                self._write_csv_output(only_non_nfs, only_nfs, mixed, output_dir, script_base_name)
            else:  # Default to console
                self._display_console_output(only_non_nfs, only_nfs, mixed)

        except Exception as e:
            self.logger.exception("An error occurred during processing or output.")
            console.print(f"[bold red]Error during processing/output:[/bold red] {e}")


@click.command()
@click.option(
    "--kubeconfig",
    required=True,
    type=click.Path(exists=True, dir_okay=False),  # Ensure file exists
    help="Path to kubeconfig file.",
    envvar="KUBECONFIG",  # Allow setting via KUBECONFIG env var
)
@click.option(
    "-f",
    "--format",
    "output_format",  # Use 'output_format' as the variable name
    type=click.Choice(["console", "json", "csv"], case_sensitive=False),
    default="console",
    show_default=True,
    help="Output format.",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False, writable=True),  # Ensure it's a writable directory
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory to save output files.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(kubeconfig: str, output_format: str, output_dir: str, debug: bool):
    """Analyze and categorize namespaces based on their storage types (NFS vs non-NFS)."""
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    # Use setup_logging from utils
    setup_logging(level=log_level, script_name=script_base_name)
    logger = get_logger(__name__)  # Get logger instance after setup

    logger.info(f"Starting Kubernetes Storage Analyzer script. Output format: {output_format}, Output dir: {output_dir}")

    # Load Kubernetes configuration using util
    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error:[/bold red] Could not load Kubernetes configuration.")
        # No need for sys.exit, Click handles exit on error implicitly if needed,
        # or we just return here.
        return

    try:
        # Initialize and run the analyzer
        analyzer = K8sStorageAnalyzer()
        # Call the new processing method
        analyzer.process_and_output(output_format, output_dir, script_base_name)
        logger.info("Kubernetes Storage Analyzer script finished successfully.")
    except RuntimeError as e:  # Catch initialization errors
        console.print(f"[bold red]Initialization Error:[/bold red] {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred during analysis.")
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
