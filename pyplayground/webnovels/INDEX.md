# Doc Index

Read this first. Every task prompt should point here, not at a list of
files — this is the single place that says what exists and what it's for.

Rule of thumb: **only read what your specific task actually touches.**
Nothing below needs to be read "in full" as a default — point at the
specific section a task needs.

| Doc | What it's for | Status |
|---|---|---|
| `PICKUP_LIST.md` | **Start here for "what's next."** Living, tiered task list (Now / Someday-Maybe / Opportunistic / Recently closed) across every doc below. | Living. Update directly when items move tiers, get done, or get added. |
| `GLOSSARY_ARCHITECTURE.md` | **Current-state reference.** How the glossary/masking/translation pipeline actually works right now — read this to understand the system, not to find decision history. | Current, read-only reference. Refreshed 2026-08-02. |
| `DESIGN.md` | Glossary/masking feature: decision history, current open questions (§8), currently-unresolved findings (§13). | Active. Split 2026-07-31 — closed/historical entries moved out (see §14's index). |
| `DESIGN_ARCHIVE.md` | Fully closed, historical entries moved out of `DESIGN.md` to keep it lean. Nothing here is actionable. | Archive only. Read only if a task specifically needs the "why" behind something already resolved. |
| `RETRANSLATION_DESIGN.md` | Line-level retranslation feature (select a word, get a corrected translation, accept/persist). | **All 5 phases complete.** No open work. |
| `REFACTOR_DESIGN.md` | Module split (`alphapolis_reader.py` → `ReaderRenderer` + `GlossaryCoordinator`) and the write-race/incremental-extraction fixes that came with it. | **Phase 3 (a-g) complete.** Phase 4 (revisit core app shell) undecided/not started — no active work. |
| `WINDOW_REDESIGN.md` | Toolbar/menu reorganization + the three glossary dialogs' own layouts. | **Phases 2-3 complete (2026-08-02).** Phase 4 investigation complete (2026-08-02); implementation next on the pickup list. |
| `agents-ui-testing.md` | *How-to*, not decisions: Xvfb setup, `run_ui_tests.sh`, `xdo_helper.py`/`log_correlator.py` usage, known environment quirks (leaked window/thread issues, screenshot gotchas). | Living reference, update when a new testing gotcha is found. |
| `safe_persistence.py` (module docstring) | Design + implementation record for the atomic-write and verify-before-write helpers in `pyplayground/utils/`. | **Implemented and migrated.** No open work. |

## Quick routing

- **"What should I work on next?"** → `PICKUP_LIST.md`.
- **"How does X currently work?"** → `GLOSSARY_ARCHITECTURE.md`.
- **"Why was X built this way / what's still open in the glossary system?"** → `DESIGN.md` (§8 open questions, §13 unresolved findings).
- **"I need historical detail on something already closed."** → `DESIGN_ARCHIVE.md`.
- **"Working on retranslation, refactor, window layout, or test infra?"** → that specific doc, not the others.
- **New doc?** Only if none of the above answers a close-enough version of the question. Split any doc once it crosses ~500 lines.
