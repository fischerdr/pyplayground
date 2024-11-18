import ssl
import certifi
import requests
from kubernetes.config.kube_config import KubeConfigMerger
import os
import base64
import argparse
from OpenSSL import crypto

def print_pem_info(pem_content):
    """
    Parse and print PEM certificate information (issuer, subject, validity, etc.).
    """
    try:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, pem_content)
        issuer = cert.get_issuer()
        subject = cert.get_subject()
        valid_from = cert.get_notBefore().decode("utf-8")
        valid_to = cert.get_notAfter().decode("utf-8")
        
        print("      PEM Certificate Information:")
        print(f"         Issuer: {issuer}")
        print(f"         Subject: {subject}")
        print(f"         Valid From: {valid_from}")
        print(f"         Valid To: {valid_to}")
    except Exception as e:
        print(f"      Error parsing PEM information: {e}")

def list_ca_certificates(kube_config_path):
    # Default Python SSL CA Certificates
    print("1. Default SSL CA Bundle (certifi):")
    ca_cert_path = certifi.where()
    print(f"   CA Certificate Path: {ca_cert_path}")
    try:
        with open(ca_cert_path, 'r') as f:
            ca_certs = f.read()
        print("   CA Certificates (showing first 500 characters):\n")
        print(ca_certs[:500])  # Display the first 500 characters for brevity
        print_pem_info(ca_certs)
    except Exception as e:
        print(f"   Error reading CA bundle: {e}")
    print("\n" + "="*60 + "\n")

    # Requests library CA Certificates
    print("2. Requests Library CA Bundle:")
    try:
        requests_ca_cert_path = requests.utils.DEFAULT_CA_BUNDLE_PATH
        print(f"   CA Certificate Path: {requests_ca_cert_path}")
        with open(requests_ca_cert_path, 'r') as f:
            ca_certs = f.read()
        print("   CA Certificates (showing first 500 characters):\n")
        print(ca_certs[:500])
        print_pem_info(ca_certs)
    except Exception as e:
        print(f"   Error reading Requests CA bundle: {e}")
    print("\n" + "="*60 + "\n")

    # Kubernetes library CA Certificates
    print("3. Kubernetes Library CA Certificates:")
    print(f"   Kubernetes Config Path: {kube_config_path}")
    if not os.path.exists(kube_config_path):
        print("   Kubernetes config file not found.")
        return

    try:
        kube_config = KubeConfigMerger(kube_config_path)

        # Extract cluster information
        clusters = kube_config.config['clusters']
        for cluster in clusters:
            name = cluster['name']
            cluster_data = cluster['cluster']
            ca_data = cluster_data['certificate-authority-data'] if 'certificate-authority-data' in cluster_data else None
            ca_file = cluster_data['certificate-authority'] if 'certificate-authority' in cluster_data else None

            print(f"   Cluster: {name}")
            if ca_data:
                print("      CA Certificate (decoded, showing first 500 characters):")
                decoded_ca = base64.b64decode(ca_data).decode('utf-8')
                print(decoded_ca[:500])
                print_pem_info(decoded_ca)
            elif ca_file:
                print(f"      CA Certificate Path: {ca_file}")
                try:
                    with open(ca_file, 'r') as f:
                        cert_content = f.read()
                    print("      CA Certificate Content (showing first 500 characters):")
                    print(cert_content[:500])
                    print_pem_info(cert_content)
                except Exception as e:
                    print(f"      Error reading CA certificate file: {e}")
            else:
                print("      No CA Certificate configured for this cluster.")
    except Exception as e:
        print(f"   Error reading Kubernetes configuration: {e}")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Display CA certificates used by Python, Requests, and Kubernetes.")
    parser.add_argument(
        "--kubeconfig",
        type=str,
        help="Path to the Kubernetes configuration file. Overrides KUBECONFIG environment variable.",
    )
    args = parser.parse_args()

    # Determine the Kubernetes config file location
    kube_config_path = (
        args.kubeconfig  # Command-line argument
        or os.environ.get("KUBECONFIG")  # Environment variable
        or os.path.expanduser("~/.kube/config")  # Default location
    )

    list_ca_certificates(kube_config_path)
