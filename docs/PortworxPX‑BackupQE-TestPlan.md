# Portworx PX-Backup QA Test Plan

**Version:** 2.9.0  
**Environment:** OpenShift  
**Storage Backend:** S3 (pre-configured)  
**Test Scope:** Final validation before production deployment  

## Prerequisites

- Portworx PX-Backup 2.9.0 installed and configured
- OpenShift cluster access with appropriate permissions
- S3 storage backend configured and accessible
- Test namespace(s) available for backup operations
- ConfigMap resources deployed in test namespace

## 1. Scheduled Backups

### 1.1 Create 15-Minute Backup Schedule

1. **Access PX-Backup Web Console**
   - Navigate to the Portworx Backup web interface
   - Authenticate with administrative credentials

2. **Create Schedule Policy**
   - Navigate to Settings → Schedule Policies
   - Click "Create Schedule Policy"
   - Configure schedule policy:
     - **Name:** `qa-15min-schedule`
     - **Type:** Interval
     - **Interval:** 15 minutes
     - **Retain:** 5 copies
   - Save the schedule policy

3. **Create Scheduled Backup**
   - Navigate to Backup → Create Backup
   - Configure backup parameters:
     - **Backup Name:** `qa-scheduled-backup`
     - **Cluster:** Select target cluster
     - **Namespaces:** Select test namespace
     - **Backup Location:** Select configured S3 location
     - **Schedule Policy:** Select `qa-15min-schedule`
   - Create the backup

4. **Verify Schedule Creation**
   - Confirm backup appears in backup list
   - Verify schedule policy is associated
   - Wait for initial backup completion (15 minutes)

### 1.2 Delete and Restore ConfigMap

1. **Prepare Test ConfigMap**
   - Create test ConfigMap in target namespace:

     ```bash
     kubectl create configmap qa-test-config --from-literal=test-key=original-value -n <test-namespace>
     ```

2. **Wait for Scheduled Backup**
   - Monitor backup completion in PX-Backup console
   - Verify ConfigMap is included in backup

3. **Delete ConfigMap**
   - Remove the ConfigMap:

     ```bash
     kubectl delete configmap qa-test-config -n <test-namespace>
     ```

   - Verify deletion:

     ```bash
     kubectl get configmap qa-test-config -n <test-namespace>
     ```

4. **Restore ConfigMap**
   - Navigate to Restore → Create Restore
   - Configure restore:
     - **Restore Name:** `qa-configmap-restore`
     - **Backup:** Select latest scheduled backup
     - **Replace Policy:** Delete
     - **Include Resources:** ConfigMap only
   - Execute restore operation

5. **Verify Restoration**
   - Confirm ConfigMap exists:

     ```bash
     kubectl get configmap qa-test-config -n <test-namespace>
     kubectl describe configmap qa-test-config -n <test-namespace>
     ```

### 1.3 Restore Specific Historical Version

1. **Modify ConfigMap**
   - Update the existing ConfigMap:

     ```bash
     kubectl patch configmap qa-test-config -n <test-namespace> --patch '{"data":{"test-key":"modified-value"}}'
     ```

2. **Wait for Next Scheduled Backup**
   - Allow 15-minute schedule to create new backup with modified data
   - Verify backup completion

3. **Restore Historical Version**
   - Navigate to Restore → Create Restore
   - Configure historical restore:
     - **Restore Name:** `qa-historical-restore`
     - **Backup:** Select previous backup (not latest)
     - **Replace Policy:** Delete
     - **Include Resources:** ConfigMap only
   - Execute restore

4. **Verify Historical Restoration**
   - Confirm ConfigMap contains original value:

     ```bash
     kubectl get configmap qa-test-config -o yaml -n <test-namespace>
     ```

   - Verify `test-key` shows `original-value`

## 2. Ad-Hoc Backups

### 2.1 Manual Namespace Backup

1. **Create Manual Backup**
   - Navigate to Backup → Create Backup
   - Configure manual backup:
     - **Backup Name:** `qa-manual-backup`
     - **Cluster:** Select target cluster
     - **Namespaces:** Select test namespace
     - **Backup Location:** Select S3 location
     - **Schedule Policy:** None (manual)
   - Create backup immediately

2. **Monitor Backup Progress**
   - Track backup status in console
   - Verify successful completion
   - Note backup size and duration

### 2.2 ConfigMap Delete and Restore

1. **Delete ConfigMap**
   - Remove test ConfigMap:

     ```bash
     kubectl delete configmap qa-test-config -n <test-namespace>
     ```

2. **Restore from Manual Backup**
   - Navigate to Restore → Create Restore
   - Configure restore:
     - **Restore Name:** `qa-manual-restore`
     - **Backup:** Select manual backup
     - **Replace Policy:** Delete
     - **Include Resources:** ConfigMap only
   - Execute restore

3. **Verify Restoration**
   - Confirm ConfigMap restoration:

     ```bash
     kubectl get configmap qa-test-config -n <test-namespace>
     ```

### 2.3 Full Namespace Overwrite Restore

1. **Modify Namespace Resources**
   - Create additional test resources:

     ```bash
     kubectl create secret generic qa-test-secret --from-literal=password=secret123 -n <test-namespace>
     kubectl create deployment qa-test-app --image=nginx -n <test-namespace>
     ```

2. **Execute Full Namespace Restore**
   - Navigate to Restore → Create Restore
   - Configure full restore:
     - **Restore Name:** `qa-full-namespace-restore`
     - **Backup:** Select manual backup
     - **Replace Policy:** Delete
     - **Include Resources:** All resources
   - Execute restore operation

3. **Verify Complete Restoration**
   - Confirm namespace state matches backup:

     ```bash
     kubectl get all,configmaps,secrets -n <test-namespace>
     ```

   - Verify additional resources are removed
   - Confirm original resources are restored

## 3. Label-Based Backups

### 3.1 Label Namespace

1. **Apply Label to Test Namespace**
   - Add backup label:

     ```bash
     kubectl label namespace <test-namespace> backup-enabled=true
     ```

2. **Verify Label Application**
   - Confirm label exists:

     ```bash
     kubectl get namespace <test-namespace> --show-labels
     ```

### 3.2 Trigger Label-Filtered Backup

1. **Create Label-Based Backup**
   - Navigate to Backup → Create Backup
   - Configure label-filtered backup:
     - **Backup Name:** `qa-label-backup`
     - **Cluster:** Select target cluster
     - **Label Selector:** `backup-enabled=true`
     - **Backup Location:** Select S3 location
     - **Schedule Policy:** None (manual)
   - Create backup

2. **Verify Label Filtering**
   - Confirm only labeled namespace is included
   - Monitor backup completion

### 3.3 Verify Auto-Inclusion of Newly Labeled Namespaces

1. **Create New Namespace**
   - Create additional test namespace:

     ```bash
     kubectl create namespace qa-test-namespace-2
     ```

2. **Apply Same Label**
   - Label new namespace:

     ```bash
     kubectl label namespace qa-test-namespace-2 backup-enabled=true
     ```

3. **Create Resources in New Namespace**
   - Add test resources:

     ```bash
     kubectl create configmap qa-test-config-2 --from-literal=env=production -n qa-test-namespace-2
     ```

4. **Execute Label-Based Backup**
   - Create new label-filtered backup:
     - **Backup Name:** `qa-label-backup-multi`
     - **Label Selector:** `backup-enabled=true`
   - Execute backup

5. **Verify Multi-Namespace Inclusion**
   - Confirm both namespaces are backed up
   - Verify backup includes resources from both namespaces

## 4. Validation Checklist

| Test Scenario | Reference Section | Status | Notes |
|---------------|-------------------|---------|-------|
| 15-minute scheduled backup creation | 1.1 | [ ] | Schedule policy and backup configured |
| ConfigMap delete/restore from scheduled backup | 1.2 | [ ] | Data integrity verified |
| Historical version restoration | 1.3 | [ ] | Previous backup version restored |
| Manual namespace backup | 2.1 | [ ] | Ad-hoc backup completed |
| ConfigMap restore from manual backup | 2.2 | [ ] | Manual backup restoration verified |
| Full namespace overwrite restore | 2.3 | [ ] | Complete namespace state restored |
| Namespace labeling | 3.1 | [ ] | Labels applied correctly |
| Label-filtered backup execution | 3.2 | [ ] | Only labeled resources backed up |
| Auto-inclusion of newly labeled namespaces | 3.3 | [ ] | Multiple labeled namespaces included |

## 5. Documentation References

### 5.1 Backup Creation and Scheduling

- **Create Backup:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup>
- **Manual Backup:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup/perform-backup/manual-backup>
- **Schedule Policies:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/schedule>

### 5.2 Backup and Restore Operations

- **Backup and Restore Guide:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore>
- **Perform Backup:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup/perform-backup>

### 5.3 Label-Based Operations

- **Label Backups:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/labels/backup-labels>
- **Concepts (Labels):** <https://docs.portworx.com/portworx-backup-on-prem/concepts>

### 5.4 General Documentation

- **PX-Backup Documentation:** <https://docs.portworx.com/portworx-backup-on-prem>
- **Use PX-Backup:** <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup>

## Test Execution Notes

- Execute tests in sequence to maintain data integrity
- Document any deviations from expected behavior
- Capture screenshots of critical operations
- Record backup/restore times for performance validation
- Verify all operations through both web console and CLI
- Confirm S3 storage utilization and retention policies
