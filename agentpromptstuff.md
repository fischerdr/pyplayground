Review this repo and give an assessment of the code and what should or could be refactored
create a new assessment document in docs/
then review the @docs/DEVELOPMENT_STANDARDS.md as it can be to this flask application and recreate @AGENTS.md 
@app_backend.py and @index.html should not be tocked or changed as they are the source of truth. this must be stated in @AGENTS.md 
If logging to console is needed as a flask app then that should be allowed
logging should go in to a directory at top of project called logs/
virtual environment must be called out as critical usage!
create a pyproject.toml and add entries for isort,black, anf flake8
also move the requirements.txt into the pyproject.toml and requirements should be generated as pyproject.toml is source of truth




now review @docs/CODE_ASSESSMENT_NEW.md @docs/code_assessment.md @docs/refactoring/REFACTORING_ANALYSIS.md and @docs/refactoring/SPRINT_PUNCHLIST.md 
plan  a document out lining the step phases in small chunks
based off @docs/refactoring/SPRINT_PUNCHLIST.md 
make sure to read all files in full to get the entire context
tasks should be stopped between and new code verified
pytests should be generated also for unit testing



You are a senior software architect tasked with analyzing a monolithic codebase and creating a comprehensive refactoring plan. Your goal is to produce two detailed documents:

1. **REFACTORING_ANALYSIS.md** - A complete analysis of the current codebase structure
2. **SPRINT_PUNCHLIST.md** - A detailed, actionable task breakdown for modularization

### Context

- **Source File**: `app_backend.py` (~9,008 lines)
- **Project**: Holy Grail AI System - an autonomous multi-agent application generator
- **Framework**: Flask backend
- **Constraint**: The source file must NEVER be modified during refactoring. All line references must remain stable.

### Task 1: Generate REFACTORING_ANALYSIS.md

Analyze `app_backend.py` and create a comprehensive analysis document with the following sections:

#### Required Sections

1. **Header Metadata**
   - File path and size
   - Analysis date
   - Status indicator (ANALYSIS ONLY)

2. **Executive Summary**
   - High-level description of what the file does
   - List of major functional areas (configuration, memory, crawling, LLM, code generation, browser automation, routes, etc.)
   - Problem statement: why refactoring is needed (size, maintainability, LLM context limits)

3. **Current File Structure (Detailed)**
   - Break down the file into logical sections with line number ranges
   - For each section, list:
     - What classes/functions it contains
     - Key responsibilities
     - Approximate line count
   - Number sections sequentially (Section 1, Section 2, etc.)

4. **Major Concerns & Boundaries**
   - Complexity issues (monolithic classes, deep nesting, circular dependencies, global state, duplicate logic)
   - Maintainability issues (duplication, sprawl, magic strings, inconsistent patterns)
   - Testing barriers (API dependencies, file I/O coupling, async/sync mixing)

5. **Proposed Modular Structure**
   - Create a directory tree showing the new package structure
   - List each module with:
     - Estimated line count
     - Primary purpose
     - Key classes/functions it will contain
   - Organize into logical groups (config, utilities, core systems, routes, etc.)

6. **Refactoring Strategy**
   - Break into phases (Phase 1, Phase 2, etc.)
   - For each phase:
     - List what modules will be extracted
     - Estimated duration
     - Benefits of completing that phase

7. **Dependency Graph**
   - Create a visual/text representation showing:
     - Which modules depend on which
     - Layers (lowest level → highest level)
     - Critical extraction order

8. **Circular Dependency Risks & Resolution**
   - Identify potential circular dependencies
   - For each risk:
     - Describe the problem
     - Propose a solution (dependency injection, lazy imports, interface layers, etc.)

9. **File Size Estimates (Post-Refactoring)**
   - Table showing each module, its estimated lines, and primary purpose
   - Total estimated size reduction

10. **Testing Strategy Post-Refactoring**
    - Unit testing approach (per module)
    - Integration testing (between modules)
    - End-to-end testing (full workflows)

11. **Migration Checklist**
    - Before starting (backup, tagging, documentation)
    - During refactoring (extraction order, verification steps)
    - After refactoring (testing, review, deployment)

12. **Benefits of Refactoring**
    - For development (locatability, clarity, iteration speed, onboarding)
    - For AI/LLM integration (context window limits, module purpose, independent enhancement)
    - For testing & quality (unit tests, mocking, debugging, coverage)
    - For maintenance (cognitive load, impact radius, git history)

13. **Notes on Existing Monkey Patches**
    - Document any monkey patching found
    - Explain why it exists (technical debt indicator)
    - Describe post-refactoring approach (keep final versions, delete dead code, use proper inheritance)

14. **Estimated Effort**
    - Breakdown by phase
    - Total estimated time

15. **Recommendation**
    - Priority level
    - Justification
    - Suggested starting point

### Task 2: Generate SPRINT_PUNCHLIST.md

Create a detailed, actionable sprint punchlist with the following structure:

#### Required Sections

1. **Header**
   - Sprint goal (build modular replacement)
   - Critical constraint (source file never modified)
   - Source file path and size
   - Target package name

2. **Dead Code & Duplicates Registry**
   - Table listing:
     - Original definition (name, line range)
     - Superseded by (name, line range)
     - Action (extract only final version, merge, etc.)
   - Identify all monkey patches and their final versions

3. **Package Directory Structure**
   - Complete directory tree of target package
   - File names with brief comments explaining purpose

4. **Task List**
   - Numbered tasks (Task 1, Task 2, etc.)
   - For each task, include:
     - **Status**: [ ] Not Started checkbox
     - **Parallel Group**: Letter (A, B, C, etc.) or "Sequential"
     - **Source Lines**: Exact line ranges from source file
     - **Output File(s)**: Target file path(s)
     - **Description**: Detailed explanation of what to extract and how
     - **Acceptance Criteria**: Bulleted list of verification steps
     - **Dependencies**: List of prerequisite task numbers

5. **Parallel Execution Groups**
   - Table showing:
     - Group identifier
     - Tasks in that group
     - Description of group purpose
     - Prerequisites

6. **Optimized Execution Timeline**
   - Visual/text representation of task dependencies
   - Shows parallel execution opportunities

7. **Dependency Graph (Condensed)**
   - Visual representation of module dependencies
   - Shows extraction order

8. **Summary Table**
   - Total tasks
   - Breakdown by category (extraction, routes, infrastructure, tests)
   - Max parallel width
   - Estimated effort
   - Dead code eliminated
   - Expected size reduction

### Instructions for Analysis

1. **Read the entire source file** carefully, noting:
   - All class definitions with line numbers
   - All function definitions with line numbers
   - All route handlers with line numbers
   - All monkey patches and their locations
   - Import statements and their locations
   - Global variables and their locations

2. **Identify logical sections** by grouping related code:
   - Configuration and initialization
   - Utility functions
   - Core classes (one per major responsibility)
   - Route handlers (group by domain)
   - Monkey patches and enhancements

3. **Map dependencies** by analyzing:
   - Import statements
   - Function calls
   - Class instantiations
   - Global variable usage

4. **Identify dead code** by finding:
   - Functions/classes that are superseded by monkey patches
   - Duplicate implementations
   - Unused imports
   - Redundant definitions

5. **Design modular structure** by:
   - Grouping related functionality
   - Ensuring each module has a single responsibility
   - Keeping modules under 600 lines (ideally under 300)
   - Creating clear dependency layers

6. **Create extraction tasks** by:
   - One task per module/component
   - Including exact line references
   - Specifying which version to extract (if multiple exist)
   - Defining clear acceptance criteria
   - Identifying dependencies

7. **Organize parallel execution** by:
   - Grouping independent tasks
   - Identifying sequential dependencies
   - Maximizing parallelization opportunities

### Output Format

- Both documents should be in Markdown format
- Use clear section headers (##, ###)
- Include tables where appropriate
- Use code blocks for directory trees and dependency graphs
- Number all tasks sequentially
- Include line number references throughout
- Use checkboxes for task status tracking

### Quality Criteria

The analysis should be:

- **Comprehensive**: Cover all aspects of the codebase
- **Accurate**: Line numbers and references must be correct
- **Actionable**: Tasks must have clear acceptance criteria
- **Organized**: Logical grouping and clear dependencies
- **Realistic**: Effort estimates should be reasonable
- **Safe**: Preserve all functionality while improving structure
