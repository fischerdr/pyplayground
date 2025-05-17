# On-Premises Storage Strategy for Kubernetes & OpenShift

## Overview

Selecting appropriate storage for on-premises Kubernetes or OpenShift environments is critical for achieving agility, security, and scalability. This document analyzes traditional (NFS) and modern (CSI-based) solutions, focusing on security, migration, backend integration, and best practices for large-scale, resilient deployments.

### Infrastructure Context

Our environment consists of a mix of bare metal and VMware ESXi clusters, with backend storage provided by Pure Storage and NetApp arrays that the PV/PVCs are connected to. Kubernetes and OpenShift clusters are broken into zones each in its own row. For ESXi, each cluster is mapped to a shelf in a rack, and all clusters are managed under a single vCenter. Bare metal clusters are similarly distributed across rows to maximize fault isolation and high availability.

- Each datacenter row is mapped to a Kubernetes/OpenShift zone (e.g., `zone-a`, `zone-b`, `zone-c`).
- Each ESXi cluster corresponds to a shelf in a rack and is mapped to a zone. Each zone is a distinct failure domain.
- All clusters (bare metal and ESXi) are managed centrally for operational consistency. *not sure this is correct*
- Portworx and NFS are used as PersistentVolume (PV) and PersistentVolumeClaim (PVC) storage backends.
- NFS PV is connected to the worker node using the primary interface of the worker node then mounted into the container.
- Portworx is connected to the worker node using either a local datastore or a shared datastore group.

### Storage Connectivity

- Storage is provisioned to esxi nodes from iscsi on dedicated network to the consuming node.
- Baremetal nodes are connected to the storage using dedicated network to the storage.

### Current Storage Strategy

We have two types of customers:

- Customers who are using NFS as their storage backend.
- Customers who are using Portworx as their storage backend.

Most of out customer that are using portworx as there PV storage are mostly using the PV for ephemeral storage. This is not a very cost effective way to use storage.

We have a few customers that are using NFS as their storage backend. Most are using this to share data across zones, datacenters, and regions.

However, as outlined above, both NFS and Portworx are often used in ways that do not align with best practices for efficiency, cost, or resilience. These patterns can lead to suboptimal performance, increased operational overhead, and potential risks to data availability.

### Storage Strategy

On-Boarding team should assess each customer's storage requirements by reviewing their workload types, data persistence needs, and access patterns. Recommend the most efficient storage solution—whether NFS, Portworx, or another backend—based on these factors.

Guide customers through a structured decision process:

- Identify whether their workloads require ephemeral, persistent, shared, or local storage.
- Match each workload to the most appropriate storage class and backend.
- Advise on best practices for data protection, cost optimization, and high availability.

Enforce adherence to recommended architectures by:

- Ensuring customers provision storage in alignment with physical zones and failure domains.
- Requiring the use of topology-aware StorageClasses for multi-zone deployments.
- Regularly reviewing customer deployments to verify compliance with storage best practices.

Example of PV storage types:

1. Ephemeral Storage:
   - Temporary data that does not need to persist between pod restarts
   - Examples: Cache files, temporary processing data
   - Applications: CI/CD build workspaces, image processing pipelines

2. Persistent Storage:
   - Data that must survive pod restarts and rescheduling
   - Examples: Database files, application state
   - Applications: MySQL, PostgreSQL, MongoDB, Elasticsearch

3. Shared Storage (ReadWriteMany):
   - Data accessed by multiple pods simultaneously across nodes
   - Examples: Media files, documents, configuration data
   - Applications: Content Management Systems, file servers, shared application assets

4. Local Storage:
   - Node-specific storage for performance-critical workloads
   - Examples: High-performance databases, streaming data
   - Applications: Time-series databases, real-time analytics engines

Currently there is a heavy reliance on NFS for enterprise Kubernetes/OpenShift PV storage.
This presents several primary concerns:

- **Coarse-Grained Access Control:** NFS permissions are IP/filesystem-based, lacking Kubernetes-native object-level granularity. This creates risks of cross-namespace access and complicates adherence to the Principle of Least Privilege (PoLP).
- **Lack of Native Encryption:** Default NFS configurations often leave data at rest and in transit unencrypted, posing risks to sensitive data (PII, IP) and potentially violating compliance mandates (e.g., GDPR, HIPAA, PCI DSS) due to the absence of inherent encryption mechanisms.
- **Limited Auditability:** Tracking storage access at the pod/PersistentVolumeClaim (PVC) level is difficult with NFS, hindering effective security monitoring and incident response.
- **Complex Credential Management:** NFS often relies on less secure, static credentialing (e.g., IP-based allowlists, `no_root_squash`), increasing the potential blast radius of compromised credentials or misconfigurations.
- **Insecure Default Mount Options:** ReadWriteMany (RWX) mounts, common with NFS, can lead to data interference between applications if not implemented with strict isolation, a feature not inherently provided by NFS for container workloads.
- **Poor Integration with Zero-Trust Architectures:** NFS integrates poorly with modern security paradigms like SPIFFE/SPIRE or policy engines such as OPA/Gatekeeper, often necessitating parallel security stacks rather than unified, identity-based controls.
- **Operational Overhead and Technical Debt:** Significant manual effort is typically required for provisioning, scaling, HA configuration, and DR with NFS. This inherent lack of automation makes it less agile for dynamic container environments and accumulates technical debt.

To address the limitations of NFS storage, we should leverage  solutions that leverage the Container Storage Interface (CSI). CSI enables Kubernetes-native storage capabilities, providing improved integration, automation, and feature sets.

We should also consider the following:

*Software-Defined Storage (SDS):*

- Software-Defined Storage (SDS) - Ceph, Portworx, Longhorn, OpenEBS
- *Description:* These solutions typically operate as applications within the Kubernetes cluster or on dedicated commodity hardware, pooling local/networked storage resources. They provide features such as data replication, snapshots, encryption, and dynamic provisioning, managed via Kubernetes APIs.
- *Pros:* Offers high scalability, a rich feature set (including HA, snapshots, tiering), potential hardware-agnosticism, and strong Kubernetes integration.
- *Cons:* May present a steeper learning curve. Performance is dependent on the underlying hardware and network configuration. Dedicated operational expertise for the SDS platform itself may be required.

or

*Enterprise SAN/NAS with CSI Drivers:*

- Enterprise SAN/NAS with CSI Drivers - Dell EMC (PowerStore, PowerFlex, Unity), NetApp (ONTAP), Pure Storage (FlashArray, FlashBlade), IBM (Spectrum Scale, FlashSystem), HPE (Primera, Alletra, 3PAR)
- *Description:* Existing or new enterprise storage arrays (Fibre Channel SAN, iSCSI SAN, high-performance NAS filers) are integrated with Kubernetes/OpenShift clusters via vendor-provided CSI drivers.
- *Pros:* Leverages existing investments in robust enterprise storage and associated operational expertise. Benefits from mature data services (e.g., advanced replication, snapshots, DR capabilities) provided by the array.
- *Cons:* The quality and feature-completeness of dynamic provisioning and other Kubernetes-native features depend heavily on the vendor's CSI driver implementation. Management of external arrays can add complexity. May not be as agile or potentially cost-effective for rapidly changing cloud-native workloads compared to some SDS alternatives.

*Brief comparison of NFS and CSI solutions:*

| Feature Area                           | NFS (Traditional On-Premises)                                       | CSI Solutions (SDS, SAN/NAS + CSI) |
|----------------------------------------|---------------------------------------------------------------------|-----------------------------------------------------------------------|
| **K8s/OpenShift Integration**        | Limited; manual operations, no deep API integration.                | Native; dynamic provisioning, lifecycle mgmt via K8s APIs (StorageClasses, PVCs). |
| **Automation Level**                   | Low; significant manual effort for provisioning, scaling, repairs.  | High; automated workflows, self-service capabilities, operator patterns. |
| **Scalability (Data Center)**          | Bottlenecks at NFS server; limited IOPS/throughput scaling.         | Horizontally scalable; distributed architectures for IOPS, throughput, capacity. |
| **Performance Consistency**            | Variable; prone to latency spikes under load.                       | Predictable; optimized for virtualization & containers, QoS capabilities. |
| **Data Services (Native)**             | Basic; snapshots/replication often array-dependent, not K8s-aware.  | Rich; K8s-integrated snapshots, cloning, replication, tiering, encryption. |
| **Encryption (At-Rest/In-Transit)**  | Typically none natively; requires complex bolt-on solutions.          | Often built-in & manageable via K8s; CSI drivers can enable/enforce. |
| **High Availability (HA)**             | External, complex HA setups for NFS server; manual failover.        | Integrated; automated failover, self-healing, data redundancy across nodes/racks. |
| **Zonal Resiliency (On-Prem)**         | Difficult to achieve reliably without significant external tooling.   | Supports topology-aware provisioning & replication across on-prem zones. |
| **Operational Complexity**             | High; manual tuning, troubleshooting, separate management stack.    | Reduced; unified K8s-centric management, telemetry, some with auto-tuning. |
| **Multi-Tenancy & Isolation**          | Weak; IP-based controls, risk of cross-namespace data exposure.     | Strong; PVC/namespace-level isolation, RBAC, ResourceQuotas for storage. |
| **Large-Scale Suitability**            | Poor; struggles with metadata, high PV counts, dynamic workloads.   | Designed for; handles high metadata load, thousands of PVs/namespaces efficiently. |
| **Zero-Trust Alignment**               | Difficult; lacks granular identity & policy integration.            | Better; integrates with K8s RBAC, some support finer-grained policies. |
| **Upgrade/Maintenance Impact**         | Often disruptive for NFS server maintenance.                        | Supports non-disruptive upgrades and maintenance for storage plane. |
| **Cost Model (On-Prem TCO)**           | Lower initial hardware (if repurposing), high long-term ops cost.   | Higher initial (for SDS/HCI licenses/nodes or modern arrays), lower long-term ops cost due to automation & efficiency. |

Also since we are running at a large scale we need to consider the following:

- **Scalability:**
  - **Control Plane:** The storage solution's control plane, and the Kubernetes/OpenShift control plane (notably etcd), must efficiently handle a high rate of PV/PVC operations (create, delete, update), volume attachments, mounts, and unmounts. For etcd, this necessitates considerations such as dedicated instances, optimized hardware, and regular performance tuning, as high PV and namespace counts directly impact etcd and API server load.
  - **Data Plane:** The storage backend must scale IOPS, throughput, and capacity to meet the aggregate demand of potentially thousands of applications distributed across numerous namespaces.
  - **Metadata Operations:** Listing, creating, and deleting a large number of volumes and snapshots can become a bottleneck if not handled efficiently by the storage system and its CSI driver. Performance testing of these operations under load is crucial.
- **Performance at Scale:**
  - **Network Infrastructure:** The network infrastructure (for NAS, iSCSI, SDS internode communication) must be provisioned to handle peak loads without contention, ensuring sufficient bandwidth and low latency, especially for synchronous replication or latency-sensitive applications.
  - **Storage Tiering and QoS:** Employ tiered storage (e.g., SSDs for high-performance, HDDs for capacity) and Quality of Service (QoS) policies if supported by the storage solution. This allows for differentiated performance levels for various applications and namespaces.
  - **Continuous Monitoring:** Implement continuous monitoring and benchmarking of storage performance (IOPS, latency, throughput per PV, per node, per application) to identify and proactively address bottlenecks.
- **Management and Automation:**
  - Robust automation for storage provisioning, de-provisioning, volume expansion, and snapshot management is critical. Utilize StorageClasses, Kubernetes Operators for storage, and GitOps principles for managing storage configurations.
  - Implement centralized monitoring and alerting for storage health, capacity (global and per-quota), and performance, integrating with platforms like Prometheus and Grafana. Ensure the storage CSI driver and system export relevant metrics.
  - Plan for non-disruptive upgrades of the storage system and CSI drivers.
- **Namespace Isolation and Multi-tenancy:**
  - The storage solution must provide strong data isolation between numerous namespaces (e.g., ~2000). While PVCs are namespaced, the underlying storage system must robustly enforce this separation to prevent data leakage or interference.
  - Implement fine-grained RBAC for storage operations, restricting permissions for StorageClass creation/deletion, snapshot management, and alteration of storage quotas at cluster and namespace levels.
  - Utilize Kubernetes ResourceQuotas to limit storage consumption (number of PVs, total capacity) per namespace. This is crucial for preventing noisy neighbor problems and ensuring fair resource distribution across numerous PVs and namespaces.
- **Capacity Management:**
  - Implement proactive capacity planning and forecasting, considering historical growth and future application onboarding. High PV counts necessitate careful monitoring as even small average growth per PV can rapidly consume capacity.
  - Storage systems should ideally support thin provisioning for optimal space utilization and efficient reclamation of freed space upon PVC deletion.
  - Establish automated alerts for low capacity thresholds at both global storage pool and per-namespace quota levels.

### Zonal Architectures

We also need to make sure customers are following our zonal architecture. This is a must for data replication and are critical for HA and DR. In our environment, each datacenter row is mapped to a Kubernetes/OpenShift zone, and storage is provisioned to match the physical location of compute resources, But we have customers that are not following this architecture. They are using NFS for their storage backend and use it across regions and zones in a mixed fashion which breaks fault isolation and high availability.

On-Boarding team should enforce adherence to the recommended zonal architecture and ensure that customers select storage appropriate to their specific use cases. Regularly review deployments to confirm that storage usage and being used in the correct manner, and that shared storage is not used in ways that compromise fault isolation or high availability.

*Defining Availability Zones:*

- Map each physical datacenter row to a Kubernetes/OpenShift zone using node labels (e.g., `topology.kubernetes.io/zone`).
- Ensure each zone is a distinct failure domain.
- Each datacenter row is managed by a single vCenter and contains 10–15 racks.
- Each rack contains multiple shelves; each shelf is an ESXi host cluster (typically 10–15 hosts).
- A Kubernetes/OpenShift cluster is deployed on one or more ESXi host clusters (shelves), and these host clusters collectively define a single zone.
- Zones are mapped at the vCenter/row level, with each zone spanning the ESXi host clusters within that row.

*Data Replication Strategies:*

- **Synchronous Replication:** Use for critical workloads requiring zero data loss. Pure Storage and NetApp support synchronous replication between arrays in different zones (rows).
- **Asynchronous Replication:** Use for less critical workloads or when zones are separated by higher latency. Configure replication policies to match RPO/RTO requirements.
- **Disaster Recovery:** Regularly test failover and failback procedures. Automate backup and restore workflows where possible.

*Best Practices:*

For multi-zone deployments, different storage types and solutions have distinct advantages:

1. *Block Storage:*
   - Best suited for high-performance, latency-sensitive workloads
   - Excellent for synchronous replication between zones
   - Supports ReadWriteOnce (RWO) access mode
   - Solutions:
     - **Portworx:** Enterprise-grade block storage with built-in replication, snapshots, and encryption
     - **OpenEBS:** Open-source storage for Kubernetes with multiple storage engines
     - **Longhorn:** Lightweight distributed block storage system by Rancher
     - Traditional arrays: Pure Storage FlashArray, NetApp ONTAP SAN
   - Recommended for: PostgreSQL, MySQL, MongoDB, message queues
   - Applications using this type tend to have there own replications that handle zone and region replication.

2. *File Storage:*
   - Supports ReadWriteMany (RWX) for shared access across pods
   - Good for moderate performance requirements
   - Can span zones but may introduce latency
   - Solutions:
     - **Rook-Ceph:** Provides CephFS for distributed file storage
     - **OpenEBS:** Supports NFS provisioner
     - Traditional NAS: NetApp ONTAP NAS, Pure FlashBlade
   - Recommended for: Web content, shared application data, development tools
   - Most applcations using this type do not need to be shared across zones, if they do they should be using a shared storage solution that is zone aware.

3. *Object Storage:*
   - Highly scalable across zones
   - Built-in replication and data protection
   - Accessed via S3-compatible API
   - Solutions:
     - **Rook-Ceph:** Provides Ceph RADOS Gateway (RGW) for S3-compatible storage
     - **MinIO:** Distributed object storage designed for high performance
     - **OpenEBS:** Can be used with MinIO for persistent storage
   - Best for: Backups, archives, static assets, ML training data, Batch processing, and other workloads.
   - Region and zone replication is handled by the object storage solution.

Software-defined storage solutions like Portworx, Rook-Ceph, and Longhorn are particularly well-suited for Kubernetes environments as they:

- Provide native integration with Kubernetes
- Support multi-zone deployments out of the box
- Offer built-in replication and failover
- Can be managed using Kubernetes-native tools

For multi-zone resilience, block storage solutions like Portworx or Rook-Ceph with synchronous replication typically provide the best balance of performance and data protection. File storage should be zone-local to avoid latency issues. Object storage naturally handles multi-zone deployments through its distributed architecture.

We need to make sure customers are following these best practices:

- Always align storage provisioning with the physical location of compute to minimize latency and avoid cross-zone traffic.
- Use topology-aware StorageClasses and ensure CSI drivers are configured for zone awareness.
- Document and regularly review the mapping between physical infrastructure and logical zones.
- Integrate storage monitoring with cluster monitoring (e.g., Prometheus, Grafana) for unified visibility.

### Cost, Compliance, and Operational Considerations

- *Total Cost of Ownership (TCO):* Consider both initial hardware/software investments and long-term operational costs, including maintenance, power, cooling, and staff expertise. Automation and efficient management can reduce long-term TCO.
- *Compliance:* Ensure storage solutions meet regulatory requirements (e.g., GDPR, HIPAA, PCI DSS) for data protection, retention, and auditability. On-premises deployments may offer more direct control over compliance but require diligent management.
- *Operational Overhead:* On-premises solutions require ongoing maintenance, upgrades, and monitoring. Evaluate the impact on IT staff and the need for specialized skills.
- *Scalability:* Plan for future growth in storage needs, considering the scalability limitations of on-premises hardware and the potential need for hardware refresh cycles.

### See Also

For cloud-native storage strategies, see [CloudStorageStrategy.md](CloudStorageStrategy.md).

---

*TODO: Add diagrams illustrating physical-to-logical zone mapping and storage/data flow.
