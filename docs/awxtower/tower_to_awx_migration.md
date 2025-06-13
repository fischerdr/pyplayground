# Migration Plan: Red Hat Ansible Tower (RHEL7) to AWX on Kubernetes

## Table of Contents

1. [Purpose and Scope](#purpose-and-scope)
2. [Current vs Target Environment](#current-vs-target-environment)
3. [Migration Phases](#migration-phases)
   - 5.1 [Phase 1: Assessment and Planning](#phase-1-assessment-and-planning)
   - 5.2 [Phase 2: Preparation](#phase-2-preparation)
   - 5.3 [Phase 3: Deployment of AWX Operator](#phase-3-deployment-of-awx-operator)
   - 5.4 [Phase 4: Data and Configuration Migration](#phase-4-data-and-configuration-migration)
   - 5.5 [Phase 5: Validation and Testing](#phase-5-validation-and-testing)
   - 5.6 [Phase 6: Cutover and Go-Live](#phase-6-cutover-and-go-live)
   - 5.7 [Phase 7: Post-Migration Review and Optimization](#phase-7-post-migration-review-and-optimization)
4. [Rollback and Contingency Plans](#rollback-and-contingency-plans)
5. [Appendices](#appendices)

---

## Purpose and Scope

This document outlines the plan for migrating our existing Red Hat Ansible Tower system (running on RHEL7) to an AWX installation managed by the AWX Operator on our Kubernetes orchestration cluster. It covers the end-to-end process, including assessment, preparation, deployment, data migration, validation, and cutover.

## Current vs Target Environment

| Current Environment                                       | Target Environment                                              |
| --------------------------------------------------------- | --------------------------------------------------------------- |
| **Platform**: RHEL7                                       | **Platform**: Kubernetes (OpenShift or upstream) cluster        |
| **Tower Version**: 3.8.5                                  | **AWX Operator Version**: [Planned Operator Version]            |
| **Inventories/Hosts**: 25 inventories / \~450 hosts       | **AWX Version**: [Planned AWX Release]                          |
| **Projects**: 35 (Git-based + manual)                     | **Storage**: PVCs for projects, database, Redis                 |
| **Job Templates**: 180 (incl. 20 workflows)               | **Ingress**: OpenShift Route or Kubernetes Ingress              |
| **Credentials**: SSH keys, Vault secrets, AWS/Azure creds | **Registry**: Internal container registry for air-gapped images |
| **Kubeconfig Mgmt**: Local kubeconfig files on Tower host | **Authentication**: LDAP/AD via AWX SSO integrations            |
| **Vault Integration**: Vault Agent on Tower host          | **Backup Strategy**: Snapshot PVCs, database dumps              |
| **Database**: Embedded PostgreSQL                         |                                                                 |
| **Authentication**: LDAP/AD                               |                                                                 |
| **Backup Frequency**: Daily DB and file-system backups    |                                                                 |

## Migration Phases

### Phase 1: Assessment and Planning

- Inventory existing Tower objects:
  - Projects, inventories, hosts, credentials, job templates, workflows, schedule
- Identify custom scripts, notifications, and callbacks
- Review integration points (SLACK, email, cloud)
- Define success criteria and rollback triggers

**Deliverables**: Assessment report, inventory spreadsheet, risk log

### Phase 2: Preparation

- Provision Kubernetes namespace/project (e.g., `awx`)
- Configure persistent storage (PVCs) and storage classes
- Mirror required container images (
  - `awx-operator`, `awx`, `postgres`, `redis`, custom EE and init images )
- Create image pull secrets for registry
- Configure network:
  - Use OpenShift Routes for AWX external access
  - Two options to have a moniker-style URL
    - Integrate with existing GTM (Global Traffic Manager), LTM (Local Traffic Manager), and GlueMesh Istio sidecars to resolve moniker‑style URLs to cluster endpoints
    - Manually manage SSL certificates by importing them into OpenShift ingress controller secrets.
    - Ensure DNS entries for moniker URLs point to GTM/LTM IPs, which route through Istio sidecars into the cluster
- Set up RBAC and service accounts

**Deliverables**: Kubernetes environment ready checklist

### Phase 3: Deployment of AWX Operator

- Install AWX Operator via OLM or `oc apply`
- Verify Operator logs and CRD availability
- Create AWX Custom Resource (CR) with base configuration
- Wait for AWX pods (web, task, redis, postgres) to become ready

**Deliverables**: Running AWX instance on Kubernetes

### Phase 4: Data and Configuration Migration

For each sub-step, use the Python scripts in Appendix A to automate export, backup, and import tasks.

1. **Credentials & Secrets**:

   - Run `tower_export_credentials.py` to export Tower credentials to JSON.
   - Load secrets into Kubernetes with `kubectl create secret` or AWX CLI.
   - Run `awx_import_credentials.py` to import credentials into AWX.

2. **Projects**:

   - Run `tower_export_projects.py` to archive manual and Git project definitions.
   - Sync Git repos to project PVC.
   - Use `awx_import_projects.py` to register projects in AWX via API.

3. **Inventory & Hosts**:

   - Run `tower_export_inventory.py` to dump inventories and hosts to JSON.
   - Run `awx_import_inventory.py` to recreate inventories and hosts in AWX.

4. **Job Templates & Workflows**:

   - Run `tower_export_job_templates.py` to export job templates and workflows.
   - Run `awx_import_job_templates.py` to import and link templates in AWX.

5. **Schedules & Notifications**:

   - Run `tower_export_schedules.py` to export schedules.
   - Run `awx_import_schedules.py` to reapply schedules and notification templates.

**Deliverables**: Configuration parity between Tower and AWX

### Phase 5: Validation and Testing

- **Smoke Tests**: Launch sample jobs for each template
- **Integration Tests**: Verify external integrations (LDAP, cloud credentials)
- **Performance Tests**: Run load tests on multiple concurrent jobs
- **Security Review**: Validate network policies, secrets encryption

**Deliverables**: Test report with pass/fail status

### Phase 6: Cutover and Go-Live

- Schedule downtime window if needed
- Disable new job triggers in legacy Tower
- Final sync of changed inventories/projects
- Switch DNS/Ingress to point to AWX
- Enable job schedules in AWX
- Monitor job execution and logs

**Deliverables**: Successful cutover and production job runs

### Phase 7: Post-Migration Review and Optimization

- Collect feedback from stakeholders
- Tune resource requests/limits, horizontal scaling
- Document lessons learned and update runbooks
- Plan regular backup and upgrade procedures

**Deliverables**: Final migration report, updated documentation

## Rollback and Contingency Plans

- Re-enable Tower if AWX issues occur
- Use Tower backups for quick recovery
- Maintain dual-run period for critical jobs (optional)
- Define escalation path and communication plan

## Appendices

### Appendix A: Migration Scripts

The following scripts are available in the `/awxtower` directory to automate the migration process:

#### Export Scripts (Tower to JSON)

- `tower_export_credentials.py`: Exports Tower credentials to JSON
- `tower_export_projects.py`: Exports Tower project definitions to JSON
- `tower_export_inventory.py`: Exports Tower inventories and hosts to JSON
- `tower_export_job_templates.py`: Exports Tower job templates and workflows to JSON
- `tower_export_schedules.py`: Exports Tower schedules and notifications to JSON

#### Import Scripts (JSON to AWX)

- `awx_import_credentials.py`: Imports credentials JSON into AWX
- `awx_import_projects.py`: Imports project definitions into AWX
- `awx_import_inventory.py`: Imports inventories and hosts JSON into AWX
- `awx_import_job_templates.py`: Imports job templates and workflows into AWX
- `awx_import_schedules.py`: Imports schedules and notification templates into AWX

#### Additional Utilities

- `download_awx_images.py`: Downloads required container images for AWX deployment
- `run_template_restapi.py`: Example of using AWX REST API to run job templates

Each script uses the `awxkit` library and includes proper error handling, logging, and progress tracking. The scripts are designed to be run in sequence as part of the migration process.

### Appendix B: Custom Dockerfiles for EE and Init Images

- EE: config/awx/Dockerfile
- Init: config/awx/init/Dockerfile

### Appendix C: Backup and Restore Commands

- Docs awx_large_scale_configuration.md

### Appendix E: AWX CLI Examples

The following examples demonstrate common AWX CLI operations using `awxkit`. These examples can be used for automation, troubleshooting, and management tasks.

#### Basic Authentication and Connection

```python
from awxkit import awx

# Connect to AWX instance
awx = awx.AWX(host='https://awx.example.com', username='admin', password='password')

# Using token authentication
awx = awx.AWX(host='https://awx.example.com', token='your-token-here')
```

#### Managing Inventories

```python
# List all inventories
inventories = awx.inventories.list()

# Create a new inventory
new_inventory = awx.inventories.create(name='My Inventory', organization=1)

# Add hosts to inventory
host = awx.hosts.create(
    name='web-server',
    inventory=new_inventory.id,
    variables={'ansible_host': '192.168.1.100'}
)
```

#### Working with Job Templates

```python
# List job templates
templates = awx.job_templates.list()

# Create a new job template
template = awx.job_templates.create(
    name='Deploy Web App',
    job_type='run',
    inventory=1,
    project=1,
    playbook='deploy.yml'
)

# Launch a job
job = template.launch()
```

#### Project Management

```python
# List projects
projects = awx.projects.list()

# Create a new project
project = awx.projects.create(
    name='My Project',
    scm_type='git',
    scm_url='https://github.com/org/repo.git'
)

# Update project
project.scm_branch = 'main'
project.update()
```

#### Credential Management

```python
# List credentials
credentials = awx.credentials.list()

# Create a new credential
credential = awx.credentials.create(
    name='AWS Credentials',
    credential_type=1,
    inputs={
        'username': 'aws-user',
        'password': 'aws-password'
    }
)
```

#### Workflow Management

```python
# List workflow job templates
workflows = awx.workflow_job_templates.list()

# Create a new workflow
workflow = awx.workflow_job_templates.create(
    name='Deployment Pipeline',
    organization=1
)

# Add nodes to workflow
workflow.workflow_nodes.create(
    unified_job_template=1,
    workflow_job_template=workflow.id
)
```

#### Monitoring and Logs

```python
# Get job status
job = awx.jobs.get(1)
print(f"Job status: {job.status}")

# Get job events
events = job.events.list()
for event in events:
    print(f"Event: {event.event}")

# Get job stdout
stdout = job.stdout
```

#### Bulk Operations

```python
# Bulk create hosts
hosts_data = [
    {'name': f'host-{i}', 'inventory': 1} for i in range(5)
]
hosts = awx.hosts.create(hosts_data)

# Bulk update job templates
templates = awx.job_templates.list()
for template in templates:
    template.extra_vars = {'new_var': 'value'}
    template.update()
```

These examples can be used as building blocks for custom automation scripts and integration with other tools. Remember to handle exceptions and implement proper error checking in production code.  
