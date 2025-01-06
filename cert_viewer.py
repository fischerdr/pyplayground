import os
import socket
import ssl
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from cryptography import x509
from cryptography.hazmat.backends import default_backend


class X509CertViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("X.509 Certificate Viewer")

        # UI Layout
        self.frame = tk.Frame(root)
        self.frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.cert_list = tk.Listbox(self.frame, height=15, width=50)
        self.cert_list.grid(row=0, column=0, padx=5, pady=5, sticky="ns")

        self.scrollbar = tk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.cert_list.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.cert_list.config(yscrollcommand=self.scrollbar.set)

        self.details_text = tk.Text(self.frame, wrap=tk.WORD, state=tk.DISABLED, height=15, width=80)
        self.details_text.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")

        self.button_frame = tk.Frame(root)
        self.button_frame.pack(pady=5)

        self.open_button = tk.Button(self.button_frame, text="Open Certificate Bundle", command=self.load_certificates)
        self.open_button.grid(row=0, column=0, padx=5)

        self.fetch_button = tk.Button(self.button_frame, text="Fetch Certificate from Site", command=self.fetch_certificate_from_site)
        self.fetch_button.grid(row=0, column=1, padx=5)

        # Bind events
        self.cert_list.bind("<<ListboxSelect>>", self.display_certificate_details)

        # Internal state
        self.certificates = []

    def load_certificates(self):
        file_path = filedialog.askopenfilename(
            title="Open Certificate Bundle",
            filetypes=[("Certificate Files", "*.pem *.crt *.cer")]
        )
        if not file_path:
            return

        if not os.path.exists(file_path):
            messagebox.showerror("Error", "File not found!")
            return

        self.certificates.clear()
        self.cert_list.delete(0, tk.END)
        self.clear_details()

        try:
            with open(file_path, "rb") as f:
                data = f.read()
                certs = data.split(b"-----END CERTIFICATE-----")
                for cert_data in certs:
                    if cert_data.strip():
                        cert_data += b"-----END CERTIFICATE-----\n"
                        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
                        self.certificates.append(cert)
                        self.cert_list.insert(tk.END, cert.subject.rfc4514_string())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load certificates: {e}")

    def fetch_certificate_from_site(self):
        hostname = simpledialog.askstring("Input", "Enter the HTTPS site (e.g., example.com):")
        if not hostname:
            return

        port = 443
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port)) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssl_sock:
                    der_certs = ssl_sock.getpeercert(binary_form=True)
                    cert = x509.load_der_x509_certificate(der_certs, default_backend())
                    self.certificates.clear()
                    self.cert_list.delete(0, tk.END)
                    self.clear_details()

                    self.certificates.append(cert)
                    self.cert_list.insert(tk.END, cert.subject.rfc4514_string())

                    # Attempt to fetch chain (if available)
                    for der_cert in ssl_sock.get_ca_certs(binary_form=True) or []:
                        ca_cert = x509.load_der_x509_certificate(der_cert, default_backend())
                        self.certificates.append(ca_cert)
                        self.cert_list.insert(tk.END, ca_cert.subject.rfc4514_string())

        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch certificate: {e}")

    def display_certificate_details(self, event):
        selection = self.cert_list.curselection()
        if not selection:
            return

        index = selection[0]
        cert = self.certificates[index]
        details = self.get_certificate_details(cert)

        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.insert(tk.END, details)
        self.details_text.config(state=tk.DISABLED)

    def get_certificate_details(self, cert):
        details = [
            f"Subject: {cert.subject.rfc4514_string()}",
            f"Issuer: {cert.issuer.rfc4514_string()}",
            f"Serial Number: {cert.serial_number}",
            f"Version: {cert.version.name}",
            f"Not Valid Before: {cert.not_valid_before}",
            f"Not Valid After: {cert.not_valid_after}",
            f"Extensions:"
        ]
        for ext in cert.extensions:
            details.append(f"  - {ext.oid._name}: {ext.value}")
        return "\n".join(details)

    def clear_details(self):
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.config(state=tk.DISABLED)


if __name__ == "__main__":
    root = tk.Tk()
    app = X509CertViewer(root)
    root.mainloop()
