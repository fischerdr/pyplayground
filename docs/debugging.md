# Debugging Log

## Phase 1 Issues

### Issue: FQCN Include Statements Not Parsed

**Found During**: Phase 1 Bug Fix  
**Date**: 2026-02-05  
**Severity**: HIGH  
**Status**: FIXED

**Symptom**:
- Script failed to detect `ansible.builtin.include_tasks` and `ansible.builtin.include_role` statements
- Playbook `etcd_db_backup_aap.yml` showed 0 includes when it should have detected:
  - `ansible.builtin.include_role: name: setup_env` (line 24)
  - `ansible.builtin.include_tasks: file: roles/upgrade_clusters/tasks/etcd_backup_aap.yml` (line 75)

**Root Cause**:
- Code only checked for short module names (`include_tasks`, `include_role`)
- Ansible uses FQCN (Fully Qualified Collection Names) like `ansible.builtin.include_tasks`
- The `_parse_task_includes` and `_parse_includes` methods only checked for short form keys

**Solution**:
- Added `_get_include_key()` helper method to check both short and FQCN forms
- Updated `_parse_task_includes()` to use helper method for all include types
- Updated `_parse_includes()` to use helper method for play-level includes
- Helper checks: short form → `ansible.builtin.*` → `ansible.legacy.*` → `ansible.posix.*`

**Code Location**:
- File: `pyplayground/ansible_structure_analyzer.py`
- Lines: 201-220 (helper method), 413-442 (task parsing), 355-389 (play parsing)
- Function: `IncludeResolver._get_include_key()`, `IncludeResolver._parse_task_includes()`, `IncludeResolver._parse_includes()`

**Verification**:
- Test: Manual test with `etcd_db_backup_aap.yml` should now detect both includes
- Manual: Run script on playbook and verify includes are found
- Logs: Check debug logs show FQCN detection

**Prevention**:
- Pattern to follow: Always check for both short and FQCN forms when parsing Ansible modules
- Check to add: Test cases for FQCN include statements
- Documentation: Document FQCN support in code comments

---

### Issue: Output File Naming Not Based on Input

**Found During**: Phase 1 Bug Fix  
**Date**: 2026-02-05  
**Severity**: MEDIUM  
**Status**: FIXED

**Symptom**:
- Output files always named `ansible_structure.json` and `ansible_structure.md`
- User requested output files should be named based on input file/directory name

**Root Cause**:
- Hardcoded default filenames in `OutputGenerator.generate_json()` and `generate_markdown()`
- No logic to derive filename from input path

**Solution**:
- Added logic in `main()` to generate base filename from input path
- For files: use `input_path.stem` (filename without extension)
- For directories: use `input_path.name` (directory name)
- Pass generated filename to output generator methods
- Format: `{base_name}_structure.json` and `{base_name}_structure.md`

**Code Location**:
- File: `pyplayground/ansible_structure_analyzer.py`
- Lines: 1411-1417 (filename generation), 1429-1436 (passing to generators)
- Function: `main()`

**Verification**:
- Test: Run with `playbooks/etcd_db_backup_aap.yml` → should create `etcd_db_backup_aap_structure.json`
- Manual: Verify output files have correct names
- Logs: Check debug log shows generated base filename

**Prevention**:
- Pattern to follow: Always derive output filenames from input when possible
- Check to add: Test cases for output file naming
- Documentation: Document filename generation logic

---
