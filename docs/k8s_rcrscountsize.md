# Kubernetes Resource Counter and Sizer (`k8s_rcrscountsize.py`)

## Overview

This Python script connects to a Kubernetes cluster to count various standard Kubernetes resources within specified namespaces. It also calculates the approximate total size of specific resource types (ConfigMaps, Secrets, PVC Capacity, and optionally Custom Resources) on a per-namespace basis. The results are exported to a CSV file.

It can be used for tasks such as general resource inventory, identifying resource-heavy namespaces (in terms of object counts or potential data volume), and providing input data for capacity planning or chargeback models.

## Features

* **Resource Counting:** Counts standard Kubernetes resources per namespace, including:
  * Pods
  * Services
  * Deployments
  * ReplicaSets
  * StatefulSets
  * DaemonSets
  * Jobs
  * CronJobs
  * ConfigMaps
  * Secrets
  * PersistentVolumeClaims (PVCs)
  * ServiceAccounts
  * Endpoints
* **Cluster-Wide PV Count:** Logs the total count of PersistentVolumes (PVs) in the cluster.
* **Size Calculation:**
  * Calculates the combined size (in KiB) of ConfigMaps and Secrets (`TotalCoreResourcesSizeKiB`).
  * Calculates the total requested storage capacity (in GiB) of PVCs (`TotalPVCCapacityGiB`).
  * Optionally calculates the combined size (in KiB) of all Custom Resource (CR) instances found (`TotalCustomResourceSizeKiB`).
* **Namespace Targeting:** Can scan all namespaces or a single specified namespace.
* **CRD Support:** Optionally includes Custom Resource Definitions (CRDs) in the counts and size calculations.
* **CSV Output:** Exports the results to a customizable CSV file.
* **Safe File Writing:** Uses a file lock to prevent issues when writing the CSV file.
* **Logging:** Writes detailed (INFO level) logs to `logs/k8s_rcrscountsize.log`. Only outputs WARNING and ERROR messages to the console during execution.
* **Progress Bar:** Displays a progress bar (using `click.progressbar`) on the console when scanning multiple namespaces (via default scan or `--label-selector`).

## Dependencies

* Python 3.x
* Python Libraries:
  * `kubernetes`
  * `click`
  * `filelock`

You can typically install these using pip:

```bash
pip install kubernetes click filelock
```

* Access to a Kubernetes cluster (via a valid `kubeconfig` file or running within a cluster with a service account).

## Usage

Run the script from your terminal using `python`:

```bash
python src/k8s_rcrscountsize.py [OPTIONS]
```

### Command-Line Options

* `--namespace TEXT`: Specify a single namespace to scan. If omitted, the script attempts to scan all accessible namespaces.
* `--label-selector TEXT`: Filter namespaces using a standard Kubernetes label selector string (e.g., `'environment=production'`, `'tier!=frontend'`). Cannot be used with `--namespace`. Useful for targeting specific sets of namespaces in large clusters.
* `--include-crds`: Include Custom Resources (CRDs) in the counts and size calculations. **Warning:** This significantly increases runtime and API load.
* `--sizes-only`: Output only namespace and size columns, omitting resource counts. (Default: False)
* `--output-file PATH`: Path to the output CSV file. If omitted, a default name is generated in the `tmp/` directory based on the scope and options used:
  * Scope: `all_namespaces` if scanning multiple namespaces (default or via `--label-selector`), or the sanitized namespace name if using `--namespace`.
  * Suffixes: `_with_crds` is added if `--include-crds` is used; `_sizes_only` is added if `--sizes-only` is used.
  * Example Defaults: `tmp/all_namespaces_resources.csv`, `tmp/my_namespace_resources_with_crds_sizes_only.csv`.
* `--kubeconfig PATH`: Path to the kubeconfig file to use. If omitted, it uses the default kubeconfig location or in-cluster configuration.
* `--help`: Show the help message and exit.

### Examples

* **Scan all namespaces and output to default file:**

    ```bash
    python src/k8s_rcrscountsize.py
    ```

* **Scan only the `production` namespace:**

    ```bash
    python src/k8s_rcrscountsize.py --namespace production
    ```

* **Scan namespaces labeled 'backup-candidate=true':**

    ```bash
    python src/k8s_rcrscountsize.py --label-selector 'backup-candidate=true'
    ```

* **Scan all namespaces, include CRDs, and output to a specific file:**

    ```bash
    python src/k8s_rcrscountsize.py --include-crds --output-file /tmp/k8s_inventory.csv
    ```

* **Scan using a specific kubeconfig:**

    ```bash
    python src/k8s_rcrscountsize.py --kubeconfig ~/.kube/my-cluster-config
    ```

## Output File

The script generates a CSV file (e.g., `namespace_resources.csv`) with the following structure:

* **`Namespace`**: The name of the Kubernetes namespace.
* **Resource Count Columns**: Columns for each standard resource type found (e.g., `Pods`, `Deployments`, `ConfigMaps`, `ServiceAccounts`). The value represents the count of that resource in the namespace.
* **`TotalCoreResourcesSizeKiB`**: The combined approximate size (in KiB) of all ConfigMaps and Secrets within the namespace.
* **`TotalPVCCapacityGiB`**: The total requested storage capacity (in GiB) by all PVCs within the namespace.
* **`TotalCustomResourceSizeKiB`** (Optional): If `--include-crds` was used, this column shows the combined approximate size (in KiB) of all instances of all Custom Resources found within the namespace.

*Note: If a specific resource type is not found in *any* scanned namespace, its corresponding column might not appear in the CSV. Missing values within a row default to '0'.*

## Understanding Size Calculations and Verification

It's important to understand how the script calculates "size" as this impacts both the results and the script's performance.

### How Sizes Are Calculated

1. **ConfigMaps, Secrets, Custom Resources (`TotalCoreResourcesSizeKiB`, `TotalCustomResourceSizeKiB`):**
    * The script fetches the **full YAML/JSON manifest** of each individual resource via the Kubernetes API.
    * This manifest is converted to a JSON string.
    * The size reported is the **byte length of this JSON string representation** (encoded as UTF-8).
    * These byte counts are summed up (ConfigMaps + Secrets for `TotalCoreResourcesSizeKiB`; all CRs for `TotalCustomResourceSizeKiB`) and converted to KiB.
    * **Key Point:** This measures the size of the object's *representation in the API*, not the disk space it uses in etcd or the memory it consumes in controllers. Fetching the full manifest for every object is resource-intensive. This size can be considered a proxy for *metadata complexity*.

2. **PersistentVolumeClaims (`TotalPVCCapacityGiB`):**
    * The script reads the `status.capacity.storage` field from the PVC's status.
    * This value represents the **storage capacity requested** by the claim.
    * These requested capacities are summed up and converted to GiB.
    * **Key Point:** This is the *requested* capacity, not the *actual* disk usage within the volume. Actual usage may be lower or potentially higher (with thin provisioning).

### Verification Methods

While you cannot easily get the script's exact aggregated totals from `kubectl`, you can verify the underlying calculations:

* **Spot Check Manifest Sizes (CMs, Secrets, CRs):** Use `kubectl` to get the JSON representation of an individual object and pipe it to `wc -c` (byte count). This closely mimics the script's process for `TotalCoreResourcesSizeKiB` and `TotalCustomResourceSizeKiB` components.

    ```bash
    # ConfigMap Example
    kubectl get configmap <cm-name> -n <namespace> -o json | wc -c

    # Secret Example
    kubectl get secret <secret-name> -n <namespace> -o json | wc -c

    # Custom Resource Example (replace kind/name)
    kubectl get <crd-kind>.<group> <cr-instance-name> -n <namespace> -o json | wc -c
    ```

    Compare the byte count from `wc -c` with the script's internal calculation for that object (minor differences due to formatting are possible).

* **Spot Check PVC Capacity:** Use `kubectl` to view the `status.capacity.storage` for a specific PVC.

    ```bash
    kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.status.capacity.storage}'
    ```

    Manually verify the parsing of this value (e.g., `10Gi` is 10 * 1024^3 bytes).

* **Test Namespace:** Create a small test namespace with a known number of resources and manually sum their `wc -c` sizes or capacities to compare against the script's output for that single namespace.

## Performance Considerations and Impact

* **API Server Load & Network:** As explained above, calculating sizes requires fetching the *full manifest* for many objects (ConfigMaps, Secrets, optional CRs). This is much heavier than just listing objects and significantly increases the load on the Kubernetes API server and consumes more network bandwidth compared to only counting resources.
* **API Server Load:** The script makes numerous read requests (`LIST`, `GET`) to the Kubernetes API server. Running it against large clusters or scanning all namespaces can put a noticeable load on the API server.
* **Size Calculation Overhead:** To calculate sizes, the script fetches the *full* manifest for every ConfigMap, Secret, and (if `--include-crds` is used) Custom Resource instance. This is significantly more expensive than just listing them, consuming more network bandwidth, memory on the script's host, and API server resources.
* **CRD Impact (`--include-crds`):** Using the `--include-crds` flag dramatically increases the script's runtime and resource consumption:
* It first lists *all* CRDs in the cluster.
* Then, for *each* CRD, it tries to list *all* instances within *each* target namespace.
* Finally, it fetches the *full* manifest for *each* CR instance found to calculate its size.
    This can result in thousands of API calls on clusters with many CRDs and namespaces.
* **Large Namespaces:** Processing namespaces containing thousands of objects will take longer and require more memory locally to hold the lists of objects before processing.
* **Network Latency:** The script's speed is sensitive to the network latency between the machine running the script and the Kubernetes API server.

**Recommendations:**

* Avoid running the script frequently on large production clusters, especially with `--include-crds`.
* Consider running during off-peak hours.
* If possible, target specific namespaces using `--namespace` instead of scanning all namespaces.
* Monitor API server performance if running the script regularly on critical clusters.
