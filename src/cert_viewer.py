#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A simple X.509 Certificate Viewer with security analysis capabilities.

Usage:
    python cert_viewer.py

    or

    python cert_viewer.py <hostname> <port>
"""

import datetime
import json

# import logging
import os
import signal
import socket
import ssl
import subprocess
import tempfile
import tkinter as tk
from datetime import timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional

import click
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from cryptography.x509.extensions import ExtensionNotFound
from cryptography.x509.oid import ExtensionOID
from rich.logging import RichHandler

from utils.logging_utils import get_logger, setup_logging


class CertificateSecurityAnalyzer:
    """Analyzes X.509 certificates for security vulnerabilities."""

    def __init__(self):
        """Initialize the CertificateSecurityAnalyzer."""
        self.logger = get_logger(__name__ + ".CertificateSecurityAnalyzer")
        self.weak_key_sizes = {
            "RSA": 2048,  # Minimum recommended RSA key size
            "EC": 256,  # Minimum recommended EC key size
        }

        self.weak_hash_algorithms = {"md5": True, "sha1": True}

        # Minimum TLS version recommended
        self.min_tls_version = ssl.TLSVersion.TLSv1_2

    def analyze_key_strength(self, cert: x509.Certificate) -> Dict[str, bool]:
        """Analyzes the strength of the certificate's public key."""
        public_key = cert.public_key()
        result = {"status": True, "message": "Strong key"}

        if isinstance(public_key, rsa.RSAPublicKey):
            key_size = public_key.key_size
            if key_size < self.weak_key_sizes["RSA"]:
                result = {
                    "status": False,
                    "message": f'Weak RSA key size: {key_size} bits (minimum recommended: {self.weak_key_sizes["RSA"]} bits)',
                }
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            key_size = public_key.curve.key_size
            if key_size < self.weak_key_sizes["EC"]:
                result = {
                    "status": False,
                    "message": f'Weak EC key size: {key_size} bits (minimum recommended: {self.weak_key_sizes["EC"]} bits)',
                }

        return result

    def analyze_signature_algorithm(self, cert: x509.Certificate) -> Dict[str, bool]:
        """Analyzes the strength of the certificate's signature algorithm."""
        sig_alg = cert.signature_algorithm_oid._name.lower()
        result = {"status": True, "message": "Strong signature algorithm"}

        for weak_alg in self.weak_hash_algorithms:
            if weak_alg in sig_alg:
                result = {"status": False, "message": f"Weak signature algorithm: {sig_alg}"}
                break

        return result

    def check_expiration(self, cert: x509.Certificate) -> Dict[str, bool]:
        """Checks the validity period of the certificate."""
        now = datetime.datetime.now(timezone.utc)
        result = {"status": True, "message": "Certificate is valid"}

        if now < cert.not_valid_before_utc:
            result = {
                "status": False,
                "message": f"Certificate is not yet valid (starts: {cert.not_valid_before_utc})",
            }
        elif now > cert.not_valid_after_utc:
            result = {
                "status": False,
                "message": f"Certificate has expired (expired: {cert.not_valid_after_utc})",
            }
        elif (cert.not_valid_after_utc - now).days < 30:
            result = {
                "status": False,
                "message": f"Certificate will expire soon ({cert.not_valid_after_utc})",
            }

        return result

    def analyze_certificate(self, cert: x509.Certificate) -> Dict[str, Dict[str, bool]]:
        """Performs a comprehensive security analysis of the certificate."""
        return {
            "key_strength": self.analyze_key_strength(cert),
            "signature": self.analyze_signature_algorithm(cert),
            "expiration": self.check_expiration(cert),
        }


class X509CertViewer:
    """Main class for the X.509 Certificate Viewer application."""

    def __init__(self, root):
        """Initialize the X509CertViewer application."""
        self.logger = get_logger(__name__ + ".X509CertViewer")
        self.root = root
        self.root.title("X.509 Certificate Viewer")

        # Handle window close button
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        # Handle Ctrl+C in terminal
        signal.signal(signal.SIGINT, self.signal_handler)

        # Initialize security analyzer
        self.security_analyzer = CertificateSecurityAnalyzer()

        # Load settings
        self.settings_file = os.path.join(str(Path.home()), ".cert_viewer_settings.json")
        self.settings = self.load_settings()

        # Apply window geometry
        if self.settings.get("window_geometry"):
            self.root.geometry(self.settings["window_geometry"])

        # UI Layout
        self.frame = tk.Frame(root)
        self.frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Create left and right panes
        self.paned_window = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        self.paned_window.grid(row=0, column=0, sticky="nsew")

        # Left pane for certificate list
        self.left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(self.left_frame, weight=1)

        # Certificate list with frame
        self.cert_list_frame = ttk.LabelFrame(self.left_frame, text="Certificates")
        self.cert_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create a frame for the listbox and scrollbar
        self.list_container = ttk.Frame(self.cert_list_frame)
        self.list_container.pack(fill=tk.BOTH, expand=True)

        # Create scrollbar first
        self.scrollbar = ttk.Scrollbar(self.list_container, orient=tk.VERTICAL)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Create listbox and pack it to fill remaining space
        self.cert_list = tk.Listbox(
            self.list_container, height=15, width=50, yscrollcommand=self.scrollbar.set
        )
        self.cert_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure the scrollbar to scroll the listbox
        self.scrollbar.config(command=self.cert_list.yview)

        # Right pane for details
        self.right_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(self.right_frame, weight=2)

        # Create notebook for different sections
        self.notebook = ttk.Notebook(self.right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Basic Info tab
        self.basic_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.basic_frame, text="Basic Info")

        # Security tab
        self.security_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.security_frame, text="Security Analysis")

        # Trust Chain tab
        self.trust_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.trust_frame, text="Trust Chain")

        # Usage tab
        self.usage_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.usage_frame, text="Usage & Restrictions")

        # Create text widgets for each tab
        self.basic_text = tk.Text(self.basic_frame, wrap=tk.WORD, height=20, width=80)
        self.basic_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.security_text = tk.Text(self.security_frame, wrap=tk.WORD, height=20, width=80)
        self.security_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.trust_text = tk.Text(self.trust_frame, wrap=tk.WORD, height=20, width=80)
        self.trust_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.usage_text = tk.Text(self.usage_frame, wrap=tk.WORD, height=20, width=80)
        self.usage_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Buttons
        self.button_frame = tk.Frame(root)
        self.button_frame.pack(pady=5)

        self.open_button = ttk.Button(
            self.button_frame,
            text="Open Certificate Bundle (Ctrl+O)",
            command=self.load_certificates,
        )
        self.open_button.grid(row=0, column=0, padx=5)

        self.fetch_button = ttk.Button(
            self.button_frame,
            text="Fetch Certificate from Site (Ctrl+F)",
            command=self.fetch_certificate_from_site,
        )
        self.fetch_button.grid(row=0, column=1, padx=5)

        self.validate_button = ttk.Button(
            self.button_frame, text="Validate Chain (Ctrl+V)", command=self.validate_trust_chain
        )
        self.validate_button.grid(row=0, column=2, padx=5)

        # Add Quit button
        self.quit_button = ttk.Button(self.button_frame, text="Quit", command=self.quit_app)
        self.quit_button.grid(row=0, column=3, padx=5)

        # Bind events
        self.cert_list.bind("<<ListboxSelect>>", self.display_certificate_details)
        self.root.bind("<Control-o>", lambda e: self.load_certificates())
        self.root.bind("<Control-f>", lambda e: self.fetch_certificate_from_site())
        self.root.bind("<Control-q>", lambda e: self.quit_app())
        self.root.bind("<Control-r>", lambda e: self.refresh_current_certificate())
        self.root.bind("<Control-v>", lambda e: self.validate_trust_chain())

        # Bind window close event
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        # Internal state
        self.certificates = []
        self.trust_chain = []

    def load_settings(self):
        """Load application settings from a JSON file."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load settings: {e}")
        return {"last_directory": str(Path.home()), "window_geometry": "800x600"}

    def save_settings(self):
        """Save application settings to a JSON file."""
        try:
            settings = {
                "last_directory": self.settings.get("last_directory", str(Path.home())),
                "window_geometry": self.root.geometry(),
            }
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
        except Exception as e:
            self.logger.error(f"Failed to save settings: {e}")

    def signal_handler(self, signum, frame):
        """Handle Ctrl+C signal."""
        self.logger.info("Received Ctrl+C. Cleaning up...")
        self.quit_app()

    def quit_app(self):
        """Clean up and quit the application."""
        try:
            self.logger.info("Shutting down application...")
            # Save settings before exit
            self.save_settings()

            # Destroy all widgets
            for widget in self.root.winfo_children():
                widget.destroy()

            # Quit the application
            self.root.quit()

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Force quit if cleanup fails
            self.root.destroy()

    def load_certificates(self):
        """Load certificates from a user-selected file."""
        self.logger.info("Loading certificates...")
        initial_dir = self.settings.get("last_directory", str(Path.home()))
        file_path = filedialog.askopenfilename(
            title="Open Certificate Bundle",
            initialdir=initial_dir,
            filetypes=[
                ("All Certificate Files", "*.pem *.crt *.cer *.der *.p12 *.pfx"),
                ("PEM Files", "*.pem"),
                ("Certificate Files", "*.crt *.cer"),
                ("DER Files", "*.der"),
                ("PKCS#12 Files", "*.p12 *.pfx"),
            ],
        )
        if not file_path:
            self.logger.debug("Certificate loading cancelled by user")
            return

        if not os.path.exists(file_path):
            error_msg = f"File not found: {file_path}"
            self.logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return

        self.logger.info(f"Loading certificates from: {file_path}")
        # Save last used directory
        self.settings["last_directory"] = os.path.dirname(file_path)

        self.certificates.clear()
        self.cert_list.delete(0, tk.END)
        self.clear_details()

        file_ext = os.path.splitext(file_path)[1].lower()

        try:
            if file_ext in [".p12", ".pfx"]:
                self.logger.info("Processing PKCS#12 file")
                self._load_pkcs12(file_path)
            elif file_ext == ".der":
                self.logger.info("Processing DER file")
                self._load_der(file_path)
            else:
                self.logger.info("Processing PEM file")
                self._load_pem(file_path)
        except Exception as e:
            error_msg = f"Failed to load certificates: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            messagebox.showerror("Error", error_msg)

    def _load_pem(self, file_path: str):
        """Load certificates from a PEM-encoded file."""
        self.logger.info(f"Loading PEM file: {file_path}")
        try:
            with open(file_path, "rb") as f:
                pem_data = f.read()
            certs = x509.load_pem_x509_certificates(pem_data)
            for cert in certs:
                self.certificates.append(cert)
                self.cert_list.insert(tk.END, cert.subject.rfc4514_string())
            self.logger.info(f"Loaded {len(certs)} certificates from PEM file.")
        except ValueError as e:
            # Handle cases where the file is not a valid PEM or contains no certs
            self.logger.error(
                f"Could not decode PEM file or no certificates found: {e}", exc_info=True
            )
            messagebox.showerror(
                "Error", f"Could not decode PEM file or no certificates found: {e}"
            )
        except Exception as e:
            self.logger.error(f"Error loading PEM file: {e}", exc_info=True)
            messagebox.showerror("Error", f"Error loading PEM file: {e}")

    def _load_der(self, file_path: str):
        """Load a certificate from a DER-encoded file."""
        self.logger.info(f"Loading DER file: {file_path}")
        try:
            with open(file_path, "rb") as f:
                der_data = f.read()
            cert = x509.load_der_x509_certificate(der_data)
            self.certificates.append(cert)
            self.cert_list.insert(tk.END, cert.subject.rfc4514_string())
            self.logger.info("Loaded 1 certificate from DER file.")
        except ValueError as e:
            self.logger.error(f"Could not decode DER file: {e}", exc_info=True)
            messagebox.showerror("Error", f"Could not decode DER file: {e}")
        except Exception as e:
            self.logger.error(f"Error loading DER file: {e}", exc_info=True)
            messagebox.showerror("Error", f"Error loading DER file: {e}")

    def _load_pkcs12(self, file_path: str):
        """Load certificates from a PKCS#12 file."""
        self.logger.info(f"Loading PKCS#12 file: {file_path}")
        password = simpledialog.askstring("Password", "Enter PKCS#12 password (if any):", show="*")
        password_bytes = password.encode() if password else None

        try:
            with open(file_path, "rb") as f:
                pkcs12_data = f.read()

            # Load the PKCS#12 data
            # The cryptography library's pkcs12.load_key_and_certificates
            # returns a tuple: (private_key, certificate, additional_certificates)
            key, cert, cas = pkcs12.load_key_and_certificates(
                pkcs12_data, password_bytes, default_backend()
            )

            if cert:
                self.certificates.append(cert)
                self.cert_list.insert(tk.END, cert.subject.rfc4514_string())
                self.logger.info("Loaded main certificate from PKCS#12 file.")

            if cas:
                for ca_cert in cas:
                    self.certificates.append(ca_cert)
                    self.cert_list.insert(tk.END, ca_cert.subject.rfc4514_string())
                self.logger.info(f"Loaded {len(cas)} CA certificates from PKCS#12 file.")

            if not cert and not cas:
                self.logger.warning("No certificates found in the PKCS#12 file.")
                messagebox.showwarning("Warning", "No certificates found in the PKCS#12 file.")

        except ValueError as e:
            # This can happen if the password is incorrect or the file is corrupted
            self.logger.error(
                f"Could not decode PKCS#12 file (check password or file integrity): {e}",
                exc_info=True,
            )
            messagebox.showerror(
                "Error",
                f"Could not decode PKCS#12 file. Ensure the password is correct and the file is not corrupted. Details: {e}",
            )
        except Exception as e:
            self.logger.error(f"Error loading PKCS#12 file: {e}", exc_info=True)
            messagebox.showerror("Error", f"Error loading PKCS#12 file: {e}")

    def _validate_chain_against_system_store(self, cert: x509.Certificate, temp_cert_path: str):
        """Helper to validate a certificate against the system trust store using OpenSSL."""
        try:
            result = subprocess.run(
                ["openssl", "verify", temp_cert_path],
                capture_output=True,
                text=True,
                check=True,
            )
            self.logger.info("Certificate validates against system trust store")
            self.trust_text.insert(tk.END, "  Certificate validates against system trust store\\n")
            self.trust_text.insert(tk.END, f"  Result: {result.stdout.strip()}\\n")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Certificate validation failed: {e.stderr.strip()}")
            self.trust_text.insert(tk.END, "  Certificate validation failed\\n")
            self.trust_text.insert(tk.END, f"  Error: {e.stderr.strip()}\\n")
        except FileNotFoundError:
            self.logger.error(
                "OpenSSL command not found. Please ensure OpenSSL is installed and in your PATH."
            )
            self.trust_text.insert(
                tk.END, "  Error: OpenSSL command not found. Cannot perform system validation.\\n"
            )

    def _perform_additional_chain_checks(self, chain: List[x509.Certificate]):  # noqa: C901
        """Helper to perform additional checks on the certificate chain."""
        all_valid = True
        for chain_cert in chain:
            exp_check = self.security_analyzer.check_expiration(chain_cert)
            if not exp_check["status"]:
                all_valid = False
                msg = f"  {exp_check['message']}"
                self.logger.warning(msg)
                self.trust_text.insert(tk.END, f"  {msg}\\n")

        if all_valid:
            self.logger.info("All certificates in chain are within validity period")
            self.trust_text.insert(
                tk.END, "  All certificates in chain are within validity period\\n"
            )

        for i, chain_cert in enumerate(chain[1:], 1):  # Skip end-entity cert
            try:
                key_usage = chain_cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
                if not key_usage.value.key_cert_sign:
                    msg = f"Certificate at level {i} doesn't have keyCertSign usage"
                    self.logger.warning(msg)
                    self.trust_text.insert(tk.END, f"  Warning: {msg}\\n")
            except ExtensionNotFound:
                msg = f"Certificate at level {i} has no Key Usage extension"
                self.logger.warning(msg)
                self.trust_text.insert(tk.END, f"  Warning: {msg}\\n")

        weak_sig = False
        for i, chain_cert in enumerate(chain):
            sig_alg = chain_cert.signature_algorithm_oid._name.lower()
            if "sha1" in sig_alg or "md5" in sig_alg:
                weak_sig = True
                msg = f"Certificate at level {i} uses weak signature algorithm: {sig_alg}"
                self.logger.warning(msg)
                self.trust_text.insert(tk.END, f"  Warning: {msg}\\n")

        if not weak_sig:
            self.logger.info("All certificates use strong signature algorithms")
            self.trust_text.insert(tk.END, "  All certificates use strong signature algorithms\\n")

    def validate_trust_chain(self):  # noqa: C901
        """Validate the trust chain of the selected certificate."""
        selection = self.cert_list.curselection()
        if not selection:
            self.logger.warning("No certificate selected for validation")
            messagebox.showwarning("Warning", "Please select a certificate first")
            return

        index = selection[0]
        cert = self.certificates[index]
        self.logger.info(f"Validating trust chain for certificate: {cert.subject.rfc4514_string()}")

        self.trust_text.config(state=tk.NORMAL)
        self.trust_text.delete(1.0, tk.END)
        self.trust_text.insert(tk.END, "=== Trust Chain Analysis ===\n\n")

        # Build trust chain from loaded certificates
        chain = self.build_trust_chain(cert)

        if not chain:
            msg = "Could not build complete trust chain from loaded certificates."
            self.logger.warning(msg)
            self.trust_text.insert(tk.END, msg + "\n\n")
        else:
            self.logger.info(f"Found chain of {len(chain)} certificates")
            self.trust_text.insert(tk.END, "Certificate Chain:\n")
            for i, chain_cert in enumerate(chain):
                self.trust_text.insert(tk.END, f"Level {i}:\n")
                self.trust_text.insert(
                    tk.END, f"  Subject: {chain_cert.subject.rfc4514_string()}\n"
                )
                self.trust_text.insert(tk.END, f"  Issuer: {chain_cert.issuer.rfc4514_string()}\n")
                if i > 0:  # Not the end-entity certificate
                    try:
                        basic_constraints = chain_cert.extensions.get_extension_for_oid(
                            ExtensionOID.BASIC_CONSTRAINTS
                        )
                        path_length = basic_constraints.value.path_length
                        self.trust_text.insert(tk.END, "  CA: Yes\n")
                        if path_length is not None:
                            self.trust_text.insert(
                                tk.END, f"  Path Length Constraint: {path_length}\n"
                            )
                    except ExtensionNotFound:
                        msg = f"Certificate at level {i} is not a CA certificate"
                        self.logger.warning(msg)
                        self.trust_text.insert(tk.END, f"  CA: No (Warning: {msg})\n")
                self.trust_text.insert(tk.END, "\n")

        # Try to validate against system trust store
        self.trust_text.insert(tk.END, "System Trust Store Validation:\n")
        try:
            self.logger.info("Attempting system trust store validation")
            # Create a temporary PEM file with the certificate
            with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as temp_cert_file:
                temp_cert_file.write(cert.public_bytes(Encoding.PEM))
                temp_cert_path = temp_cert_file.name

            self._validate_chain_against_system_store(cert, temp_cert_path)

            # Clean up temporary file
            if os.path.exists(temp_cert_path):
                os.unlink(temp_cert_path)

        except Exception as e:
            error_msg = f"Error during system validation: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.trust_text.insert(tk.END, f"  Error: {error_msg}\n")

        # Additional chain checks
        self.trust_text.insert(tk.END, "\nChain Analysis:\n")
        self.logger.info("Performing additional chain analysis")
        self._perform_additional_chain_checks(chain)

        self.trust_text.config(state=tk.DISABLED)

    def build_trust_chain(self, cert: x509.Certificate) -> List[x509.Certificate]:
        """Build the trust chain for a given certificate from loaded certificates."""
        chain = [cert]
        current_cert = cert

        # Try to build chain from loaded certificates
        while True:
            issuer_found = False
            for potential_issuer in self.certificates:
                if (
                    current_cert.issuer == potential_issuer.subject
                    and current_cert != potential_issuer
                ):
                    chain.append(potential_issuer)
                    current_cert = potential_issuer
                    issuer_found = True
                    break

            if not issuer_found:
                break

        return chain

    def check_tls_compatibility(self, cert: x509.Certificate):
        """Check TLS compatibility for the certificate (Placeholder)."""
        # Check signature algorithm compatibility
        sig_alg = cert.signature_algorithm_oid._name.lower()

        self.security_text.insert(tk.END, "  Compatible with:\n")

        # TLS 1.0/1.1
        if "sha1" in sig_alg or "md5" in sig_alg:
            self.security_text.insert(tk.END, "  - TLS 1.0 (Deprecated)\n")
            self.security_text.insert(tk.END, "  - TLS 1.1 (Deprecated)\n")

        # TLS 1.2
        if "sha256" in sig_alg or "sha384" in sig_alg or "sha512" in sig_alg:
            self.security_text.insert(tk.END, "  - TLS 1.2\n")

        # TLS 1.3
        if (
            ("sha256" in sig_alg or "sha384" in sig_alg or "sha512" in sig_alg)
            and not isinstance(cert.public_key(), rsa.RSAPublicKey)
            or cert.public_key().key_size >= 2048
        ):
            self.security_text.insert(tk.END, "  - TLS 1.3\n")

    def display_certificate_details(self, event):
        """Display all details for the selected certificate."""
        selection = self.cert_list.curselection()
        if not selection:
            self.logger.debug("No certificate selected")
            return

        index = selection[0]
        cert = self.certificates[index]
        self.logger.info(f"Displaying details for certificate: {cert.subject.rfc4514_string()}")

        # Clear all text widgets
        for widget in [self.basic_text, self.security_text, self.trust_text, self.usage_text]:
            widget.config(state=tk.NORMAL)
            widget.delete(1.0, tk.END)

        # Display basic information
        self.basic_text.insert(tk.END, self.get_basic_info(cert))

        # Display security analysis
        self.display_security_analysis(cert)

        # Display usage restrictions
        self.display_usage_restrictions(cert)

        # Display trust chain information
        self.display_trust_chain(cert)

        # Disable editing
        for widget in [self.basic_text, self.security_text, self.trust_text, self.usage_text]:
            widget.config(state=tk.DISABLED)

    def get_basic_info(self, cert: x509.Certificate) -> str:
        """Get basic certificate information."""
        self.logger.debug("Getting basic certificate information")
        return (
            f"Subject: {cert.subject.rfc4514_string()}\n"
            f"Issuer: {cert.issuer.rfc4514_string()}\n"
            f"Serial Number: {cert.serial_number}\n"
            f"Version: {cert.version.name}\n"
            f"Not Valid Before: {cert.not_valid_before_utc}\n"
            f"Not Valid After: {cert.not_valid_after_utc}\n"
        )

    def display_security_analysis(self, cert: x509.Certificate):
        """Display security analysis of the certificate."""
        self.logger.info("Performing security analysis")
        analysis = self.security_analyzer.analyze_certificate(cert)

        self.security_text.insert(tk.END, "=== Security Analysis ===\n\n")

        # Key Strength
        self.security_text.insert(tk.END, "Key Strength:\n")
        key_result = analysis["key_strength"]
        if not key_result["status"]:
            self.logger.warning(f"Weak key detected: {key_result['message']}")
        self.security_text.insert(tk.END, f"  {key_result['message']}\n\n")

        # Signature Algorithm
        self.security_text.insert(tk.END, "Signature Algorithm:\n")
        sig_result = analysis["signature"]
        if not sig_result["status"]:
            self.logger.warning(f"Weak signature algorithm: {sig_result['message']}")
        self.security_text.insert(tk.END, f"  {sig_result['message']}\n\n")

        # Expiration Status
        self.security_text.insert(tk.END, "Expiration Status:\n")
        exp_result = analysis["expiration"]
        if not exp_result["status"]:
            self.logger.warning(f"Certificate expiration issue: {exp_result['message']}")
        self.security_text.insert(tk.END, f"  {exp_result['message']}\\n\\n")

    def _display_key_usage(self, cert: x509.Certificate):
        """Helper to display Key Usage extension."""
        try:
            key_usage = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
            self.usage_text.insert(tk.END, "Key Usage:\\n")
            for usage, value in key_usage.value.__dict__.items():
                if value:
                    self.usage_text.insert(tk.END, f"  - {usage}\\n")
            self.logger.debug(
                f"Found {sum(1 for _, v in key_usage.value.__dict__.items() if v)} key usage restrictions"
            )
        except ExtensionNotFound:
            self.logger.warning("No Key Usage restrictions specified")
            self.usage_text.insert(tk.END, "No Key Usage restrictions specified\\n")

    def _display_extended_key_usage(self, cert: x509.Certificate):
        """Helper to display Extended Key Usage extension."""
        try:
            ext_key_usage = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
            self.usage_text.insert(tk.END, "\\nExtended Key Usage:\\n")
            for usage in ext_key_usage.value:
                self.usage_text.insert(tk.END, f"  - {usage._name}\\n")
            self.logger.debug(f"Found {len(ext_key_usage.value)} extended key usage restrictions")
        except ExtensionNotFound:
            self.logger.warning("No Extended Key Usage restrictions specified")
            self.usage_text.insert(tk.END, "\\nNo Extended Key Usage restrictions specified\\n")

    def _display_basic_constraints(self, cert: x509.Certificate):
        """Helper to display Basic Constraints extension."""
        try:
            basic_constraints = cert.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            )
            self.usage_text.insert(tk.END, "\\nBasic Constraints:\\n")
            self.usage_text.insert(tk.END, f"  CA: {basic_constraints.value.ca}\\n")
            if basic_constraints.value.ca and basic_constraints.value.path_length is not None:
                self.usage_text.insert(
                    tk.END, f"  Path Length Constraint: {basic_constraints.value.path_length}\\n"
                )
            self.logger.debug(
                f"Basic Constraints - CA: {basic_constraints.value.ca}, Path Length: {basic_constraints.value.path_length}"
            )
        except ExtensionNotFound:
            self.logger.warning("No Basic Constraints specified")
            self.usage_text.insert(tk.END, "\\nNo Basic Constraints specified\\n")

    def display_usage_restrictions(self, cert: x509.Certificate):
        """Display certificate usage restrictions."""
        self.logger.info("Analyzing certificate usage restrictions")
        self.usage_text.insert(tk.END, "=== Certificate Usage Restrictions ===\\n\\n")

        self._display_key_usage(cert)
        self._display_extended_key_usage(cert)
        self._display_basic_constraints(cert)

    def display_trust_chain(self, cert: x509.Certificate):
        """Display trust chain information for the certificate."""
        self.logger.info("Displaying trust chain information")
        chain = self.build_trust_chain(cert)

        self.trust_text.insert(tk.END, "=== Trust Chain ===\n\n")

        if not chain:
            msg = "Could not build trust chain from loaded certificates"
            self.logger.warning(msg)
            self.trust_text.insert(tk.END, f"{msg}\n")
            return

        self.logger.info(f"Found trust chain with {len(chain)} certificates")
        for i, chain_cert in enumerate(chain):
            self.trust_text.insert(tk.END, f"Level {i}:\n")
            self.trust_text.insert(tk.END, f"  Subject: {chain_cert.subject.rfc4514_string()}\n")
            self.trust_text.insert(tk.END, f"  Issuer: {chain_cert.issuer.rfc4514_string()}\n\n")

    def clear_details(self):
        """Clear all certificate detail text widgets."""
        for widget in [self.basic_text, self.security_text, self.trust_text, self.usage_text]:
            widget.config(state=tk.NORMAL)
            widget.delete(1.0, tk.END)
            widget.config(state=tk.DISABLED)

    def _get_certificate_from_socket(
        self, hostname: str, port: int = 443
    ) -> Optional[x509.Certificate]:
        """Helper to fetch the end-entity certificate from a host and port.

        Args:
            hostname: The hostname of the server.
            port: The port number (default is 443).

        Returns:
            An x509.Certificate object if successful, None otherwise.
        """
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssl_sock:
                der_cert = ssl_sock.getpeercert(binary_form=True)
                return x509.load_der_x509_certificate(der_cert, default_backend())
        return None  # Should not be reached if successful

    def _get_certificate_chain_from_socket(
        self, hostname: str, port: int = 443
    ) -> List[x509.Certificate]:
        """Helper to fetch the certificate chain from a host and port.

        Args:
            hostname: The hostname of the server.
            port: The port number (default is 443).

        Returns:
            A list of x509.Certificate objects representing the chain (excluding end-entity).
        """
        chain_certs = []
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssl_sock:
                cert_chain_pem = ssl_sock.getpeercert().get("chain", [])
                for cert_pem_item in cert_chain_pem:
                    # ssl_sock.getpeercert() for chain might return PEM strings or binary DER
                    # We need to handle both. The example here assumes PEM strings, which need conversion.
                    # If it directly provides DER, ssl.PEM_cert_to_DER_cert would fail.
                    # A more robust solution might check the type or try both decodings.
                    try:
                        # Assuming item is a PEM string
                        cert_der = ssl.PEM_cert_to_DER_cert(cert_pem_item)
                        ca_cert = x509.load_der_x509_certificate(cert_der, default_backend())
                        chain_certs.append(ca_cert)
                    except ssl.SSLError:  # If it's already DER or not a valid PEM
                        try:
                            # Assuming item might be binary DER
                            ca_cert = x509.load_der_x509_certificate(
                                cert_pem_item, default_backend()
                            )
                            chain_certs.append(ca_cert)
                        except Exception as e_der_load:  # Catch specific loading errors
                            self.logger.warning(
                                f"Could not decode certificate in chain (as DER): {e_der_load}"
                            )
                    except Exception as e_pem_load:  # Catch specific loading errors
                        self.logger.warning(
                            f"Could not decode certificate in chain (as PEM): {e_pem_load}"
                        )
        return chain_certs

    def _process_fetched_chain(self, hostname: str, port: int):
        """Helper to fetch and process the certificate chain.

        Args:
            hostname: The hostname of the server from which to fetch the chain.
            port: The port number to connect to.
        """
        try:
            self.logger.info(f"Attempting to fetch certificate chain for {hostname}")
            chain_certs_list = self._get_certificate_chain_from_socket(hostname, port)
            if chain_certs_list:
                self.logger.info(f"Found {len(chain_certs_list)} additional certificates in chain")
                for ca_cert in chain_certs_list:
                    if (
                        ca_cert not in self.certificates
                    ):  # Avoid duplicates if server sends end-entity in chain
                        self.certificates.append(ca_cert)
                        self.cert_list.insert(tk.END, ca_cert.subject.rfc4514_string())
            else:
                self.logger.info(
                    "No additional certificates found in chain via getpeercert()['chain']"
                )
        except Exception as e_chain:
            self.logger.warning(f"Could not fetch or process certificate chain: {e_chain}")

    def fetch_certificate_from_site(self):
        """Fetch SSL/TLS certificate from a remote HTTPS site."""
        hostname = simpledialog.askstring("Input", "Enter the HTTPS site (e.g., example.com):")
        if not hostname:
            self.logger.debug("Certificate fetch cancelled by user")
            return

        port = 443
        try:
            self.logger.info(f"Fetching certificate from {hostname}:{port}")
            cert = self._get_certificate_from_socket(hostname, port)

            if cert:
                self.logger.info("Successfully fetched end-entity certificate")
                self.certificates.clear()
                self.cert_list.delete(0, tk.END)
                self.clear_details()

                self.certificates.append(cert)
                self.cert_list.insert(tk.END, cert.subject.rfc4514_string())

                # Attempt to get the certificate chain
                self._process_fetched_chain(hostname, port)
            else:
                self.logger.error(f"Failed to fetch end-entity certificate for {hostname}")
                messagebox.showerror("Error", f"Could not retrieve certificate for {hostname}")

        except socket.gaierror:
            error_msg = f"Could not resolve hostname: {hostname}"
            self.logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
        except socket.timeout:
            error_msg = f"Connection to {hostname} timed out"
            self.logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
        except ssl.SSLError as e_ssl:
            error_msg = f"SSL error occurred: {str(e_ssl)}"
            self.logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
        except Exception as e_generic:
            error_msg = f"Failed to fetch certificate: {str(e_generic)}"
            self.logger.error(error_msg, exc_info=True)
            messagebox.showerror("Error", error_msg)


@click.command()
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging")
def main(debug):
    """X.509 Certificate Viewer GUI."""
    log_level = "DEBUG" if debug else "INFO"
    # Use RichHandler for console
    setup_logging(
        level=log_level,
        script_name="cert_viewer",
        handlers=[
            RichHandler(rich_tracebacks=True, show_time=False, show_level=True, show_path=False)
        ],
    )
    logger = get_logger(__name__)
    try:
        logger.info("Starting X.509 Certificate Viewer")
        import tkinter as tk  # Ensure Tkinter is imported here for click CLI

        root = tk.Tk()
        app = X509CertViewer(root)
        root.mainloop()
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception:
        logger.error("Unhandled exception", exc_info=True)
    finally:
        logger.info("Shutting down")
        try:
            if "root" in locals() and root.winfo_exists():
                root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
