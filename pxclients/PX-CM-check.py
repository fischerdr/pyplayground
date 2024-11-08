import json
from collections import defaultdict


def summarize_configmap_requests(log_file_path):
    """
    Analyzes and summarizes the API logs to determine how many times each ConfigMap
    was accessed by which pods and from which source IPs. Also verifies total logs processed.
    """
    # Dictionary to store summarized information on ConfigMap requests
    configmap_summary = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    total_entries = 0
    valid_entries = 0

    with open(log_file_path, 'r') as file:
        for line in file:
            total_entries += 1  # Count each line processed
            try:
                # Parse each line as JSON
                log_entry = json.loads(line)

                # We're interested in "GET" requests to ConfigMaps
                if log_entry.get("verb") == "get" and log_entry.get("objectRef", {}).get("resource") == "configmaps":
                    namespace = log_entry["objectRef"].get("namespace")
                    name = log_entry["objectRef"].get("name")

                    # Ensure pod_name is always a string
                    pod_name_data = log_entry["user"]["extra"].get("authentication.kubernetes.io/pod-name", "unknown")
                    pod_name = pod_name_data if isinstance(pod_name_data, str) else ",".join(pod_name_data)

                    source_ip = log_entry.get("sourceIPs", ["unknown"])[0]

                    # Track accesses by namespace, ConfigMap, pod, and source IP
                    configmap_summary[f"{namespace}/{name}"][pod_name][source_ip] += 1
                    valid_entries += 1  # Count each valid log entry processed
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # Handle any parsing or data issues and continue processing
                continue

    # Output the summarized findings
    print(f"Total entries processed: {total_entries}")
    print(f"Total valid entries: {valid_entries}\n")

    for configmap, pod_data in configmap_summary.items():
        print(f"ConfigMap: {configmap}")
        total_accesses = 0
        for pod_name, ip_data in pod_data.items():
            pod_access_count = sum(ip_data.values())
            total_accesses += pod_access_count
            print(f"  Pod: {pod_name}, Total accesses: {pod_access_count}")
            for ip, count in ip_data.items():
                print(f"    From IP: {ip}, Accesses: {count}")
        print(f"Total accesses to {configmap}: {total_accesses}\n")


# Usage example:
log_file_path = 'CS0799266-cld-paas-p-euse1c-4-ocadmlogs.txt'
summarize_configmap_requests(log_file_path)
