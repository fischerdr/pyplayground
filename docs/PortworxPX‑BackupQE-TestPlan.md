# Portworx PX‑Backup QE Test Plan

This test plan provides clear instructions for testing **scheduled** and **ad‑hoc namespace backups** in PX‑Backup, including backups by **namespace label** and restores of config maps. Each step points to Portworx documentation for context.

---

## 1. Scheduled Backup Testing

### 1.1 Create a 15‑Minute Backup Schedule for a Namespace

1. In the PX‑Backup UI, go to **Settings → Schedule Policy**.
2. Create a new schedule policy (e.g. `ns‑15min‑sched`), type **Periodic**, interval = **15 minutes**.
3. Save.
4. Navigate to **Settings → Rules**, define a rule targeting your namespace under “Applications → NS”.
5. Go to **Backups → Create Scheduled Backup**, select namespace, associate the new schedule policy and rule, choose backup location and snapshot class, and **Create**.

### 1.2 Delete a ConfigMap

```bash
kubectl delete configmap <configmap-name> -n <namespace>
```

### 1.3 Restore from Scheduled Backup

1. Wait up to 15 minutes for backup to complete.
2. Under Backups, locate the latest namespace backup.
3. Click ⋮ → Restore; use default namespace mapping and enable Replace existing resources if needed.
4. After completion, verify:

    ```bash
    kubectl get configmap <configmap-name> -n <namespace>
    kubectl describe configmap <configmap-name> -n <namespace>
    ```

### 1.4 Vary ConfigMap Across Intervals & Restore Specific Version

1. During successive 15‑min intervals, update the ConfigMap value (e.g. v2, v3).
2. Confirm backups are created for each version.
3. Select a backup corresponding to a specific version and restore.
4. Confirm correct version content via kubectl describe.

## 2. Ad‑Hoc Backup Testing

### 2.1 Create Ad‑Hoc Namespace Backup

1. In PX‑Backup UI, go to Backups → Create Backup.
2. Select the namespace, backup location, CSI snapshot class.
3. Ensure scheduling is disabled (manual backup).
4. Create the backup.

### 2.2 Delete a ConfigMap

```bash
kubectl delete configmap <configmap-name> -n <namespace>
```

### 2.3 Restore ConfigMap from Ad‑Hoc Backup

1. Locate manual backup in UI under Backups.
2. Click restore; choose same namespace, enable Replace existing resources.
3. Verify recovery:

    ```bash
    kubectl get configmap <configmap-name> -n <namespace>
    kubectl describe configmap <configmap-name> -n <namespace>
    ```

### 2.4 Full Namespace Restore with Overwriting

Delete additional resources (e.g. Secrets, Deployments).

Trigger full restore from backup with Overwrite existing resources enabled.

Verify all deleted objects are restored and state matches snapshot.

## 3. Ad‑Hoc Backup by Namespace Label

### 3.1 Purpose

Verify that PX‑Backup correctly performs ad‑hoc backups by namespace labels, selecting all namespaces matching specified label filters
.

### 3.2 Prerequisites

Stork version ≥ 23.9.1 installed on your cluster for label filtering in UI

### 3.3 Create namespace and apply labels

```bash
kubectl create namespace labtest
kubectl label namespace labtest env=qa team=testing
kubectl get namespaces --show-labels
```

### 3.4 Steps

1. In PX‑Backup UI, go to Clusters → select cluster → Applications → NS tab.

2. In Search by backup label field, enter (for example): env=qa,team=testing and press Enter.

3. UI auto-selects namespaces matching all labels using AND semantics

4. Click Backup.

5. In the Create Backup dialog:

6. Enter backup name (e.g. label‑based‑backup‑<timestamp>)

7. Select backup location and snapshot class

8. Confirm manual backup (schedule disabled)

9. Click Create.

10. Monitor progress in Backups tab.

11. Validate the backup entry includes the namespace and all its resources.

### 3.5 Optional: Delete & Restore

1. Delete a resource (e.g. config map) in labtest.

2. Find the backup in UI → ⋮ → Restore, restoring to same namespace, enable overwrite.

3. Validate resource recovery via:

```bash
kubectl get configmap -n labtest
kubectl describe configmap <name> -n labtest
```

### 3.6 Validation Checklist

Test Scenario Expected Result
15‑min scheduled backup triggers Backup record appears after 15 min
Scheduled restore recovers deleted config ConfigMap restored with correct version
Versioned config map restores correctly Restored content matches selected backup
Manual backup created ad‑hoc Backup appears immediately in UI
Restore from manual backup works correctly Deleted resources restored
Label‑based manual backup selects namespace Only labeled namespace is backed up and shown
Label‑based restore works as expected Deleted item in labeled namespace is recovered

### 3.7 References

### 3.7.1 Documentation Sources

#### 3.7.1.1 Schedule Policies & Scheduled Backups

#### 3.7.1.2 Create schedule policies: Explains how to define periodic, daily, weekly, and locked/unlocked schedule policies through the PX‑Backup UI under Settings → Schedule Policies

#### 3.7.1.3 Create a scheduled backup: Guides selecting namespaces (with label filters), associating schedule policies, specifying backup location, CSI snapshot class, and clicking “Backup” to create a scheduled job

#### 3.7.1.4 Namespace Label Filtering & Ad‑Hoc Label‑Based Backups

#### 3.7.1.5 Backup labeled namespaces: Details applying namespace labels via CLI (kubectl label namespace …), filtering namespaces using the UI Search by backup label field (AND semantics), and initiating backups based on labels

#### 3.7.1.6 Labels in Portworx Backup: Describes label usage for automation and inclusion of future namespaces matching labels in scheduled backups

#### 3.7.1.7 General Backup Types

#### 3.7.1.8 Backup overview: Covers various backup modes supported by Portworx Backup, including manual (ad‑hoc) and scheduled options for namespaces and VMs, including dependency on storage provisioners and rules

| Topic                            | Description                                                                | Docs Reference                                             |
| -------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Add Schedule Policies**        | How to create and manage periodic/unlocked schedule policies               | ([Portworx Documentation][1])                              |
| **Create Scheduled Backup**      | UI process for scheduled namespace backup with filtering and settings      | ([Portworx Documentation][2], [Portworx Documentation][3]) |
| **Label-Based Namespace Backup** | CLI label apply + UI filter behavior with VLAN AND filtering semantics     | ([Portworx Documentation][4], [Portworx Documentation][5]) |
| **Label Automation Behavior**    | Future namespace inclusion in scheduled backups and behavior with labeling | ([Portworx Documentation][5], [Portworx Documentation][6]) |
| **Manual / Ad‑Hoc Backups**      | How to create one-time backups and manage backup types via UI              | ([Portworx Documentation][7], [Portworx Documentation][3]) |

[1]: https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/schedule?utm_source=chatgpt.com "Add schedule policies"
[2]: https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup/scheduled-backup?utm_source=chatgpt.com "Create a scheduled backup"
[3]: https://docs.portworx.com/portworx-backup-on-prem/2.6/use-px-backup/backup-restore/create-backup/perform-backup/scheduled-backup?utm_source=chatgpt.com "Create a scheduled backup"
[4]: https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/labels/namespace-labels?utm_source=chatgpt.com "Backup labeled namespaces"
[5]: https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/labels?utm_source=chatgpt.com "Labels in Portworx Backup"
[6]: https://docs.portworx.com/portworx-backup-on-prem/concepts?utm_source=chatgpt.com "Concepts - Portworx Documentation"
[7]: https://docs.portworx.com/portworx-backup-on-prem/use-px-backup/backup-restore/create-backup?utm_source=chatgpt.com "Backup"

### 3.7.2 Namespace‑label backup filtering UI and CLI label application

#### 3.7.2.1 Requirements for Stork v23.9.1 to support label filtering

#### 3.7.2.2 Use of label filters (“AND” semantics) in namespace selection UI

#### 3.7.2.3 Overview of labels in Portworx Backup UI and backup creation flows

### 3.8 Notes

#### 3.8.1 Any unspecified values (e.g. backup location, snapshot class) should align with your team’s standard configuration

#### 3.8.2 Where UI steps are ambiguous, refer directly to Portworx documentation linked above

#### 3.8.3 Automation recommendation: integrate CLI/API for backup creation, status polling, and restore triggering for repeatable validation
