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

## **Conclusion**

This plan enables a **smooth migration** from **HashiCorp Vault to Kubernetes Secrets** while gradually **decommissioning encrypted storage**. The phased approach ensures **minimal disruption** and **data integrity** throughout the transition.
