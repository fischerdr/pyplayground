# Ansible Structure Analyzer Test Fixtures

This directory contains comprehensive test fixtures for the `ansible_structure_analyzer.py` script. These fixtures cover various Ansible patterns and scenarios to ensure the analyzer correctly handles:

- Loops (with_sequence, with_items, loop)
- Templates (short form, FQCN, unnamed, with loops)
- Includes (include_tasks, import_tasks, include_role, import_role)
- Roles (simple, nested, with dependencies)
- Edge cases (circular dependencies, missing files, relative paths)

## Directory Structure

```
tests/fixtures/ansible_structure/
├── README.md                          # This file
├── playbooks/                         # Top-level playbooks
│   ├── simple_playbook.yml           # Basic playbook
│   ├── with_loops.yml                # Playbook with loops
│   ├── with_includes.yml             # Playbook with includes
│   ├── with_roles.yml                # Playbook with roles
│   ├── circular_dependency.yml       # Circular dependency test
│   └── complex_nested.yml            # Complex nested structure
├── roles/                             # Test roles
│   ├── simple_role/                  # Basic role
│   ├── role_with_loops/              # Role with loop includes
│   ├── nested_role/                  # Role that includes other roles
│   └── template_role/                # Role with various templates
└── tasks/                             # Shared task files
    ├── common_tasks.yml
    ├── validation.yml
    ├── setup.yml
    ├── task_a.yml                    # Circular dependency chain A
    ├── task_b.yml                    # Circular dependency chain B
    └── task_c.yml                    # Circular dependency chain C
```

## Test Scenarios

### 1. Basic Playbook (`playbooks/simple_playbook.yml`)

- Simple playbook with basic tasks
- No includes or roles
- Basic template usage

**Expected Results:**
- 1 playbook found
- 0 includes
- 0 roles
- 1 template (if template file exists)

### 2. Loops (`playbooks/with_loops.yml`)

- include_tasks with `with_sequence`
- include_tasks with `with_items`
- include_tasks with `loop`
- include_role with `loop`
- Nested loops

**Expected Results:**
- Includes should be detected
- Loop context should be preserved in breadcrumbs
- No false positive circular dependencies from loop iterations

### 3. Includes (`playbooks/with_includes.yml`)

- include_tasks (short form)
- ansible.builtin.include_tasks (FQCN)
- import_tasks
- include_role
- import_role
- Relative path includes
- Absolute path includes (from repo root)

**Expected Results:**
- All include types detected
- FQCN includes parsed correctly
- Path resolution works for relative and absolute paths

### 4. Roles (`playbooks/with_roles.yml`)

- Simple role inclusion
- Role with vars
- Role with nested includes
- Role with templates

**Expected Results:**
- Roles detected and resolved
- Nested includes within roles found
- Templates in roles detected

### 5. Circular Dependencies (`playbooks/circular_dependency.yml`)

- True circular: A -> B -> C -> A
- False positive case: A -> B -> C, A -> D -> C (different branches)
- With loops: A -> B [with_sequence] -> C, where C includes something from A

**Expected Results:**
- True circular dependencies detected
- False positives not flagged (different branches)
- Loop context helps distinguish false positives

### 6. Templates (`roles/template_role/`)

- Short form: `template: file.j2`
- FQCN: `ansible.builtin.template: file.j2`
- Unnamed template tasks
- Templates with `with_items`
- Templates with `loop_control`
- Templates in nested directories

**Expected Results:**
- All template forms detected
- Unnamed templates found
- Templates with loops detected
- Nested template paths resolved

### 7. Complex Nested (`playbooks/complex_nested.yml`)

- Playbook -> Role -> Task File -> Include -> Role -> Task File
- Multiple levels of nesting
- Mix of includes and roles
- Templates at various levels

**Expected Results:**
- Deep nesting handled correctly
- All includes and roles found at all levels
- Templates found at various nesting levels

## Usage in Tests

Reference fixtures in pytest tests:

```python
from pathlib import Path

# Get fixture directory
fixture_dir = Path(__file__).parent / "fixtures" / "ansible_structure"

# Use in tests
playbook_path = fixture_dir / "playbooks" / "simple_playbook.yml"
```

## Running Tests

```bash
# Run analyzer on a specific playbook
python -m pyplayground.ansible_structure_analyzer \
    --input tests/fixtures/ansible_structure/playbooks/simple_playbook.yml \
    --repo-root tests/fixtures/ansible_structure \
    --debug

# Run pytest tests
pytest tests/test_ansible_structure_analyzer.py -v
```

## Notes

- All YAML files use valid Ansible syntax
- Examples are realistic but simplified for testing
- Files include comments explaining test purpose
- Fixtures are self-contained (no external dependencies)
- Follows Ansible best practices where possible
