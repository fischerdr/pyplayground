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

### Appendix A: Python Migration Scripts

The following skeleton scripts use `logging`, `typer`, and `awxcli` to automate Tower and AWX export/import tasks. Customize API endpoints, credentials, and file paths as needed.

#### `tower_export_credentials.py`

```python
import logging
import typer
from awxcli import Tower

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def export(output: str = "credentials.json"):
    """Export Tower credentials to a JSON file"""
    tower = Tower(host="https://tower.example.com", token="YOUR_TOWER_TOKEN")
    creds = tower.credentials.list()
    with open(output, "w") as f:
        f.write(creds.json())
    logger.info(f"Exported {len(creds)} credentials to {output}")

if __name__ == "__main__":
    app()
```

#### `awx_import_credentials.py`

```python
import logging
import typer
from awxcli import AWX
import json

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def import_creds(input: str = "credentials.json"):
    """Import credentials JSON into AWX"""
    awx = AWX(host="https://awx.example.com", token="YOUR_AWX_TOKEN")
    data = json.load(open(input))
    for cred in data:
        awx.credentials.create(**cred)
        logger.info(f"Imported credential {cred['name']}")

if __name__ == "__main__":
    app()
```

#### `tower_export_projects.py`

```python
import logging
import typer
from awxcli import Tower

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def export(output: str = "projects.json"):
    """Export Tower project definitions to JSON"""
    tower = Tower(host="https://tower.example.com", token="YOUR_TOWER_TOKEN")
    projs = tower.projects.list()
    with open(output, "w") as f:
        f.write(projs.json())
    logger.info(f"Exported {len(projs)} projects to {output}")

if __name__ == "__main__":
    app()
```

#### `awx_import_projects.py`

```python
import logging
import typer
from awxcli import AWX
import json

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def import_projects(input: str = "projects.json"):
    """Import project definitions into AWX"""
    awx = AWX(host="https://awx.example.com", token="YOUR_AWX_TOKEN")
    data = json.load(open(input))
    for proj in data:
        awx.projects.create(**proj)
        logger.info(f"Imported project {proj['name']}")

if __name__ == "__main__":
    app()
```

#### `tower_export_inventory.py`

```python
import logging
import typer
from awxcli import Tower

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def export(output: str = "inventory.json"):
    """Export Tower inventories and hosts to JSON"""
    tower = Tower(host="https://tower.example.com", token="YOUR_TOWER_TOKEN")
    inv = tower.inventories.list()
    with open(output, "w") as f:
        f.write(inv.json())
    logger.info(f"Exported {len(inv)} inventories to {output}")

if __name__ == "__main__":
    app()
```

#### `awx_import_inventory.py`

```python
import logging
import typer
from awxcli import AWX
import json

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def import_inventory(input: str = "inventory.json"):
    """Import inventories and hosts JSON into AWX"""
    awx = AWX(host="https://awx.example.com", token="YOUR_AWX_TOKEN")
    data = json.load(open(input))
    for inv in data:
        awx.inventories.create(**inv)
        logger.info(f"Imported inventory {inv['name']}")

if __name__ == "__main__":
    app()
```

#### `tower_export_job_templates.py`

```python
import logging
import typer
from awxcli import Tower

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def export(output: str = "job_templates.json"):
    """Export Tower job templates and workflows to JSON"""
    tower = Tower(host="https://tower.example.com", token="YOUR_TOWER_TOKEN")
    jt = tower.job_templates.list()
    with open(output, "w") as f:
        f.write(jt.json())
    logger.info(f"Exported {len(jt)} job templates to {output}")

if __name__ == "__main__":
    app()
```

#### `awx_import_job_templates.py`

```python
import logging
import typer
from awxcli import AWX
import json

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def import_job_templates(input: str = "job_templates.json"):
    """Import job templates and workflows into AWX"""
    awx = AWX(host="https://awx.example.com", token="YOUR_AWX_TOKEN")
    data = json.load(open(input))
    for jt in data:
        awx.job_templates.create(**jt)
        logger.info(f"Imported job template {jt['name']}")

if __name__ == "__main__":
    app()
```

#### `tower_export_schedules.py`

```python
import logging
import typer
from awxcli import Tower

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def export(output: str = "schedules.json"):
    """Export Tower schedules and notifications to JSON"""
    tower = Tower(host="https://tower.example.com", token="YOUR_TOWER_TOKEN")
    sch = tower.schedules.list()
    with open(output, "w") as f:
        f.write(sch.json())
    logger.info(f"Exported {len(sch)} schedules to {output}")

if __name__ == "__main__":
    app()
```

#### `awx_import_schedules.py`

```python
import logging
import typer
from awxcli import AWX
import json

app = typer.Typer()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.command()
def import_schedules(input: str = "schedules.json"):
    """Import schedules and notification templates into AWX"""
    awx = AWX(host="https://awx.example.com", token="YOUR_AWX_TOKEN")
    data = json.load(open(input))
    for sch in data:
        awx.schedules.create(**sch)
        logger.info(f"Imported schedule {sch['name']}")

if __name__ == "__main__":
    app()
```

- Appendix B: Custom Dockerfiles for EE and Init Images

- Appendix C: Backup and Restore Commands

- Appendix D: Useful AWX CLI Commands

- Appendix A: Tower API Export/Import Scripts

- Appendix B: Custom Dockerfiles for EE and Init Images

- Appendix C: Backup and Restore Commands

- Appendix D: Useful AWX CLI Commands

