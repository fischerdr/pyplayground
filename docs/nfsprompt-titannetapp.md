
## Questions and Responses


**What is the logical flow of communication between NetApp Trident and the Kubernetes cluster using CSI and NFS? What networking and firewall configurations are required for high availability?**

**Is there a need for a dedicated network connection to the worker nodes (e.g., a separate VLAN or NIC) to allow storage access outside of routed networks and avoid firewalls?**

**What are the failover options if NFS is served through the frontend interface on worker nodes, and how does this impact cross-zone availability?**

**Is the VLAN carrying the NFS export required to be accessible by the Kubernetes worker nodes? Is the NFS IP dynamically assigned to the nodes?**

### ✅ Response

- Explained separation between **control plane** (PVC provisioning via Trident API) and **data plane** (NFS mounts to nodes).
- Control plane requires outbound HTTPS to Trident API (port 443).
- Data plane requires Kubernetes worker nodes to access Trident NFS endpoints over TCP 2049.
- Firewalls must allow bidirectional access from nodes to Trident NFS IPs.
- DNS resolution must be stable for Trident endpoints.

---
### ✅ Response:
- Described two architectural options:
  - **Routed Access:** Default and preferred in most environments.
  - **Dedicated Storage VLAN:** Valid for on-prem setups with multi-homed nodes and strict isolation.
- Noted that Kubernetes does not natively support multi-interface mount logic.
- Advised only using storage VLANs if custom routing or binding is configured on the nodes.

---

### ✅ Response

- Clarified that NFS does not support multipathing or native failover.
- Recommended using **zone-local Trident NFS endpoints** and **CSI topology awareness** to bind PVCs to nodes within the same zone.
- Described limitations of cross-zone failover without data replication or manually re-provisioned PVCs.
- Emphasized need for Trident support for **HA frontends or replication** if failover across zones is a requirement.

---
### ✅ Response

- Confirmed that NFS IPs are **not dynamically assigned** to nodes.
- The nodes initiate NFS mount requests using their default routing interface unless explicitly configured.
- The NFS VLAN or subnet must be **reachable from the worker nodes** via routed paths or dedicated interfaces.
- Trident does not perform interface injection or dynamic mount targeting.

###