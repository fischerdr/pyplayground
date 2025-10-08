# AWX Large Scale Configuration Guide

This document outlines the configuration settings for running AWX at scale, specifically designed for environments with 500+ hosts, 1000+ templates, and 100+ projects.

## Table of Contents

1. [Resource Requirements](#resource-requirements)
2. [PostgreSQL Configuration](#postgresql-configuration)
3. [High Availability](#high-availability)
4. [Monitoring and Logging](#monitoring-and-logging)
5. [Security Settings](#security-settings)
6. [Container and Instance Groups](#container-and-instance-groups)
7. [Performance Tuning](#performance-tuning-awx-instanceyml)
8. [Storage Configuration](#storage-configuration)
9. [OpenShift Integration](#openshift-integration)
10. [Capacity Management](#capacity-management)
11. [Backup Configuration](#backup-configuration)
12. [Grafana Dashboard](#grafana-dashboard)

## Resource Requirements

### Task Pod Resources

```yaml
task_resource_requirements:
  requests:
    cpu: "1000m"    # 1 CPU core minimum
    memory: "4Gi"   # 4GB RAM minimum
  limits:
    cpu: "2000m"    # 2 CPU cores maximum
    memory: "8Gi"   # 8GB RAM maximum
```

**Purpose**: Task pods handle job execution. These resources ensure:

- Sufficient CPU for concurrent job execution
- Adequate memory for large playbook runs
- Resource limits prevent pod from consuming excessive resources

### Web Pod Resources

```yaml
web_resource_requirements:
  requests:
    cpu: "1000m"    # 1 CPU core minimum
    memory: "2Gi"   # 2GB RAM minimum
  limits:
    cpu: "2000m"    # 2 CPU cores maximum
    memory: "4Gi"   # 4GB RAM maximum
```

**Purpose**: Web pods handle UI/API requests. These resources ensure:

- Responsive web interface
- Efficient API handling
- Support for multiple concurrent users

### PostgreSQL Resources

```yaml
postgres_resource_requirements:
  requests:
    cpu: "1000m"    # 1 CPU core minimum
    memory: "4Gi"   # 4GB RAM minimum
  limits:
    cpu: "2000m"    # 2 CPU cores maximum
    memory: "8Gi"   # 8GB RAM maximum
```

**Purpose**: Database performance optimization for:

- Large number of concurrent connections
- Complex queries
- Efficient data storage and retrieval

## PostgreSQL Configuration

### Performance Tuning postgres extra args

```yaml
postgres_extra_args:
  - 'max_connections=1000'      # Maximum concurrent connections
  - 'shared_buffers=2GB'        # Memory for caching data
  - 'work_mem=64MB'            # Memory for complex operations
  - 'maintenance_work_mem=256MB' # Memory for maintenance tasks
  - 'effective_cache_size=6GB'  # Estimated available system memory
  - 'max_worker_processes=8'    # Parallel query workers
  - 'max_parallel_workers=8'    # Maximum parallel workers
  - 'max_parallel_workers_per_gather=4' # Workers per gather operation
```

**Purpose**: Optimize PostgreSQL for:

- High concurrency
- Complex queries
- Efficient data processing
- Parallel operations

## High Availability

### HA Configuration

```yaml
ha_enabled: true
ha_replicas: 2
pod_disruption_budget:
  minAvailable: 1
  maxUnavailable: 1
```

**Purpose**: Ensure:

- Service availability
- Zero-downtime updates
- Load distribution

### Pod Anti-Affinity

```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values:
            - awx
        topologyKey: kubernetes.io/hostname
```

**Purpose**: Distribute pods across nodes for:

- Better availability
- Resource utilization
- Failure isolation

## Monitoring and Logging

### Metrics Configuration

```yaml
metrics_enabled: true
metrics_port: 9090
metrics_path: /metrics
```

**Purpose**: Enable:

- Performance monitoring
- Resource utilization tracking
- Health checks

### Logging Configuration

```yaml
logging_configuration:
  level: INFO
  handlers:
    - type: file
      filename: /var/log/awx/awx.log
      maxBytes: 10485760
      backupCount: 5
```

**Purpose**: Manage logs for:

- Troubleshooting
- Audit trails
- Performance analysis

### Prometheus Integration

```yaml
monitoring:
  prometheus:
    serviceMonitor:
      enabled: true
      interval: 30s
      scrapeTimeout: 10s
      namespaceSelector:
        matchNames:
          - monitoring
      selector:
        matchLabels:
          app.kubernetes.io/name: awx
      endpoints:
        - port: metrics
          path: /metrics
          scheme: https
          tlsConfig:
            insecureSkipVerify: true
```

### Grafana Dashboard

A comprehensive Grafana dashboard has been configured at `config/awx/monitoring/grafana-dashboard-awx.json`. The dashboard includes:

1. **Job Events Rate**
   - Tracks rate of job events over time
   - Breaks down by status
   - Helps monitor automation activity

2. **Job Status Distribution**
   - Shows total jobs by status
   - Identifies success/failure trends
   - Provides historical data

3. **Job Success Rate**
   - Gauge panel showing successful job percentage
   - Visual status indicator
   - Configurable thresholds

4. **Job Duration (95th Percentile)**
   - Performance monitoring
   - Execution time tracking
   - Helps identify bottlenecks

5. **Inventory Sync Rate**
   - Monitors inventory synchronization
   - Tracks sync status
   - Infrastructure change monitoring

6. **Project Update Rate**
   - Source control integration monitoring
   - Update success/failure tracking
   - Project synchronization status

Dashboard Features:

- 10-second refresh rate
- 6-hour default time range
- Dark theme
- Interactive tooltips
- Responsive layout
- Tagged for easy categorization

To use the dashboard:

1. Import the JSON configuration into Grafana
2. Configure the Prometheus data source
3. Adjust time ranges and refresh rates as needed
4. Set up alerts based on thresholds

## Security Settings

### Security Context

```yaml
security_context_settings:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
```

**Purpose**: Ensure:

- Proper file permissions
- Security isolation
- Compliance requirements

### Network Policies

```yaml
network_policy:
  ingress:
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: awx
  egress:
    - to:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: awx
```

**Purpose**: Control:

- Pod-to-pod communication
- Network isolation
- Security boundaries

## Container and Instance Groups

### Container Groups

```yaml
container_groups:
  - name: "default"
    credential: "k8s-credential"
    pod_spec_override:
      spec:
        containers:
          - name: "worker"
            resources:
              requests:
                cpu: "1000m"
                memory: "2Gi"
              limits:
                cpu: "2000m"
                memory: "4Gi"
```

**Purpose**: Manage:

- Worker pod resources
- Execution environments
- Job distribution

### Instance Groups

```yaml
instance_groups:
  - name: "default"
    policy_instance_minimum: 1
    policy_instance_percentage: 100
```

**Purpose**: Control:

- Job distribution
- Resource allocation
- Scaling behavior

## Performance Tuning (awx-instance.yml)

### Task Management

```yaml
extra_settings:
  - setting: AWX_TASK_LAUNCH_TIMEOUT
    value: "600"
  - setting: AWX_TASK_LAUNCH_RETRY_COUNT
    value: "3"
  - setting: AWX_TASK_LAUNCH_RETRY_DELAY
    value: "30"
```

**Purpose**: Optimize:

- Job execution
- Error handling
- Resource utilization

### Event Processing

```yaml
extra_settings:
  - setting: JOB_EVENT_WORKERS
    value: "8"
  - setting: MAX_UI_JOB_EVENTS
    value: "4000"
  - setting: MAX_EVENT_RES_DATA
    value: "700000"
```

**Purpose**: Manage:

- Event processing
- UI performance
- Data handling

## Storage Configuration

### Storage Requirements

```yaml
projects_storage_size: 20Gi    # For 100+ projects
postgres_storage_size: 50Gi    # For large database
redis_storage_size: 4Gi        # For job queue
```

**Purpose**: Ensure sufficient storage for:

- Project files
- Database data
- Job queue management

## OpenShift Integration

### Route Configuration

```yaml
service_type: ClusterIP
ingress_type: Route
```

**Purpose**: Enable:

- OpenShift routing
- External access
- Load balancing

## Capacity Management

### Auto-scaling

```yaml
capacity_adjustment:
  min_capacity: 1
  max_capacity: 10
  scale_up_threshold: 80
  scale_down_threshold: 20
```

**Purpose**: Automate:

- Resource scaling
- Load management
- Cost optimization

## Backup Configuration

### Automated Backups

```yaml
backup_configuration:
  enabled: true
  schedule: "0 0 * * *"  # Daily at midnight
  retention: 7  # Keep backups for 7 days
  storage_class: "standard"
  storage_size: "10Gi"
  backup_command: |
    pg_dump -h ${POSTGRES_HOST} -U ${POSTGRES_USER} -d ${POSTGRES_DB} -F c -b -v -f /backup/awx-$(date +%Y%m%d-%H%M%S).backup
```

## Best Practices

1. **Regular Monitoring**
   - Monitor resource usage
   - Track performance metrics
   - Review logs regularly

2. **Backup Strategy**
   - Regular database backups
   - Configuration backups
   - Disaster recovery plan

3. **Security Updates**
   - Regular security patches
   - Access control reviews
   - Network policy audits

4. **Performance Optimization**
   - Regular performance reviews
   - Resource utilization analysis
   - Configuration tuning

## Troubleshooting

### Common Issues and Solutions

1. **High Job Failure Rate**
   - Check job success rate in Grafana dashboard
   - Review job duration metrics
   - Verify resource availability

2. **Slow Performance**
   - Monitor job duration percentiles
   - Check PostgreSQL performance metrics
   - Review resource utilization

3. **Inventory Sync Issues**
   - Check inventory sync rate in dashboard
   - Verify network connectivity
   - Review sync logs

4. **Project Update Failures**
   - Monitor project update rate
   - Check source control connectivity
   - Review update logs

### Monitoring Alerts

Set up alerts in Grafana for:

- Job success rate below 95%
- Job duration above 95th percentile
- High inventory sync failure rate
- Project update failures
- Resource utilization above 80%

## References

- [AWX Documentation](https://docs.ansible.com/ansible-tower/latest/html/administration/index.html)
- [PostgreSQL Tuning](https://www.postgresql.org/docs/current/runtime-config-resource.html)
- [OpenShift Documentation](https://docs.openshift.com/)
