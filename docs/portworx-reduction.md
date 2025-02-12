# Reducing the Footprint of Portworx Enterprise in OpenShift Deployments

## 1. Executive Summary

This document outlines a strategic approach to reducing the resource footprint of Portworx Enterprise within OpenShift deployments. The focus is on enhancing performance, optimizing resource allocation, and ensuring scalability to meet evolving customer demands.

### Key Initiatives

* Refactoring Helm charts for efficient node scheduling
* Reorganizing OpenShift deployments to target specific ESXi hosts
* Optimizing the decision engine for intelligent workload placement
* Establishing a robust monitoring framework

### Expected Benefits

* 30-40% reduction in resource utilization
* Improved data locality and performance
* Enhanced operational resilience
* Better capacity planning and forecasting

### Timeline and Resources

* Implementation Duration: 8 months
* Required Teams: Platform, Storage, Operations
* Key Stakeholders: Infrastructure, Development, Operations

## 2. Introduction / Background

Portworx Enterprise plays a critical role in managing persistent storage for OpenShift clusters. However, as the scale of deployments grows, inefficiencies in resource usage, data distribution, and workload placement have emerged. This document addresses these challenges, focusing on reducing unnecessary overhead, improving data locality, and enhancing operational resilience across ESXi-backed OpenShift environments.

### Current Challenges

* Resource inefficiency with Portworx running on nodes without storage workloads
* Data redundancy gaps due to non-optimized zone configurations
* Inconsistent workload placement across clusters, leading to resource fragmentation
* Limited visibility into capacity trends, making future scaling unpredictable

### Technical Environment

* Portworx Enterprise: 3.2.1.1 or later
* OpenShift: 4.14 or later
* VMware ESXi: 7.0 U3 or later
* Minimum Node Requirements:
  * CPU: 32 cores
  * Memory: 192GB RAM
  * Storage: 50TB NVMe storage per node

## 3. Scope and Assumptions

### Scope

* Applies to all OpenShift clusters deployed on ESXi infrastructure
* Focus on clusters managed via IPI (Installer-Provisioned Infrastructure)
* Portworx zonal configurations for environments with multiple ESXi clusters

### Assumptions

* All ESXi hosts can be labeled and grouped based on storage capabilities
* OpenShift IPI configurations can be modified without vendor constraints
* Portworx metrics are available for integration with the monitoring stack

### Prerequisites

* Administrative access to OpenShift clusters
* VMware vSphere privileges for resource pool management
* Network connectivity between all components
* Prometheus and Grafana deployed in the cluster

## 4. Goals and Success Metrics

### Objectives

* Reduce Portworx resource consumption across non-storage nodes
* Improve data resiliency through optimized multi-zone replication
* Ensure customer workloads are intelligently routed based on storage needs
* Proactively predict capacity requirements to prevent resource bottlenecks

### Key Metrics

* Resource Efficiency: Reduction in CPU/memory usage for Portworx services
* Deployment Accuracy: % of workloads placed correctly based on storage needs
* Data Resiliency: Improved RTO (Recovery Time Objective) with zonal replication
* Capacity Forecasting Accuracy: Prediction variance within acceptable thresholds (<5%)

## 5. Key Initiatives

### 5.1 Refactoring Helm Charts with Affinity and Anti-Affinity Rules

#### Objective

Optimize Portworx deployments to run exclusively on storage-enabled nodes using Kubernetes affinity/anti-affinity rules.

#### Implementation

**Node Labeling:**

```bash
oc label node <node-name> storage=enabled
```

**Helm Chart Modifications:**

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: storage
              operator: In
              values:
                - enabled
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: app
              operator: In
              values:
                - portworx
        topologyKey: "kubernetes.io/hostname"
```

#### Expected Impact

* Reduced resource consumption on non-storage nodes
* Improved workload performance through optimal data locality

### 5.2 Reorganizing OpenShift Deployments for Targeted Portworx Utilization

#### Objective

Ensure Portworx operates only on designated ESXi hosts with local storage, while OpenShift IPI deployments land worker nodes on these hosts. Implement a zonal model for data distribution across ESXi clusters.

#### Implementation

**VM Placement (vSphere):**
Configure VM affinity rules to target specific ESXi hosts with local disks.

**OpenShift IPI Customization:**

```yaml
spec:
  providerSpec:
    value:
      placement:
        resourcePool: /Datacenter/host/Cluster/Resources/StoragePool
        hosts:
          - esxi-01.local
          - esxi-02.local
```

**Portworx Zonal Model:**

Node Labeling:

```bash
oc label node worker-1 topology.portworx.io/zone=zone-a
oc label node worker-2 topology.portworx.io/zone=zone-b
```

Cluster Configuration:

```yaml
spec:
  storageCluster:
    spec:
      placement:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.portworx.io/zone
                    operator: In
                    values:
                      - zone-a
                      - zone-b
```

#### Expected Impact

* Focused Portworx utilization on storage-optimized infrastructure
* Enhanced data resilience with cross-cluster replication

### 5.3 Optimizing the Decision Engine for Intelligent Cluster Placement

#### Objective

Enhance the decision engine to route customer deployments based on storage requirements and real-time cluster capacity.

#### Predictive Analytics

* Use historical data for capacity forecasting, integrating with Prometheus metrics

#### Expected Impact

* Optimal resource allocation with reduced deployment delays
* Data-driven placement decisions improving workload performance

### 5.4 Monitoring and Analyzing Capacity and Performance

#### Objective

Implement a comprehensive monitoring framework to track capacity and performance, enabling proactive scaling and resource planning.

#### Implementation

**Monitoring Stack:**

* Prometheus: For metric collection
* Grafana: For visualization
* Portworx Metrics: For storage performance tracking

**Key Metrics to Monitor:**

* Resource Utilization
  * `portworx_cluster_disk_utilized_bytes`
  * `portworx_cluster_disk_available_bytes`
  * `portworx_node_cpu_usage_percent`
  * `portworx_node_memory_usage_bytes`

* Worker Node Metrics
  * `container_cpu_usage_seconds_total{container!="",pod!=""}`
  * `container_memory_usage_bytes{container!="",pod!=""}`
  * `node_cpu_seconds_total{mode="idle"}`
  * `node_memory_MemAvailable_bytes`
  * `node_memory_MemTotal_bytes`
  * `kubelet_volume_stats_used_bytes`
  * `kubelet_volume_stats_capacity_bytes`

* vSphere ESXi Metrics (via vSphere Exporter)
  * Cluster Metrics
    * `vsphere_cluster_cpu_usage_percent`
    * `vsphere_cluster_mem_usage_percent`
    * `vsphere_cluster_cpu_total_mhz`
    * `vsphere_cluster_mem_total_mb`
    * `vsphere_cluster_vm_count`
  * Host Metrics
    * `vsphere_host_cpu_usage_percent{host="esxi-host"}`
    * `vsphere_host_memory_usage_percent{host="esxi-host"}`
    * `vsphere_host_memory_size_bytes{host="esxi-host"}`
    * `vsphere_host_cpu_mhz{host="esxi-host"}`
  * Datastore Metrics
    * `vsphere_datastore_capacity_size{datastore="name"}`
    * `vsphere_datastore_freespace_size{datastore="name"}`
    * `vsphere_datastore_uncommitted_size{datastore="name"}`

* Performance Metrics
  * `portworx_disk_ops_total`
  * `portworx_disk_read_latency_seconds`
  * `portworx_disk_write_latency_seconds`
  * `portworx_volume_iops`

* Health Metrics
  * `portworx_cluster_status`
  * `portworx_node_status`
  * `portworx_volume_ha_level`

**Example Grafana Dashboard:**

```yaml
dashboard:
  title: "Portworx Cluster Overview"
  panels:
    - title: "Cluster Storage Utilization"
      type: "graph"
      metrics:
        - expr: "sum(portworx_cluster_disk_utilized_bytes) / sum(portworx_cluster_disk_available_bytes) * 100"
    
    - title: "Node CPU Usage"
      type: "graph"
      metrics:
        - expr: "avg(portworx_node_cpu_usage_percent) by (node)"
    
    - title: "Worker Node CPU Usage"
      type: "graph"
      metrics:
        - expr: "sum(rate(container_cpu_usage_seconds_total{container!=''}[5m])) by (node) / on(node) sum(machine_cpu_cores) by (node) * 100"
    
    - title: "Worker Node Memory Usage"
      type: "graph"
      metrics:
        - expr: "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100"
    
    - title: "ESXi Cluster Resource Usage"
      type: "graph"
      metrics:
        - expr: "avg(vsphere_cluster_cpu_usage_percent)"
        - expr: "avg(vsphere_cluster_mem_usage_percent)"
    
    - title: "ESXi Host Resource Usage"
      type: "graph"
      metrics:
        - expr: "avg(vsphere_host_cpu_usage_percent) by (host)"
        - expr: "avg(vsphere_host_memory_usage_percent) by (host)"
    
    - title: "Datastore Utilization"
      type: "graph"
      metrics:
        - expr: "(vsphere_datastore_capacity_size - vsphere_datastore_freespace_size) / vsphere_datastore_capacity_size * 100"
```

**Automated Alerts:**

```yaml
groups:
  - name: capacity-alerts
    rules:
      - alert: HighCPUUsage
        expr: sum(rate(container_cpu_usage_seconds_total[5m])) by (instance) > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage detected on {{ $labels.instance }}"
      
      - alert: StorageUtilizationHigh
        expr: sum(portworx_cluster_disk_utilized_bytes) / sum(portworx_cluster_disk_available_bytes) * 100 > 80
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Storage utilization exceeds 80%"
      
      - alert: HighLatency
        expr: avg(portworx_disk_write_latency_seconds) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High storage latency detected"

      - alert: WorkerNodeHighCPU
        expr: sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (node) / on(node) sum(machine_cpu_cores) by (node) * 100 > 85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Worker node CPU usage exceeds 85% on {{ $labels.node }}"

      - alert: WorkerNodeHighMemory
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Worker node memory usage exceeds 90% on {{ $labels.node }}"

      - alert: ESXiClusterHighCPU
        expr: avg(vsphere_cluster_cpu_usage_percent) > 80
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "ESXi cluster CPU usage exceeds 80%"

      - alert: ESXiClusterHighMemory
        expr: avg(vsphere_cluster_mem_usage_percent) > 85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "ESXi cluster memory usage exceeds 85%"

      - alert: DatastoreSpaceCritical
        expr: (vsphere_datastore_capacity_size - vsphere_datastore_freespace_size) / vsphere_datastore_capacity_size * 100 > 85
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Datastore {{ $labels.datastore }} usage exceeds 85%"
```
### Capacity Forecasting
Apply machine learning models to predict future resource requirements based on historical metrics:

* Storage Growth Prediction

* Resource Trend Analysis
  * Use historical data from Prometheus for:
    * Storage utilization trends
    * CPU/Memory usage patterns
    * Workload growth patterns
    * ESXi cluster resource consumption

* Capacity Planning Metrics
  * Growth rate per resource type
  * Seasonal patterns identification
  * Resource exhaustion predictions
  * Recommended scaling thresholds

#### Expected Impact

* Real-time insights into system health and capacity
* Proactive capacity planning to support future growth
* Early warning system for resource constraints
* Data-driven infrastructure scaling decisions

## 6. Technical Architecture Overview

* Current vs. Target Architecture Diagrams (to be created)
* Data flow between OpenShift, Portworx, ESXi, and the decision engine

## 7. Implementation Roadmap

* Phase 1: Refactor Helm Charts (Month 1-2)
* Phase 2: Reorganize OpenShift Deployments (Month 3-4)
* Phase 3: Enhance Decision Engine (Month 5-6)
* Phase 4: Implement Monitoring & Forecasting (Month 7-8)

## 8. Risk Assessment and Mitigation

* Data Locality Issues: Mitigated through rigorous zone tagging validation
* Capacity Misalignment: Continuous integration with monitoring feedback loops
* Operational Disruptions: Change management protocols and staged rollouts

## 9. Operational Considerations

* Day-2 operations adjustments for monitoring and troubleshooting
* Backup and DR implications with zonal data distribution
* Training and documentation for operations teams

## 10. Cost and Resource Analysis

* Potential cost savings through resource optimization
* Resource investments needed for implementation (tooling, training)

## 11. Future Considerations / Continuous Improvement

* Scaling to multi-cloud environments
* Integrating with automation tools like Ansible and Terraform
* Continuous optimization based on performance data

### Advanced Storage Optimization

#### Intelligent Tiering

* What to Consider: Implement dynamic storage tiering within Portworx to automatically move less frequently accessed data to lower-cost storage (e.g., cold storage on slower disks)
* Impact: Reduces storage costs while maintaining high performance for critical workloads

#### Volume Placement Strategies

* What to Consider: Leverage Portworx Autopilot rules for dynamic resizing and optimizing volume placement based on IOPS and latency thresholds
* Impact: Enhances performance efficiency without manual intervention

### Enhancements in the Decision Engine

#### AI-Driven Placement Algorithms

* What to Consider: Introduce machine learning algorithms that not only factor in current resource utilization but also predict future workload demands
* Impact: Proactively optimizes workload distribution to prevent bottlenecks before they occur

#### Policy-Based Governance

* What to Consider: Integrate governance policies for data residency, compliance, and workload affinity rules directly into the decision engine
* Impact: Ensures workloads meet both technical and regulatory requirements automatically

### Resilience and Disaster Recovery (DR)

#### Cross-Cluster Failover Automation

* What to Consider: Implement Portworx Disaster Recovery (PX-DR) with automated failover between OpenShift clusters across different ESXi hosts or even data centers
* Impact: Enhances business continuity with near-zero downtime in case of catastrophic failures

#### Chaos Engineering for Storage

* What to Consider: Incorporate chaos testing (e.g., using tools like LitmusChaos) to simulate storage failures, network partitions, and node crashes regularly
* Impact: Validates system resilience under extreme conditions, ensuring reliability

### Observability & Predictive Insights

#### Enhanced SLOs and Error Budgets

* What to Consider: Define Service Level Objectives (SLOs) with error budgets for storage latency, availability, and performance, integrated into Grafana dashboards
* Impact: Provides proactive indicators of performance degradation before they breach SLAs

#### Predictive Analytics

* What to Consider: Expand Prometheus with AI-based analytics to forecast capacity and performance anomalies before they occur, using historical data trends
* Impact: Moves from reactive monitoring to proactive operations

## 12. Conclusion

This strategic approach will reduce Portworx’s resource footprint, enhance workload placement efficiency, and improve system resiliency. The initiatives will ensure that OpenShift environments remain scalable, cost-effective, and ready for future demands.

## 13. Troubleshooting Guide

### Common Issues and Solutions

1. **Node Scheduling Issues**
   * Symptom: Pods not scheduling on storage nodes
   * Solution: Verify node labels and taints
   * Validation: `oc get nodes --show-labels`

2. **Performance Degradation**
   * Symptom: High latency in storage operations
   * Solution: Check network connectivity and storage device health
   * Validation: Review Prometheus metrics

3. **Replication Issues**
   * Symptom: Volumes not maintaining HA level
   * Solution: Verify zone configuration and network connectivity
   * Validation: `pxctl status`

### Rollback Procedures

1. **Zone Configuration**
   * Backup current configuration
   * Restore previous zone labels
   * Verify volume distribution

## 14. References

### Documentation

* [Portworx Documentation](https://docs.portworx.com/)
* [OpenShift Documentation](https://docs.openshift.com/)
* [VMware ESXi Documentation](https://docs.vmware.com/en/VMware-vSphere/)

### Tools and Utilities

* [Prometheus Operator](https://github.com/prometheus-operator/prometheus-operator)
* [Grafana Dashboards](https://grafana.com/grafana/dashboards/)
* [PX-Backup](https://docs.portworx.com/reference/px-backup/)

### Best Practices

* [Kubernetes Storage Best Practices](https://kubernetes.io/docs/concepts/storage/)
* [OpenShift Scaling and Performance](https://docs.openshift.com/container-platform/latest/scalability_and_performance/recommended-host-practices.html)
* [Portworx Deployment Best Practices](https://docs.portworx.com/operations/operate-kubernetes/)
