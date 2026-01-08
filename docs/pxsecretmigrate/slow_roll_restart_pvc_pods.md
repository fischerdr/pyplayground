# Slow-Roll Pod Restart Script

## Overview

The `slow_roll_restart_pvc_pods.py` script performs a controlled, sequential restart of Kubernetes pods that use specific Portworx PVCs. It's designed to safely restart pods after Vault secret migrations or configuration changes, ensuring minimal disruption to running applications.

**Location:** `pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py`

**Purpose:** After migrating Portworx volume encryption secrets in Vault, pods need to be restarted to pick up the new secret configurations. This script automates that process with safety controls and optional wait mechanisms.

## Key Features

- **Namespace-by-Namespace Processing**: Processes one namespace at a time with configurable pauses
- **Per-Pod Restart Control**: Deletes pods one at a time with pauses between deletions
- **Readiness Verification**: Optionally waits for new pods to be ready before proceeding
- **Failure Detection**: Detects and reports pod failures with event details
- **Dry-Run Mode**: Preview what would be restarted without making changes
- **Flexible Pacing**: Configurable pauses or fast mode with no delays
- **Rich Output**: Color-coded console output with progress indicators and summary tables

## How It Works

### Input Data

The script requires a JSON export file produced by `k8s_px_pvc_data_exporter.py` with this structure:

```json
{
  "namespace1": [
    {
      "pvc": "pvc-name-1",
      "pv": "pv-name-1",
      "vaultpath": "path/to/secret",
      "vaultnamespace": "vault/namespace",
      "portworxvolumeinspect_labels": {...},
      "vault_data": {...}
    }
  ],
  "namespace2": [...]
}
```

### Logic Flow

#### Phase 1: Initialization

```text
1. Load JSON export data
2. Parse namespace → PVC mappings
3. Connect to Kubernetes cluster
4. Display operation mode (dry-run, wait-ready, etc.)
```

#### Phase 2: Namespace Processing

For each namespace in the export:

```text
1. Extract PVC names from namespace data
   Example: {"pvc-1", "pvc-2", "pvc-3"}

2. Pause before processing (if --namespace-pause > 0)
   Default: 5 seconds

3. Find all pods using those PVCs
   - Scans all pods in namespace
   - Checks pod.spec.volumes for persistent_volume_claim
   - Returns list of pod names

4. If no pods found → skip to next namespace

5. Display found pods (list on console)
```

#### Phase 3: Pod-by-Pod Restart

For each pod found:

```text
1. CAPTURE PRE-DELETION STATE
   a. Get PVCs used by this specific pod
      pod_pvcs = get_pvcs_for_pod("pod-abc-123")
      → Returns: {"pvc-1"}
   
   b. Get all current pods using those PVCs
      current_pods = get_pods_using_pvcs({"pvc-1"})
      → Returns: {"pod-abc-123", "pod-xyz-456", "other-pod"}

2. DELETE POD
   core_v1.delete_namespaced_pod("pod-abc-123")
   
   Kubernetes controller notices deletion and creates NEW pod
   → New pod might be: "pod-abc-789" (Deployment/ReplicaSet)
   → Or same name: "pod-abc-123" (StatefulSet)

3. WAIT FOR NEW POD (if --wait-ready enabled)
   a. Poll every 5 seconds for new pods
   
   b. Get current pods using same PVCs
      new_current_pods = get_pods_using_pvcs({"pvc-1"})
      → Returns: {"pod-abc-789", "pod-xyz-456", "other-pod"}
   
   c. Find NEW pods (not in old list)
      new_pods = ["pod-abc-789"]  # Not in original list!
   
   d. Check health of new pods
      - Detect failures: CrashLoopBackOff, ImagePullBackOff, etc.
      - If failed: Display error + pod events → EXIT
   
   e. Check readiness
      - All containers must be ready
      - If ready → Continue to next pod
      - If not ready → Continue polling (up to timeout)
   
   f. If timeout reached → Log warning, continue

4. PAUSE BETWEEN PODS (if --pod-pause > 0)
   Default: 2 seconds
```

#### Phase 4: Summary

```text
1. Display summary table:
   - Namespace
   - Pod count
   - Success count
   - Status

2. Show totals across all namespaces

3. Exit
```

### Finding New Pods: The Key Algorithm

The most critical part is finding the NEW pod after deletion:

```python
# BEFORE deletion
old_pods = {"pod-abc-123", "pod-xyz-456"}  # All pods using PVC

# DELETE pod-abc-123
# Kubernetes creates pod-abc-789

# AFTER deletion - Poll for new pods
current_pods = {"pod-abc-789", "pod-xyz-456"}  # Re-scan pods using PVC
new_pods = [p for p in current_pods if p not in old_pods]
# Result: ["pod-abc-789"] ← This is the NEW pod!

# Wait for pod-abc-789 to be ready
```

This works for:

- **Deployments**: New pod with random suffix (pod-abc-789)
- **StatefulSets**: Same name, new UID (pod-abc-123 v2)
- **ReplicaSets**: New pod with different suffix
- **DaemonSets**: New pod on same node
- **ReadWriteMany PVCs**: Multiple pods, only tracks the replaced one

## Prerequisites

1. **Kubernetes Access**: Valid kubeconfig with permissions to:
   - List pods in namespaces
   - Delete pods
   - Read pod status and events

2. **Input File**: JSON export from `k8s_px_pvc_data_exporter.py`

3. **Python Environment**: Python 3.9+ with required packages installed

## Command-Line Options

### Required Options

| Option | Description |
| ------ | ----------- |
| `--input-file FILE` | Path to JSON file from k8s_px_pvc_data_exporter.py |

### Optional Options

| Option | Default | Description |
| ------ | ------- | ----------- |
| `--kubeconfig FILE` | Auto-detect | Path to kubeconfig file |
| `--dry-run` | False | Preview pods without deleting them |
| `--namespace-pause INT` | 5 | Seconds to pause before each namespace |
| `--pod-pause INT` | 2 | Seconds to pause between pod deletions |
| `--no-pause` | False | Skip all pauses (sets both to 0) |
| `--wait-ready` | False | Wait for pods to be ready after deletion |
| `--wait-timeout INT` | 300 | Max seconds to wait for pod readiness |
| `--debug` | False | Enable debug logging |

## Usage Examples

### 1. Dry-Run Mode (Preview Only)

Preview what would be restarted without making changes:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json \
  --dry-run
```

**Output:**

```text
DRY RUN MODE - No pods will be deleted

Cluster: my-cluster

Processing namespace: app-namespace (pausing 5s before start...)
  Found 3 pod(s) to restart:
    - app-pod-1
    - app-pod-2
    - app-pod-3
  Would delete pod app-namespace/app-pod-1
  Would delete pod app-namespace/app-pod-2
  Would delete pod app-namespace/app-pod-3

Summary:
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Namespace      ┃ Pod Count ┃ Success Count ┃ Status  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ app-namespace  │ 3         │ 3             │ Dry-Run │
└────────────────┴───────────┴───────────────┴─────────┘
```

### 2. Standard Mode (Default Pauses)

Restart pods with default timing:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json
```

- 5-second pause before each namespace
- 2-second pause between pods
- No waiting for pod readiness

### 3. Safe Mode (Wait for Readiness)

Ensure each pod is ready before proceeding:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json \
  --wait-ready \
  --wait-timeout 600
```

- Waits up to 10 minutes for each pod to be ready
- Detects and reports pod failures
- Shows pod events if failures occur

### 4. Fast Mode (No Pauses)

For urgent restarts when throttling isn't needed:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json \
  --no-pause
```

- No namespace pauses
- No pod pauses
- Restarts as fast as possible

### 5. Production-Safe Mode

Recommended for production environments:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json \
  --wait-ready \
  --wait-timeout 600 \
  --namespace-pause 10 \
  --pod-pause 5 \
  --debug
```

- 10-second pause between namespaces
- 5-second pause between pods
- Wait for readiness with 10-minute timeout
- Debug logging enabled

### 6. Custom Kubeconfig

Use a specific kubeconfig file:

```bash
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/cluster_export_20260108_120000.json \
  --kubeconfig ~/.kube/config-prod
```

## Common Scenarios

### Scenario 1: Migrating Vault Secrets

After migrating Portworx volume encryption secrets in Vault:

```bash
# Step 1: Export current PVC data
python pyplayground/pxsecretmigrate/k8s_px_pvc_data_exporter.py \
  --output-file my-cluster

# Step 2: Migrate secrets in Vault (manual or automated process)

# Step 3: Dry-run to verify
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/my-cluster_20260108_120000.json \
  --dry-run

# Step 4: Execute restart with safety checks
python pyplayground/pxsecretmigrate/slow_roll_restart_pvc_pods.py \
  --input-file tmp/my-cluster_20260108_120000.json \
  --wait-ready \
  --wait-timeout 600
```

### Scenario 2: ReadWriteMany PVCs

Multiple pods sharing the same RWX PVC:

```text
PVC: shared-data-pvc (ReadWriteMany)
Pods: web-1, web-2, web-3 (all mount shared-data-pvc)

Restart sequence:
1. Delete web-1 → Wait for web-1-new ready → Pause
2. Delete web-2 → Wait for web-2-new ready → Pause
3. Delete web-3 → Wait for web-3-new ready → Done
```

The script correctly handles this because it tracks which specific pod was deleted and only waits for that pod's replacement.

### Scenario 3: StatefulSet Pods

StatefulSets recreate pods with the same name:

```text
Before: myapp-0 (uses pvc-myapp-0)
Delete: myapp-0
After:  myapp-0 (same name, different UID)

Detection: Still works because we compare against the SET of old pods,
and the new myapp-0 appears in the current pod list.
```

### Scenario 4: Handling Pod Failures

If a pod fails to start during restart:

```text
  Deleted pod my-namespace/app-pod-abc-123
  Waiting for new pod in my-namespace to be ready (timeout: 300s)...
  
  ERROR: Pod my-namespace/app-pod-def-456 failed!
  Reason: Container web in CrashLoopBackOff: Back-off restarting failed container
  
  Recent pod events:
    [Warning] BackOff: Back-off restarting failed container web
    [Warning] Failed: Error: command /app/start.sh exited with code 1
    [Normal] Pulled: Container image already present
    [Normal] Created: Created container web
    [Normal] Started: Started container web

Script exits with failure → Investigate and fix before continuing
```

## Troubleshooting

### Issue: "No pods found using PVCs"

**Cause:** Pods might not be mounting the PVCs, or PVC annotations are incorrect.

**Solution:**

1. Verify PVCs exist: `kubectl get pvc -n <namespace>`
2. Check pod volumes: `kubectl get pod <pod> -n <namespace> -o yaml | grep -A5 volumes`
3. Run dry-run to see what the script detects

### Issue: "Timeout waiting for new pods"

**Cause:** New pod is taking longer than timeout to become ready.

**Solution:**

1. Increase timeout: `--wait-timeout 900`
2. Check pod status: `kubectl describe pod <pod> -n <namespace>`
3. Check node resources: `kubectl describe node`
4. Review pod logs: `kubectl logs <pod> -n <namespace>`

### Issue: "Pod entered failed state"

**Cause:** Pod cannot start due to configuration, image, or resource issues.

**Solution:**

1. Script shows pod events automatically
2. Check pod details: `kubectl describe pod <pod> -n <namespace>`
3. Check logs: `kubectl logs <pod> -n <namespace> --previous`
4. Fix issue before continuing restarts

### Issue: "Error listing pods in namespace"

**Cause:** Insufficient Kubernetes RBAC permissions.

**Solution:**

1. Verify kubeconfig: `kubectl auth can-i list pods -n <namespace>`
2. Check cluster access: `kubectl get pods --all-namespaces`
3. Ensure service account has proper RBAC roles

## Safety Features

### 1. Dry-Run Mode

- Preview all operations without making changes
- Verify pod discovery works correctly
- Confirm namespace and pod counts

### 2. Incremental Processing

- One namespace at a time
- One pod at a time within namespace
- Configurable pauses prevent overwhelming cluster

### 3. Readiness Verification

- Optional wait for pod readiness
- Detects failed pods immediately
- Shows detailed error information with events

### 4. Failure Detection

Automatically detects:

- CrashLoopBackOff
- ImagePullBackOff / ErrImagePull
- Failed pod phase
- Container exit codes ≠ 0
- Terminating containers

### 5. Rich Logging

- Console output with color coding
- Debug logging for troubleshooting
- Summary tables with statistics
- Real-time progress indicators

## Related Scripts

- **k8s_px_pvc_data_exporter.py**: Generates the input JSON file for this script
- **Vault migration scripts**: Scripts that migrate secrets in Vault (run before this script)

## Best Practices

1. **Always run dry-run first** to verify the script will do what you expect
2. **Use --wait-ready in production** to ensure pods are healthy before moving on
3. **Monitor the first few namespaces** before leaving the script unattended
4. **Save console output** for audit trail: `script -c "python ..." output.log`
5. **Have rollback plan** in case pods fail to start with new configurations
6. **Coordinate with application teams** during maintenance windows
7. **Use appropriate timeouts** based on application startup times
8. **Enable debug logging** if you encounter issues

## Script Exit Codes

- **0**: Success - all pods restarted successfully
- **1**: Failure - configuration errors, permission errors, or pod failures

## Performance Considerations

### Timing Estimates

For a cluster with:

- 10 namespaces
- 5 pods per namespace
- Default settings (5s namespace pause, 2s pod pause)

**Without --wait-ready:**

- Time: ~10×5 + 50×2 = 150 seconds (~2.5 minutes)

**With --wait-ready (average 30s per pod):**

- Time: ~10×5 + 50×(2+30) = 1650 seconds (~27 minutes)

### Resource Impact

- **API Calls**: Frequent polling during --wait-ready mode
- **Cluster Load**: Minimal - deletes are throttled
- **Network**: Low bandwidth usage
- **CPU/Memory**: Negligible on client machine

## Limitations

1. **Requires Controllers**: Pods must be managed by Deployment, StatefulSet, ReplicaSet, or DaemonSet to be recreated
2. **No Rollback**: Script doesn't automatically rollback if issues occur
3. **Sequential Only**: Cannot restart pods in parallel
4. **StatefulSet Considerations**: Respects StatefulSet update strategy - manual intervention may be needed

## Future Enhancements

Potential improvements:

- Parallel namespace processing option
- Automatic retry on transient failures
- Integration with monitoring/alerting systems
- Support for rollback scenarios
- Pre-flight validation checks
