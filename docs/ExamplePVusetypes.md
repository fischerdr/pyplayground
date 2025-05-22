# Example of PV Storage Types

## Part 1: Choosing the Right Storage Type for Your Workload

Selecting the correct storage type in Kubernetes is critical for application reliability, cost, and performance. This section explains the main storage types, typical workload patterns, and common mistakes—especially the overuse of persistent volumes (PVs) for ephemeral data.

### Ephemeral Storage

Ephemeral storage is temporary. Kubernetes deletes this data when the pod is removed. Use ephemeral storage for data that does not need to persist, such as build artifacts, caches, or temporary files.

- **When to use:** Build pipelines, CI/CD, scratch space, temporary processing.
- **Common mistake:** Using a PV for data that is recreated every time the pod starts. This wastes resources and adds unnecessary complexity.
- **Best practice:** Use `emptyDir` (memory or disk-backed) for data that can be lost when the pod is deleted. If you need to fetch data at startup, consider pulling from S3 or another object store.

### Persistent Storage

Persistent storage survives pod restarts and rescheduling. Use persistent storage for stateful applications that need to retain data.

- **When to use:** Databases, application state, user uploads.
- **Common mistake:** Using persistent storage for data that could be ephemeral or easily regenerated.
- **Best practice:** Use a PersistentVolumeClaim (PVC) for data that must survive pod restarts. Match storage class and size to your application's needs.

### S3/Object Storage Patterns

S3 and other object stores provide external storage. You can fetch or sync data into the pod at runtime.

- **When to use:** Static assets, ML models, reference data, large files that don't need to persist in the cluster.
- **Best practice:** Use init-containers or sidecars to pull from or push to S3 as needed. This reduces PV usage and can improve scalability.

### Shared Storage (ReadWriteMany)

Shared storage can be mounted by multiple pods across nodes at the same time. Use this only when true sharing is required.

- **When to use:** Shared assets, CMS, file servers.
- **Best practice:** For static files, consider S3/object storage patterns instead of RWX volumes.

### Modern Patterns

Modern Kubernetes design patterns help you optimize storage, improve scalability, and reduce costs. Consider these approaches:

- **Init-Container Pattern:** Use an init-container to fetch or generate data at pod startup (e.g., download from S3, run a setup script). Keeps the main container image smaller and separates initialization logic.
- **Sidecar Pattern:** Add a sidecar container to handle tasks like syncing data from S3, log shipping, or proxying. Sidecars run alongside your main app and can be reused across workloads.
- **S3/Object Store Integration:** Store large, static, or cacheable data in S3 or another object store. Use init-containers or sidecars to pull data into the pod at runtime, reducing the need for persistent volumes.
- **Cache Pattern:** For workloads that can tolerate data loss or re-fetching, use `emptyDir` as a cache. Combine with S3/object store for warm/cold cache strategies.
- **Stateless vs. Stateful:** Prefer stateless patterns (ephemeral storage, S3 integration) for horizontally scalable workloads. Use stateful patterns (PVCs, StatefulSets) only when data durability is required.
- **Batch/Periodic Job Pattern:** Use Kubernetes Jobs or CronJobs for one-time or scheduled data processing, backup, or sync tasks. These can use ephemeral or persistent storage as needed.

These patterns help you:

- Avoid over-provisioning persistent storage for ephemeral data.
- Separate initialization and runtime logic for better maintainability.
- Scale workloads efficiently by decoupling storage from compute.
- Reduce costs by using object storage for large or infrequently accessed data.

---

## Part 2: Practical Examples—Using S3, Init-Containers, and Sidecars

This section provides YAML examples for common patterns. Each example includes a short context to help you decide when to use it.

### Example 1: Memory-backed emptyDir with S3 Init-Container

Use this pattern for fast, temporary storage. Fetch data from S3 at pod startup. Data is lost when the pod is deleted.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-init-memory
spec:
  initContainers:
    - name: fetch-from-s3
      image: amazon/aws-cli
      command: ['sh', '-c', 'aws s3 cp s3://mybucket/myfile /data/myfile']
      volumeMounts:
        - name: memtmp
          mountPath: /data
      resources:
        requests:
          memory: 2Gi
        limits:
          memory: 2Gi
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: memtmp
          mountPath: /app/data
      resources:
        requests:
          memory: 2Gi
        limits:
          memory: 2Gi
  volumes:
    - name: memtmp
      emptyDir:
        medium: Memory
```

### Example 2: Memory-backed emptyDir with S3 Sidecar

Use this pattern to continuously sync data from S3 into a RAM-backed temporary volume. Data is lost when the pod is deleted.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-sidecar-memory
spec:
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: memtmp
          mountPath: /app/data
      resources:
        requests:
          memory: 2Gi
        limits:
          memory: 2Gi
    - name: s3-sync
      image: amazon/aws-cli
      command: ['sh', '-c', 'while true; do aws s3 sync s3://mybucket/assets /data; sleep 300; done']
      volumeMounts:
        - name: memtmp
          mountPath: /data
      resources:
        requests:
          memory: 2Gi
        limits:
          memory: 2Gi
  volumes:
    - name: memtmp
      emptyDir:
        medium: Memory
```

### Example 3: Disk-backed emptyDir with S3 Init-Container

Use this pattern for temporary storage on disk. Fetch data from S3 at pod startup. Data is lost when the pod is deleted.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-init-disk
spec:
  initContainers:
    - name: fetch-from-s3
      image: amazon/aws-cli
      command: ['sh', '-c', 'aws s3 cp s3://mybucket/myfile /data/myfile']
      volumeMounts:
        - name: disktmp
          mountPath: /data
      resources:
        requests:
          ephemeral-storage: 2Gi
        limits:
          ephemeral-storage: 2Gi
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: disktmp
          mountPath: /app/data
      resources:
        requests:
          ephemeral-storage: 2Gi
        limits:
          ephemeral-storage: 2Gi
  volumes:
    - name: disktmp
      emptyDir: {}
```

### Example 4: Disk-backed emptyDir with S3 Sidecar

Use this pattern to continuously sync data from S3 into a disk-backed temporary volume. Data is lost when the pod is deleted.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-sidecar-disk
spec:
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: disktmp
          mountPath: /app/data
      resources:
        requests:
          ephemeral-storage: 2Gi
        limits:
          ephemeral-storage: 2Gi
    - name: s3-sync
      image: amazon/aws-cli
      command: ['sh', '-c', 'while true; do aws s3 sync s3://mybucket/assets /data; sleep 300; done']
      volumeMounts:
        - name: disktmp
          mountPath: /data
      resources:
        requests:
          ephemeral-storage: 2Gi
        limits:
          ephemeral-storage: 2Gi
  volumes:
    - name: disktmp
      emptyDir: {}
```

### Example 5: Persistent Storage with S3 Init-Container

Use this pattern to restore or fill static data from S3 into a persistent volume at pod startup. Data persists across pod restarts.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-init-persistent
spec:
  initContainers:
    - name: fetch-from-s3
      image: amazon/aws-cli
      command: ['sh', '-c', 'aws s3 cp s3://mybucket/myfile /data/myfile']
      volumeMounts:
        - name: persistent-data
          mountPath: /data
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: persistent-data
          mountPath: /app/data
  volumes:
    - name: persistent-data
      persistentVolumeClaim:
        claimName: my-pvc
```

### Example 6: Persistent Storage with S3 Sidecar

Use this pattern to periodically back up or update static data from a persistent volume to S3 while the app is running.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-sidecar-persistent
spec:
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: persistent-data
          mountPath: /app/data
    - name: s3-backup
      image: amazon/aws-cli
      command: ['sh', '-c', 'while true; do aws s3 sync /data s3://mybucket/assets; sleep 300; done']
      volumeMounts:
        - name: persistent-data
          mountPath: /data
  volumes:
    - name: persistent-data
      persistentVolumeClaim:
        claimName: my-pvc
```

## References

- [Kubernetes Volumes: emptyDir](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)
- [Managing Resources for Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [Kubernetes Init Containers](https://kubernetes.io/docs/concepts/workloads/pods/init-containers/)
- [Kubernetes Sidecar Container – Best Practices and Examples](https://spacelift.io/blog/kubernetes-sidecar-container)
- [How I backup and restore data in my Kubernetes persistent volumes](https://brennonloveless.medium.com/how-i-backup-and-restore-data-in-my-kubernetes-persistent-volumes-a5deec5d31ae)
