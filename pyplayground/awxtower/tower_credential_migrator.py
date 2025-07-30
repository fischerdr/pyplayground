#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tower to AAP Credential Migration Tool.

This script extracts encrypted credentials from an Ansible Tower instance
and prepares them for migration to Red Hat Ansible Automation Platform (AAP).

The script must run on the source Tower instance with root privileges to:
1. Access the Tower SECRET_KEY from filesystem
2. Query the Tower database directly
3. Decrypt credential secrets using Tower's encryption
4. Export credentials to a secure format for AAP import

Author: Tower Migration Team
License: Apache 2.0
"""

import base64
import datetime
import hashlib
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Confirm, Prompt
from rich.table import Table

# Import project utilities
sys.path.append(str(Path(__file__).parent.parent))
from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Initialize Rich console for output
console = Console()
# Setup logging
logger = get_logger(__name__)


def get_env_override(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable override for Tower configuration.

    Args:
        key: Environment variable name
        default: Default value if not found

    Returns:
        Environment variable value or default
    """
    return get_env_var(key, default=default)


@dataclass
class TowerConnection:
    """Tower database connection parameters."""

    host: str
    port: str = "5432"
    database: str = "awx"
    username: str = "awx"
    password: str = ""


@dataclass
class CredentialTypeData:
    """Represents a Tower credential type definition."""

    id: int
    name: str
    description: str
    kind: str
    namespace: Optional[str]
    managed: bool
    inputs: Dict[str, Any]
    injectors: Dict[str, Any]
    created: Optional[str] = None
    modified: Optional[str] = None


@dataclass
class CredentialData:
    """Represents a Tower credential with decrypted data."""

    id: int
    name: str
    description: str
    organization_id: Optional[int]
    credential_type_id: int
    credential_type_name: str
    inputs: Dict[str, Any]
    created: Optional[str] = None
    modified: Optional[str] = None


class Fernet256(Fernet):
    """Enhanced Fernet using AES-256-CBC instead of AES-128-CBC.

    Maintains compatibility with Tower's encryption format while using
    stronger encryption for credential data.
    """

    def __init__(self, key: bytes, backend=None) -> None:
        """Initialize Fernet256 with AES-256 support.

        Args:
            key: 64-byte encryption key
            backend: Cryptography backend (defaults to default_backend)

        Raises:
            ValueError: If key is not 64 bytes
        """
        if backend is None:
            backend = default_backend()

        if isinstance(key, str):
            key = key.encode("utf-8")

        key = base64.urlsafe_b64decode(key)
        if len(key) != 64:
            raise ValueError("Fernet256 key must be 64 url-safe base64-encoded bytes.")

        self._signing_key = key[:32]
        self._encryption_key = key[32:]
        self._backend = backend


class TowerCredentialExtractor:
    """Extracts and decrypts credentials from Tower database."""

    def __init__(self, connection: TowerConnection, secret_key: str) -> None:
        """Initialize the credential extractor.

        Args:
            connection: Tower database connection parameters
            secret_key: Tower SECRET_KEY for decryption
        """
        self.connection = connection
        self.secret_key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        self._db_connection: Optional[psycopg2.connection] = None

    def connect(self) -> None:
        """Establish database connection to Tower instance."""
        try:
            self._db_connection = psycopg2.connect(
                host=self.connection.host,
                port=self.connection.port,
                database=self.connection.database,
                user=self.connection.username,
                password=self.connection.password,
            )
            logger.info(f"Connected to Tower database at {self.connection.host}")
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to Tower database: {e}")
            raise click.ClickException(f"Database connection failed: {e}")

    def disconnect(self) -> None:
        """Close database connection."""
        if self._db_connection:
            self._db_connection.close()
            logger.info("Disconnected from Tower database")

    def get_encryption_key(self, field_name: str, pk: Optional[int] = None) -> bytes:
        """Generate encryption key for a specific field.

        Args:
            field_name: Name of the encrypted field
            pk: Primary key of the credential (optional)

        Returns:
            Base64-encoded encryption key
        """
        h = hashlib.sha512()
        h.update(self.secret_key)
        if pk is not None:
            h.update(str(pk).encode("utf-8"))
        h.update(field_name.encode("utf-8"))
        return base64.urlsafe_b64encode(h.digest())

    def decrypt_value(self, encryption_key: bytes, encrypted_value: str) -> str:
        """Decrypt a single encrypted value.

        Args:
            encryption_key: Key for decryption
            encrypted_value: Encrypted value from database

        Returns:
            Decrypted plaintext value

        Raises:
            ValueError: If encryption format is unsupported
            InvalidToken: If decryption fails
        """
        if not encrypted_value.startswith("$encrypted$"):
            return encrypted_value

        raw_data = encrypted_value[len("$encrypted$") :]

        # Handle UTF8 marker
        utf8 = raw_data.startswith("UTF8$")
        if utf8:
            raw_data = raw_data[len("UTF8$") :]

        try:
            algo, b64data = raw_data.split("$", 1)
        except ValueError:
            raise ValueError(f"Invalid encryption format: {encrypted_value}")

        if algo != "AESCBC":
            raise ValueError(f"Unsupported encryption algorithm: {algo}")

        encrypted = base64.b64decode(b64data)
        f = Fernet256(encryption_key)
        decrypted = f.decrypt(encrypted)

        # Decode UTF8 if marker was present
        if utf8:
            decrypted = decrypted.decode("utf-8")
        else:
            decrypted = decrypted.decode("utf-8", errors="replace")

        return decrypted

    def extract_credential_types(self) -> List[CredentialTypeData]:
        """Extract all credential types from Tower database.

        Returns:
            List of credential type definitions
        """
        if not self._db_connection:
            raise RuntimeError("Database connection not established")

        cursor = self._db_connection.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Query credential types
        query = """
        SELECT
            id, name, description, kind, namespace, managed,
            inputs, injectors, created, modified
        FROM main_credentialtype
        ORDER BY name
        """

        try:
            cursor.execute(query)
        except psycopg2.errors.UndefinedColumn as e:
            if "managed" in str(e):
                logger.warning(
                    "Column 'managed' not found, falling back to default. This is common on older Tower versions."
                )
                if self._db_connection:
                    self._db_connection.rollback()  # Rollback the failed transaction
                fallback_query = """
                SELECT
                    id, name, description, kind, namespace, false as managed,
                    inputs, injectors, created, modified
                FROM main_credentialtype
                ORDER BY name
                """
                cursor.execute(fallback_query)
            else:
                raise  # Re-raise if it's a different undefined column

        results = cursor.fetchall()
        cursor.close()

        credential_types = []

        with Progress(console=console) as progress:
            task = progress.add_task("Extracting credential types...", total=len(results))

            for row in results:
                try:
                    credential_type = self._process_credential_type_row(row)
                    credential_types.append(credential_type)
                    progress.update(task, advance=1)

                except Exception as e:
                    logger.error(f"Failed to process credential type '{row['name']}': {e}")
                    console.print(
                        f"[red]Error processing credential type '{row['name']}': {e}[/red]"
                    )
                    continue

        logger.info(f"Successfully extracted {len(credential_types)} credential types")
        return credential_types

    def _process_credential_type_row(self, row: psycopg2.extras.DictRow) -> CredentialTypeData:
        """Process a single credential type database row.

        Args:
            row: Database row data

        Returns:
            Processed credential type data
        """
        # Handle JSON fields
        inputs = row["inputs"] if row["inputs"] else {}
        injectors = row["injectors"] if row["injectors"] else {}

        if isinstance(inputs, str):
            inputs = json.loads(inputs)
        if isinstance(injectors, str):
            injectors = json.loads(injectors)

        return CredentialTypeData(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            kind=row["kind"] or "",
            namespace=row["namespace"],
            managed=bool(row["managed"]),
            inputs=inputs,
            injectors=injectors,
            created=row["created"].isoformat() if row["created"] else None,
            modified=row["modified"].isoformat() if row["modified"] else None,
        )

    def extract_credentials(self) -> List[CredentialData]:
        """Extract all credentials from Tower database.

        Returns:
            List of credential data with decrypted secrets
        """
        if not self._db_connection:
            raise RuntimeError("Database connection not established")

        cursor = self._db_connection.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Query credentials with credential type information
        query = """
        SELECT
            c.id, c.name, c.description, c.organization_id,
            c.credential_type_id, c.inputs, c.created, c.modified,
            ct.name as credential_type_name
        FROM main_credential c
        LEFT JOIN main_credentialtype ct ON c.credential_type_id = ct.id
        ORDER BY c.name
        """

        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()

        credentials = []

        with Progress(console=console) as progress:
            task = progress.add_task("Extracting credentials...", total=len(results))

            for row in results:
                try:
                    credential = self._process_credential_row(row)
                    credentials.append(credential)
                    progress.update(task, advance=1)

                except Exception as e:
                    logger.error(f"Failed to process credential '{row['name']}': {e}")
                    console.print(f"[red]Error processing credential '{row['name']}': {e}[/red]")
                    continue

        logger.info(f"Successfully extracted {len(credentials)} credentials")
        return credentials

    def _process_credential_row(self, row: psycopg2.extras.DictRow) -> CredentialData:
        """Process a single credential database row.

        Args:
            row: Database row data

        Returns:
            Processed credential with decrypted inputs
        """
        inputs = row["inputs"] if row["inputs"] else {}

        # Handle JSON string inputs
        if isinstance(inputs, str):
            inputs = json.loads(inputs)

        # Decrypt encrypted input fields
        decrypted_inputs = {}
        for field_name, field_value in inputs.items():
            if isinstance(field_value, str) and field_value.startswith("$encrypted$"):
                try:
                    encryption_key = self.get_encryption_key(field_name, row["id"])
                    decrypted_value = self.decrypt_value(encryption_key, field_value)
                    decrypted_inputs[field_name] = decrypted_value
                    logger.debug(f"Decrypted field '{field_name}' for credential '{row['name']}'")
                except InvalidToken:
                    logger.warning(
                        f"Failed to decrypt field '{field_name}' for credential '{row['name']}'"
                        " - invalid encryption key"
                    )
                    decrypted_inputs[field_name] = "[DECRYPTION_FAILED]"
                except Exception as e:
                    logger.error(f"Error decrypting field '{field_name}': {e}")
                    decrypted_inputs[field_name] = "[DECRYPTION_ERROR]"
            else:
                decrypted_inputs[field_name] = field_value

        return CredentialData(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            organization_id=row["organization_id"],
            credential_type_id=row["credential_type_id"],
            credential_type_name=row["credential_type_name"] or "Unknown",
            inputs=decrypted_inputs,
            created=row["created"].isoformat() if row["created"] else None,
            modified=row["modified"].isoformat() if row["modified"] else None,
        )


def discover_tower_secret_key(config_path: str = "/etc/tower/conf.d") -> Optional[str]:
    """Discover Tower SECRET_KEY from configuration files.

    Args:
        config_path: Path to Tower configuration directory

    Returns:
        Tower SECRET_KEY if found, None otherwise
    """
    secret_files = [
        os.path.join(config_path, "secrets.py"),
        os.path.join(config_path, "secret_key.py"),
        "/etc/tower/SECRET_KEY",
        "/etc/tower/settings.py",  # Main settings file
        "/etc/tower/conf.d/settings.py",  # Settings in conf.d
    ]

    for secret_file in secret_files:
        if os.path.exists(secret_file):
            try:
                with open(secret_file, "r") as f:
                    content = f.read()

                # Look for SECRET_KEY assignment
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("SECRET_KEY"):
                        # Extract the key value
                        if "=" in line:
                            key_part = line.split("=", 1)[1].strip()
                            # Remove quotes and spaces
                            key_part = key_part.strip("'\"").strip()
                            if key_part:
                                logger.info(f"Found SECRET_KEY in {secret_file}")
                                return key_part

            except Exception as e:
                logger.warning(f"Could not read {secret_file}: {e}")
                continue

    logger.warning("Could not automatically discover Tower SECRET_KEY")
    return None


def _parse_django_databases_config(content: str) -> Optional[dict]:  # noqa: C901
    """Parse Django DATABASES configuration from postgres.py content.

    Args:
        content: Content of the postgres.py file

    Returns:
        Database configuration dict if found, None otherwise
    """
    db_config = {}
    in_databases = False
    in_default = False
    current_key = None

    for line in content.split("\n"):
        line = line.strip()

        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        # Check for DATABASES = {
        if "DATABASES" in line and "=" in line and "{" in line:
            in_databases = True
            continue

        # Check for 'default': {
        if in_databases and "'default'" in line and "{" in line:
            in_default = True
            continue

        # Check for closing braces
        if in_default and "}" in line:
            in_default = False
            if "}" in line and line.count("}") > line.count("{"):
                in_databases = False
            continue

        # Parse database settings
        if in_default and ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip().strip("'\"")
                value = parts[1].strip().rstrip(",").strip("'\"")

                # Handle multi-line string values
                if value == '""""""':
                    current_key = key
                    continue
                elif current_key and value == '""':
                    db_config[current_key] = ""
                    current_key = None
                    continue
                elif current_key:
                    db_config[current_key] = value
                    current_key = None
                    continue

                # Handle regular values
                if key in ["NAME", "USER", "PASSWORD", "HOST", "PORT"]:
                    db_config[key.lower()] = value

    return db_config if db_config else None


def discover_tower_database_config(
    config_path: str = "/etc/tower/conf.d",
) -> Optional[TowerConnection]:
    """Discover Tower database connection from postgres.py configuration file.

    Args:
        config_path: Path to Tower configuration directory

    Returns:
        TowerConnection object if found, None otherwise
    """
    postgres_file = os.path.join(config_path, "postgres.py")

    if not os.path.exists(postgres_file):
        logger.warning(f"Database config file not found: {postgres_file}")
        return None

    try:
        with open(postgres_file, "r") as f:
            content = f.read()

        # Parse Django DATABASES configuration
        db_config = _parse_django_databases_config(content)

        if not db_config:
            logger.warning(f"Could not parse database configuration from {postgres_file}")
            return None

        # Check if we found the essential database info
        if "name" in db_config and "user" in db_config:
            connection = TowerConnection(
                host=db_config.get("host", "127.0.0.1"),
                port=db_config.get("port", "5432"),
                database=db_config["name"],
                username=db_config["user"],
                password=db_config.get("password", ""),
            )
            logger.info(
                f"Found database config: {connection.host}:{connection.port}/"
                f"{connection.database}"
            )
            return connection
        else:
            logger.warning(f"Incomplete database config found in {postgres_file}")
            return None

    except Exception as e:
        logger.warning(f"Could not read database config from {postgres_file}: {e}")
        return None


def export_data_to_file(
    credentials: List[CredentialData], credential_types: List[CredentialTypeData], output_file: str
) -> None:
    """Export credentials and credential types to secure JSON file.

    Args:
        credentials: List of credential data to export
        credential_types: List of credential type definitions to export
        output_file: Path to output file
    """
    export_data = {
        "metadata": {
            "export_date": datetime.datetime.now().isoformat(),
            "export_tool": "tower_credential_migrator",
            "version": "2.0",
            "total_credentials": len(credentials),
            "total_credential_types": len(credential_types),
        },
        "credential_types": [asdict(cred_type) for cred_type in credential_types],
        "credentials": [asdict(cred) for cred in credentials],
    }

    # Create secure temporary file first
    temp_fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="tower_creds_")
    try:
        with os.fdopen(temp_fd, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        # Set restrictive permissions (owner read/write only)
        os.chmod(temp_path, 0o600)

        # Move to final location
        os.rename(temp_path, output_file)
        os.chmod(output_file, 0o600)

        logger.info(
            f"Exported {len(credentials)} credentials and "
            f"{len(credential_types)} credential types to {output_file}"
        )

    except Exception as e:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise e


def display_credentials_summary(credentials: List[CredentialData]) -> None:
    """Display a summary table of extracted credentials.

    Args:
        credentials: List of credentials to summarize
    """
    table = Table(title="Extracted Tower Credentials")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Type", style="blue")
    table.add_column("Org ID", style="magenta")
    table.add_column("Encrypted Fields", style="yellow")

    for cred in credentials:
        encrypted_fields = []
        for field_name, field_value in cred.inputs.items():
            if isinstance(field_value, str) and (
                field_value.startswith("$encrypted$")
                or field_value in ["[DECRYPTION_FAILED]", "[DECRYPTION_ERROR]"]
            ):
                encrypted_fields.append(field_name)

        table.add_row(
            str(cred.id),
            cred.name[:30] + "..." if len(cred.name) > 30 else cred.name,
            cred.credential_type_name,
            str(cred.organization_id) if cred.organization_id else "None",
            ", ".join(encrypted_fields) if encrypted_fields else "None",
        )

    console.print(table)


def display_credential_types_summary(credential_types: List[CredentialTypeData]) -> None:
    """Display a summary table of extracted credential types.

    Args:
        credential_types: List of credential types to summarize
    """
    table = Table(title="Extracted Tower Credential Types")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Kind", style="blue")
    table.add_column("Managed", style="magenta")
    table.add_column("Namespace", style="yellow")

    for cred_type in credential_types:
        table.add_row(
            str(cred_type.id),
            cred_type.name[:40] + "..." if len(cred_type.name) > 40 else cred_type.name,
            cred_type.kind,
            "✓" if cred_type.managed else "✗",
            cred_type.namespace or "None",
        )

    console.print(table)


@click.command()
@click.option("--tower-host", default="localhost", help="Tower database host", show_default=True)
@click.option("--tower-port", default="5432", help="Tower database port", show_default=True)
@click.option("--tower-db", default="awx", help="Tower database name", show_default=True)
@click.option("--tower-user", default="awx", help="Tower database username", show_default=True)
@click.option("--tower-password", help="Tower database password (will prompt if not provided)")
@click.option("--secret-key", help="Tower SECRET_KEY (will auto-discover if not provided)")
@click.option(
    "--config-path",
    default="/etc/tower/conf.d",
    help="Path to Tower configuration directory",
    show_default=True,
)
@click.option(
    "--output-file",
    default="tower_credentials_export.json",
    help="Output file for exported credentials",
    show_default=True,
)
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--dry-run", is_flag=True, help="Extract credentials but do not write to file")
def main(  # noqa: C901
    tower_host: str,
    tower_port: str,
    tower_db: str,
    tower_user: str,
    tower_password: Optional[str],
    secret_key: Optional[str],
    config_path: str,
    output_file: str,
    debug: bool,
    dry_run: bool,
) -> None:
    r"""Extract encrypted credentials from Ansible Tower for migration to AAP.

    This tool must be run on the Tower instance with root privileges to access
    the SECRET_KEY and database. It extracts and decrypts all credential data
    for secure migration to a new AAP instance.

    Examples:
        # Basic extraction with auto-discovery
        sudo python tower_credential_migrator.py

        # Specify custom database connection
        sudo python tower_credential_migrator.py --tower-host db.example.com --tower-password mypass

        # Dry run to test without writing file
        sudo python tower_credential_migrator.py --dry-run
    """
    global logger

    # Load environment variables from .env file
    load_env_file()

    # Override command line options with environment variables
    tower_host = get_env_override("TOWER_HOST", tower_host)
    tower_port = get_env_override("TOWER_PORT", tower_port)
    tower_db = get_env_override("TOWER_DB", tower_db)
    tower_user = get_env_override("TOWER_USER", tower_user)
    tower_password = get_env_override("TOWER_PASSWORD", tower_password)
    secret_key = get_env_override("TOWER_SECRET_KEY", secret_key)
    config_path = get_env_override("TOWER_CONFIG_PATH", config_path)
    output_file = get_env_override("TOWER_OUTPUT_FILE", output_file)
    # Handle boolean flags
    debug_env = get_env_override("TOWER_DEBUG")
    if debug_env:
        debug = debug_env.lower() in ("true", "1", "yes", "on")

    dry_run_env = get_env_override("TOWER_DRY_RUN")
    if dry_run_env:
        dry_run = dry_run_env.lower() in ("true", "1", "yes", "on")

    # Setup logging
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    # Display banner
    console.print(
        Panel.fit(
            "[bold blue]Tower Credential Migration Tool[/bold blue]\n"
            "Extracts encrypted credentials from Ansible Tower for AAP migration",
            border_style="blue",
        )
    )

    # Check if running as root
    if os.geteuid() != 0:
        console.print(
            "[red]Warning: Not running as root. May not be able to access SECRET_KEY.[/red]"
        )
        if not Confirm.ask("Continue anyway?"):
            raise click.Abort()

    try:
        # Discover or prompt for SECRET_KEY
        if not secret_key:
            console.print("[yellow]Attempting to discover Tower SECRET_KEY...[/yellow]")
            secret_key = discover_tower_secret_key(config_path)

        if not secret_key:
            console.print("[red]Could not auto-discover SECRET_KEY.[/red]")
            secret_key = Prompt.ask(
                "Please enter Tower SECRET_KEY", password=True, show_default=False
            )

        if not secret_key:
            raise click.ClickException("SECRET_KEY is required for credential decryption")

        # Discover or create database connection
        connection = None

        # Try to discover database config from postgres.py
        console.print("[yellow]Attempting to discover Tower database configuration...[/yellow]")
        discovered_connection = discover_tower_database_config(config_path)

        if discovered_connection:
            # Use discovered config, but allow password override
            connection = discovered_connection
            if tower_password:
                connection.password = tower_password
            elif not connection.password:
                connection.password = Prompt.ask(
                    f"Enter password for database user '{connection.username}'",
                    password=True,
                    show_default=False,
                )
        else:
            # Fall back to command line parameters
            console.print("[yellow]Using command line database parameters...[/yellow]")

            # Prompt for database password if not provided
            if not tower_password:
                tower_password = Prompt.ask(
                    f"Enter password for database user '{tower_user}'",
                    password=True,
                    show_default=False,
                )

            connection = TowerConnection(
                host=tower_host,
                port=tower_port,
                database=tower_db,
                username=tower_user,
                password=tower_password,
            )

        # Extract credentials
        extractor = TowerCredentialExtractor(connection, secret_key)

        console.print("[green]Connecting to Tower database...[/green]")
        extractor.connect()

        try:
            console.print("[green]Extracting credential types...[/green]")
            credential_types = extractor.extract_credential_types()

            console.print("[green]Extracting and decrypting credentials...[/green]")
            credentials = extractor.extract_credentials()

            if not credentials:
                console.print("[yellow]No credentials found in Tower database.[/yellow]")
                return

            # Display summaries
            if credential_types:
                display_credential_types_summary(credential_types)
            display_credentials_summary(credentials)

            if dry_run:
                console.print(
                    f"[yellow]Dry run complete. Found {len(credential_types)} credential types "
                    f"and {len(credentials)} credentials.[/yellow]"
                )
                return

            # Confirm export
            if not Confirm.ask(
                f"Export {len(credential_types)} credential types and "
                f"{len(credentials)} credentials to {output_file}?"
            ):
                console.print("[yellow]Export cancelled.[/yellow]")
                return

            # Export to file
            console.print(f"[green]Exporting data to {output_file}...[/green]")
            export_data_to_file(credentials, credential_types, output_file)

            console.print(
                Panel.fit(
                    f"[bold green]Success![/bold green]\n\n"
                    f"Exported {len(credential_types)} credential types and "
                    f"{len(credentials)} credentials to:\n"
                    f"[cyan]{os.path.abspath(output_file)}[/cyan]\n\n"
                    f"[yellow]Security Note:[/yellow] File has restricted permissions (600).\n"
                    f"Transfer securely to your AAP instance for import.",
                    border_style="green",
                )
            )

        finally:
            extractor.disconnect()

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
        raise click.ClickException(f"Migration failed: {e}")


if __name__ == "__main__":
    main()
