Handling disaster recovery for a Kubernetes or OpenShift cluster, particularly in relation to etcd, involves several methodologies that ensure minimal disruption to live operations. Here’s a detailed overview:
1. Backup Strategies for etcd
a. Regular Scheduled Backups

    Use the built-in etcdctl tool to create consistent snapshots.
    Example:

    ETCDCTL_API=3 etcdctl snapshot save /path/to/backup.db \
      --endpoints=<etcd-endpoint> \
      --cacert=/path/to/ca.crt \
      --cert=/path/to/server.crt \
      --key=/path/to/server.key

    Automate this process with cron jobs or similar scheduling tools.

b. OpenShift-Specific Tools

    OpenShift provides the cluster-backup.sh script, which automates etcd backups and includes other essential cluster data:

    /usr/local/bin/cluster-backup.sh /path/to/backup/destination

c. Snapshot Storage

    Store snapshots in a secure, redundant location like an object storage service (e.g., AWS S3, Azure Blob Storage) or a remote NFS/SMB share.

d. Testing Backups

    Periodically test backups by restoring them in a staging or testing environment to ensure they are valid.

2. Restoring etcd Without Impacting Live Operations
a. Restore Procedure

    Stop the Control Plane Components:
        Prevent other services from connecting to etcd during the restoration process.

systemctl stop kube-apiserver kube-controller-manager kube-scheduler

Restore the Snapshot:

    Use the etcdctl tool to restore:

    ETCDCTL_API=3 etcdctl snapshot restore /path/to/backup.db \
      --data-dir=/path/to/new-etcd-data-dir

Reconfigure etcd to Use the Restored Data Directory:

    Update the etcd service configuration to point to the restored data directory.

Restart etcd:

systemctl start etcd

Restart Control Plane Components:

    systemctl start kube-apiserver kube-controller-manager kube-scheduler

b. OpenShift-Specific Restore:

    OpenShift provides cluster-restore.sh:

    /usr/local/bin/cluster-restore.sh /path/to/backup/

3. Recovering from etcd Corruption
a. Identification of Corruption

    Monitor etcd logs for errors indicating corruption.
    Use etcdctl health checks to confirm issues:

    ETCDCTL_API=3 etcdctl endpoint health --endpoints=<etcd-endpoint>

b. Restoration from Snapshot

    If corruption is detected, follow the steps above for restoring from a known good backup.

c. Isolated Restoration

    If the cluster is multi-node, isolate the faulty etcd member:
        Remove the member from the cluster.
        Restore it separately.
        Re-add it to the cluster.

d. Rebuilding etcd from Remaining Nodes

    If the majority of etcd nodes are intact, rebuild the cluster using healthy nodes:

    ETCDCTL_API=3 etcdctl member remove <failed-member-id>
    ETCDCTL_API=3 etcdctl member add <new-member-name> --peer-urls=<new-peer-url>

4. Cluster Recovery
a. Recreate Resources

    If certain Kubernetes resources are lost, use GitOps tools like ArgoCD or Flux to redeploy the cluster state from a source-controlled configuration.

b. Data Consistency Validation

    After restoring etcd, validate the cluster’s state:
        Ensure all nodes are functioning.
        Confirm workloads are running as expected.
        Test critical services and ingress/egress traffic.

c. Monitoring and Auditing

    Use Prometheus or OpenShift monitoring tools to keep track of etcd health and cluster metrics post-recovery.

5. Best Practices for Disaster Recovery

    Immutable Backups: Ensure backups are write-protected to prevent tampering.
    High Availability (HA): Deploy etcd in a 3- or 5-node HA configuration to minimize single points of failure.
    Frequent DR Drills: Simulate disaster recovery scenarios regularly to validate processes and refine them.
    Monitoring and Alerts: Set up real-time monitoring for etcd performance and errors.
    Separation of Duties: Restrict access to backup and restore operations to reduce risk.

By combining these methodologies, you can maintain robust disaster recovery capabilities for Kubernetes or OpenShift clusters, ensuring minimal downtime and data integrity.