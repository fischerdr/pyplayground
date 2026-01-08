# Portworx Secret Migration Tools

This directory contains a suite of Python scripts designed to facilitate the migration of Portworx volume encryption keys from HashiCorp Vault to Kubernetes Secrets. The tools provide export, checking, migration, and verification capabilities to ensure a smooth and auditable transition.

## Overview

The migration process follows a three-step workflow:

1. **Export** - Gather current PVC, PV, and Vault secret data
2. **Migrate** - Transfer encryption keys from Vault to Kubernetes Secrets
3. **Verify** - Confirm that the migration completed successfully

Additional utility scripts help with data gathering and validation throughout the process.

---

## Scripts

### 1. k8s_px_pvc_data_exporter.py

**Purpose:** Exports Portworx PVC data including persistent volume information, Vault secret paths, volume labels, and encryption keys to a timestamped JSON file.

**Description:**
This script connects to a Kubernetes cluster, identifies all Portworx PVCs with Vault annotations, retrieves their associated encryption keys from Vault, and exports the data to a structured JSON file. This export file serves as the input for the migration script.

**Key Features:**

- Discovers PVCs with Vault secret annotations
- Retrieves encryption keys from Vault using service account authentication
- Executes `pxctl volume inspect` to gather Portworx volume labels
- Exports data to timestamped JSON files in `tmp/` directory
- Supports custom kubeconfig and namespace configuration

**Basic Usage:**

```bash
# Export from current cluster context
python k8s_px_pvc_data_exporter.py

# Export with specific kubeconfig
python k8s_px_pvc_data_exporter.py --kubeconfig /path/to/kubeconfig

# Export with custom output filename
python k8s_px_pvc_data_exporter.py --output-file my-cluster-export

# Enable debug logging
python k8s_px_pvc_data_exporter.py --debug
```

**Options:**

- `--kubeconfig PATH` - Path to kubeconfig file (defaults to standard lookup)
- `--px-namespace TEXT` - Portworx namespace (default: kube-system)
- `--output-file TEXT` - Base name for output JSON file (defaults to cluster name)
- `--debug` - Enable debug logging

**Output:**
Creates a JSON file in `tmp/` directory with naming pattern: `{cluster-name}_{timestamp}.json`

---

### 2. k8s_px_pvc_vault_secret_checker.py

**Purpose:** Checks and validates Vault secrets referenced by Portworx PVC annotations.

**Description:**
This diagnostic script verifies that all Vault secrets referenced by Portworx PVCs are accessible and contain valid data. It displays results in a formatted table showing the status of each secret and includes volume labels from Portworx.

**Key Features:**

- Validates Vault secret accessibility
- Checks authentication to Vault namespaces
- Retrieves and displays volume labels from `pxctl`
- Supports masking/unmasking of secret values
- Provides rich formatted table output

**Basic Usage:**

```bash
# Check all PVCs with default settings
python k8s_px_pvc_vault_secret_checker.py

# Check with specific kubeconfig
python k8s_px_pvc_vault_secret_checker.py --kubeconfig /path/to/kubeconfig

# Show unmasked secret values
python k8s_px_pvc_vault_secret_checker.py --no-mask

# Enable debug logging
python k8s_px_pvc_vault_secret_checker.py --debug
```

**Options:**

- `--kubeconfig PATH` - Path to kubeconfig file
- `--px-namespace TEXT` - Portworx namespace (default: kube-system)
- `--mask/--no-mask` - Mask or unmask sensitive values (default: mask)
- `--debug` - Enable debug logging

**Output:**
Rich formatted table displaying:

- PVC namespace and name
- Vault secret path and namespace
- Secret status (Found/Not Found/Error)
- Secret data (keys shown, values optionally masked)
- Volume labels from Portworx

---

### 3. k8s_px_volume_details.py

**Purpose:** Query Portworx PVs/PVCs and enrich with detailed `pxctl` inspection data.

**Description:**
This comprehensive script combines Kubernetes metadata with Portworx-specific volume details by executing `pxctl volume inspect` for each volume. It supports multiple output formats and can process single or multiple clusters.

**Key Features:**

- Discovers Portworx PVs and PVCs using StorageClass information
- Executes `pxctl volume inspect` to gather detailed volume information
- Supports namespace filtering with prefix exclusion
- Multiple output formats: console table, JSON, CSV
- Multi-cluster support via cluster list file
- Automatic Portworx security token detection

**Basic Usage:**

```bash
# Display volume details in console
python k8s_px_volume_details.py --kubeconfig /path/to/kubeconfig

# Export to JSON
python k8s_px_volume_details.py --kubeconfig /path/to/kubeconfig --format json

# Export to CSV
python k8s_px_volume_details.py --kubeconfig /path/to/kubeconfig --format csv

# Process multiple clusters
python k8s_px_volume_details.py --clusterlist /path/to/cluster-configs.txt --format json

# Skip system namespaces
python k8s_px_volume_details.py --kubeconfig /path/to/kubeconfig \
  --skip-namespace-prefix kube- --skip-namespace-prefix istio-

# Set environment variables for pxctl
python k8s_px_volume_details.py --kubeconfig /path/to/kubeconfig \
  --env-var "VAR1=value1" --env-var "VAR2=value2"
```

**Options:**

- `--kubeconfig PATH` - Path to kubeconfig file
- `--clusterlist PATH` - Path to file containing list of kubeconfig files
- `--px-namespace TEXT` - Portworx pod namespace (default: kube-system)
- `-f, --format [console|json|csv]` - Output format (default: console)
- `--skip-namespace-prefix TEXT` - Namespace prefix to exclude (can be used multiple times)
- `--env-var VAR=VALUE` - Environment variable for pxctl (can be used multiple times)
- `--debug` - Enable debug logging

**Output:**

- **Console:** Rich formatted table with volume details
- **JSON:** Timestamped JSON file in `tmp/` directory
- **CSV:** Timestamped CSV file in `tmp/` directory

---

### 4. px_vault_to_k8s_secret_migrator.py

**Purpose:** Migrate Portworx volume encryption keys from HashiCorp Vault to Kubernetes Secrets.

**Description:**
The main migration script that processes the export data from `k8s_px_pvc_data_exporter.py` and performs the actual migration. It creates Kubernetes secrets, updates Portworx volume labels, removes Vault annotations, and updates PVC annotations to reference the new secrets.

**Key Features:**

- Creates Kubernetes secrets with encryption keys
- Normalizes secret names to comply with Kubernetes naming requirements
- Updates Portworx volume labels via `pxctl` commands
- Removes Vault-related annotations from PVCs
- Adds Kubernetes secret annotations to PVCs
- Dry-run mode for testing without making changes
- Comprehensive error handling and logging

**Basic Usage:**

```bash
# Perform migration
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json

# Dry-run mode (simulate without changes)
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json --dry-run

# Specify custom Portworx namespace
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json \
  --px-namespace portworx

# Enable debug logging
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json --debug
```

**Options:**

- `--input PATH` - Path to JSON export file (required)
- `--dry-run` - Simulate actions without making changes
- `--px-namespace TEXT` - Portworx namespace (default: kube-system)
- `--debug` - Enable debug logging

**Migration Steps:**
For each PVC in the export data:

1. Creates Kubernetes secret in the target namespace
2. Normalizes secret name if needed (handles special characters)
3. Removes `px/vault-namespace` annotation from PVC
4. Updates Portworx volume labels:
   - Sets `SECRET_NAME` and `px/secret-name`
   - Removes `px/vault-namespace`
5. Adds secret reference annotations to PVC:
   - `px/secret-key`
   - `px/secret-name`
   - `px/secret-namespace`

**Output:**

- Progress messages for each PVC processed
- Summary of migration results (total, successful, failed)
- Comprehensive logs in `logs/` directory

---

### 5. verify_px_k8s_secret_migration.py

**Purpose:** Verify the migration of Portworx encryption keys from Vault to Kubernetes Secrets.

**Description:**
This verification script validates that the migration completed successfully by checking that secrets exist, volume labels are correct, and PVC annotations have been properly updated. It produces both a console summary and a detailed JSON report.

**Key Features:**

- Verifies Kubernetes secret existence and content
- Checks Portworx volume labels via `pxctl`
- Validates PVC annotations
- Confirms removal of Vault-related annotations
- Generates detailed verification report
- Rich formatted console output

**Basic Usage:**

```bash
# Verify migration
python verify_px_k8s_secret_migration.py --input /path/to/export.json

# Verify with custom Portworx namespace
python verify_px_k8s_secret_migration.py --input /path/to/export.json \
  --px-namespace portworx

# Enable debug logging
python verify_px_k8s_secret_migration.py --input /path/to/export.json --debug
```

**Options:**

- `--input PATH` - Path to JSON export file (required)
- `--px-namespace TEXT` - Portworx namespace (default: kube-system)
- `--debug` - Enable debug logging

**Verification Checks:**
For each PVC:

1. **Kubernetes Secret Check:**
   - Secret exists in expected namespace
   - Secret contains correct key
   - Secret value matches expected encryption key

2. **Portworx Volume Labels Check:**
   - `SECRET_NAME` label is correct
   - `px/secret-name` label is correct
   - `px/vault-namespace` label has been removed

3. **PVC Annotations Check:**
   - `px/vault-namespace` annotation has been removed
   - `px/secret-name` annotation is correct
   - `px/secret-key` annotation is correct
   - `px/secret-namespace` annotation is correct

**Output:**

- Console table showing verification status for each PVC
- Detailed JSON report in `tmp/migration_verification_report_{timestamp}.json`
- Exit code 1 if any verifications fail

---

### 6. slow_roll_restart_pvc_pods.py

**Purpose:** Restart pods using Portworx PVCs to apply new secret configurations.

**Description:**
After migrating encryption keys from Vault to Kubernetes Secrets, pods need to restart to pick up the new secret references. This script performs controlled, sequential pod restarts with configurable pauses and optional readiness verification to minimize application disruption.

**Key Features:**

- Namespace-by-namespace sequential processing
- Per-pod restart with configurable delays
- Optional wait for pod readiness before continuing
- Automatic detection of pod failures with event details
- Dry-run mode for preview without changes
- Handles ReadWriteMany PVCs with multiple pods
- Supports all controller types (Deployment, StatefulSet, ReplicaSet, DaemonSet)

**Basic Usage:**

```bash
# Dry-run to preview pods that would be restarted
python slow_roll_restart_pvc_pods.py --input-file tmp/export.json --dry-run

# Standard restart with default pauses
python slow_roll_restart_pvc_pods.py --input-file tmp/export.json

# Safe mode with readiness verification
python slow_roll_restart_pvc_pods.py --input-file tmp/export.json --wait-ready

# Fast mode without pauses
python slow_roll_restart_pvc_pods.py --input-file tmp/export.json --no-pause

# Production-safe mode with extended timeouts
python slow_roll_restart_pvc_pods.py --input-file tmp/export.json \
  --wait-ready --wait-timeout 600 --namespace-pause 10 --pod-pause 5
```

**Options:**

- `--input-file PATH` - Path to JSON export file from k8s_px_pvc_data_exporter.py (required)
- `--kubeconfig PATH` - Path to kubeconfig file
- `--dry-run` - Preview pods without deleting them
- `--namespace-pause INT` - Seconds to pause before each namespace (default: 5)
- `--pod-pause INT` - Seconds to pause between pod deletions (default: 2)
- `--no-pause` - Skip all pauses (sets both to 0)
- `--wait-ready` - Wait for pods to be ready after deletion
- `--wait-timeout INT` - Max seconds to wait for pod readiness (default: 300)
- `--debug` - Enable debug logging

**Restart Process:**

1. Identifies pods using PVCs from export data
2. Captures pre-deletion state (pod list, PVC mappings)
3. Deletes pod and allows Kubernetes to recreate it
4. Optionally waits for new pod to reach ready state
5. Detects failures (CrashLoopBackOff, ImagePullBackOff, etc.)
6. Shows pod events if failures occur
7. Pauses before next pod (configurable)

**Output:**

- Real-time progress with color-coded console messages
- Summary table showing namespace, pod count, and success rate
- Pod events displayed for any failures
- Comprehensive logs in `logs/` directory

**See Also:** [docs/pxsecretmigrate/slow_roll_restart_pvc_pods.md](../../docs/pxsecretmigrate/slow_roll_restart_pvc_pods.md) for detailed documentation.

---

## Workflow Example

Complete migration workflow:

```bash
# Step 1: Export current state
python k8s_px_pvc_data_exporter.py --output-file production-cluster

# Step 2: (Optional) Check Vault secrets are accessible
python k8s_px_pvc_vault_secret_checker.py

# Step 3: Test migration with dry-run
python px_vault_to_k8s_secret_migrator.py \
  --input tmp/production-cluster_20231117_140530.json \
  --dry-run

# Step 4: Perform actual migration
python px_vault_to_k8s_secret_migrator.py \
  --input tmp/production-cluster_20231117_140530.json

# Step 5: Verify migration success
python verify_px_k8s_secret_migration.py \
  --input tmp/production-cluster_20231117_140530.json

# Step 6: Preview pod restarts (dry-run)
python slow_roll_restart_pvc_pods.py \
  --input-file tmp/production-cluster_20231117_140530.json \
  --dry-run

# Step 7: Restart pods to apply new secret configurations
python slow_roll_restart_pvc_pods.py \
  --input-file tmp/production-cluster_20231117_140530.json \
  --wait-ready \
  --wait-timeout 600
```

**Note:** Step 7 restarts all pods using the migrated PVCs so they pick up the new Kubernetes secret references. Use `--wait-ready` in production to ensure each pod is healthy before continuing.

---

## Prerequisites

### Required Permissions

**Kubernetes:**

- Read access to PVs, PVCs, and StorageClasses
- Create/read access to Secrets
- Patch access to PVCs
- Delete access to Pods (for restart script)
- Read access to Pod events (for restart script)
- Exec access to Portworx pods

**Vault:**

- Read access to encryption key secrets
- Access to appropriate Vault namespaces
- Valid service account with Vault authentication

### Required Configuration

1. **Portworx Setup:**
   - Portworx installed and running
   - Volumes encrypted with Vault-stored keys
   - PVCs annotated with Vault secret paths

2. **Vault Setup:**
   - Vault accessible from cluster
   - Service account configured for Vault authentication
   - Vault credentials stored in Portworx namespace

3. **Kubernetes:**
   - Valid kubeconfig with appropriate context
   - Network access to cluster API server

---

## Common Issues

### Secret Name Normalization

Vault secret names may contain characters not allowed in Kubernetes secret names. The migration script automatically normalizes these names by:

- Converting to lowercase
- Replacing invalid characters with hyphens
- Ensuring names start and end with alphanumeric characters
- Preserving `-pvc` suffix if present

### Authentication Failures

If Vault authentication fails:

- Verify service account has correct Vault role
- Check Vault credential secrets exist in Portworx namespace
- Ensure Vault is accessible from cluster network

### pxctl Command Timeouts

If pxctl commands timeout:

- Verify Portworx pods are running
- Check network connectivity to Portworx pods
- Consider increasing timeout values in utility functions

---

## Logging

All scripts generate detailed logs in the `logs/` directory with timestamps and script names:

- `logs/k8s_px_pvc_data_exporter_YYYYMMDD_HHMMSS.log`
- `logs/px_vault_to_k8s_secret_migrator_YYYYMMDD_HHMMSS.log`
- `logs/verify_px_k8s_secret_migration_YYYYMMDD_HHMMSS.log`
- `logs/slow_roll_restart_pvc_pods_YYYYMMDD_HHMMSS.log`

Enable debug logging with `--debug` flag for detailed troubleshooting information.

---

## Related Utilities

These scripts depend on utility modules in `pyplayground/utils/`:

- `k8s_utils.py` - Kubernetes client initialization and configuration
- `vault_utils.py` - Vault client and authentication
- `px_api.py` - Portworx-specific operations and pxctl commands
- `migration_utils.py` - Migration-specific helpers and validation
- `logging_utils.py` - Logging configuration and setup
