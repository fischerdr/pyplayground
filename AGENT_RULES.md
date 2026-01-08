Repository Agent Governance and Operating Rules

## Purpose and Authority

This file defines the **minimum required rules, constraints, and operating boundaries** for all automated agents acting within this repository, regardless of vendor, model, execution environment, or invocation method.

These rules apply equally to:

* Code-writing agents
* Refactoring agents
* Documentation agents
* Analysis or inspection agents
* Interactive or non-interactive automation

Tool-specific instruction files may exist to provide additional detail or workflow guidance. Such files **must not relax, override, or contradict** any rule defined here.

If a stricter rule exists elsewhere, that stricter rule is implicitly required for all agents unless explicitly scoped otherwise.

In all cases of ambiguity or conflict, **this file takes precedence**.

---

## Project Configuration (Single Source of Truth)

**CRITICAL**: This project uses `pyproject.toml` as the single source of truth for all configuration.

### Scope of `pyproject.toml`

`pyproject.toml` defines and governs:

* Project dependencies
* Optional development dependencies
* Tool configuration (formatters, linters, type checkers, test runners)
* Package metadata
* Code standards and formatting rules

Agents **must consult `pyproject.toml` before proposing or making changes** that affect configuration, dependencies, or tooling.

### Prohibited Actions

Agents must not:

* Manually edit `requirements.txt`
* Introduce standalone configuration files (for example `.flake8`, `.isort.cfg`, etc.)
* Duplicate configuration already defined in `pyproject.toml`
* Assume default tool behavior without checking configuration

All dependency changes must be made in `pyproject.toml`.

---

## Agent Authorization Boundaries

Agents are not autonomous decision-makers. Their authority is limited to the scope explicitly granted by the user and constrained by this file.

Unless explicitly instructed otherwise, agents must assume the following actions are **not authorized**:

* Creating new documentation files
* Modifying existing documentation files
* Introducing architectural refactors
* Performing cross-layer changes
* Performing large-scale cleanups or rewrites
* Modernizing code for style or consistency alone

When authorization is unclear, the correct behavior is to **stop and request clarification** before proceeding.

---

## Repository Structure and Architectural Integrity

This repository follows a layered architecture with clear separation of concerns.

Agents must respect architectural boundaries and must not blur responsibilities between layers unless explicitly instructed.

Key principles:

* Each layer has a defined role
* Cross-layer changes carry high risk
* Improvements in one layer must not implicitly reshape others

Agents must not “improve” architecture opportunistically.

---

## Legacy Code Handling and Modernization Guardrails

This repository contains a legacy Python 2.x codebase under active, phased modernization.

Agents must adhere to the following constraints:

* Legacy patterns must not be altered unless required for correctness or explicitly authorized
* Stylistic modernization alone is not a valid justification for change
* Deprecated constructs may remain intentionally until their scheduled replacement phase
* Cross-layer refactors are prohibited without explicit instruction
* Modernization must follow documented phase order and scope

Agents must not pre-modernize code in anticipation of future phases.

---

## Binary Compatibility (Hard Requirement)

**Binary compatibility is non-negotiable.**

For any work involving file format parsers, serializers, binary I/O, or resource handling:

* Byte-for-byte equivalence after load/save cycles is mandatory
* Binary layout, ordering, field sizes, signedness, and encoding must not change
* Perceived improvements, refactors, or cleanup do not justify incompatibility

Agents must treat binary compatibility as a hard stop condition.

---

## Mandatory Validation Workflow for Binary Changes

When modifying any binary-related code:

* Original input files must be preserved for comparison
* Output must be verified as byte-identical to the input
* Validation must be performed using real Neverwinter Nights assets
* Successful parsing alone is insufficient; written output must also be loadable by the game

If validation is incomplete, uncertain, or unavailable, the change must not proceed.

---

## Change Scope Discipline

Agents must limit changes to the smallest scope necessary to achieve the stated goal.

Unless explicitly authorized, agents must not:

* Touch unrelated files
* Reformat code opportunistically
* Normalize patterns across the codebase
* Replace deprecated constructs outside the task scope
* Combine unrelated changes into a single proposal

Broad cleanup is not an acceptable substitute for targeted correctness.

---

## Testing Expectations

The absence of an existing automated test suite does not reduce correctness expectations.

When tests exist:

* They must be updated or extended as necessary
* All relevant tests must pass before changes are considered complete

When tests do not exist:

* Agents must propose appropriate tests
* Agents must describe how correctness was validated
* Static analysis alone is insufficient for validation

Testing rigor increases, not decreases, when working with legacy or binary-sensitive code.

---

## Documentation Creation and Modification Policy

Documentation is a controlled artifact.

Agents must not create, modify, or expand documentation unless explicitly instructed.

When documentation work is authorized:

* Documentation must be professional and text-only
* Emojis, icons, branding, or stylistic embellishments are prohibited
* Content must reflect actual behavior and decisions, not speculation

Unsolicited documentation is considered an error.

---

## Commit and Attribution Rules

Agents must produce clean outputs suitable for long-term maintenance.

Unless explicitly instructed otherwise, agents must not:

* Add tool, model, or vendor attribution
* Add co-authorship markers
* Include branding, signatures, or automation credits

All changes must appear as if authored by a human contributor following repository norms.

---

## Conservative Failure Mode

When faced with ambiguity, incomplete information, or conflicting signals:

* The default behavior is to stop
* The correct action is to request clarification
* Proceeding with assumptions is prohibited

Correctness, safety, and reversibility take precedence over speed or completeness.

---

## Final Principle

Agents operating in this repository are expected to behave conservatively, predictably, and with respect for long-term maintainability.

The goal is not maximal automation.
The goal is **controlled, auditable, and correct change**.

---

