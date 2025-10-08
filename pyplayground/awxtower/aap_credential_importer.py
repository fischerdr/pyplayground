#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AAP Credential Import Tool.

This script imports credentials exported from Ansible Tower into Red Hat
Ansible Automation Platform (AAP) using the REST API.

The script uses the AAP API to create credentials, allowing AAP to handle
encryption automatically with its own SECRET_KEY.

Author: Tower Migration Team
License: Apache 2.0
"""

import json
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import click
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Confirm, Prompt
from rich.table import Table
from urllib3.util.retry import Retry

# Suppress SSL warnings for self-signed certificates
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Import project utilities
sys.path.append(str(Path(__file__).parent.parent))
from pyplayground.utils.logging_utils import setup_logging

# Initialize Rich console for output
console = Console()
logger = None  # Will be initialized in main


@dataclass
class AAPConnection:
    """AAP instance connection parameters."""

    url: str
    username: str
    password: str
    verify_ssl: bool = True
    timeout: int = 30


@dataclass
class CredentialTypeCreateResult:
    """Result of credential type creation operation."""

    credential_type_name: str
    success: bool
    message: str
    aap_credential_type_id: Optional[int] = None


@dataclass
class ImportResult:
    """Result of credential import operation."""

    credential_name: str
    success: bool
    message: str
    aap_credential_id: Optional[int] = None


class AAPCredentialImporter:
    """Imports credentials into AAP using REST API."""

    def __init__(self, connection: AAPConnection) -> None:
        """Initialize the AAP credential importer.

        Args:
            connection: AAP connection parameters
        """
        self.connection = connection
        self.session = requests.Session()
        self._setup_session()
        self._org_cache: Dict[int, Dict] = {}
        self._credtype_cache: Dict[int, Dict] = {}

    def _setup_session(self) -> None:
        """Configure requests session with authentication and retry logic."""
        # Setup authentication
        self.session.auth = HTTPBasicAuth(self.connection.username, self.connection.password)

        # Setup retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        # SSL verification
        self.session.verify = self.connection.verify_ssl

    def test_connection(self) -> bool:
        """Test connection to AAP instance.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self.session.get(
                urljoin(self.connection.url, "/api/v2/ping/"), timeout=self.connection.timeout
            )
            response.raise_for_status()

            ping_data = response.json()
            logger.info(f"Connected to AAP: {ping_data.get('version', 'Unknown version')}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to AAP: {e}")
            return False

    def get_organizations(self) -> Dict[int, Dict]:
        """Get all organizations from AAP.

        Returns:
            Dictionary mapping organization IDs to organization data
        """
        if self._org_cache:
            return self._org_cache

        try:
            response = self.session.get(
                urljoin(self.connection.url, "/api/v2/organizations/"),
                timeout=self.connection.timeout,
            )
            response.raise_for_status()

            orgs_data = response.json()
            for org in orgs_data["results"]:
                self._org_cache[org["id"]] = org

            logger.info(f"Found {len(self._org_cache)} organizations in AAP")
            return self._org_cache

        except Exception as e:
            logger.error(f"Failed to retrieve organizations: {e}")
            return {}

    def get_credential_types(self) -> Dict[int, Dict]:
        """Get all credential types from AAP.

        Returns:
            Dictionary mapping credential type IDs to credential type data
        """
        if self._credtype_cache:
            return self._credtype_cache

        try:
            response = self.session.get(
                urljoin(self.connection.url, "/api/v2/credential_types/"),
                timeout=self.connection.timeout,
            )
            response.raise_for_status()

            types_data = response.json()
            for cred_type in types_data["results"]:
                self._credtype_cache[cred_type["id"]] = cred_type

            logger.info(f"Found {len(self._credtype_cache)} credential types in AAP")
            return self._credtype_cache

        except Exception as e:
            logger.error(f"Failed to retrieve credential types: {e}")
            return {}

    def create_credential_type(self, credential_type_data: Dict) -> CredentialTypeCreateResult:
        """Create a new credential type in AAP.

        Args:
            credential_type_data: Credential type data from Tower export

        Returns:
            Creation result with success status and details
        """
        type_name = credential_type_data["name"]

        try:
            # Check if credential type already exists
            existing = self.get_credential_type_by_name(type_name)
            if existing:
                return CredentialTypeCreateResult(
                    credential_type_name=type_name,
                    success=False,
                    message=f"Credential type already exists (ID: {existing['id']})",
                    aap_credential_type_id=existing["id"],
                )

            # Skip managed credential types
            if credential_type_data.get("managed", False):
                return CredentialTypeCreateResult(
                    credential_type_name=type_name,
                    success=False,
                    message="Skipping managed credential type (should exist in AAP)",
                )

            # Prepare payload for AAP API
            payload = {
                "name": type_name,
                "description": credential_type_data.get("description", ""),
                "kind": credential_type_data.get("kind", "cloud"),
                "inputs": credential_type_data.get("inputs", {}),
                "injectors": credential_type_data.get("injectors", {}),
            }

            # Only include namespace for custom types
            if credential_type_data.get("namespace"):
                payload["namespace"] = credential_type_data["namespace"]

            # Create credential type via API
            response = self.session.post(
                urljoin(self.connection.url, "/api/v2/credential_types/"),
                json=payload,
                timeout=self.connection.timeout,
            )

            if response.status_code == 201:
                result_data = response.json()
                return CredentialTypeCreateResult(
                    credential_type_name=type_name,
                    success=True,
                    message="Created successfully",
                    aap_credential_type_id=result_data["id"],
                )
            else:
                error_msg = f"API error {response.status_code}: {response.text}"
                return CredentialTypeCreateResult(
                    credential_type_name=type_name,
                    success=False,
                    message=error_msg,
                )

        except Exception as e:
            logger.error(f"Error creating credential type '{type_name}': {e}")
            return CredentialTypeCreateResult(
                credential_type_name=type_name,
                success=False,
                message=f"Exception: {e}",
            )

    def get_credential_type_by_name(self, name: str) -> Optional[Dict]:
        """Get credential type by name from AAP.

        Args:
            name: Credential type name to search for

        Returns:
            Credential type data if found, None otherwise
        """
        try:
            response = self.session.get(
                urljoin(self.connection.url, "/api/v2/credential_types/"),
                params={"name": name},
                timeout=self.connection.timeout,
            )
            response.raise_for_status()

            results = response.json()["results"]
            if results:
                return results[0]  # Return first match

        except Exception as e:
            logger.warning(f"Error checking for existing credential type '{name}': {e}")

        return None

    def map_credential_type(self, tower_type_id: int, tower_type_name: str) -> Optional[int]:
        """Map Tower credential type to AAP credential type.

        Args:
            tower_type_id: Tower credential type ID
            tower_type_name: Tower credential type name

        Returns:
            AAP credential type ID if found, None otherwise
        """
        aap_types = self.get_credential_types()

        # First try exact name match (preferred for reliability)
        for aap_id, aap_type in aap_types.items():
            if aap_type["name"] == tower_type_name:
                logger.debug(f"Mapped credential type '{tower_type_name}' -> ID {aap_id}")
                return aap_id

        # Try case-insensitive name matching
        for aap_id, aap_type in aap_types.items():
            if aap_type["name"].lower() == tower_type_name.lower():
                logger.debug(
                    f"Mapped credential type '{tower_type_name}' -> ID {aap_id} (case insensitive)"
                )
                return aap_id

        # Common mappings for Tower -> AAP
        type_mappings = {
            "machine": "Machine",
            "ssh": "Machine",
            "scm": "Source Control",
            "aws": "Amazon Web Services",
            "gce": "Google Compute Engine",
            "azure": "Microsoft Azure",
            "vmware": "VMware vCenter",
            "openstack": "OpenStack",
            "vault": "Vault",
        }

        tower_name_lower = tower_type_name.lower()
        if tower_name_lower in type_mappings:
            target_name = type_mappings[tower_name_lower]
            for aap_id, aap_type in aap_types.items():
                if aap_type["name"] == target_name:
                    logger.debug(
                        f"Mapped credential type '{tower_type_name}' -> "
                        f"'{target_name}' (ID {aap_id})"
                    )
                    return aap_id

        logger.warning(f"Could not map credential type '{tower_type_name}' (ID {tower_type_id})")
        return None

    def check_credential_exists(
        self, name: str, organization_id: Optional[int] = None
    ) -> Optional[Dict]:
        """Check if a credential with the given name already exists.

        Args:
            name: Credential name to check
            organization_id: Organization ID to scope the search

        Returns:
            Existing credential data if found, None otherwise
        """
        params = {"name": name}
        if organization_id:
            params["organization"] = organization_id

        try:
            response = self.session.get(
                urljoin(self.connection.url, "/api/v2/credentials/"),
                params=params,
                timeout=self.connection.timeout,
            )
            response.raise_for_status()

            results = response.json()["results"]
            if results:
                return results[0]  # Return first match

        except Exception as e:
            logger.warning(f"Error checking for existing credential '{name}': {e}")

        return None

    def create_credential(self, credential_data: Dict) -> ImportResult:
        """Create a new credential in AAP.

        Args:
            credential_data: Credential data from Tower export

        Returns:
            Import result with success status and details
        """
        cred_name = credential_data["name"]

        try:
            # Map credential type
            aap_type_id = self.map_credential_type(
                credential_data["credential_type_id"], credential_data["credential_type_name"]
            )

            if not aap_type_id:
                return ImportResult(
                    credential_name=cred_name,
                    success=False,
                    message=f"Unsupported credential type: "
                    f"{credential_data['credential_type_name']}",
                )

            # Check if credential already exists
            existing = self.check_credential_exists(
                cred_name, credential_data.get("organization_id")
            )
            if existing:
                return ImportResult(
                    credential_name=cred_name,
                    success=False,
                    message=f"Credential already exists (ID: {existing['id']})",
                    aap_credential_id=existing["id"],
                )

            # Prepare payload for AAP API
            payload = {
                "name": cred_name,
                "description": credential_data.get("description", ""),
                "credential_type": aap_type_id,
                "inputs": credential_data["inputs"],
            }

            # Add organization if specified and exists
            if credential_data.get("organization_id"):
                orgs = self.get_organizations()
                if credential_data["organization_id"] in orgs:
                    payload["organization"] = credential_data["organization_id"]
                else:
                    logger.warning(
                        f"Organization ID {credential_data['organization_id']} not found in AAP"
                    )

            # Create credential via API
            response = self.session.post(
                urljoin(self.connection.url, "/api/v2/credentials/"),
                json=payload,
                timeout=self.connection.timeout,
            )

            if response.status_code == 201:
                result_data = response.json()
                return ImportResult(
                    credential_name=cred_name,
                    success=True,
                    message="Created successfully",
                    aap_credential_id=result_data["id"],
                )
            else:
                error_msg = f"API error {response.status_code}: {response.text}"
                return ImportResult(credential_name=cred_name, success=False, message=error_msg)

        except Exception as e:
            logger.error(f"Error creating credential '{cred_name}': {e}")
            return ImportResult(credential_name=cred_name, success=False, message=f"Exception: {e}")

    def import_credentials(
        self, credentials: List[Dict], skip_existing: bool = True
    ) -> List[ImportResult]:
        """Import multiple credentials into AAP.

        Args:
            credentials: List of credential data from Tower export
            skip_existing: Whether to skip existing credentials

        Returns:
            List of import results
        """
        results = []

        with Progress(console=console) as progress:
            task = progress.add_task("Importing credentials...", total=len(credentials))

            for cred_data in credentials:
                try:
                    # Add small delay to avoid overwhelming the API
                    time.sleep(0.5)

                    result = self.create_credential(cred_data)
                    results.append(result)

                    if result.success:
                        logger.info(f"✓ Imported credential: {result.credential_name}")
                    else:
                        logger.warning(
                            f"✗ Failed to import {result.credential_name}: {result.message}"
                        )

                    progress.update(task, advance=1)

                except Exception as e:
                    logger.error(
                        f"Unexpected error importing {cred_data.get('name', 'Unknown')}: {e}"
                    )
                    results.append(
                        ImportResult(
                            credential_name=cred_data.get("name", "Unknown"),
                            success=False,
                            message=f"Unexpected error: {e}",
                        )
                    )
                    progress.update(task, advance=1)

        return results

    def import_credential_types(
        self, credential_types: List[Dict]
    ) -> List[CredentialTypeCreateResult]:
        """Import multiple credential types into AAP.

        Args:
            credential_types: List of credential type data from Tower export

        Returns:
            List of creation results
        """
        results = []

        with Progress(console=console) as progress:
            task = progress.add_task("Creating credential types...", total=len(credential_types))

            for type_data in credential_types:
                try:
                    # Add small delay to avoid overwhelming the API
                    time.sleep(0.2)

                    result = self.create_credential_type(type_data)
                    results.append(result)

                    if result.success:
                        logger.info(f"✓ Created credential type: {result.credential_type_name}")
                        # Refresh credential types cache
                        self._credtype_cache = {}
                    else:
                        if "already exists" in result.message:
                            logger.info(f"○ Credential type exists: {result.credential_type_name}")
                        elif "managed" in result.message.lower():
                            logger.debug(f"○ Skipped managed type: {result.credential_type_name}")
                        else:
                            logger.warning(
                                f"✗ Failed to create {result.credential_type_name}: "
                                f"{result.message}"
                            )

                    progress.update(task, advance=1)

                except Exception as e:
                    logger.error(
                        f"Unexpected error creating {type_data.get('name', 'Unknown')}: {e}"
                    )
                    results.append(
                        CredentialTypeCreateResult(
                            credential_type_name=type_data.get("name", "Unknown"),
                            success=False,
                            message=f"Unexpected error: {e}",
                        )
                    )
                    progress.update(task, advance=1)

        return results


def load_exported_data(file_path: str) -> tuple[List[Dict], List[Dict]]:
    """Load credentials and credential types from exported JSON file.

    Args:
        file_path: Path to exported data file

    Returns:
        Tuple of (credentials list, credential_types list)

    Raises:
        click.ClickException: If file cannot be loaded
    """
    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        if "credentials" not in data:
            raise click.ClickException("Invalid export file format: missing 'credentials' key")

        credentials = data["credentials"]
        credential_types = data.get("credential_types", [])
        metadata = data.get("metadata", {})

        logger.info(
            f"Loaded {len(credentials)} credentials and "
            f"{len(credential_types)} credential types from {file_path}"
        )
        if metadata.get("export_date"):
            logger.info(f"Export date: {metadata['export_date']}")

        return credentials, credential_types

    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON in export file: {e}")
    except FileNotFoundError:
        raise click.ClickException(f"Export file not found: {file_path}")
    except Exception as e:
        raise click.ClickException(f"Error loading export file: {e}")


def display_import_summary(results: List[ImportResult]) -> None:
    """Display summary table of import results.

    Args:
        results: List of import results to display
    """
    table = Table(title="Credential Import Results")
    table.add_column("Credential Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("AAP ID", style="green")
    table.add_column("Message", style="yellow")

    successful = 0
    failed = 0

    for result in results:
        status = "[green]✓ Success[/green]" if result.success else "[red]✗ Failed[/red]"
        aap_id = str(result.aap_credential_id) if result.aap_credential_id else "-"

        table.add_row(
            result.credential_name,
            status,
            aap_id,
            result.message[:50] + "..." if len(result.message) > 50 else result.message,
        )

        if result.success:
            successful += 1
        else:
            failed += 1

    console.print(table)
    console.print(f"\n[green]Successful: {successful}[/green] | [red]Failed: {failed}[/red]")


def display_credential_type_summary(results: List[CredentialTypeCreateResult]) -> None:
    """Display summary table of credential type creation results.

    Args:
        results: List of credential type creation results to display
    """
    table = Table(title="Credential Type Creation Results")
    table.add_column("Credential Type Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("AAP ID", style="green")
    table.add_column("Message", style="yellow")

    successful = 0
    failed = 0
    skipped = 0

    for result in results:
        if result.success:
            status = "[green]✓ Created[/green]"
            successful += 1
        elif "already exists" in result.message:
            status = "[blue]○ Exists[/blue]"
            skipped += 1
        elif "managed" in result.message.lower():
            status = "[blue]○ Managed[/blue]"
            skipped += 1
        else:
            status = "[red]✗ Failed[/red]"
            failed += 1

        aap_id = str(result.aap_credential_type_id) if result.aap_credential_type_id else "-"

        table.add_row(
            result.credential_type_name,
            status,
            aap_id,
            result.message[:50] + "..." if len(result.message) > 50 else result.message,
        )

    console.print(table)
    console.print(
        f"\n[green]Created: {successful}[/green] | "
        f"[blue]Existing/Skipped: {skipped}[/blue] | "
        f"[red]Failed: {failed}[/red]"
    )


@click.command()
@click.option("--aap-url", required=True, help="AAP instance URL (e.g., https://aap.example.com)")
@click.option("--aap-username", required=True, help="AAP username for authentication")
@click.option("--aap-password", help="AAP password (will prompt if not provided)")
@click.option(
    "--credentials-file",
    required=True,
    help="Path to exported credentials JSON file",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--skip-existing", is_flag=True, default=True, help="Skip credentials that already exist in AAP"
)
@click.option("--verify-ssl/--no-verify-ssl", default=True, help="Verify SSL certificates")
@click.option("--timeout", default=30, help="API request timeout in seconds", show_default=True)
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--dry-run", is_flag=True, help="Load and validate credentials but do not import")
def main(  # noqa: C901
    aap_url: str,
    aap_username: str,
    aap_password: Optional[str],
    credentials_file: str,
    skip_existing: bool,
    verify_ssl: bool,
    timeout: int,
    debug: bool,
    dry_run: bool,
) -> None:
    r"""Import Tower credentials into Red Hat Ansible Automation Platform.

    This tool imports credentials exported from Ansible Tower using the
    tower_credential_migrator.py script. It uses the AAP REST API to create
    credentials, allowing AAP to handle encryption automatically.

    Examples:
        # Basic import
        python aap_credential_importer.py \\
            --aap-url https://aap.example.com \\
            --aap-username admin \\
            --credentials-file tower_credentials_export.json

        # Import with custom options
        python aap_credential_importer.py \\
            --aap-url https://aap.example.com \\
            --aap-username admin \\
            --aap-password mypass \\
            --credentials-file credentials.json \\
            --no-verify-ssl

        # Dry run to test without importing
        python aap_credential_importer.py \\
            --aap-url https://aap.example.com \\
            --aap-username admin \\
            --credentials-file credentials.json \\
            --dry-run
    """
    global logger

    # Setup logging
    script_name = Path(__file__).stem
    log_level = "DEBUG" if debug else "INFO"
    logger = setup_logging(level=log_level, script_name=script_name)

    # Display banner
    console.print(
        Panel.fit(
            "[bold blue]AAP Credential Import Tool[/bold blue]\n"
            "Import Tower credentials into Red Hat Ansible Automation Platform",
            border_style="blue",
        )
    )

    try:
        # Prompt for password if not provided
        if not aap_password:
            aap_password = Prompt.ask(
                f"Enter password for AAP user '{aap_username}'", password=True, show_default=False
            )

        # Load credentials and credential types from export file
        console.print(f"[green]Loading data from {credentials_file}...[/green]")
        credentials, credential_types = load_exported_data(credentials_file)

        if not credentials and not credential_types:
            console.print(
                "[yellow]No credentials or credential types found in export file.[/yellow]"
            )
            return

        console.print(
            f"[green]Loaded {len(credentials)} credentials and "
            f"{len(credential_types)} credential types for import.[/green]"
        )

        # Create AAP connection
        connection = AAPConnection(
            url=aap_url,
            username=aap_username,
            password=aap_password,
            verify_ssl=verify_ssl,
            timeout=timeout,
        )

        # Initialize importer
        importer = AAPCredentialImporter(connection)

        # Test connection
        console.print("[green]Testing connection to AAP...[/green]")
        if not importer.test_connection():
            raise click.ClickException("Failed to connect to AAP instance")

        # Load AAP metadata
        console.print("[green]Loading AAP organizations and credential types...[/green]")
        orgs = importer.get_organizations()
        cred_types = importer.get_credential_types()

        console.print(f"Found {len(orgs)} organizations and {len(cred_types)} credential types")

        if dry_run:
            console.print("[yellow]Dry run mode - validating data without importing[/yellow]")

            # Validate credential types first
            if credential_types:
                console.print(
                    f"[blue]Validating {len(credential_types)} credential types...[/blue]"
                )
                type_validation_results = []
                for cred_type in credential_types:
                    existing = importer.get_credential_type_by_name(cred_type["name"])
                    type_validation_results.append(
                        {
                            "name": cred_type["name"],
                            "exists": existing is not None,
                            "managed": cred_type.get("managed", False),
                            "creatable": not cred_type.get("managed", False) and existing is None,
                        }
                    )

                # Display credential type validation
                type_table = Table(title="Credential Type Validation Results")
                type_table.add_column("Name", style="cyan")
                type_table.add_column("Managed", style="blue")
                type_table.add_column("Exists", style="green")
                type_table.add_column("Action", style="bold")

                creatable = 0
                for result in type_validation_results:
                    managed_str = "✓" if result["managed"] else "✗"
                    exists_str = "✓" if result["exists"] else "✗"

                    if result["managed"]:
                        action = "[blue]Skip (Managed)[/blue]"
                    elif result["exists"]:
                        action = "[blue]Skip (Exists)[/blue]"
                    elif result["creatable"]:
                        action = "[green]Create[/green]"
                        creatable += 1
                    else:
                        action = "[red]Unknown[/red]"

                    type_table.add_row(result["name"], managed_str, exists_str, action)

                console.print(type_table)
                console.print(f"[green]Will create: {creatable} credential types[/green]")

            # Validate credentials
            if credentials:
                console.print(f"[blue]Validating {len(credentials)} credentials...[/blue]")
                validation_results = []
                for cred in credentials:
                    aap_type_id = importer.map_credential_type(
                        cred["credential_type_id"], cred["credential_type_name"]
                    )

                    validation_results.append(
                        {
                            "name": cred["name"],
                            "type_mappable": aap_type_id is not None,
                            "aap_type_id": aap_type_id,
                            "tower_type": cred["credential_type_name"],
                        }
                    )

                # Display credential validation results
                table = Table(title="Credential Validation Results")
                table.add_column("Name", style="cyan")
                table.add_column("Tower Type", style="blue")
                table.add_column("AAP Type ID", style="green")
                table.add_column("Status", style="bold")

                mappable = 0
                for result in validation_results:
                    status = (
                        "[green]✓ OK[/green]"
                        if result["type_mappable"]
                        else "[red]✗ No Mapping[/red]"
                    )
                    aap_type = str(result["aap_type_id"]) if result["aap_type_id"] else "-"

                    table.add_row(result["name"], result["tower_type"], aap_type, status)

                    if result["type_mappable"]:
                        mappable += 1

                console.print(table)
                console.print(
                    f"\n[green]Mappable: {mappable}[/green] | "
                    f"[red]Not Mappable: {len(validation_results) - mappable}[/red]"
                )
            return

        # Confirm import
        if not Confirm.ask(
            f"Import {len(credential_types)} credential types and "
            f"{len(credentials)} credentials into AAP?"
        ):
            console.print("[yellow]Import cancelled.[/yellow]")
            return

        # Create credential types first
        type_results = []
        if credential_types:
            console.print("[green]Creating credential types...[/green]")
            type_results = importer.import_credential_types(credential_types)
            display_credential_type_summary(type_results)

        # Then import credentials
        cred_results = []
        if credentials:
            console.print("[green]Importing credentials...[/green]")
            cred_results = importer.import_credentials(credentials, skip_existing)
            display_import_summary(cred_results)

        # Final summary
        cred_successful = sum(1 for r in cred_results if r.success)
        cred_failed = len(cred_results) - cred_successful

        type_successful = sum(1 for r in type_results if r.success)
        type_failed = sum(
            1
            for r in type_results
            if (
                not r.success
                and "exists" not in r.message.lower()
                and "managed" not in r.message.lower()
            )
        )

        total_failed = cred_failed + type_failed
        if total_failed == 0:
            console.print(
                Panel.fit(
                    f"[bold green]Import Complete![/bold green]\n\n"
                    f"Successfully created {type_successful} credential types and "
                    f"imported {cred_successful} credentials into AAP.",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel.fit(
                    f"[bold yellow]Import Partially Complete[/bold yellow]\n\n"
                    f"Credential types: {type_successful} created, {type_failed} failed\n"
                    f"Credentials: {cred_successful} imported, {cred_failed} failed\n\n"
                    f"Check the output above for details on failed imports.",
                    border_style="yellow",
                )
            )

    except click.ClickException:
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        raise click.Abort()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        console.print(f"[red]Error: {e}[/red]")
        if debug:
            console.print_exception()
        raise click.ClickException(f"Import failed: {e}")


if __name__ == "__main__":
    main()
