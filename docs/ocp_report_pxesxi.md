# OpenShift and VMware ESXi Host Report Generator

## Overview

The `ocp_report_pxesxi.py` script generates comprehensive reports about OpenShift clusters, their MachineSets, and the corresponding VMware ESXi hosts. It provides insights into the relationship between OpenShift infrastructure and the underlying VMware infrastructure, including Portworx pod counts and ESXi host distribution.

## Features

- Connect to both OpenShift and VMware vSphere environments
- Process single or multiple OpenShift clusters
- Generate detailed or brief reports
- Output in table or JSON format
- Track Portworx pods across clusters
- Map MachineSets to VMware clusters and ESXi hosts
- Identify unique ESXi hosts per cluster

## Prerequisites

- Python 3.9+
- Required Python packages:
  - kubernetes
  - pyVmomi
  - click
  - rich
  - tenacity
- Access to OpenShift clusters (kubeconfig files)
- Access to VMware vSphere environment

## Usage

### Basic Usage

```bash
# Process a single cluster
python src/ocp_report_pxesxi.py --kubeconfig /path/to/kubeconfig

# Process multiple clusters from a list file
python src/ocp_report_pxesxi.py --clusterlist /path/to/clusterlist.txt

# Generate a brief report
python src/ocp_report_pxesxi.py --kubeconfig /path/to/kubeconfig --brief

# Output in JSON format
python src/ocp_report_pxesxi.py --kubeconfig /path/to/kubeconfig --output-format json
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--kubeconfig` | Path to a single kubeconfig file |
| `--clusterlist` | Path to a file containing multiple kubeconfig paths (one per line) |
| `--vsphere-host` | VMware vSphere host address (optional if using credentials secret) |
| `--vsphere-user` | VMware vSphere username (optional if using credentials secret) |
| `--vsphere-password` | VMware vSphere password (optional if using credentials secret or env var) |
| `--namespace` | Namespace where MachineSets reside (default: openshift-machine-api) |
| `--output-format` | Output format: table or json (default: table) |
| `--disable-ssl` | Disable SSL verification for vSphere connection |
| `--vsphere-cert-path` | Path to a custom SSL certificate file for vSphere connection. Overrides VSPHERE_SSL_CERT_PATH env var and default fallback. |
| `--brief` | Generate a brief summary report instead of detailed report |
| `--credentials-secret` | Kubernetes Secret containing vSphere credentials (default: px-vsphere-secret) |
| `--credentials-namespace` | Namespace containing the credentials Secret (default: portworx) |
| `--timeout` | Connection timeout in seconds (default: 30) |
| `--px-namespace` | Namespace where Portworx pods are located (default: portworx) |
| `--debug` | Enable debug logging |

## Output Formats

### Detailed Table Output

The detailed table output includes:

1. For each OpenShift cluster:
   - Cluster name
   - Portworx pods count
   - Total unique ESXi hosts count
   - Table of MachineSets with their Datacenter, VMware Cluster, and Datastore
   - Table of unique ESXi hosts with CPU cores, memory, and state information

Example:

```text
Cluster: cluster-name
Portworx pods in namespace 'portworx': 146
Total unique ESXi hosts in this cluster: 54

OpenShift MachineSets to VMware ESXi Clusters Mapping for cluster-name
┏━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ MachineSet ┃ Datacenter ┃ VMware Cluster ┃ Datastore ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ machineset1│ datacenter1│ vmware-cluster1│ datastore1│
└────────────┴───────────┴───────────────┴───────────┘

ESXi Hosts Details for cluster-name
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Cluster       ┃ Host        ┃ CPU Cores ┃ Memory (GB) ┃ State   ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━┩
│ vmware-cluster1│ esxi-host1  │        32 │         256 │ poweredOn│
└───────────────┴─────────────┴───────────┴─────────────┴─────────┘
```

### Brief Table Output

The brief table output includes:

- Total Portworx pods count across all clusters
- Total unique ESXi hosts count across all clusters (globally unique ESXi hosts based on their names)
- Summary table showing OpenShift clusters, VMware clusters, ESXi host counts, and Portworx pod counts (shown only once per OpenShift cluster)

Example:

```text
Total Portworx pods across all clusters: 146
Total unique ESXi hosts across all clusters: 54

                       OpenShift and VMware Clusters Summary                        
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ OpenShift Cluster   ┃ VMware Cluster      ┃ ESXi Host Count ┃ Portworx Pod Count ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ cluster-name        │ vmware-cluster1     │              10 │                146 │
│ cluster-name        │ vmware-cluster2     │              10 │                    │
│ cluster-name        │ vmware-cluster3     │              14 │                    │
│ cluster-name        │ vmware-cluster4     │              20 │                    │
└─────────────────────┴─────────────────────┴─────────────────┴────────────────────┘
```

### Detailed JSON Output

The detailed JSON output organizes data hierarchically:

- By OpenShift cluster
- Within each cluster:
  - Portworx pods count
  - Total ESXi hosts count
  - Datacenters
  - VMware clusters within each datacenter
  - ESXi hosts within each VMware cluster

Example:

```json
{
  "cluster-name": {
    "portworx_pods_count": 146,
    "total_esxi_hosts": 54,
    "datacenters": {
      "datacenter1": {
        "vmware-cluster1": {
          "hosts": ["esxi-host1", "esxi-host2"],
          "hosts_count": 2
        },
        "vmware-cluster2": {
          "hosts": ["esxi-host3", "esxi-host4"],
          "hosts_count": 2
        }
      }
    }
  }
}
```

### Brief JSON Output

The brief JSON output provides a condensed view:

- Total Portworx pods count across all clusters
- Total unique ESXi hosts count across all clusters (globally unique ESXi hosts based on their names)
- Summary of OpenShift clusters with:
  - Portworx pod count per cluster (shown only once per OpenShift cluster)
  - VMware clusters with their host counts

Example:

```json
{
  "portworx_pods_count": 146,
  "total_esxi_hosts": 54,
  "clusters": {
    "cluster-name": {
      "px_pod_count": 146,
      "vmware_clusters": {
        "vmware-cluster1": {
          "hosts_count": 10
        },
        "vmware-cluster2": {
          "hosts_count": 10
        },
        "vmware-cluster3": {
          "hosts_count": 14
        },
        "vmware-cluster4": {
          "hosts_count": 20
        }
      }
    }
  }
}
```

## Use Cases

### 1. Single Cluster Analysis

```bash
python src/ocp_report_pxesxi.py --kubeconfig /path/to/kubeconfig
```

This scenario is useful for:

- Detailed analysis of a single OpenShift cluster
- Understanding the relationship between MachineSets and VMware infrastructure
- Identifying ESXi hosts running OpenShift nodes
- Checking Portworx pod distribution

### 2. Multi-Cluster Comparison

```bash
python src/ocp_report_pxesxi.py --clusterlist /path/to/clusterlist.txt
```

This scenario is useful for:

- Comparing multiple OpenShift clusters
- Understanding resource distribution across clusters
- Identifying clusters with high or low ESXi host utilization
- Checking Portworx pod distribution across multiple clusters

### 3. Brief Summary for Quick Overview

```bash
python src/ocp_report_pxesxi.py --clusterlist /path/to/clusterlist.txt --brief
```

This scenario is useful for:

- Quick overview of all clusters
- High-level summary of ESXi host distribution
- Total Portworx pod count across the environment
- Management reporting and capacity planning

### 4. JSON Output for Integration

```bash
python src/ocp_report_pxesxi.py --clusterlist /path/to/clusterlist.txt --output-format json
```

This scenario is useful for:

- Integration with other tools or dashboards
- Data processing and analysis
- Custom reporting
- Automation workflows

## Troubleshooting

### Common Issues

1. **VMware Connection Failures**
   - Ensure vSphere credentials are correct
   - Check network connectivity to vSphere host
   - Verify SSL settings (use `--disable-ssl` if needed)

2. **Kubernetes Authentication Issues**
   - Ensure kubeconfig files are valid and up-to-date
   - Verify permissions to access MachineSets in the specified namespace

3. **Missing Portworx Pods**
   - Check if Portworx is installed in the specified namespace
   - Verify that pods have the label `name=portworx`

### Logging

The script uses Python's logging module to provide detailed information about its operation. Set the log level as needed for troubleshooting.

## Security Considerations

- VMware credentials can be provided through:
  - Command-line options (not recommended for production)
  - Environment variables (VSPHERE_PASSWORD)
  - Kubernetes Secrets (recommended)
- The script uses HTTPS for communication with external services
- SSL verification can be disabled if needed, but this is not recommended for production environments
- The script attempts to load a custom CA certificate from the hardcoded path `/path/to/your/cert.pem` if it exists and SSL verification is not disabled. If using custom CAs for vSphere, ensure your CA bundle is placed at this location, modify the script, or ensure SSL is disabled if this path is not intended for use.

### VMware Credential Sourcing Order

1. **Command-Line Options**: Explicitly provided `--vsphere-host`, `--vsphere-user`, and `--vsphere-password` are used first.
2. **Kubernetes Secret**: If `--credentials-secret` (and optionally `--credentials-namespace`) is provided:
    - Username and password are fetched from the Secret.
    - If `--vsphere-host` was not given via CLI, the script attempts to derive the vSphere host/server name from the `providerSpec.value.workspace.server` field of the first MachineSet.
3. **Environment Variable**: If the password is not supplied by CLI or a Secret, the script checks the `VSPHERE_PASSWORD` environment variable.

### vSphere SSL Certificate Handling

The script determines the SSL certificate to use for vSphere connections with the following precedence:

1. **`--disable-ssl` CLI Flag**: If present, SSL verification is disabled entirely.
2. **`--vsphere-cert-path` CLI Option**: If provided, this path to a custom SSL certificate file is used.
3. **`VSPHERE_SSL_CERT_PATH` Environment Variable**: If the CLI option is not used, this environment variable is checked for a certificate path.
4. **Default Fallback Path**: If neither the CLI option nor the environment variable is set, the script checks for a certificate at the hardcoded path `DEFAULT_FALLBACK_CERT_PATH` (currently `"/path/to/your/cert.pem"`). *Note: This path is hardcoded in the script; for production use, ensure your certificate is at this location, modify the script to point to the correct path, or use one of the higher-precedence methods.*
5. **System Default CAs**: If none of the above specific paths are provided or valid (and SSL is not disabled), the system's default CA trust store is used for SSL verification.
