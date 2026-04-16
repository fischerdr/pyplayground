# Development Standards and Methodology

**Version**: 1.0  
**Last Updated**: 2026-02-03  
**Source**: Neveredit Modernization Project Lessons Learned

---

## Purpose

This document defines the development standards, testing methodology, debugging practices, and documentation requirements for systematic software modernization and maintenance projects. These standards evolved from real-world experience modernizing a 20-year-old Python 2.x codebase to Python 3.11+.

**Key Principle**: Quality through discipline, not speed through shortcuts.

---

## Related Documentation

This comprehensive reference document is integrated into the repository's rule files:

- **`AGENT_RULES.md`** - Minimum required rules for all agents (highest precedence) - Contains critical enforcement rules extracted from this document
- **`CLAUDE.md`** - Tool-specific guidance for Claude Code - Contains actionable development standards and patterns
- **`AGENTS.md`** - Repository guidelines for contributors - Contains contributor-focused standards and templates

**Usage**:

- For **quick reference** and **enforcement rules**, see the rule files above
- For **detailed templates**, **workflows**, **case studies**, and **comprehensive examples**, see this document

The rule files reference specific sections of this document for detailed guidance, ensuring consistency across all documentation.

---

---

## 1. Coding Standards

### 1.1 Core Principles

**NO EXCEPTIONS to these rules**:

1. **Fix Bugs Immediately** - No "low priority" deferrals, regardless of fix time
2. **No Deprecated API** - Update immediately when found
3. **Consistent Patterns** - Copy proven code, don't reinvent
4. **Complete Error Handling** - All user-facing code must have try/except/finally
5. **Resource Cleanup** - Always use finally blocks for cleanup

### 1.2 Code Pattern Template

Every user-facing function follows this pattern:

```python
import logging
logger = logging.getLogger(__name__)

def userAction(self, event):
    """Clear docstring explaining purpose and behavior.
    
    Args:
        event: Description of parameter
        
    Returns:
        Description of return value (if any)
    """
    logger.info("User action started - describe what user did")
    
    try:
        # Setup phase
        logger.debug(f"Setup details: {variable}")
        
        # Main logic
        result = performOperation()
        
        # Handle result
        if result:
            logger.info(f"Operation succeeded: {result}")
            # Success path
        else:
            logger.debug("User cancelled operation")
            # Cancellation path
            
    except SpecificException as e:
        # Handle specific exceptions if possible
        logger.error(f"Specific error in operation: {e}", exc_info=True)
        showUserError(f"Specific error message: {e}")
    except Exception as e:
        # Catch-all for unexpected errors
        logger.error(f"Unexpected error in operation: {e}", exc_info=True)
        showUserError(f"An error occurred: {e}")
    finally:
        # Cleanup ALWAYS runs
        cleanup_resources()
        logger.debug("Cleanup completed")
```

### 1.3 Mandatory Code Elements

**Every function with user interaction MUST have**:

- ✅ Logger initialization at module level
- ✅ Entry logging (info level) when user triggers action
- ✅ try/except/finally structure
- ✅ Error logging with `exc_info=True` for stack traces
- ✅ User feedback on errors
- ✅ Resource cleanup in finally block

**Every module MUST have**:

- ✅ `import logging` at top
- ✅ `logger = logging.getLogger(__name__)` after imports
- ✅ Docstrings on all functions/classes
- ✅ Type hints on new code (existing code optional)

### 1.4 Forbidden Patterns

**Never use these in production/runtime code**:

- ❌ `print()` statements (except CLI tools and startup checks)
- ❌ Bare `except:` clauses without logging
- ❌ Resource allocation without cleanup
- ❌ Deprecated API calls
- ❌ Magic numbers without constants/comments
- ❌ Copy-paste code (extract to function)

---

## 2. Testing Methodology

### 2.1 Three-Tier Testing Strategy

**Tier 1: Automated Tests** (pytest or equivalent)

- **When**: After EVERY code change
- **Requirement**: Must remain passing (no tolerance for breaking tests)
- **Frequency**: Continuous
- **Command**: `pytest tests/` or equivalent

**Tier 2: Programmatic Validation**

- **When**: GUI/integration testing not available
- **Methods**:
  - Syntax validation (`python -m py_compile`)
  - Pattern verification (grep, static analysis)
  - Round-trip testing (load → process → save → compare)
  - API compliance checking
  - Comparison with reference implementations
- **Purpose**: Test what CAN be tested without full environment

**Tier 3: Manual Testing**

- **When**: Full environment available
- **Requirements**:
  - Structured checklist (not ad-hoc)
  - Document each step result
  - Capture logs for review
  - Verify with automated tools after
- **Purpose**: User experience validation, visual verification

### 2.2 Testing Principles

**Key Rules**:

1. **Test at highest available tier** - Don't skip testing because ideal environment unavailable
2. **Never skip Tier 1** - Automated tests always run
3. **Document test strategy** - Explain which tier used and why
4. **Validate with lower tiers** - Manual testing should still run automated tests

**Test Coverage Requirements**:

- Critical paths: 100% (must have tests)
- User-facing features: 90%+ (should have tests)
- Utility functions: 70%+ (nice to have tests)
- Legacy code: Test during modification (add as you touch)

### 2.3 Test-Driven Bug Fixing

When fixing bugs:

1. Write test that reproduces bug (if possible)
2. Verify test fails
3. Fix bug
4. Verify test passes
5. Keep test in suite (prevent regression)

---

## 3. Phase & Task Structure

### 3.1 Phase Definition

**Phase = Major Goal** with clear deliverable

**Requirements**:

- **Duration**: 2-4 weeks typical (flexible)
- **Self-contained**: Can merge/pause at phase boundaries
- **Clear goal**: One sentence description
- **Measurable success**: Specific completion criteria

**Phase Structure**:

```markdown
# Phase X: [Name]

**Goal**: One clear sentence describing what this phase accomplishes

**Duration**: Estimated time
**Priority**: CRITICAL / HIGH / MEDIUM / LOW
**Dependencies**: What must be done first

**Success Criteria**:
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All tests passing

**Tasks**: 6-10 tasks typically
**Deliverables**: What exists at end of phase
```

### 3.2 Task Definition

**Task = Specific Deliverable** completed in one session

**Requirements**:

- **Duration**: 2-8 hours typical
- **Atomic**: Complete in one sitting
- **Sequential**: Builds on previous tasks
- **Documented**: Creates/updates documentation

**Task Structure** (MANDATORY - all sections required):

```markdown
### Task X.Y: [Name]

**Priority**: CRITICAL / HIGH / MEDIUM / LOW
**Effort**: X-Y hours
**Status**: Not started / In Progress / Complete / Blocked

**Goal**: One clear sentence

**Prerequisites Checklist**:
- [ ] Previous task complete
- [ ] Branch created/active
- [ ] Virtual environment active
- [ ] Tests passing

**Sub-tasks**:
1. Specific action 1
2. Specific action 2
3. Specific action 3

**Logging Requirements** (MANDATORY):
```python
# Code examples showing what to log
logger.info("User action")
logger.debug(f"Details: {var}")
logger.error(f"Error: {e}", exc_info=True)
```

**Testing Requirements** (MANDATORY):

```bash
# Exact commands to run
pytest tests/
python -m py_compile file.py
# Manual test steps if needed
```

**Documentation Requirements** (MANDATORY):

```bash
# Commit message includes all required sections
# See Section 7.2 for template format
```

**Git Commit** (MANDATORY):

```bash
git add [files]
git commit -m "[Template showing format]"
```

**STOP and Report** (MANDATORY):

```bash
echo "=== TASK X.Y COMPLETE ==="
[Show evidence commands]
echo "Ready for next task? (Awaiting approval)"
```

**STOP HERE. Do not proceed without approval.**

**Success Criteria**:

- ✅ Criterion 1
- ✅ Criterion 2
- ✅ Tests passing
- ✅ Documentation updated
- ✅ Git committed

```

### 3.3 Task Enforcement

**CRITICAL**: Every task MUST have ALL sections above.

**No shortcuts allowed**:
- ❌ "Simple task, skip documentation" → NO
- ❌ "Just a bug fix, no logging needed" → NO
- ❌ "Tests are fine, skip STOP point" → NO
- ❌ "Will document later" → NO

**Enforcement mechanism**: Task cannot be marked complete until all sections filled.

---

## 4. Debugging Methodology

### 4.1 Anti-Whack-a-Mole Strategy

**Core Principle**: Fix root causes, not symptoms.

**Rule 1: Fix Bugs in Current Phase**
- ❌ "Low priority, fix later" → Creates technical debt
- ❌ "Only takes 5 minutes, skip it" → Accumulates
- ✅ "Fix now, regardless of size" → Prevents accumulation
- ✅ "Document in commit message" → Builds knowledge

**Rule 2: Investigation Before Implementation**
- ❌ Jump straight to fixing
- ❌ Guess at solutions
- ✅ Thorough investigation task first
- ✅ Document root cause
- ✅ Plan fix approach
- ✅ Then implement

**Rule 3: Use Reference Implementations**
- ❌ Debug blindly when stuck
- ✅ Check reference implementation first
- ✅ Use comparison tools
- ✅ Validate assumptions
- ✅ Copy proven patterns

**Rule 4: Document Everything**
- ❌ "Fixed bug, move on"
- ✅ Document WHY it happened
- ✅ Document HOW to prevent
- ✅ Add to commit message
- ✅ Create test to prevent regression

### 4.2 Debugging Workflow

**Standard Process** (no exceptions):

```

1. Bug discovered
   └─ STOP - Don't fix yet

2. Create investigation task
   └─ Understand root cause
   └─ Check reference implementations
   └─ Document findings

3. Document findings
    └─ Symptom
    └─ Root cause
    └─ Proposed solution

4. Create fix with logging
    └─ Follow code pattern template
    └─ Add comprehensive logging
    └─ Include error handling

5. Test fix thoroughly
    └─ Automated tests
    └─ Manual verification
    └─ Comparison tool (if applicable)

6. Update documentation
    └─ Commit message with fix details
    └─ Code comments if complex

7. Git commit
    └─ Detailed message
    └─ Include findings and solution

8. STOP for approval
   └─ Show evidence
   └─ Await review

```

### 4.3 Comparison Tool Usage

**When to use**:
- Data format changes
- Round-trip operations
- Refactoring without behavior change
- Validating against reference implementation

**How to use**:
1. Run operation with current code
2. Run operation with reference code
3. Compare outputs semantically (not byte-by-byte)
4. Document differences
5. Determine if differences are acceptable

**Semantic vs Byte Comparison**:
- Use semantic: Data structures, file formats, serialization
- Use byte: Binary protocols, checksums, exact reproduction

---

## 5. Logging Standards

### 5.1 Three-Level Hierarchy

**DEBUG Level** - Technical details for developers:
```python
logger.debug(f"Function called with args: {args}")
logger.debug(f"Current state: {state}")
logger.debug(f"Processing item {i} of {total}")
logger.debug("Internal operation completed")
```

**INFO Level** - User actions and major events:

```python
logger.info("Application started")
logger.info("User opened file dialog")
logger.info(f"User selected file: {path}")
logger.info(f"File saved successfully: {path}")
logger.info("Operation completed")
```

**WARNING Level** - Potential issues, recoverable problems:

```python
logger.warning("Deprecated API used, consider updating")
logger.warning(f"Retrying operation after failure: {retry_count}")
logger.warning("Configuration missing, using defaults")
```

**ERROR Level** - Exceptions and failures:

```python
logger.error(f"Failed to open file: {e}", exc_info=True)
logger.error(f"Operation failed: {e}", exc_info=True)
logger.error(f"Unexpected error: {e}", exc_info=True)
```

### 5.2 Mandatory Logging Patterns

**Every module**:

```python
import logging
logger = logging.getLogger(__name__)  # REQUIRED at module level
```

**Every user action**:

```python
logger.info("User triggered [action name]")  # REQUIRED when action starts
```

**Every exception**:

```python
logger.error(f"Error in [operation]: {e}", exc_info=True)  # REQUIRED - note exc_info
```

**Every resource operation**:

```python
logger.debug("Opening resource: {resource}")
# ... operation ...
logger.debug("Closing resource: {resource}")
```

### 5.3 Forbidden Logging Patterns

**Never do these**:

```python
# ❌ Using print() in runtime code
print("Debug info")  # Only acceptable in CLI tools and startup

# ❌ Logging without context
logger.info("Success")  # What succeeded?

# ❌ Exception without stack trace
logger.error(f"Error: {e}")  # Missing exc_info=True

# ❌ Using logging module directly
logging.info("Message")  # Use logger instance

# ❌ Excessive logging in loops
for item in huge_list:
    logger.debug(f"Processing {item}")  # Will flood logs

# ❌ Logging sensitive data
logger.info(f"Password: {password}")  # Security issue
```

### 5.4 Logging Audit Process

**Periodic audits required** (every phase or major milestone):

```bash
# 1. Check for print() violations
grep -rn "print(" src/ --include="*.py" | grep -v "# print" | grep -v "__main__"

# 2. Check logger initialization
for file in src/**/*.py; do
    if grep -q "def " "$file"; then  # Has functions
        grep -q "logger = logging.getLogger" "$file" || echo "MISSING: $file"
    fi
done

# 3. Count logging statements
grep -c "logger\." src/file.py

# 4. Create violations report
# Document all violations found

# 5. Fix ALL violations
# No exceptions - fix in same phase

# 6. Verify compliance
# Re-run checks until clean
```

**Acceptable print() uses**:

- CLI tool output in `if __name__ == "__main__":` blocks
- Startup checks before logging initialized
- Python version compatibility checks

**All other print() uses are violations and must be fixed.**

---

## 6. Documentation Standards

### 6.1 Documentation Requirements

**This repo (scripting-focused)**: Documentation tracking (progress.md/debugging.md) is NOT required.

**Enterprise projects**: MUST maintain:

1. `docs/progress.md` - Timeline of what's been done
2. `docs/debugging.md` - Issues found and solutions

### 6.2 progress.md Structure

**Purpose**: Track chronological progress through tasks

**Template**:

```markdown
# Project Progress Tracking

## Phase X: [Phase Name]

### Phase X Task Y: [Task Name]

**Status**: ✅ Complete / 🔄 In Progress / ⏸️ Blocked  
**Date**: YYYY-MM-DD  
**Branch**: feature/branch-name  
**Commit**: [commit-hash]  

**Changes Made**:
- Specific change 1 (with rationale if non-obvious)
- Specific change 2
- Logging added: info/debug/error levels
- Error handling added: try/except/finally

**Tests**:
- Manual: [PASS/FAIL with description]
- Automated: pytest (X/Y passing)
- Validation: [comparison tool / other checks]

**Logging Added/Verified**:
- User actions: logger.info()
- Flow details: logger.debug()
- Exceptions: logger.error(exc_info=True)

**Issues Found**:
[Link to debugging.md entry if any issues discovered]

**Files Modified**:
- path/to/file1.py (+X, -Y lines)
- path/to/file2.py (+A, -B lines)

**Next Steps**: Task Y+1 ([brief description])

---
```

**Update Frequency**: After EVERY task completion (mandatory)

**Review Frequency**: At phase boundaries, look back at progress to inform next phase

### 6.3 debugging.md Structure

**Purpose**: Document issues, root causes, and solutions

**Template**:

```markdown
# Debugging Log

## Phase X Issues

### Issue: [Brief Description]

**Found During**: Phase X Task Y  
**Date**: YYYY-MM-DD  
**Severity**: CRITICAL / HIGH / MEDIUM / LOW  
**Status**: FIXED / INVESTIGATING / DEFERRED (with reason)

**Symptom**:
[What went wrong - user perspective]

**Root Cause**:
[Why it happened - technical analysis]

**Solution**:
[How it was fixed - implementation details]

**Code Location**:
- File: `path/to/file.py`
- Lines: XXX-YYY
- Function: `functionName()`

**Verification**:
[How we confirmed the fix works]
- Test: [specific test that now passes]
- Manual: [manual verification performed]
- Logs: [relevant log entries]

**Logs**:
```text
[Relevant log entries showing the issue and/or fix]
```

**Prevention**:
[How to avoid this issue in future]

- Pattern to follow: [code pattern]
- Check to add: [automated check if possible]
- Documentation: [what to document]

**Related Issues**:

- [Link to similar issues if any]

---

```

**Update Frequency**: When issues found (as needed)

**Cross-reference**: Link from progress.md to debugging.md entries

### 6.4 Documentation Principles

**Rules**:
1. **Update immediately** - Don't defer documentation
2. **Be specific** - "Fixed bug" is not sufficient
3. **Include code** - Show before/after when relevant
4. **Link between docs** - Cross-reference progress.md ↔ debugging.md
5. **No emojis in professional docs** - Text only (except status indicators)

**What to document**:
- ✅ Every task completion
- ✅ Every bug found and fixed
- ✅ Every decision made (with rationale)
- ✅ Every test result
- ✅ Every code pattern established

**What NOT to document**:
- ❌ Every line of code (that's what code comments are for)
- ❌ Obvious changes (use judgment)
- ❌ Duplicate information (link instead)

**Note for this repo**: progress.md and debugging.md are NOT required for scripting-focused work.

---

## 7. Git Workflow

### 7.1 Branch Strategy

**Structure**:
```

main (or primary working branch)
  └─ feature/phase-X-name
       └─ One commit per task
       └─ Clean, linear history

```

**Branch Naming**:
- `feature/phase-name` - New features or enhancements
- `bugfix/issue-description` - Bug fixes
- `refactor/component-name` - Refactoring work
- `test/test-description` - Test development

**Branch Lifecycle**:
1. Create at phase start
2. One commit per task
3. Merge at phase complete (or logical milestone)
4. Delete after merge

### 7.2 Commit Message Template

**Format** (all sections required):
```

Phase X Task Y: [Short description - 50 chars max]

Changes:

- [What changed and WHY - be specific]
- [Added logging: levels used]
- [Added error handling: pattern used]
- [Refactored: what and why]

Testing:

- Manual: [Specific test performed and result]
- Automated: [pytest status - X/Y passing]
- Validation: [comparison tool / other checks]

Logging:

- [What's now logged - be specific about levels]
- [New logger.info(): user actions]
- [New logger.debug(): technical details]
- [New logger.error(): exception handling]

Files Modified:

- path/to/file1.py (+X, -Y lines): [what changed]
- path/to/file2.py (+A, -B lines): [what changed]

Next: [Brief description of next task]

```

**Commit Message Rules**:
1. First line: 50 characters max, imperative mood
2. All sections required (even if empty, say "None")
3. Be specific: "Fixed bug" → "Fixed memory leak in dialog cleanup"
4. Reference issues: "Closes #123" if applicable
5. No AI attribution (keep professional)

### 7.3 Commit Frequency

**One commit per task** - no more, no less:
- ❌ Multiple commits per task → Breaks task atomicity
- ❌ Multiple tasks per commit → Can't revert cleanly
- ✅ One task = one commit → Clean history

**When to commit**:
- After task completion
- After all tests passing
- After documentation updated
- After STOP point approval received

### 7.4 Pre-Commit Checklist

**Before EVERY commit**:
```bash
# 1. All tests passing
pytest tests/

# 2. Code quality checks (if applicable)
black src/
isort src/
ruff check src/
mypy src/

# 3. Documentation updated
# Note: progress.md/debugging.md NOT required for this scripting-focused repo

# 4. Commit message prepared
# Use template above

# 5. Review changes
git diff --staged

# 6. Commit
git commit -m "[message]"

# 7. Verify
git log -1 --stat
```

---

## 8. STOP Point Enforcement

### 8.1 Purpose of STOP Points

**Why mandatory**:

- ✅ Prevents rushing ahead without review
- ✅ Ensures quality of each task
- ✅ Catches issues early
- ✅ Maintains discipline
- ✅ Allows course correction
- ✅ Creates natural pause points

### 8.2 STOP Point Template

**Every task ends with**:

```bash
echo "================================================"
echo "TASK X.Y COMPLETE"
echo "================================================"
echo ""

echo "Git Commit:"
git log -1 --oneline
echo ""

echo "Files Changed:"
git diff --stat HEAD~1 HEAD
echo ""

echo "Test Results:"
pytest --co -q | tail -1
# OR
echo "Manual tests: [results]"
echo ""

echo "Task-Specific Evidence:"
[Show relevant evidence for this specific task]
# Examples:
# - Log excerpts showing new logging
# - Comparison tool results
# - File sizes before/after
# - Performance metrics
echo ""

echo "Documentation Updated:"
# Note: progress.md/debugging.md NOT required for this scripting-focused repo
echo ""

echo "================================================"
echo "STOP HERE - Awaiting Approval"
echo "================================================"
echo ""
echo "Ready to proceed to Task Y+1?"
echo "Options:"
echo "  1. Proceed with Task Y+1"
echo "  2. Fix [issue] first"
echo "  3. Pause here"
echo "  4. Change direction"
```

### 8.3 Reviewer Response Options

**After STOP point, reviewer should**:

**Option 1: Proceed**

```
"Proceed with Task Y+1"
[Paste task Y+1 instructions]
```

**Option 2: Fix Issue**

```
"Fix [specific issue] first"
[Explain what needs fixing]
[Provide fix instructions]
```

**Option 3: Pause**

```
"Pause here - good stopping point"
[Explain why pausing]
[Plan for resumption]
```

**Option 4: Course Correct**

```
"Change direction: [new approach]"
[Explain why changing]
[Provide new instructions]
```

### 8.4 STOP Point Violations

**Never acceptable**:

- ❌ "Task looks good, proceeding to next" (without approval)
- ❌ "Skipping STOP since it's simple" (no exceptions)
- ❌ "Combining tasks to save time" (breaks discipline)
- ❌ "Will STOP at next task" (defeats purpose)

**Consequence of violations**:

- Quality degrades
- Issues accumulate
- Technical debt increases
- Whack-a-mole debugging begins
- Project velocity decreases

---

## 9. Key Principles Summary

### 9.1 The Ten Commandments

1. **Fix Bugs Immediately** - No "low priority" deferrals, any size
2. **Investigation Before Implementation** - Understand before coding
3. **Use Reference Implementations** - Don't debug blindly
4. **Semantic Correctness Over Bytes** - Test data, not layout
5. **STOP After Every Task** - Show evidence, get approval
6. **No Print() in Runtime** - Professional logging only
7. **Document As You Go** - Update commit messages immediately (NOT required for this scripting-focused repo)
8. **Test What Can Be Tested** - Use available testing tiers
9. **Consistent Code Patterns** - Copy proven code
10. **Complete Error Handling** - All paths, all resources

### 9.2 Red Flags

**Warning signs process is breaking down**:

- 🚩 "We'll fix that later" (technical debt)
- 🚩 "It's low priority" (deferred bugs)
- 🚩 "Just a quick fix" (no documentation)
- 🚩 "Tests can wait" (untested code)
- 🚩 "Skip the STOP point" (lost discipline)
- 🚩 "Combine these tasks" (broken atomicity)
- 🚩 "Documentation later" (never happens)
- 🚩 "One more quick change" (scope creep)

**Response to red flags**: STOP, reset, return to process.

### 9.3 Success Indicators

**Signs process is working**:

- ✅ All tasks complete with documentation
- ✅ All tests passing continuously
- ✅ No deferred bugs (fixed immediately)
- ✅ Clean git history (one commit per task)
- ✅ Current documentation (commit messages up to date)
- ✅ No whack-a-mole debugging
- ✅ Predictable velocity
- ✅ Low regression rate

---

## 10. Adaptation Guidelines

### 10.1 Customizing for Your Project

**Core principles are universal** - don't change:

- Fix bugs immediately
- STOP after tasks
- Document as you go
- Test continuously

**Customizable elements**:

- Specific logging levels (but keep hierarchy)
- Documentation file names (but keep one doc - commit messages)
- Branch naming (but keep strategy)
- Task duration (but keep atomic)
- Commit frequency (but keep one per task)

### 10.2 Scaling the Process

**Small Projects** (1-2 developers, <6 months):

- Simplify documentation templates
- Less formal STOP points (but still do them)
- Shorter task descriptions (but still complete)

**Large Projects** (5+ developers, 1+ years):

- More detailed task templates
- Additional documentation (architecture, API docs)
- Formal code review process
- Automated quality gates
- More rigorous STOP points

**Critical Projects** (high stakes, regulatory):

- Maximum documentation detail
- Formal sign-offs at STOP points
- Additional audits and reviews
- Traceability requirements
- Change control process

### 10.3 Tool Integration

**Recommended tools** (adapt to your ecosystem):

- **Version Control**: Git (mandatory)
- **Testing**: pytest, unittest, or equivalent (mandatory)
- **Code Quality**: black, ruff, mypy, or equivalents (recommended)
- **CI/CD**: GitHub Actions, GitLab CI, or equivalent (recommended)
- **Documentation**: Markdown files in repo (mandatory)
- **Issue Tracking**: GitHub Issues, Jira, or equivalent (optional but helpful)

**Tool principles**:

- Documentation lives with code (version controlled)
- Automated checks in CI/CD (prevent violations)
- Local tools mirror CI checks (catch issues early)

---

## 11. Training and Adoption

### 11.1 Introducing to Team

**Gradual adoption**:

1. **Week 1**: Introduce core principles, run pilot task
2. **Week 2**: Add logging standards, documentation
3. **Week 3**: Add STOP points, full process
4. **Week 4**: Review and refine

**Pilot task selection**:

- Medium complexity
- Well-understood requirements
- Low risk if delayed
- Good learning opportunity

### 11.2 Common Resistance

**"Too much overhead"**:

- Response: Overhead prevents rework (show metrics)
- Evidence: Faster long-term velocity
- Compromise: Start with core principles, add detail gradually

**"We're agile, this is waterfall"**:

- Response: This IS agile - small iterations with feedback
- Evidence: STOP points = frequent feedback loops
- Compromise: Emphasize flexibility within structure

**"Documentation slows us down"**:

- Response: Missing documentation slows us MORE
- Evidence: Lost context costs (show examples)
- Compromise: Commit messages serve as documentation for this repo

### 11.3 Measuring Success

**Metrics to track**:

- Task completion rate (should be consistent)
- Test pass rate (should stay high)
- Bug recurrence rate (should decrease)
- Time to onboard new developers (should decrease)

**Before/After comparison**:

- Technical debt accumulation
- Rework frequency
- Debug time per bug
- Release confidence

---

## 12. Case Study: Neveredit Modernization

### 12.1 Project Context

**Challenge**: Modernize 20-year-old Python 2.x codebase to Python 3.11+

- 14,000+ lines of code
- 70+ Python files
- Binary file format handling (NWN game files)
- wxPython 2.x → 4.x migration
- No test suite initially

### 12.2 What Worked

**Early wins**:

- Phase 1-2: Systematic file parser validation (100% success)
- Task 3.2: All file dialogs fixed in one task
- Task 3.4: Comprehensive dialog audit found ALL issues
- Task 3.6: Logging audit found and fixed all violations

**Key successes**:

- 359 automated tests created and maintained passing
- Zero deprecated API remaining (100% compliance)
- Complete logging coverage (137 logging statements)
- All bugs fixed in discovery phase (no deferrals)

### 12.3 What We Learned

**Mistakes avoided**:

- NO "low priority" deferrals (would have become debt)
- NO whack-a-mole debugging (comparison tool prevented)
- NO undocumented changes (commit messages prevented context loss)
- NO skipped STOP points (maintained quality)

**Process improvements**:

- Investigation tasks before fixes (prevented wrong solutions)
- Semantic comparison over byte comparison (correct testing strategy)
- Three-tier testing (adapted to environment constraints)
- Immediate bug fixes (prevented accumulation)

### 12.4 Metrics

**Velocity**:

- Phase 3: 6 tasks completed in ~2 weeks
- Zero rework needed
- All changes first-time-right

**Quality**:

- Test suite: 359/359 passing maintained throughout
- Zero regressions introduced
- All code review points addressed immediately

---

## Appendix A: Quick Reference Checklist

### Starting a New Task

```
[ ] Read task description completely
[ ] Verify prerequisites checklist
[ ] Create/verify branch
[ ] Verify tests passing
[ ] Understand logging requirements
[ ] Understand testing requirements
[ ] Begin work
```

### Completing a Task

```
[ ] All code changes complete
[ ] Logging added (info/debug/error)
[ ] Error handling added (try/except/finally)
[ ] Tests run and passing
[ ] Code quality checks passing
[ ] Git commit with complete message
[ ] STOP point evidence gathered
[ ] Wait for approval
```

### Daily Review

```
[ ] All commits have complete messages
[ ] No uncommitted changes
[ ] All tests still passing
[ ] No deferred bugs
[ ] Tomorrow's task identified
```

---

## Appendix B: Template Files

### B.1 Task Template

See Section 3.2 for complete task template.

### B.2 Commit Message Template

See Section 7.2 for complete commit message template.

### B.4 Commit Message Template

See Section 7.2 for complete commit message template.

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial version based on Neveredit project |

---

## License

This document is released under CC BY-SA 4.0. You are free to adapt it for your projects while maintaining attribution.

**Source Project**: Neveredit Modernization (Python 2.x → 3.11+)  
**Original Author**: Based on practices developed during modernization project  
**Last Updated**: 2026-02-03
