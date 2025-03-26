# **Portworx Encrypted Volume Migration Plan**

## **Objective**

This document outlines the transition strategy for migrating **Portworx-encrypted volumes** from using **HashiCorp Vault** to **Kubernetes Secrets** while also phasing out encrypted storage where applicable. The plan ensures:

- **Cluster-wide migration** from HashiCorp Vault to Kubernetes Secrets for key management.
- **Gradual decommissioning** of encrypted storage for workloads that do not require encryption.
- **No data loss** for persistent workloads requiring encryption migration.
- **Minimal service disruption** through a controlled rollout strategy.

## **Migration Strategy**

The migration involves two key phases:

1. **Cluster-Wide Key Management Migration**: Transition all existing **Portworx-encrypted volumes** from HashiCorp Vault to Kubernetes Secrets.
2. **Decommissioning Encrypted Storage**: Gradually shift workloads to **non-encrypted storage classes**, where feasible.

> **IMPORTANT**: This migration must be performed across **all Portworx-encrypted volumes simultaneously**. Portworx enforces a cluster-wide approach to secret management, meaning partial migrations are not supported. The entire cluster must transition from HashiCorp Vault to Kubernetes Secrets in a coordinated operation.

### **Phase 1: Cluster-Wide Migration from HashiCorp Vault to Kubernetes Secrets**

Portworx enforces a cluster-wide approach to secret management, meaning the migration must be executed simultaneously for all encrypted volumes.

#### **Step 1: Prepare Kubernetes Secrets**

- **Create a Kubernetes Secret to Store the Cluster-Wide Encryption Key:**

  ```sh
  NAMESPACE=<px-namespace>
  kubectl -n ${NAMESPACE} create secret generic px-vol-encryption \
    --from-literal=<cluster-wide-secret-key>=<value>
  ```

- This secret (`px-vol-encryption`) will be used by all encrypted Portworx volumes going forward.

#### **Step 2: Create an Encrypted Storage Class using Kubernetes Secrets**

- **Define the StorageClass with Kubernetes Secrets:**

  ```yaml
  kind: StorageClass
  apiVersion: storage.k8s.io/v1
  metadata:
    name: px-encrypted-sc
  provisioner: pxd.portworx.com
  allowVolumeExpansion: true
  parameters:
    repl: "2"
    priority_io: "high"
    io_profile: auto
    encryption: "true"
    secret_name: "px-vol-encryption"
    secret_namespace: "<px-namespace>"
  ```

- **Apply the StorageClass:**

  ```sh
  kubectl apply -f px-encrypted-sc.yaml
  ```

#### **Step 3: Configure Portworx to Use Kubernetes Secrets**

- **Modify Portworx Configuration:**
  - Update the StorageCluster specification to select **Kubernetes** as the secrets store type.
- **Set the Cluster-Wide Secret Key:**

  ```sh
  PX_POD=$(kubectl get pods -l name=portworx -n ${NAMESPACE} -o jsonpath='{.items[0].metadata.name}')
  kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl secrets set-cluster-key \
    --secret <cluster-wide-secret-key>
  ```

- This ensures that Portworx references Kubernetes Secrets instead of HashiCorp Vault for encryption.

#### **Step 4: Migrate Existing PVCs to Kubernetes Secrets**

- **Recreate PVCs to Use the New Encrypted Storage Class:**

  ```yaml
  kind: PersistentVolumeClaim
  apiVersion: v1
  metadata:
    name: encrypted-pvc
  spec:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 10Gi
    storageClassName: px-encrypted-sc
  ```

  ```sh
  kubectl apply -f encrypted-pvc.yaml
  ```

- **Validate Data Accessibility:**
  - Ensure that applications can still access their encrypted data post-migration.

#### **Step 5: Remove HashiCorp Vault Configuration**

- Once all volumes are migrated, update the Portworx configuration to remove **HashiCorp Vault references**.
- **Perform validation tests** to ensure no disruptions.

### **Phase 2: Gradual Decommissioning of Encrypted Storage**

Once Kubernetes Secrets fully replace HashiCorp Vault, we proceed with transitioning workloads to **non-encrypted storage classes** where possible. This phase includes two independent approaches:

#### **Approach 1: Data-Preserving Migration (Recommended for Persistent Data)**

1. **Identify Encrypted PVCs**

   ```sh
   kubectl get pvc -A -o wide | grep <encrypted-storage-class>
   ```

2. **Extract Encryption Secret and Store in Kubernetes**

   ```sh
   vault kv get -format=json secret/<namespace>/<pvc-name> | jq -r '.data.data.key'
   ```

   ```sh
   kubectl create secret generic <pvc-secret> --from-literal=key=<retrieved-key> -n <namespace>
   ```

3. **Delete and Recreate the PVC with Non-Encrypted Storage**

   ```sh
   kubectl delete pvc <pvc-name> -n <namespace>
   ```

   - Recreate the PVC using a **non-encrypted storage class**.
4. **Validate Data Integrity**
   - Ensure applications function correctly after migration.

#### **Approach 2: Non-Encrypted Redeployment for Non-Persistent Data**

This is a standalone approach for workloads where data persistence is not required.

1. **Create a Non-Encrypted Storage Class**

   ```yaml
   kind: StorageClass
   apiVersion: storage.k8s.io/v1
   metadata:
     name: px-storage-class
   provisioner: pxd.portworx.com
   allowVolumeExpansion: true
   parameters:
     repl: "2"
     priority_io: "high"
     io_profile: auto
   ```

   ```sh
   kubectl apply -f px-storage-class.yaml
   ```

2. **Redeploy Applications with Non-Encrypted Storage**
   - Applications using ephemeral data should be redeployed using the **new non-encrypted storage class**.
   - **Important Note**: This method **results in data loss** but is appropriate for **stateless applications** or applications where data can be regenerated.

3. **Update Application Manifests**
   - Modify application deployment manifests to reference the non-encrypted storage class.
   - Example PVC definition:

   ```yaml
   kind: PersistentVolumeClaim
   apiVersion: v1
   metadata:
     name: app-data
   spec:
     accessModes:
       - ReadWriteOnce
     resources:
       requests:
         storage: 10Gi
     storageClassName: px-storage-class
   ```

4. **Apply the Updated Manifests**

   ```sh
   kubectl apply -f updated-app-deployment.yaml
   ```

## **Migration Approach Comparison**

The following table provides a side-by-side comparison of the two migration approaches to help with decision-making:

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Data-Preserving Migration** | • Preserves all existing data• No application downtime if done correctly• Maintains data integrity | • More complex process• Requires manual PVC recreation• Higher risk of errors | • Production workloads• Databases• Any application with valuable persistent data |
| **Non-Encrypted Redeployment** | • Simpler implementation• Clean slate for applications• Faster execution | • Complete data loss• Requires application redeployment• Service interruption | • Development/test environments• Stateless applications• Caches and temporary storage |

## **Risk Assessment and Mitigation**

### **Potential Risks**

| Risk | Impact | Mitigation Strategy |
|------|--------|---------------------|
| **Secret Key Mismatch** | Data becomes inaccessible | Verify secret key values before migration; maintain HashiCorp Vault access until migration is complete |
| **Application Downtime** | Service interruption | Schedule migration during maintenance windows; perform in stages |
| **Data Loss** | Permanent loss of information | Backup all PVCs before migration; test recovery procedures |
| **PVC Recreation Failures** | Migration incomplete | Document current PVC specifications; prepare rollback plan |
| **Partial Cluster Migration** | Inconsistent encryption state | Ensure all volumes are migrated simultaneously; validate cluster-wide configuration |

### **Rollback Plan**

If issues arise during migration, follow these steps to roll back:

1. **Revert to HashiCorp Vault Configuration**:

   ```sh
   kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl secrets set-cluster-key --vault <vault-options>
   ```

2. **Restore Original Storage Classes**:

   ```sh
   kubectl apply -f original-storage-classes.yaml
   ```

3. **Restore PVCs from Backups** if data loss occurred.

## **Testing and Validation**

### **Pre-Migration Testing**

1. **Environment Validation**:

   ```sh
   # Verify Portworx status
   kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl status
   
   # Verify current encryption configuration
   kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl secrets list
   ```

2. **Create Test Volumes**:
   - Deploy test applications with encrypted volumes
   - Verify data can be written and read correctly

3. **Backup Verification**:
   - Ensure backup procedures are working correctly
   - Test restore functionality in a separate environment

### **Post-Migration Validation**

1. **Encryption Verification**:

   ```sh
   # Verify volumes are using Kubernetes Secrets
   kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl volume list
   kubectl exec $PX_POD -n ${NAMESPACE} -- /opt/pwx/bin/pxctl volume inspect <volume-id>
   ```

2. **Application Testing**:
   - Verify all applications can access their data
   - Run application-specific validation tests
   - Check for any performance impacts

3. **Security Validation**:
   - Ensure HashiCorp Vault is no longer being accessed
   - Verify Kubernetes Secrets are properly secured

## **Helm Chart Changes**

To enforce these changes, updates are required in Helm charts.

### **Helm Chart Modifications**

- **Set Default Storage Class to Non-Encrypted**

  ```yaml
  storage:
    class: "px-storage-class"
    size: "100Gi"
  ```

- **Conditional Handling for Existing Encrypted PVCs**

  ```yaml
  storage:
    useEncrypted: false  # Default for new deployments
    existingPVC: ""      # Set for migrations
  ```

### **Affected Helm Values**

The following Helm chart values will need to be updated across all applications:

| Helm Value | Current Setting | New Setting | Purpose |
|------------|----------------|------------|---------|
| `storage.class` | `px-encrypted-sc` | `px-storage-class` | Change default storage class to non-encrypted |
| `storage.useEncryption` | `true` | `false` | Disable encryption by default |
| `portworx.secretsProvider` | `vault` | `k8s` | Change secrets provider to Kubernetes |
| `portworx.secretsNamespace` | `<vault-namespace>` | `<px-namespace>` | Update secrets namespace |

### **Implementation Example**

For applications using the standard Helm chart structure:

```yaml
# values.yaml modifications
global:
  storageClass: px-storage-class  # Previously px-encrypted-sc
  
persistence:
  enabled: true
  storageClass: ""  # Will use global.storageClass
  
portworx:
  secretsProvider: k8s  # Previously vault
  secretsNamespace: portworx-system
```

## **Deployment Strategy**

1. **Phase 1: Deploy Helm Chart Updates**
   - Ensure all new deployments default to **non-encrypted storage**.
   - Stop new workloads from using HashiCorp Vault.
2. **Phase 2: Migrate Existing Workloads**
   - Perform **data-preserving migration** where required.
   - Guide customers in **redeploying ephemeral workloads**.
3. **Phase 3: Full Transition and Validation**
   - Validate that **no new workloads use encryption**.
   - Remove legacy encrypted storage classes.

## **Success Criteria**

The migration will be considered successful when the following measurable outcomes are achieved:

| Metric | Target | Validation Method |
|--------|--------|------------------|
| **HashiCorp Vault References** | 0 active references | Audit cluster configuration and application logs |
| **New Workloads Using Non-Encrypted Storage** | 100% | Monitor StorageClass usage in new PVCs |
| **Existing Workloads Migrated** | 100% | Verify all PVCs use either K8s Secrets or non-encrypted storage |
| **Application Availability** | 99.9% during migration | Monitor application uptime metrics |
| **Data Integrity** | 100% preserved | Run data validation tests on migrated volumes |
| **Performance Impact** | < 5% degradation | Compare pre- and post-migration performance metrics |

## **Conclusion**

This plan enables a **smooth migration** from **HashiCorp Vault to Kubernetes Secrets** while gradually **decommissioning encrypted storage**. The phased approach ensures **minimal disruption** and **data integrity** throughout the transition.

By following the detailed steps, risk mitigation strategies, and validation procedures outlined in this document, organizations can successfully complete this migration with confidence and maintain the security and reliability of their Kubernetes environments.
