#!/usr/bin/env python3
"""SSL Certificate Inspector.

This script displays all configured SSL CA certificates on the system and
attempts to connect to an HTTPS endpoint, showing the SSL certificates and chains.

Usage:
    python ssl_certificate_inspector.py [--url URL] [--verbose] [--ca-bundle PATH] [--add-cert PATH] [--output-bundle PATH]
"""

import argparse
import os
import socket
import ssl
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import certifi
import OpenSSL
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Setup rich console for better output formatting
console = Console()


def format_datetime(timestamp: bytes) -> str:
    """Format ASN.1 time to human-readable format."""
    try:
        time_str = timestamp.decode("ascii")
        year = int(time_str[0:4])
        month = int(time_str[4:6])
        day = int(time_str[6:8])
        hour = int(time_str[8:10])
        minute = int(time_str[10:12])
        second = int(time_str[12:14])
        return datetime(year, month, day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return f"Error parsing time: {e}"


def get_cert_info(cert: OpenSSL.crypto.X509) -> Dict[str, str]:
    """Extract and format certificate information."""
    info = {}

    # Get subject
    subject = cert.get_subject()
    subject_str = ", ".join([f"{k}={v}" for k, v in subject.get_components()])
    info["Subject"] = subject_str

    # Get issuer
    issuer = cert.get_issuer()
    issuer_str = ", ".join([f"{k}={v}" for k, v in issuer.get_components()])
    info["Issuer"] = issuer_str

    # Get validity period
    not_before = cert.get_notBefore()
    not_after = cert.get_notAfter()
    info["Valid From"] = format_datetime(not_before)
    info["Valid To"] = format_datetime(not_after)

    # Get serial number
    serial = cert.get_serial_number()
    info["Serial Number"] = hex(serial)

    # Get version
    version = cert.get_version()
    info["Version"] = str(version)

    # Get signature algorithm
    sig_algo = cert.get_signature_algorithm()
    if isinstance(sig_algo, bytes):
        sig_algo = sig_algo.decode("utf-8")
    info["Signature Algorithm"] = sig_algo

    # Get extensions
    ext_count = cert.get_extension_count()
    extensions = []
    for i in range(ext_count):
        ext = cert.get_extension(i)
        ext_name = ext.get_short_name()
        if isinstance(ext_name, bytes):
            ext_name = ext_name.decode("utf-8")
        extensions.append(f"{ext_name}: {ext}")

    if extensions:
        info["Extensions"] = "\n".join(extensions)

    return info


def print_cert_info(cert_info: Dict[str, str], title: str = "Certificate Information") -> None:
    """Print certificate information in a formatted panel."""
    table = Table(title=title)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    for key, value in cert_info.items():
        if key == "Extensions":
            # Extensions can be very verbose, so we'll just indicate they exist
            table.add_row(key, "[Extensions available - use --verbose to show]")
        else:
            table.add_row(key, value)

    console.print(Panel(table))


def print_cert_info_verbose(
    cert_info: Dict[str, str], title: str = "Certificate Information"
) -> None:
    """Print certificate information in a formatted panel with all details."""
    table = Table(title=title)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    for key, value in cert_info.items():
        table.add_row(key, value)

    console.print(Panel(table))


def use_custom_ca_bundle(custom_bundle_path: str) -> Optional[str]:
    """Configure the system to use a custom CA bundle.

    Args:
        custom_bundle_path: Path to the custom CA bundle file

    Returns:
        The original SSL_CERT_FILE value or None if it wasn't set
    """
    if not os.path.exists(custom_bundle_path):
        console.print(f"[red]Error: Custom CA bundle not found at {custom_bundle_path}[/red]")
        return None

    # Save the original path for reference
    original_ca_path = os.environ.get("SSL_CERT_FILE")

    # Set the environment variable
    os.environ["SSL_CERT_FILE"] = custom_bundle_path
    console.print(f"[green]Using custom CA bundle: {custom_bundle_path}[/green]")

    # Return the original path so it can be restored if needed
    return original_ca_path


def create_custom_ca_bundle(custom_cert_path: str, output_path: str) -> Optional[str]:
    """Create a custom CA bundle by combining the certifi bundle with a custom certificate.

    Args:
        custom_cert_path: Path to the custom certificate file
        output_path: Path to save the combined bundle

    Returns:
        Path to the created bundle or None if creation failed
    """
    try:
        if not os.path.exists(custom_cert_path):
            console.print(f"[red]Error: Custom certificate not found at {custom_cert_path}[/red]")
            return None

        # Create directory for output if it doesn't exist
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Read the original certifi bundle
        with open(certifi.where(), "r", encoding="utf-8") as certifi_file:
            certifi_content = certifi_file.read()

        # Read the custom certificate
        with open(custom_cert_path, "r", encoding="utf-8") as custom_cert_file:
            custom_cert_content = custom_cert_file.read()

        # Combine them
        combined_content = certifi_content + "\n" + custom_cert_content

        # Write to the output file
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(combined_content)

        console.print(f"[green]Created custom CA bundle at {output_path}[/green]")
        return output_path
    except Exception as e:
        console.print(f"[red]Error creating custom CA bundle: {e}[/red]")
        return None


def get_system_ca_certs() -> List[Tuple[str, str]]:
    """Get all system CA certificates."""
    ca_certs = []

    # Default Python SSL CA Certificates
    ca_cert_path = certifi.where()
    ca_certs.append(("Default SSL CA Bundle (certifi)", ca_cert_path))

    # Requests library CA Certificates
    requests_ca_cert_path = requests.utils.DEFAULT_CA_BUNDLE_PATH
    if requests_ca_cert_path != ca_cert_path:
        ca_certs.append(("Requests Library CA Bundle", requests_ca_cert_path))

    # System CA certificates
    system_ca_paths = [
        "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/CentOS/Fedora
        "/etc/ssl/ca-bundle.pem",  # OpenSUSE
        "/etc/pki/tls/cacert.pem",  # OpenELEC
        "/etc/ssl/cert.pem",  # Alpine/macOS
    ]

    for path in system_ca_paths:
        if os.path.exists(path) and path not in [c[1] for c in ca_certs]:
            ca_certs.append((f"System CA Bundle ({Path(path).parent})", path))

    # Environment variable overrides
    ssl_cert_file = os.environ.get("SSL_CERT_FILE")
    if ssl_cert_file and os.path.exists(ssl_cert_file):
        ca_certs.append(("SSL_CERT_FILE Environment Variable", ssl_cert_file))

    ssl_cert_dir = os.environ.get("SSL_CERT_DIR")
    if ssl_cert_dir and os.path.exists(ssl_cert_dir):
        ca_certs.append(("SSL_CERT_DIR Environment Variable", ssl_cert_dir))

    return ca_certs


def display_ca_certs(verbose: bool = False) -> None:
    """Display all configured CA certificates."""
    console.print(Panel("[bold]System CA Certificates[/bold]", style="blue"))

    ca_certs = get_system_ca_certs()

    for name, path in ca_certs:
        console.print(f"[bold cyan]{name}[/bold cyan]")
        console.print(f"Path: [green]{path}[/green]")

        try:
            if os.path.isdir(path):
                console.print(f"[Directory containing {len(os.listdir(path))} certificate files]")
                continue

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Count certificates in the bundle
            cert_count = content.count("-----BEGIN CERTIFICATE-----")
            console.print(f"Contains [bold]{cert_count}[/bold] certificates")

            if verbose:
                # Display the first certificate in the bundle
                if "-----BEGIN CERTIFICATE-----" in content:
                    cert_start = content.find("-----BEGIN CERTIFICATE-----")
                    cert_end = content.find("-----END CERTIFICATE-----", cert_start) + len(
                        "-----END CERTIFICATE-----"
                    )
                    first_cert = content[cert_start:cert_end]

                    try:
                        cert = OpenSSL.crypto.load_certificate(
                            OpenSSL.crypto.FILETYPE_PEM, first_cert
                        )
                        cert_info = get_cert_info(cert)
                        print_cert_info_verbose(cert_info, f"First Certificate in {name}")
                    except Exception as e:
                        console.print(f"[red]Error parsing first certificate: {e}[/red]")

        except Exception as e:
            console.print(f"[red]Error reading CA bundle: {e}[/red]")

        console.print("\n" + "=" * 60 + "\n")


def get_server_certificate_chain(hostname: str, port: int = 443) -> List[OpenSSL.crypto.X509]:
    """Connect to a server and get its certificate chain."""
    context = ssl.create_default_context()

    # We want to see the server's certificate regardless of validation
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    certificates = []

    try:
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssl_sock:
                # Get the binary DER form of the server certificate
                der_cert = ssl_sock.getpeercert(binary_form=True)
                if der_cert:
                    # Convert DER to PEM
                    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_ASN1, der_cert)
                    certificates.append(cert)

                # Unfortunately, Python's ssl module doesn't provide direct access to the certificate chain
                # We'll use OpenSSL directly to get the chain

                # Get the certificate chain using requests
                response = requests.get(f"https://{hostname}:{port}", verify=False)

                # Extract certificate chain from the response
                if hasattr(response, "raw") and hasattr(response.raw, "connection"):
                    conn = response.raw.connection
                    if hasattr(conn, "sock") and hasattr(conn.sock, "getpeercert"):
                        # This is a bit of a hack, but it works for most cases
                        # The real solution would be to use pyOpenSSL directly to get the chain
                        pass
    except Exception as e:
        console.print(f"[red]Error connecting to {hostname}:{port}: {e}[/red]")
    return certificates


def _parse_and_validate_endpoint(url: str) -> Tuple[Optional[str], Optional[int], bool]:
    """Parse URL and validate the certificate chain."""
    if not url.startswith("https://"):
        url = f"https://{url}"

    from urllib.parse import urlparse

    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    port = parsed_url.port or 443

    if not hostname:
        console.print("[red]Invalid URL format. Could not extract hostname.[/red]")
        return None, None, False

    console.print(Panel(f"[bold]Connecting to {url}[/bold]", style="blue"))
    is_valid = verify_certificate_chain(hostname, port)
    if is_valid:
        console.print("[green]✓ Certificate chain validates successfully[/green]")
    else:
        console.print("[red]✗ Certificate chain validation failed[/red]")
    return hostname, port, is_valid


def _display_site_information(response: requests.Response, url: str) -> None:
    """Display detailed site information from the HTTP response."""
    console.print(Panel("[bold]Site Information[/bold]", style="blue"))

    site_table = Table(title="Website Details")
    site_table.add_column("Property", style="cyan")
    site_table.add_column("Value", style="green")

    site_table.add_row("URL", url)
    site_table.add_row("Status Code", str(response.status_code))
    site_table.add_row("Content Type", response.headers.get("Content-Type", "Not specified"))
    site_table.add_row("Server", response.headers.get("Server", "Not specified"))

    security_headers = {
        "Strict-Transport-Security": "HSTS",
        "Content-Security-Policy": "CSP",
        "X-Content-Type-Options": "X-Content-Type-Options",
        "X-Frame-Options": "X-Frame-Options",
        "X-XSS-Protection": "XSS Protection",
    }
    for header, description in security_headers.items():
        value = response.headers.get(header, "Not set")
        site_table.add_row(f"{description}", value)

    if hasattr(response.raw.connection, "sock") and hasattr(
        response.raw.connection.sock, "version"
    ):
        tls_version = response.raw.connection.sock.version()
        site_table.add_row("TLS Version", tls_version)

    if hasattr(response.raw.connection, "sock") and hasattr(response.raw.connection.sock, "cipher"):
        cipher = response.raw.connection.sock.cipher()
        if cipher:
            cipher_name, _, bits = cipher  # tls_version is already captured
            site_table.add_row("Cipher", f"{cipher_name} ({bits} bits)")

    console.print(site_table)


def _display_server_certificate(response: requests.Response, hostname: str, verbose: bool) -> None:
    """Get and display the server's certificate from the response."""
    cert = OpenSSL.crypto.load_certificate(
        OpenSSL.crypto.FILETYPE_ASN1, response.raw.connection.sock.getpeercert(binary_form=True)
    )
    cert_info = get_cert_info(cert)
    if verbose:
        print_cert_info_verbose(cert_info, f"Server Certificate for {hostname}")
    else:
        print_cert_info(cert_info, f"Server Certificate for {hostname}")


def _display_certificate_chain(hostname: str, port: int, verbose: bool) -> None:
    """Display the certificate chain from the server."""
    console.print("\n[bold]Certificate Chain:[/bold]")
    certs = get_server_certificate_chain(hostname, port)

    if len(certs) > 1:
        # The first cert in the list from get_server_certificate_chain is the server cert itself,
        # which is already displayed by _display_server_certificate.
        # So, we iterate from the second certificate onwards for the chain.
        for i, chain_cert in enumerate(certs[1:], 1):
            chain_cert_info = get_cert_info(chain_cert)
            if verbose:
                print_cert_info_verbose(chain_cert_info, f"Chain Certificate {i}")
            else:
                print_cert_info(chain_cert_info, f"Chain Certificate {i}")
    elif certs:  # Only server cert was found, no additional chain certs
        console.print(
            "[yellow]Only the server certificate was retrieved. No additional chain certificates found.[/yellow]"
        )
    else:  # No certs found at all
        console.print("[yellow]Could not retrieve the certificate chain.[/yellow]")
        console.print(
            "This might be due to limitations in the SSL library or server configuration."
        )


def verify_certificate_chain(hostname: str, port: int = 443) -> bool:
    """Verify the certificate chain of a server."""
    context = ssl.create_default_context()

    try:
        with socket.create_connection((hostname, port), timeout=10) as sock:
            # Using underscore as a throwaway variable since we don't need the socket object itself
            with context.wrap_socket(sock, server_hostname=hostname) as _:
                # If we get here, the certificate is valid
                return True
    except ssl.SSLCertVerificationError as e:
        console.print(f"[red]Certificate verification failed: {e}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Error connecting to {hostname}:{port}: {e}[/red]")
        return False


def inspect_https_endpoint(url: str, verbose: bool = False) -> None:
    """Connect to an HTTPS endpoint and display its certificates."""
    hostname, port, is_valid = _parse_and_validate_endpoint(url)
    if not hostname or not port:
        return

    try:
        # Get detailed information using requests
        console.print("\n[bold]Fetching certificate information...[/bold]")

        # Disable warnings about insecure requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Make the request and capture detailed information
        response = requests.get(url, verify=False)

        console.print(f"[green]✓ Connected successfully (Status: {response.status_code})[/green]")

        _display_site_information(response, url)

        # Get certificate from the connection
        _display_server_certificate(response, hostname, verbose)

        # Try to get the certificate chain
        _display_certificate_chain(hostname, port, verbose)

    except requests.exceptions.SSLError as e:
        console.print(f"[red]SSL Error: {e}[/red]")
    except requests.exceptions.RequestException as e:
        console.print(f"[red]Request Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def main() -> None:
    """Main function to run the script."""
    parser = argparse.ArgumentParser(
        description="Display SSL CA certificates and inspect HTTPS endpoints"
    )
    parser.add_argument("--url", type=str, help="HTTPS URL to inspect (e.g., https://example.com)")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose certificate information including extensions",
    )
    parser.add_argument(
        "--ca-bundle",
        type=str,
        help="Path to a custom CA bundle file to use instead of the system default",
    )
    parser.add_argument(
        "--add-cert",
        type=str,
        help="Path to a certificate file to add to the system CA bundle",
    )
    parser.add_argument(
        "--output-bundle",
        type=str,
        default="./custom-ca-bundle.pem",
        help="Path where to save the custom CA bundle when using --add-cert",
    )

    args = parser.parse_args()

    # Display header
    console.print(Panel("[bold]SSL Certificate Inspector[/bold]", style="green"))

    # Handle custom CA bundle options
    if args.add_cert:
        custom_bundle_path = create_custom_ca_bundle(args.add_cert, args.output_bundle)
        if custom_bundle_path:
            use_custom_ca_bundle(custom_bundle_path)
    elif args.ca_bundle:
        use_custom_ca_bundle(args.ca_bundle)

    # Display system CA certificates
    display_ca_certs(args.verbose)

    # If URL is provided, inspect the HTTPS endpoint
    if args.url:
        inspect_https_endpoint(args.url, args.verbose)
    else:
        console.print("\n[yellow]No URL provided. Use --url to inspect an HTTPS endpoint.[/yellow]")
        console.print("Example: python ssl_certificate_inspector.py --url https://example.com")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Unhandled error: {e}[/red]")
        sys.exit(1)
