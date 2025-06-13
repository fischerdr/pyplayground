# AWX Migration Guide: Configuring a Jump Host (Bastion) for Remote Playbook Execution

## Context

This document covers how to configure AWX (running via the AWX Operator on OpenShift) to support execution of existing Red Hat Tower playbooks that require a remote jump host (bastion) to access target systems. Since the existing playbooks **must not be modified**, all adaptations are done at the inventory and AWX configuration layers.

---

## Objective

Ensure seamless migration from Tower to AWX for Ansible playbooks that connect to remote targets via a jump host, while preserving execution environments and existing Python virtual environment usage on remote systems.

---

## Architecture Overview

```text
+------------+      SSH       +-------------+      SSH       +-------------+
| AWX Pod    | ------------> | Jump Host   | -----------> | Target Host |
| (EE)       |               | (Bastion)   |              |             |
+------------+               +-------------+              +-------------+
```

- **AWX Pod:** Runs playbook using an Execution Environment (containerized)
- **Jump Host:** Intermediate SSH host; used for routing and access control
- **Target Host:** Actual playbook target, with custom Python virtual environment

---

## AWX Configuration Steps

### 1. Inventory Setup with Jump Host

Create or modify your inventory in AWX to include `ansible_ssh_common_args` for jump routing:

```ini
[target]
appserver01.internal ansible_host=10.1.1.25

[target:vars]
ansible_user=remote_user
ansible_ssh_common_args='-o ProxyJump=jumpuser@jump.example.com'
ansible_python_interpreter=/opt/venvs/legacy/bin/python
```

> Ensure the `ansible_python_interpreter` path matches what is used in existing Tower playbooks.

### 2. Credentials Setup

In AWX:

- Go to **Credentials → Add**
- Create a **Machine Credential**
  - SSH Private Key for `remote_user`
  - Ensure **Privilege Escalation** is enabled if needed
- If the jump host requires a different SSH key, use `~/.ssh/config` entries inside custom Execution Environments (advanced)

### 3. Project and Job Template Setup

- Link your Git or SCM-based **Project** containing playbooks
- Create a **Job Template**:
  - Inventory: the one created above
  - Project: your SCM project
  - Playbook: select from dropdown
  - Credentials: the machine credential
  - Execution Environment: choose one compatible with the playbook’s expectations

### 4. Test Connection

Before running the full job, verify SSH from the AWX pod (or from a test container in the same namespace) works:

```bash
ssh -J jumpuser@jump.example.com remote_user@10.1.1.25
```

If SSH agent forwarding or custom SSH config is needed, ensure your Execution Environment includes those tools and files.

---

## Notes on Python Virtual Environments

- The `ansible_python_interpreter` variable must be set in inventory to point to the correct remote Python binary.
- Ansible will not source `activate`; it directly uses the interpreter path.
- The virtual environment must be pre-created and accessible on the target host.

```yaml
ansible_python_interpreter: /opt/venvs/legacy/bin/python
```

---

## Security Recommendations

- Restrict jump host access to AWX IPs only
- Use SSH key with limited privileges
- Audit jump host connections via PAM or session-aware proxies

---

## Appendix: Sample Inventory YAML (for automation)

```yaml
all:
  hosts:
    appserver01.internal:
      ansible_host: 10.1.1.25
      ansible_user: remote_user
      ansible_python_interpreter: /opt/venvs/legacy/bin/python
      ansible_ssh_common_args: "-o ProxyJump=jumpuser@jump.example.com"
```

---

## Per-Project Virtualenv Standardization

To support multiple legacy playbooks that depend on different Python virtual environments per host or project:

### Approach

1. **Use Tags or Labels:**

   - Use AWX tags (labels) to denote which Python venv is required (e.g., `venv_legacy`, `venv_data`, etc.)
   - Alternatively, use Tower surveys or inventory groups to select the environment.

2. **Configure `ansible_python_interpreter` Dynamically:**

   - Define group vars or host vars mapped to the label/tag.
   - Use a lightweight pre-task role to validate or bootstrap the virtualenv if missing.

3. **Pre-Task Checks:**

```yaml
- name: Verify Python version from virtualenv
  command: "/opt/venvs/{{ venv_tag }}/bin/python --version"
  register: python_check
  failed_when: python_check.rc != 0

- name: List installed Python packages
  command: "/opt/venvs/{{ venv_tag }}/bin/pip list"
  register: pip_list
  changed_when: false

- name: Display pip list
  debug:
    var: pip_list.stdout_lines
```

---

## AWXKit / AWX CLI Import Template

### Reusable Project Template

```yaml
---
projects:
  - name: legacy-playbooks
    description: Legacy automation from Tower
    organization: Default
    scm_type: git
    scm_url: https://git.example.com/infra/legacy-playbooks.git
    scm_branch: main
    scm_clean: true
    scm_update_on_launch: true

inventories:
  - name: legacy-inventory
    organization: Default
    variables: |
      all:
        children:
          target:
            hosts:
              appserver01.internal:
                ansible_host: 10.1.1.25
                ansible_user: remote_user
                ansible_python_interpreter: /opt/venvs/legacy/bin/python
                ansible_ssh_common_args: "-o ProxyJump=jumpuser@jump.example.com"

job_templates:
  - name: Legacy Appserver Job
    description: Runs legacy playbook through jump host
    job_type: run
    inventory: legacy-inventory
    project: legacy-playbooks
    playbook: site.yml
    credentials:
      - machine-ssh-key
    execution_environment: default-ee
    ask_verbosity_on_launch: true
    ask_tags_on_launch: true
    labels:
      - venv_legacy
```

> To import, save as `awx_import.yaml` and run: `awx import awx_import.yaml`
