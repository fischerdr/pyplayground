# Portworx PX-Backup QA Test Plan

**Version:** 2.9.0  
**Platform:** OpenShift  
**Storage Backend:** S3  
**Environment Status:** Pre-production validation  
**Document Version:** 1.0  
**Last Updated:** {{ DATE }}

## Executive Summary

This test plan validates critical backup and restore operations for Portworx PX-Backup 2.9.0 in an OpenShift environment with S3 storage backend. All infrastructure components are pre-configured and operational.

## Prerequisites

- OpenShift cluster with Portworx PX-Backup 2.9.0 installed
- S3 storage backend configured and accessible
- Administrative access to PX-Backup UI and CLI
- Test namespace with sample applications deployed
- ConfigMap resources available for testing

**Testing Approach:** This test plan prioritizes PX-Backup UI operations over CLI commands. CLI usage is limited to operations not available through the PX-Backup interface (namespace creation/labeling).

## Test Environment Configuration

| Component | Version/Configuration |
|-----------|----------------------|
| Portworx PX-Backup | 2.9.0 |
| OpenShift | 4.x (cluster-specific) |
| Storage Backend | S3 |
| Access Level | Administrative |
| Test Cluster | [CLUSTER_NAME_TO_BE_PROVIDED] |

---

## 1. Scheduled Backup Testing

### 1.1 Create 15-Minute Backup Schedule

**Objective:** Validate scheduled backup creation and execution

**Steps:**

1. **Create Schedule Policy First:**
   - Navigate to **Settings > Schedule Policies**
   - Click **Create Schedule Policy**
   - Configure policy:
     - **Name:** `qa-15min-policy`
     - **Type:** Interval
     - **Interval:** 15 minutes
     - **Retain:** 5 copies
   - Save schedule policy

2. **Create Scheduled Backup:**
   - Navigate to **Backup > Schedules**
   - Click **Create Schedule**
   - Configure schedule parameters:
     - **Name:** `qa-test-schedule-15min`
     - **Cluster:** [TARGET_CLUSTER]
     - **Namespace:** `qa-test-namespace`
     - **Schedule Policy:** Select `qa-15min-policy`
     - **Backup Location:** [S3_BACKUP_LOCATION]
   - Click **Create**

3. **Verify Schedule Creation:**
   - Confirm schedule appears in schedule list
   - Verify schedule policy is properly associated
   - Wait for first backup execution (maximum 15 minutes)
   - Record backup start and completion times for performance validation
   - Confirm backup completion in **Backup > Backups** section

**Expected Result:** Schedule created successfully with first backup completed within 15 minutes

### 1.2 ConfigMap Deletion and Restore

**Objective:** Validate point-in-time restore capability

**Prerequisites:** Scheduled backup from section 1.1 completed

**Steps:**

1. **Prepare Test ConfigMap (if not already present):**
   - Create test ConfigMap via CLI:

     ```bash
     oc create configmap qa-test-config --from-literal=test-key=original-value -n qa-test-namespace
     ```

   - Wait for next scheduled backup to include this ConfigMap

2. Navigate to **Application > Resources** in PX-Backup UI
3. Select target cluster and namespace `qa-test-namespace`
4. Locate and document existing ConfigMap details in UI
5. Note ConfigMap name and current configuration values
6. Use **Actions > Delete** to remove target ConfigMap via UI
7. Confirm deletion in resource view
8. Navigate to **Backup > Backups**
9. Select most recent scheduled backup
10. Click **Restore**
11. Configure restore parameters:
    - **Restore Name:** `qa-configmap-restore-[TIMESTAMP]`
    - **Cluster:** [TARGET_CLUSTER]
    - **Namespace Mapping:** `qa-test-namespace`
    - **Replace Policy:** Delete
    - **Resource Selection:** ConfigMap only (specific resource type)
12. Execute restore via UI
13. Return to **Application > Resources** to verify ConfigMap restoration
14. Compare restored ConfigMap values with documented original state

**Expected Result:** ConfigMap successfully restored with original configuration intact

### 1.3 Historical Version Restore

**Objective:** Validate restore from specific historical backup

**Prerequisites:** Multiple scheduled backups available (minimum 3)

**Steps:**

1. Navigate to **Backup > Backups** in PX-Backup UI
2. Filter backups by schedule name `qa-test-schedule-15min`
3. Review backup list and identify backup from previous day/hour
4. Navigate to **Application > Resources**
5. Locate target ConfigMap in `qa-test-namespace`
6. Use **Actions > Edit** to modify ConfigMap data values
7. Save modified ConfigMap configuration
8. Return to **Backup > Backups**
9. Select historical backup (not most recent)
10. Click **Restore**
11. Configure restore to temporary namespace:
    - **Restore Name:** `qa-historical-restore-[TIMESTAMP]`
    - **Cluster:** [TARGET_CLUSTER]
    - **Namespace Mapping:** `qa-test-namespace-historical`
12. Execute restore via UI
13. Navigate to **Application > Resources**
14. Compare ConfigMap data between `qa-test-namespace` and `qa-test-namespace-historical`
15. Verify historical version contains original data values

**Expected Result:** Historical version restored to separate namespace with original data intact

---

## 2. Ad-Hoc Backup Testing

### 2.1 Manual Namespace Backup

**Objective:** Validate on-demand backup functionality

**Steps:**

1. Navigate to **Backup > Backups**
2. Click **Create Backup**
3. Configure backup parameters:
   - **Name:** `qa-adhoc-backup-[TIMESTAMP]`
   - **Cluster:** [TARGET_CLUSTER]
   - **Namespace:** `qa-test-namespace`
   - **Backup Location:** [S3_BACKUP_LOCATION]
   - **Type:** Full namespace backup
4. Click **Create**
5. Monitor backup progress in real-time
6. Verify backup completion status
7. Validate backup size and duration metrics

**Expected Result:** Manual backup completes successfully with all namespace resources included

### 2.2 ConfigMap Delete and Restore (Ad-Hoc)

**Objective:** Validate restore from manual backup

**Prerequisites:** Ad-hoc backup from section 2.1 completed

**Steps:**

1. Navigate to **Application > Resources** in PX-Backup UI
2. Select `qa-test-namespace` from cluster dropdown
3. Click **Create Resource > ConfigMap**
4. Configure new ConfigMap:
   - **Name:** `qa-adhoc-test`
   - **Key:** `adhoc-key`
   - **Value:** `adhoc-value`
5. Save ConfigMap creation
6. Verify ConfigMap appears in resource list
7. Use **Actions > Delete** to remove ConfigMap
8. Confirm deletion in resource view
9. Navigate to **Backup > Backups**
10. Select ad-hoc backup from section 2.1
11. Click **Restore**
12. Configure restore:
    - **Restore Name:** `qa-adhoc-configmap-restore-[TIMESTAMP]`
    - **Cluster:** [TARGET_CLUSTER]
    - **Namespace Mapping:** `qa-test-namespace`
    - **Resource Selection:** Specific ConfigMap only
13. Execute restore via UI
14. Return to **Application > Resources** to verify ConfigMap restoration

**Expected Result:** ConfigMap restored successfully from ad-hoc backup

### 2.3 Full Namespace Overwrite Restore

**Objective:** Validate complete namespace replacement

**Prerequisites:** Ad-hoc backup with multiple resources available

**Steps:**

1. Navigate to **Application > Resources** in PX-Backup UI
2. Select `qa-test-namespace` from cluster dropdown
3. Document current resource state by taking screenshots of:
   - All deployments and their replica counts
   - All ConfigMaps and their data values
   - All secrets and their keys
   - All services and their configurations
4. **Create Additional Test Resources:**
   - Navigate to **Application > Resources**
   - Create test secret via CLI (not available in UI):

     ```bash
     oc create secret generic qa-test-secret --from-literal=password=secret123 -n qa-test-namespace
     ```

   - Create test deployment via CLI:

     ```bash
     oc create deployment qa-test-app --image=nginx -n qa-test-namespace
     ```

   - Refresh UI to verify resources appear

5. Modify multiple resources using UI **Actions** menu:
   - Scale deployments to different replica counts
   - Edit ConfigMap data values
   - Create additional ConfigMaps via UI
6. Navigate to **Backup > Backups**
7. Select ad-hoc backup from section 2.1
8. Click **Restore**
9. Configure overwrite restore:
   - **Restore Name:** `qa-full-overwrite-[TIMESTAMP]`
   - **Cluster:** [TARGET_CLUSTER]
   - **Namespace Mapping:** `qa-test-namespace`
   - **Replace Policy:** Delete
   - **Restore Type:** Replace existing resources
   - **Resource Selection:** All resources
10. Execute restore via UI
11. Return to **Application > Resources**
12. Compare final resource state with documented pre-modification baseline
13. Verify all modifications reverted to backup state
14. Confirm additional test resources (secret, deployment) are removed

**Expected Result:** Namespace completely restored to backup state, overwriting all modifications

---

## 3. Label-Based Backup Testing

### 3.1 Namespace Labeling and Initial Backup

**Objective:** Validate label-based backup filtering

**Steps:**

1. Label target namespace via CLI (namespace labeling not available in PX-Backup UI):

   ```bash
   oc label namespace qa-test-namespace backup-tier=gold
   oc label namespace qa-test-namespace environment=qa
   ```

2. Navigate to **Application > Namespaces** in PX-Backup UI
3. Verify labels appear on namespace in UI display
4. Navigate to **Backup > Backups**
5. Click **Create Backup**
6. Configure label-based backup:
   - **Name:** `qa-label-backup-[TIMESTAMP]`
   - **Cluster:** [TARGET_CLUSTER]
   - **Backup Type:** Label Selector
   - **Label Selector:** `backup-tier=gold,environment=qa`
   - **Backup Location:** [S3_BACKUP_LOCATION]
7. Execute backup via UI
8. Review backup details to verify only labeled namespace included in scope
9. Monitor backup progress and completion status

**Expected Result:** Backup created successfully targeting only namespaces with specified labels

### 3.2 Ad-Hoc Label-Filtered Backup

**Objective:** Validate manual label-based backup execution

**Steps:**

1. Create additional test namespace via CLI (namespace creation not available in PX-Backup UI):

   ```bash
   oc create namespace qa-test-namespace-2
   ```

2. Navigate to **Application > Resources** in PX-Backup UI
3. Select `qa-test-namespace-2` from cluster dropdown
4. Click **Create Resource > ConfigMap**
5. Configure test ConfigMap:
   - **Name:** `label-test`
   - **Key:** `test`
   - **Value:** `value`
6. Save ConfigMap creation
7. Apply matching labels via CLI:

   ```bash
   oc label namespace qa-test-namespace-2 backup-tier=gold
   oc label namespace qa-test-namespace-2 environment=qa
   ```

8. Navigate to **Application > Namespaces** to verify labels
9. Navigate to **Backup > Backups**
10. Click **Create Backup**
11. Configure filtered backup:
    - **Name:** `qa-multi-label-backup-[TIMESTAMP]`
    - **Cluster:** [TARGET_CLUSTER]
    - **Backup Type:** Label Selector
    - **Label Selector:** `backup-tier=gold`
    - **Backup Location:** [S3_BACKUP_LOCATION]
12. Execute backup via UI
13. Review backup details to verify both labeled namespaces included

**Expected Result:** Both namespaces with matching labels included in single backup operation

### 3.3 Auto-Inclusion Verification

**Objective:** Validate automatic inclusion of newly labeled namespaces

**Prerequisites:** Scheduled backup with label selector configured

**Steps:**

1. Navigate to **Backup > Schedules** in PX-Backup UI
2. Click **Create Schedule**
3. Configure label-based schedule:
   - **Name:** `qa-auto-inclusion-schedule`
   - **Cluster:** [TARGET_CLUSTER]
   - **Backup Type:** Label Selector
   - **Label Selector:** `backup-tier=gold`
   - **Schedule:** `0 */2 * * *` (every 2 hours)
   - **Backup Location:** [S3_BACKUP_LOCATION]
4. Save schedule configuration
5. Create new namespace via CLI after schedule creation:

   ```bash
   oc create namespace qa-test-namespace-3
   ```

6. Navigate to **Application > Resources** in PX-Backup UI
7. Select `qa-test-namespace-3` from cluster dropdown
8. Click **Create Resource > ConfigMap**
9. Configure test ConfigMap:
   - **Name:** `auto-test`
   - **Key:** `auto`
   - **Value:** `value`
10. Save ConfigMap creation
11. Apply matching label via CLI:

    ```bash
    oc label namespace qa-test-namespace-3 backup-tier=gold
    ```

12. Navigate to **Application > Namespaces** to verify label applied
13. Wait for next scheduled backup execution
14. Navigate to **Backup > Backups** to review latest scheduled backup
15. Verify backup includes resources from all three labeled namespaces

**Expected Result:** Newly labeled namespace automatically included in subsequent scheduled backups

---

## 4. Validation Checklist

| Test Scenario | Reference Section | Pass/Fail | Notes |
|---------------|------------------|-----------|-------|
| 15-Minute Schedule Creation | 1.1 | | |
| Scheduled ConfigMap Restore | 1.2 | | |
| Historical Version Restore | 1.3 | | |
| Manual Namespace Backup | 2.1 | | |
| Ad-Hoc ConfigMap Restore | 2.2 | | |
| Full Namespace Overwrite | 2.3 | | |
| Namespace Labeling | 3.1 | | |
| Label-Filtered Backup | 3.2 | | |
| Auto-Inclusion Verification | 3.3 | | |

## 5. Success Criteria

- [ ] All scheduled backups execute on time with 100% success rate
- [ ] Schedule policies are properly created and associated with backups
- [ ] All restore operations complete without data loss
- [ ] Replace policies function correctly during restore operations
- [ ] Label-based filtering operates correctly
- [ ] Historical backups accessible and restorable
- [ ] Full namespace overwrite restores to exact backup state
- [ ] S3 storage integration functions without errors
- [ ] UI and CLI operations complete within expected performance metrics
- [ ] Backup and restore times meet performance benchmarks
- [ ] Multi-resource restoration (ConfigMaps, Secrets, Deployments) works correctly
- [ ] S3 retention policies are enforced correctly

---

## 6. Documentation References

### Portworx Official Documentation

| Feature | Documentation URL |
|---------|------------------|
| Backup Scheduling | <https://docs.portworx.com/portworx-backup-on-prem/backup/schedule-backups/> |
| Schedule Policies | <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/schedule> |
| Manual Backups | <https://docs.portworx.com/portworx-backup-on-prem/backup/create-backup/> |
| Perform Backup | <https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup/perform-backup> |
| Restore Operations | <https://docs.portworx.com/portworx-backup-on-prem/restore/restore-backup/> |
| Label-Based Backups | <https://docs.portworx.com/portworx-backup-on-prem/backup/namespace-labels/> |
| S3 Configuration | <https://docs.portworx.com/portworx-backup-on-prem/install/configure-backup-location/> |
| OpenShift Integration | <https://docs.portworx.com/portworx-backup-on-prem/install/openshift/> |

### Additional Resources

- [PX-Backup CLI Reference](https://docs.portworx.com/portworx-backup-on-prem/reference/px-backup-cli/)
- [Troubleshooting Guide](https://docs.portworx.com/portworx-backup-on-prem/troubleshooting/)
- [Best Practices](https://docs.portworx.com/portworx-backup-on-prem/backup/best-practices/)

---

## Appendix

### Test Data Requirements

- Minimum 3 ConfigMaps per test namespace
- Sample application deployments with persistent volumes
- Various resource types (Services, Secrets, ConfigMaps, Deployments)

### Environment Variables

```bash
export CLUSTER_NAME="[TO_BE_PROVIDED]"
export S3_BACKUP_LOCATION="[TO_BE_PROVIDED]"
export PX_BACKUP_ENDPOINT="[TO_BE_PROVIDED]"
```

### Cleanup Procedures

After test completion:

**UI Cleanup:**

1. Navigate to **Backup > Schedules** and delete all test schedules
2. Navigate to **Backup > Backups** and delete test backup instances
3. Navigate to **Application > Resources** and clean up test resources

**CLI Cleanup:**

```bash
oc delete namespace qa-test-namespace qa-test-namespace-2 qa-test-namespace-3 qa-test-namespace-historical
```

**Storage Cleanup:**

- Verify S3 backup location cleanup if required
- Confirm backup retention policies applied correctly

## 7. Test Execution Guidelines

### 7.1 Execution Requirements

- Execute tests in sequential order to maintain data integrity
- Document any deviations from expected behavior in validation checklist
- Capture screenshots of critical operations for evidence
- Record backup and restore completion times for performance validation
- Verify operations through both PX-Backup UI and CLI where applicable
- Confirm S3 storage utilization and retention policy enforcement

### 7.2 Performance Metrics

Track the following metrics during test execution:

| Operation | Expected Duration | Actual Duration | Notes |
|-----------|------------------|-----------------|-------|
| 15-minute scheduled backup | < 5 minutes | | |
| ConfigMap restore | < 2 minutes | | |
| Full namespace backup | < 10 minutes | | |
| Full namespace restore | < 15 minutes | | |
| Label-filtered backup | < 8 minutes | | |

### 7.3 Evidence Collection

- Screenshot each major UI operation
- Save backup/restore operation logs
- Document S3 bucket contents before and after operations
- Record any error messages or warnings
- Capture resource state before and after restore operations

---

**Document Control:** This test plan must be reviewed and approved by the QA Lead before execution. All test results must be documented and retained for compliance purposes.
