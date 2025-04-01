import os

import certifi


def create_custom_ca_bundle(custom_cert_path, output_path):
    """
    Create a custom CA bundle by combining the certifi bundle with a custom certificate.

    Args:
        custom_cert_path (str): Path to the custom certificate file.
        output_path (str): Path to the output file where the combined CA bundle will be saved.

    Returns:
        str: Path to the output file containing the combined CA bundle.
    """
    with open(certifi.where(), "r") as certifi_file:
        certifi_content = certifi_file.read()

    with open(custom_cert_path, "r") as custom_cert_file:
        custom_cert_content = custom_cert_file.read()

    combined_content = certifi_content + "\n" + custom_cert_content

    with open(output_path, "w") as output_file:
        output_file.write(combined_content)

    return output_path


# Create the custom bundle
custom_bundle_path = create_custom_ca_bundle(
    "/path/to/your/custom/cert.pem", "/path/to/output/custom-ca-bundle.pem"
)

# Set the environment variable to use the custom bundle
os.environ["SSL_CERT_FILE"] = custom_bundle_path
