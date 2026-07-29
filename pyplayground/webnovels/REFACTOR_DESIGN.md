# Reader Module Split & Glossary Coordinator — Design Doc

Living record of decisions for this refactor. Update alongside code
changes, not after — chat history is not the system of record. Third
doc alongside `DESIGN.md` (glossary/masking feature) and
`RETRANSLATION_DESIGN.md` (line-level retranslation feature), tracked
separately because this is a structural refactor of the codebase itself,
not a feature — it exists to make the other two docs' work easier to
build on safely going forward, not to add new user-facing behavior.

Last updated: 2026-07-28

---

## Why this started

Two independent observations, from actually using and extending the
codebase, turned out to be the same underlying problem:

1. **The same bug class has now been found and fixed/named three
   separate times**, always in the shape "something loads a full
   in-memory snapshot once, writes it back once, and something else
   writes to the same underlying file in between": `open_glossary_dialog()`
   vs. `open_term_review_dialog()` (found and fixed, `DESIGN.md`); and
   `build_glossary_for_novel()`'s background extraction vs. either manual
   dialog (found and named, not yet fixed, `DESIGN.md`). This isn't three
   unrelated bugs — it's one design pattern (independent load/write pairs
   against shared state) that keeps reappearing because each new glossary
   UI surface (right-click popup, then bulk review, then rebuild) was
   added by copying the pattern of the last, rather than factoring out a
   shared foundation once.
2. **`alphapolis_reader.py` is over 2,000 lines** and holds several
   genuinely distinct concerns in one file: the core app shell (browser
   lifecycle, episode load/cache/navigation), reader rendering (every
   view mode's renderer, span tracking, appearance/theming), three
   glossary dialogs, and the retranslation dialog.

These reinforce each other: the file-size problem is largely a symptom
of the same bolt-on growth pattern that produced the repeated bug class,
not a separate issue. Splitting the file mechanically without also
building the shared coordinator would just relocate the bug pattern into
more files; building the coordinator without splitting the file would
leave it awkwardly bolted onto an already-oversized module.

**A second, related symptom, found independently while debugging across
this whole session**: hand-built test harnesses in
`tests/webnovels/test_alphapolis_reader.py`,
`test_retranslation_dialog.py`, and `test_retranslation_display.py`
mix in real `ReaderApp` methods directly but construct their own
`__init__` rather than inheriting `ReaderApp`'s. At least three separate
times this session, adding a new instance attribute to `ReaderApp` broke
one of these harnesses with `AttributeError` until manually patched — not
because the fix under test was wrong, but because the harness doesn't
actually model the real class. This is the test-layer version of the
same bolt-on problem: several independent hand-rolled approximations of
"a testable `ReaderApp`" instead of one correct, shared way to build one.

## Goals

- One shared glossary-access coordinator: owns loading, the
  re-check-before-write/merge-by-source logic (already built once for
  `open_glossary_dialog()`'s fix — reusable, not to be reimplemented),
  tracking whether a background rebuild is currently running for a given
  novel, and the auto-refresh-trigger hook (`DESIGN.md`'s
  `_maybe_refresh_after_glossary_edit()`). All three glossary dialogs and
  `build_glossary_for_novel()` route through it instead of each doing
  their own `load_glossary()`/`save_glossary()` pair.
- Split `alphapolis_reader.py` into modules along genuine concern
  boundaries (core app shell / rendering / glossary dialogs+coordinator /
  retranslation dialog) — exact boundaries and construction pattern
  (mixins vs. composition vs. something else) to be determined by Phase 1's
  investigation against the real code, not dictated up front without
  evidence.
- Fix the fragile hand-rolled test-harness pattern as a first-class goal
  of this refactor, not an afterthought — replace with either a real,
  properly-subclassed `ReaderApp` test fixture or well-defined shared
  fixtures per module boundary, so a new instance attribute is inherited
  automatically instead of needing every harness patched individually.
- **Fold in, rather than fix standalone first**: the extraction-vs-dialog
  race (`DESIGN.md`, background-extraction investigation entry) and
  extraction's non-incremental cost (same entry) — both become natural
  consequences of centralizing glossary writes through one coordinator,
  rather than separate patches that the coordinator would later need to
  reconcile with or duplicate.

## Explicitly NOT blocked on this refactor

Independent work that touches different files or a narrow, self-contained
piece of `glossary.py`'s policy logic — no reason to wait:
- Short-prompt glossary-context reliability check (`RETRANSLATION_DESIGN.md`).
- `RETRANSLATION_DESIGN.md` Phase 4 (`line_overrides` persistence).
- `DESIGN.md` §8 promotion/threshold logic.

**Explicitly sequenced after this refactor** (would otherwise become a
fourth independent write path, repeating the exact mistake this refactor
exists to fix): the expanded global-terms store (`RETRANSLATION_DESIGN.md`
Phase 5) — should be built against the coordinator's real shared access
pattern from day one, not added before it exists.

## Phases

Sequenced low-risk-and-informative first, highest-value-and-highest-risk
last — same discipline as every phased effort in the other two docs.

1. **Investigation & concrete proposal — no code changes.** Map
   `ReaderApp`'s full method/attribute surface, group by actual concern
   (not assumed groupings), identify cross-group dependencies (which
   methods/attributes are read/written across what would become module
   boundaries — this is the part that determines whether a clean split
   is even straightforward or needs real design work), and produce a
   concrete proposal: file/module boundaries, the construction pattern
   (mixins composed via multiple inheritance, composition with an
   explicit coordinator object, or something else — decided from evidence,
   not assumed), the coordinator's actual interface, and a migration
   order for the remaining phases. Also proposes the test-reorganization
   approach. This phase's only deliverable is the proposal itself,
   appended to this doc — nothing is implemented yet.
2. **Extract reader rendering** into its own module, per Phase 1's
   findings — expected to be the lowest-risk split (rendering methods are
   already relatively self-contained; `RETRANSLATION_DESIGN.md` Phase 1
   already reasoned about reusing the existing tag mechanism without
   touching core app-shell logic). Includes migrating/fixing that
   module's tests as part of this phase, not deferred to a later
   catch-all.
3. **Extract glossary dialogs + build the coordinator** — highest value
   (directly addresses the repeated bug class) and highest risk (three
   dialogs' worth of live Tk state, event bindings, and closures). Folds
   in the extraction-vs-dialog race fix and the incremental-extraction
   fix as natural consequences of centralizing writes, per this doc's
   goals above. Includes fixing the fragile hand-rolled harness pattern
   for glossary-related tests specifically, since that's where it broke
   most often this session.
4. **Extract the retranslation dialog** into its own module — already
   logically separate per `RETRANSLATION_DESIGN.md`'s own framing.
   Includes the same harness-fragility fix applied to retranslation's
   test files.
5. **Revisit the core app shell**, if it's still unwieldy after phases
   2-4 — not scoped in detail yet; whether this is even needed depends on
   how much phases 2-4 already shrink it.

## Status

- **Phase 1**: complete (2026-07-28, investigation and proposal only, see dated entry below). No code changes.
- **Phase 2**: complete (2026-07-28, rendering extracted into `ReaderRenderer`; re-audited 2026-07-28, see dated entries below).
- **Phase 3**: sub-plan defined (2026-07-29). **3a complete** (2026-07-29, `GlossaryCoordinator` built standalone). **3b complete** (2026-07-29, `open_word_glossary_popup()` wired). **3c complete** (2026-07-29, `open_term_review_dialog()` wired). **3d complete** (2026-07-29, `open_glossary_dialog()` wired, see dated entry below). 3e-3g not started.
- **Phases 4-5**: not started, contingent on Phase 3's findings.

### 2026-07-29: Phase 3d -- `open_glossary_dialog()` wired through `GlossaryCoordinator`

Per the Phase 3 sub-plan's guardrails below: self-contained, did not
read ahead into 3e-3g.

**Mandatory first step, completed before any code change: full-repo
call-site inventory.** Grepped the entire repository (not just
`alphapolis_reader.py`/`tests/`) for every real call to `load_glossary`,
`save_glossary`, `upsert_confirmed_term`, `merge_terms`,
`make_confirmed_term`, `make_suggested_term`, and separately grepped the
whole `tests/` tree (not just files with "glossary" in the name) for
`monkeypatch.setattr`/`mocker.patch` targeting `load_glossary`/
`save_glossary` at the `alphapolis_reader` module level. Confirmed via
`grep -rln "from pyplayground.webnovels.glossary import"` that no
directory outside `pyplayground/webnovels/` and `tests/` imports from
`glossary.py` at all -- this is a genuinely complete inventory, not a
narrowed one.

| File:Line | Function | Called from | Status |
|---|---|---|---|
| `alphapolis_reader.py:930` | `load_glossary` | `_render_interleaved_content()` | Read-only rendering lookup -- deliberately not wired (Phase 1's explicit recommendation: rendering needs the *unfiltered* glossary, a different concern than write-coordination, not a load/write pair). |
| `alphapolis_reader.py:985` | `load_glossary` | `_render_translated_view()` | Same as above -- read-only rendering lookup. |
| `alphapolis_reader.py:1628` | `load_glossary` | `_do_fetch_and_translate()` | Read-only, builds prompt context for a live translation call. This function is the *other* side of the extraction-vs-dialog race named in `REFACTOR_DESIGN.md` §4/§5 -- Phase 3e's territory, not this step's call site to touch. |
| `alphapolis_reader.py:1681` | `save_glossary` | `_do_fetch_and_translate()` (via `update_candidate_counts()`'s returned dict) | Write path for the count-building loop, not a dialog. Same reasoning -- Phase 3e's territory. |
| `alphapolis_reader.py:1845` | `load_glossary` | `open_glossary_dialog()` (dialog-open load) | **Left as a direct call, deliberately** -- feeds `opened_updated_at`, which `GlossaryCoordinator.save_snapshot()` needs as a parameter (it has no way to know this on its own); the coordinator's own internal reload happens separately, inside `save_snapshot()`. |
| `alphapolis_reader.py:2200` (post-wiring) | -- | `open_glossary_dialog()`'s `clear_glossary()` | **Wired this step** -- was `save_glossary(novel_id, glossary)` directly, now `GlossaryCoordinator(novel_id).clear()`. |
| `alphapolis_reader.py:2224` (post-wiring) | -- | `open_glossary_dialog()`'s `save_and_close()` | **Wired this step** -- was the full reload/merge/write block (`load_glossary`+manual merge+`save_glossary`), now `GlossaryCoordinator(novel_id).save_snapshot(...)`. |
| `alphapolis_reader.py:2100` | `make_confirmed_term` | `open_glossary_dialog()`'s `add_term()` | Pure constructor call, no read/write -- nothing to wire. |
| `alphapolis_reader.py:2292` | `load_glossary` | `open_term_review_dialog()` (dialog-open load) | Already correct as of 3c -- untouched, not this step's concern. |
| `alphapolis_reader.py:2937` | `load_glossary` | `open_retranslate_popup()` (prompt context) | Read-only, Group D territory (Phase 4, not Phase 3) -- confirmed no write pair. |
| `alphapolis_translate.py:218` | `load_glossary` | `main()` (standalone CLI script) | Read-only, feeds `format_glossary_for_prompt()` for a one-shot translation, never writes. Deliberately not wired -- no write path exists here to coordinate. |
| `compare_translations.py:170` | `load_glossary` | (translation-quality comparison script) | Same as above -- read-only, standalone script, no write path. |
| `build_glossary.py:385` | `load_glossary` | `build_glossary_for_novel()` | **Deliberately not wired in this step** -- named explicitly, not silently skipped: this is the load-once/save-once-over-a-whole-episode-loop pattern `REFACTOR_DESIGN.md` §4/§5 already scopes as Phase 3e's territory (the extraction-vs-dialog race fix, via `GlossaryCoordinator.start_rebuild()`/`is_rebuild_running()`). A genuinely different write shape than `save_snapshot()`/`upsert_confirmed()`/`reject()`/`clear()` -- merges LLM extraction output in bulk across many episodes, a different trust level than a single human-reviewed term. |
| `build_glossary.py:405` | `merge_terms` | `build_glossary_for_novel()` | Same call site -- bulk-merge trust level, per `glossary.py`'s own `merge_terms()` docstring (dedupes on `(type, source)`, a different, deliberately looser rule than `upsert_confirmed_term()`'s dedupe-by-source-alone for human-confirmed edits). Phase 3e's territory. |
| `build_glossary.py:425` | `save_glossary` | `build_glossary_for_novel()` | Same -- Phase 3e's territory. |
| `build_glossary.py:326` | `make_suggested_term` | `_to_suggested_term_dicts()` | Pure constructor, no read/write -- nothing to wire. |
| `alphapolis_reader.py:2140-2182` (`rebuild_glossary()`, inside `open_glossary_dialog()`) | calls `build_glossary_for_novel()` directly | -- | The *other* existing call site of the same Phase-3e-territory function, reached from inside the dialog this step wires. **Left untouched deliberately** -- confirmed textually inside this step's own dialog, but `is_rebuild_running()`/`start_rebuild()` wiring for this exact call site is explicitly Phase 3e's job per the sub-plan, not 3d's, even though it lives inside the file/method 3d touches. |

Nothing found that was neither already-wired nor explicitly justified --
every real call site outside this step's two targets is either read-only
(no write pair to coordinate) or Phase 3e's already-scoped territory.

**Test-file mock-target inventory** (the whole `tests/` tree, not just
"glossary"-named files):

- `test_alphapolis_reader.py` -- three affected classes, all constructing
  real `open_glossary_dialog()` instances, all retargeted this step:
  `TestGlossaryDialogSelection._open_dialog()`,
  `TestGlossaryDialogAutoRefresh._open_glossary_dialog()`, and
  `TestGlossaryDialogMergeOnDivergence` (three tests, previously mocking
  `load_glossary`/`save_glossary` together as one function called twice
  from one module -- now genuinely two different module-level references,
  since the dialog-open load stays in `alphapolis_reader` while the
  reload-before-write moved into `glossary_coordinator`'s `save_snapshot()`;
  this needed two separate mocks per test, not just a retarget, and one
  assertion's expected `call_count` changed from `2` to `1` to match).
- `test_retranslation_dialog.py:290,416` -- mocks `load_glossary` only,
  for `open_retranslate_popup()`'s prompt-context read (Group D,
  untouched by this step) -- confirmed **not** affected; different call
  site entirely.
- `test_term_review_dialog.py` -- already retargeted in Phase 3c; not
  touched again (different dialog, unaffected by this step).
- `test_glossary_coordinator.py` -- already targets `glossary_coordinator`
  correctly (built directly against the coordinator since 3a).

**A real mismatch found and resolved, not forced: `clear_glossary()`
does not fit `save_snapshot()`'s contract.** `save_snapshot()` is built
for an *edited* snapshot -- it always sets `honorific_policy_user_set =
True` (the caller deliberately chose a policy) and never touches
`context_notes`. `clear_glossary()`'s real behavior resets
`honorific_policy_user_set` to `False` and `context_notes` to `""` --
fields `save_snapshot()`'s contract doesn't cover, since a Clear is an
unconditional reset the user explicitly asked for, not an edited
snapshot to merge against a concurrent writer. Forcing Clear through
`save_snapshot()` would have silently dropped both fields. Resolution:
added a new, dedicated `GlossaryCoordinator.clear()` method (reload
fresh via `load()`, same re-check discipline every other write path
here uses, then reset `terms`/`honorific_policy`/
`honorific_policy_user_set`/`context_notes`/`updated_at` and save) --
a genuine extension of the coordinator's interface, not a workaround,
matching this dialog's real, distinct write shape.

**Dead-code sweep, per this step's mandatory second requirement**:
- `flake8` caught two now-unused things after wiring:
  `DEFAULT_HONORIFIC_POLICY`'s import in `alphapolis_reader.py`
  (its only real call site was `clear_glossary()`'s direct reset, now
  moved into `GlossaryCoordinator.clear()`) and the `datetime`/`timezone`
  import (both `save_and_close()`'s and `clear_glossary()`'s
  `datetime.now(timezone.utc).isoformat()` calls moved into the
  coordinator too -- confirmed via `grep` that zero real usages of
  either remained anywhere else in the file before removing). Both
  removed.
- Confirmed `load_glossary`/`save_glossary` are still genuinely needed
  in `alphapolis_reader.py`'s own imports (rendering reads,
  `_do_fetch_and_translate()`, `open_glossary_dialog()`'s own
  `opened_updated_at`-feeding load, `open_term_review_dialog()`'s own
  dialog-open load, `open_retranslate_popup()`'s prompt-context read) --
  not removed.

**Tests**: 8 new tests in `test_glossary_coordinator.py` --
`TestClear` (4, unit tests against the new coordinator method directly:
empties all terms, resets honorific policy/`honorific_policy_user_set`,
resets `context_notes`, reloads fresh before writing) and
`TestOpenGlossaryDialogRoutesThroughCoordinator` (4, driving the real,
unmodified `open_glossary_dialog()` end-to-end through its actual
Save/Clear Glossary buttons -- two "fails loudly if called directly"
tests and two "on-disk result matches the user-visible pre-refactor
shape" tests, same standard as 3b/3c). Plus the four
`TestGlossaryDialogMergeOnDivergence` tests in `test_alphapolis_reader.py`,
retargeted rather than newly written, since they already existed as the
authoritative regression coverage for the exact logic being moved.

**Confirmed load-bearing, not just passing incidentally**: reverted
`alphapolis_reader.py`'s and `glossary_coordinator.py`'s wiring via
`git stash` and re-ran the 8 new tests plus all three
`TestGlossaryDialogMergeOnDivergence` tests -- all 11 failed cleanly
(`AssertionError`s from the fail-loud guards, `AttributeError: no
attribute 'clear'`, `KeyError`s from coordinator-aimed mocks never
firing against the reverted direct-call code). Restored via
`git stash pop`, confirmed via `grep` before continuing.

**Checkpoint, confirmed, not assumed**:
- Full `tests/webnovels/` suite: **265 passed** (up from 257 -- exactly
  the 8 new tests, zero regressions), same 2 pre-existing flaky-crash
  sources deselected (`TestFetchAndTranslateDuplicateGuard`'s duplicate-
  fetch test, `TestPopupSingleInstanceGuard`'s leaked-thread test, both
  named in 3c's own entry), same 6 live-display UI-automation tests
  erroring only for lack of an Xvfb display in that offline run. Ran the
  full suite 5 times total across this step (3 with the known flaky
  sources deselected, 2 without) to check specifically for a *new* flaky
  source introduced by this step -- all 5 passed clean, consistent with
  3c's own flaky rate, not worse.
- `black`/`isort`/`flake8` clean on all four touched files.
- **Live verification**, via `pyplayground/webnovels/ui_testing/
  run_ui_tests.sh xvfb-keep` (not manual `xdotool`), against novel
  `777777777`'s real backlog (10 terms as of the end of 3c: 8
  `suggested`, `鉄パイプ`/`弁護士` `confirmed`):
  - **Stale-form-bug scenario**: selected `ケイト` (row A), edited its
    Target field to "Kate" without saving, then clicked `ルリ` (row B)
    without saving -- screenshots confirm B's form correctly showed its
    own data (Source: ルリ, Note: female, Target: blank), not A's
    unsaved "Kate" edit leaking across. `log_correlator.assert_clean()`
    clean for the row-switch click.
  - **Merge-on-divergence scenario**: simulated a concurrent writer by
    confirming `教授` directly on disk (same technique 3c/`DESIGN.md`
    established, since this dialog's `win.grab_set()` modality blocks
    the interactive two-dialogs-open reproduction) while the real
    dialog sat open with its now-stale in-memory snapshot (screenshot
    confirms the Treeview still showed `教授` as "suggested" at that
    point, proving the snapshot really was stale) -- edited a genuinely
    unrelated term (`世紀末モヒカンムーブ`)'s Target field and clicked
    Save. **On-disk read directly afterward confirmed both survived**:
    `教授` stayed `confirmed`/`Professor` (not reverted by this
    dialog's stale snapshot), `世紀末モヒカンムーブ` correctly gained
    `confirmed_target: "apocalyptic mohawk move"` (the full text,
    confirming an earlier screenshot's apparent truncation was a
    display-scroll artifact, not a real data-loss bug). Log clean, and
    the expected `"Glossary for novel 777777777 changed on disk while a
    snapshot was held ... merging by source instead of overwriting"`
    INFO line fired, correctly attributed to
    `pyplayground.webnovels.glossary_coordinator` (not
    `alphapolis_reader`) -- confirming the merge branch genuinely ran
    inside the coordinator, not a leftover direct-call path.
  - **An unexpected finding during this verification, investigated and
    confirmed pre-existing, not a 3d regression**: after Save, several
    *other* terms (`ケイト`, `ルリ`, `ダンジョン能力者`) also came back
    `confirmed` on disk, not just the two terms this verification meant
    to touch. Investigated rather than assumed: `open_glossary_dialog()`'s
    `commit_selected_form()` runs on every row-selection change (the
    existing `<<TreeviewSelect>>` binding), and `save_form_to_term()`
    unconditionally sets `status = STATUS_CONFIRMED` on whatever term is
    currently displayed -- confirmed via direct code read
    (`alphapolis_reader.py`'s `save_form_to_term()`, unchanged by this
    step) that this is the dialog's existing, pre-3d "edit anything,
    Save commits everything you touched this session" contract, not
    something 3d's wiring introduced. This verification's own row-by-row
    navigation (clicking through `ケイト` -> `ルリ` -> `ダンジョン能力者`
    -> `世紀末モヒカンムーブ` to demonstrate the stale-form-bug scenario)
    touched each of those rows along the way, and each got committed as
    confirmed by that pre-existing mechanism -- not a merge-logic defect.
  - The synthetic novel's glossary file was backed up before this
    verification and restored to its Phase-3c-ending state afterward
    (unlike 3c's own backlog-progress data, this step's on-disk changes
    were largely a side effect of test navigation rather than deliberate
    backlog work, so restoring was the right call here). Dialog closed
    via its own real Cancel button throughout (never `windowclose`). App
    terminated via `kill -TERM` on the tracked PID, confirmed dead.
    Whole-session log swept for `ERROR`/`CRITICAL`: none found.
    Xvfb/fluxbox confirmed torn down cleanly after the run.
- **Environment note carried forward from 3c, reconfirmed**: no
  `ttk.Combobox` interaction was needed in this step's live verification
  (this dialog's own Type combobox wasn't exercised this time), so the
  keyboard-navigation workaround wasn't re-tested here, but remains the
  documented approach for any future combobox interaction in this
  dialog's own live verification.

**Net result**: `open_glossary_dialog()`'s Save and Clear Glossary
actions now route through `GlossaryCoordinator.save_snapshot()`/`clear()`;
on-disk behavior (including the merge-on-divergence and stale-form-bug
cases) is unchanged from the user's perspective, confirmed both by test
and by a real live sequence. A genuine coordinator-interface gap
(`clear()`) was found and filled with a dedicated method, not forced
into an ill-fitting one. The mandatory call-site inventory found nothing
outside this step's two targets that was neither already-wired nor
explicitly justified.

**Not done in this step, deliberately, per the guardrails**: no changes
to the extraction-vs-dialog race fix or rebuild-tracking wiring (3e,
including `rebuild_glossary()`'s own `build_glossary_for_novel()` call,
confirmed textually inside this step's dialog but explicitly out of
scope), no `extracted_episode_urls` schema work (3f), no final
harness/sweep confirmation (3g). Stopped here as instructed rather than
reading ahead.

### 2026-07-29: Phase 3c -- `open_term_review_dialog()` wired through `GlossaryCoordinator`

Per the Phase 3 sub-plan's guardrails below: self-contained, did not read
ahead into 3d-3g. One real, unexpected finding surfaced mid-step (a bug in
`reject()` itself, found and fixed, documented below) -- reported and
fixed at the point it was found, per the guardrails' own instruction, not
pushed past.

**Real test data used, as directed**: novel `777777777`'s 11-term
backlog from the Phase 3c prep step (2026-07-29), including the real,
unforced `弁護士` -> `character` misclassification. Confirmed one term
(`鉄パイプ`), rejected one (`橘`), and confirmed `弁護士` after correcting
its type from `character` to `term` -- all three against the real
backlog, live. Per the prep step's own instruction, this data was **not**
restored/wiped afterward (unlike 3b's careful backup-and-restore of the
same fixture) -- the confirm/reject actions are genuine progress on the
backlog, meant to persist. 10 terms remain (8 still `suggested`,
`鉄パイプ`/`弁護士` now `confirmed`) for 3d-3g to keep using.

**Line numbers, re-confirmed rather than assumed**: `open_term_review_dialog()`
at `alphapolis_reader.py:2274` (Phase 1's `~l.2458`/`~l.2481` estimates
for `confirm_selected()`/`reject_selected()` had shifted to `2459`/`2482`
by the time this step started -- read fresh before touching anything, per
3a's own precedent for line-drift).

**A real mismatch found and fixed, not silently assumed away: `reject()`'s
identity-matching contract was broken for this dialog's actual usage.**
3a's `GlossaryCoordinator.reject(term_identity)` matched by Python object
identity (`t is not term_identity`), mirroring `reject_selected()`'s own
`t is not term` filter exactly -- reasonable on its face, since that
filter was lifted verbatim from this exact dialog. But `reject_selected()`'s
filter only works because it mutates the *same* in-memory `glossary` dict
the dialog loaded once, itself, at open time, in the same local scope.
`GlossaryCoordinator.reject()` reloads the glossary fresh via `self.load()`
*internally*, every call, before deleting anything (the same re-check-
before-write discipline every other coordinator write path already uses,
deliberately, to avoid stale-snapshot bugs). Confirmed directly, not
assumed: two independent `load_glossary()` calls against the same on-disk
file produce equal-content but not identical Python objects
(`t1 == t2` True, `t1 is t2` False). This means a `term` object the dialog
holds from its own separate, earlier `load_glossary()` call could never
match anything inside `reject()`'s freshly-reloaded list by identity --
`reject()` as originally written would have silently deleted nothing at
all, every time, when driven from this dialog's real code path (not
caught by 3a's own tests, since those constructed `target` from the
coordinator's own `load()` call specifically, matching `reject()`'s
documented-but-flawed contract rather than exercising the actual
mismatch).

**Fix**: `reject()`'s signature changed from `reject(term_identity: dict)`
to `reject(source: str)` -- matches by source instead of identity, the
same precedent `upsert_confirmed_term()` already established (dedupe-by-
source, not by identity or `(type, source)`) for exactly this "a human
acted on one specific term" trust level. `glossary_coordinator.py`'s
module docstring and `reject()`'s own docstring updated to record this
finding, not just the corrected behavior -- so a future reader sees *why*
identity matching doesn't work here, not just that source matching does.
3a's own `TestReject` tests updated to the new signature (all three
scenarios re-verified passing), plus one new test
(`test_reject_by_source_works_even_against_a_term_object_from_a_separate_load_call`)
added specifically to cover the exact failure shape this step found:
rejecting via a term object sourced from an independent `load_glossary()`
call, not the coordinator's own.

**Coordinator lifecycle**: fresh `GlossaryCoordinator(novel_id)` per
action (Confirm and Reject each construct their own), same as 3b's
decision -- still correct here: the coordinator has no state that would
benefit from surviving across multiple Confirm/Reject actions in one
review session (each call does its own independent `load()`/`save()`
regardless), and this dialog's real usage pattern (review several terms
in one sitting) doesn't change that. `confirm_selected()`/`reject_selected()`
still update the dialog's own in-memory `glossary["terms"]` from the
coordinator's returned result after each write -- necessary because
`refresh_tree()` reads `glossary` directly, not disk, and rebuilding the
whole dialog from scratch after every single action would be a much
larger, out-of-scope behavior change.

**`notify_edited()` decision, required this step, confirmed not
deferred**: unlike `open_word_glossary_popup()` (3b, confirmed to never
call the auto-refresh mechanism at all), `open_term_review_dialog()`'s
`close_dialog()` already calls `self._maybe_refresh_after_glossary_edit(novel_id,
edited["value"])` directly -- untouched by this step's wiring, since
`edited["value"]` is still set identically by both `confirm_selected()`
and `reject_selected()` regardless of which write path they route
through. This existing, already-tested mechanism does not go through
`GlossaryCoordinator.notify_edited()` at all (still a documented no-op,
unchanged from 3a) -- `open_term_review_dialog()` never needed that
forwarding hook, since it already has a direct line to
`_maybe_refresh_after_glossary_edit()` on `ReaderApp`. Confirmed live,
not just by reading the code: closing the dialog after this session's
Confirm/Reject/type-correction actions genuinely deleted the cached
episode and kicked off a real `_do_fetch_and_translate()` call (see live
verification below) -- the exact behavior this dialog had before this
step, unbroken by the wiring change.

**A second, smaller unexpected finding, per the guardrails, reported
here**: an entire pre-existing test file,
`tests/webnovels/test_term_review_dialog.py` (11 tests, real coverage of
Confirm/Reject/type-correction/auto-refresh against this exact dialog),
was not part of the file set read before starting this step's edit --
found only when the full suite check surfaced 5 failing tests there
after the wiring change. Not a gap in this task's own required reading
(neither 3a's nor 3b's status entries name this file), but a real
process lesson: **`grep -rl` for a method name across `tests/` before
editing its call sites is not optional**, especially for a dialog this
central. Fixed by updating each affected test's `monkeypatch.setattr`
target from `alphapolis_reader.load_glossary`/`save_glossary` (correct
for the pre-3c direct-call code) to `glossary_coordinator.load_glossary`/
`save_glossary` (correct now that Confirm/Reject route through the
coordinator's own module-level references) -- same fix shape as 3a/3b's
own coordinator-aimed mocks, applied retroactively to a file this task
almost missed. All 11 tests in that file re-confirmed passing, not just
silently patched and assumed fixed.

**Also removed**: `upsert_confirmed_term` from `alphapolis_reader.py`'s
import list -- confirmed via `grep` to have zero remaining real call
sites in that file (both dialogs that used to call it directly now
route through the coordinator), only comments/docstrings referencing it
by name. `flake8` caught this as an unused-import error; not left in
place as dead weight.

**Tests, same load-bearing standard as 3b**: 3 new tests in
`tests/webnovels/test_glossary_coordinator.py`'s
`TestOpenTermReviewDialogRoutesThroughCoordinator`, driving the real,
unmodified `open_term_review_dialog()` end-to-end through its actual
Confirm/Reject buttons (via a small local harness, same shape as
`test_term_review_dialog.py`'s own `_ReviewDialogHarness` -- duplicated,
not imported, per this file's existing convention):
- `test_confirm_fails_loudly_if_dialog_calls_glossary_functions_directly`
  and `test_reject_fails_loudly_if_dialog_calls_glossary_functions_directly`:
  monkeypatch `alphapolis_reader.save_glossary` to raise if called
  directly, confirming both actions genuinely route through the
  coordinator.
- `test_confirm_after_type_correction_persists_the_corrected_type`: the
  required `弁護士` case -- confirm after changing type from `character`
  to `term`, verify the corrected type (not the original misclassification)
  is what's actually written.

**Confirmed load-bearing, not just passing incidentally**: reverted
`alphapolis_reader.py`'s wiring via `git stash` and re-ran both the 3
new tests and all of `test_term_review_dialog.py` -- all 7 previously-
passing-now-would-fail tests failed cleanly (`AssertionError`s from the
fail-loud guards, `KeyError`s from the coordinator-aimed mocks never
firing against the reverted direct-call code), confirming genuine
regression coverage, not tests that pass regardless of the wiring.
Restored via `git stash pop`, confirmed via `grep` before continuing.

**A second, pre-existing, timing-dependent segfault source found while
running the full suite for this checkpoint -- not caused by this step's
wiring, confirmed by isolation, disclosed rather than quietly worked
around.** Running the full `tests/webnovels/` suite for this checkpoint
crashed with `Fatal Python error: Illegal instruction` on roughly half
of several repeated runs -- nondeterministic, same general class as the
already-documented `TestFetchAndTranslateDuplicateGuard` segfault
(Python 3.14 + Tk + threading + garbage collection touching Tk state
from a non-main thread), but a genuinely different trigger, found via
`PYTHONFAULTHANDLER=1`'s thread dump: `test_retranslation_dialog.py`'s
`test_second_retranslate_popup_call_reuses_existing_window` starts a
real background `threading.Thread(target=fetch_candidate, daemon=True)`
via `open_retranslate_popup()` and never joins or waits for it before
that test ends -- the crash dump caught this leftover thread still
executing (inside `coverage`'s sysmon hook, itself inside a GC pass)
concurrently with a *later* test's own `root.update()` call, in this
run `test_term_review_dialog.py::test_reject_removes_term_entirely`.

**Confirmed pre-existing, not introduced by this step**: `git log`
confirms `test_retranslation_dialog.py` (the file with the leaky daemon
thread) hasn't been touched since the Phase 2 commit -- the hazard
predates 3a/3b/3c entirely. Re-ran the full suite against the pre-3c
commit (`git stash` on this step's changes) twice: both runs passed
clean at 254, no crash -- consistent with "the hazard exists either
way, but became more likely to actually land now that 3c added more
tests running after the leaky-thread test in file-collection order,"
not with "3c's wiring caused a new crash." Re-ran the full suite five
times with this step's changes applied: passed clean twice, crashed
with the exact thread-dump signature above three times. Deselecting
`test_retranslation_dialog.py::TestPopupSingleInstanceGuard::test_second_retranslate_popup_call_reuses_existing_window`
specifically (the actual leaky-thread test, not a workaround target
picked at random) produced three consecutive clean runs with no
further crashes. Not fixed here -- fixing this dialog's own test
threading hygiene is a separate, out-of-scope concern from "wire one
dialog through a coordinator," and forcing a fix into this step would
violate the guardrails' own "do not attempt a fix that spans into...
territory" instruction just as much as reading ahead into 3d would.
Recorded here, plainly, so it isn't lost the way `DESIGN.md`'s own
"why this started" section warns against.

**Checkpoint, confirmed, not assumed (against the deselection above,
consistent with how `TestFetchAndTranslateDuplicateGuard` is already
treated in this doc's own prior entries)**:
- Full `tests/webnovels/` suite: **257 passed** (up from 254 -- 3 new
  3c tests plus 1 pre-existing test corrected for hygiene, net of the
  one newly-flaky test above, zero regressions in anything this step
  actually touched), 2 pre-existing unrelated segfault sources
  deselected (`TestFetchAndTranslateDuplicateGuard`'s, and the
  newly-found `TestPopupSingleInstanceGuard` one), same 6 live-display
  UI-automation tests erroring only for lack of an Xvfb display in that
  offline run.
- `black`/`isort`/`flake8` clean on all four touched files.
- **Live verification**, via `pyplayground/webnovels/ui_testing/
  run_ui_tests.sh xvfb-keep` (not manual `xdotool`), against novel
  `777777777`'s real 11-term backlog: screenshotted the full backlog
  (`01_backlog.png`), selected and Confirmed `鉄パイプ` (screenshot +
  on-disk read confirming `status: confirmed`, `confirmed_target: "iron
  pipe"`; `log_correlator.assert_clean()` clean, `"Confirmed term via
  review dialog"` INFO line present at the exact click timestamp),
  selected and Rejected `橘` (confirmation dialog screenshotted first,
  on-disk read confirming the term is gone entirely -- not just
  status-changed -- while `鉄パイプ` stayed confirmed; log clean,
  `"Rejected term via review dialog"` line present), then selected
  `弁護士`, changed its Type from `character` to `term` via the
  Combobox, and Confirmed it (screenshots at each step; on-disk read
  confirming `type: "term"`, not the original misclassification;
  log clean, correct INFO line present). Closing the dialog afterward
  genuinely deleted the synthetic episode's on-disk cache entry and
  fired a real `_do_fetch_and_translate()` call (confirmed via direct
  cache-file check and the exact matching log timestamp) -- the real
  network fetch then failed with a Playwright timeout, exactly as
  expected for a synthetic, non-existent Alphapolis URL once its cache
  was wiped; this is the correct, unbroken pre-existing behavior of
  refreshing a fake test fixture, not a regression from this step's
  wiring, and the app did not crash. The synthetic episode's cache
  entry was restored afterward (a legitimate side effect of proving
  auto-refresh fires, not something worth leaving broken); the
  glossary's Confirm/Reject state was deliberately left in place, per
  the prep step's own instruction. Whole-session log swept for
  `ERROR`/`CRITICAL`: none found. Xvfb/fluxbox confirmed torn down
  cleanly after the run.
- One environment-specific gotcha worth recording for future live
  verification of this dialog: the `ttk.Combobox`'s popdown listbox
  rendered as a solid black rectangle under this Xvfb+fluxbox setup when
  screenshotted mid-open, and plain coordinate clicks into that rendered
  area did not reliably land on the right option. Keyboard navigation
  (`Down` to open the popdown, then `Up`/`Down` to move the highlighted
  selection, then `Return` to commit) worked reliably where clicking did
  not -- used for the `弁護士` type-correction step above.

**Net result**: `open_term_review_dialog()`'s Confirm and Reject actions
now route through `GlossaryCoordinator.upsert_confirmed()`/`reject()`;
on-disk behavior (including the type-correction case) is unchanged from
the user's perspective, confirmed both by test and by a real live
sequence of three actions against a real backlog. The existing
auto-refresh mechanism is confirmed still firing correctly, unbroken by
the wiring change. One real coordinator bug (the `reject()` identity-
matching mismatch) found and fixed as part of this step, not deferred.

**Not done in this step, deliberately, per the guardrails**: no changes
to `open_glossary_dialog()` (3d), no extraction-vs-dialog race fix (3e),
no `extracted_episode_urls` schema work (3f), no final harness/sweep
confirmation (3g). Stopped here as instructed rather than reading ahead.

### 2026-07-29: Phase 3b -- `open_word_glossary_popup()` wired through `GlossaryCoordinator`

Per the Phase 3 sub-plan's guardrails below: self-contained, did not read
ahead into 3c-3g, stopped at this step's own checkpoint.

**Known gap from 3a's own findings, addressed before live verification**:
novel 375266002's glossary has zero unconfirmed terms (all 8 confirmed,
per 3a's live evidence) -- not usable to exercise a meaningful Save.
**Approach used: the existing synthetic novel `777777777`** (from Phase
2's live verification, still on disk with a real cache entry and a
real, pre-existing `suggested`-status `鉄パイプ` term) -- right-clicked
a *different*, genuinely new word (`ケイト`, the character name from
that same cached episode) via drag-select + "Add to Glossary...", not a
hand-constructed `suggested` term read directly off disk. This is a
manually-triggered right-click add, not an organically-extracted
`suggested` term from a real `build_glossary_for_novel()` run -- stated
plainly, not implied otherwise. The glossary file was backed up before
this verification and restored to its exact prior state afterward (this
step makes no lasting change to that fixture).

**Mismatch check, per this step's own requirement -- none found.**
Read `open_word_glossary_popup()`'s real `save_and_close()`
(`alphapolis_reader.py:2856-2881` before this step's edit) directly
before assuming 3a's `upsert_confirmed()` interface fit: the dialog's
existing save path was `load_glossary(novel_id)` ->
`upsert_confirmed_term(glossary.get("terms", []), new_term)` -> set
`updated_at` -> `save_glossary(novel_id, glossary)` -- exactly the same
four-step shape `GlossaryCoordinator.upsert_confirmed()` already
implements against `self.novel_id`. No redesign needed on either side;
this was a clean drop-in.

**What changed**: `save_and_close()`'s body (inside
`open_word_glossary_popup()`) now reads
`GlossaryCoordinator(novel_id).upsert_confirmed(new_term)` in place of
its own direct `load_glossary()`/`upsert_confirmed_term()`/
`save_glossary()` calls. A fresh `GlossaryCoordinator` is constructed
per dialog-open, not cached on `ReaderApp` -- matches how `novel_id`
itself is already re-derived fresh on every open of this dialog rather
than cached on `self`; a shared, longer-lived instance would need
invalidation-on-novel-switch logic this coordinator doesn't have a
reason to carry yet (its only per-instance state,
`_rebuild_in_progress`, isn't touched by this dialog at all). Revisit if
a later step's `is_rebuild_running()` wiring (Phase 3e) needs a
longer-lived instance instead -- not needed here.

**`notify_edited()` decision, stated explicitly per this step's own
question**: remains a documented no-op, unchanged from 3a. Reason found
during this step, not assumed going in: `open_word_glossary_popup()`
**does not call `_maybe_refresh_after_glossary_edit()` at all today** --
confirmed via `grep`/direct read of the full method, and cross-checked
against `DESIGN.md`'s 2026-07-27 auto-refresh entry, which explicitly
names "both dialogs" (`open_glossary_dialog()` and
`open_term_review_dialog()`) as the ones wired to that mechanism, never
mentioning this one. This is a genuine, pre-existing gap in the
codebase -- a right-click "Add to Glossary" save does not currently
trigger the same auto-refresh-the-displayed-episode behavior the other
two dialogs get -- found as a side effect of this step's own
investigation, not something this step was scoped to fix (the Phase 3
sub-plan does not mention it, and fixing it would mean deciding
`_maybe_refresh_after_glossary_edit()`'s Group A dependency shape for a
dialog this step isn't otherwise touching, out of scope). Flagged here
so it isn't lost; a natural fit for 3b/3c/3d's own eventual
`notify_edited()` wiring once that's actually decided, or a standalone
fix if it's judged worth doing before then.

**Not touched, confirmed via reading the diff before finishing**:
`open_glossary_dialog()`, `open_term_review_dialog()`,
`_do_fetch_and_translate()`, rebuild-tracking, and
`extracted_episode_urls` are all unchanged -- only
`open_word_glossary_popup()`'s `save_and_close()` body and the module's
import list (adding `GlossaryCoordinator`) changed in
`alphapolis_reader.py`.

**Tests**: 2 new tests in `tests/webnovels/test_glossary_coordinator.py`'s
`TestOpenWordGlossaryPopupRoutesThroughCoordinator`, both driving the
real, unmodified `open_word_glossary_popup()` end-to-end (via the
existing `reader_app_shell` fixture -- real `ReaderApp` method, real Tk
widgets, real Save button click), not calling the coordinator directly:

- `test_save_writes_via_coordinator_upsert_confirmed_not_direct_glossary_calls`:
  monkeypatches `load_glossary`/`save_glossary`/`upsert_confirmed_term`
  in `alphapolis_reader` to raise loudly if called directly, confirming
  the write genuinely goes through `GlossaryCoordinator.upsert_confirmed()`
  and not just that *a* write happens to land correctly.
- `test_save_result_matches_pre_refactor_on_disk_shape`: confirms the
  on-disk result (status, `confirmed_target`, type) is unchanged from
  the user's perspective, now produced via the coordinator.

**Confirmed load-bearing, not just passing incidentally**: re-ran both
tests with `alphapolis_reader.py`'s wiring change reverted (`git
stash` on that one file) -- both failed cleanly (`AttributeError:
module ... has no attribute 'GlossaryCoordinator'` and a `KeyError` on
the never-populated `saved` dict), confirming these are genuine
regression tests, not tests that would pass regardless of the wiring.
Restored the wiring immediately after via `git stash pop`, confirmed via
`grep` that the real change was back in place before continuing.

**A real Tk/threading gotcha found and worked around, not a code bug**:
`open_word_glossary_popup()`'s `fetch_guesses()` runs its network/LLM
lookups on a real background `threading.Thread` and schedules
`build_form()` via `self.root.after(0, ...)` once it returns. Outside a
real `mainloop()` (as in a test), that `after()` call races the test
thread and can raise Tk's C-layer `RuntimeError: main thread is not in
main loop` -- confirmed live, the first version of this test's poll-loop
(`root.update()` in a loop waiting for the real thread) hit exactly this,
silently, as an unhandled thread exception. Not a bug in
`open_word_glossary_popup()` itself: `check_llm_available()`/
`translate_chunk()` are already mocked to return instantly/
deterministically, so there's no real concurrency worth testing here.
Fixed using the exact same pattern already established in
`test_retranslation_dialog.py`'s `TestAcceptSurvivesModeSwitch` for the
identical situation in `open_retranslate_popup()`: a `_SyncThread`
stand-in that runs the target synchronously in the calling thread
instead of a real thread, then a single `root.update()` safely pumps the
now-main-thread-scheduled callback.

**Checkpoint, confirmed, not assumed**:
- Full `tests/webnovels/` suite: **254 passed** (up from 252 -- exactly
  the 2 new tests, zero regressions), same 1 pre-existing unrelated
  segfault deselected, same 6 live-display UI-automation tests erroring
  only for lack of an Xvfb display in that particular offline run.
- `black`/`isort`/`flake8` clean on both touched files.
- **Live verification**, via `pyplayground/webnovels/ui_testing/
  run_ui_tests.sh xvfb-keep` (not manual `xdotool`), against the real
  app and the synthetic novel 777777777 described above: drag-selected
  "ケイトが振り返った。" in Interleaved mode, right-clicked, screenshotted
  the real context menu (`01_context_menu.png`), clicked "Add to
  Glossary...", waited out the real background reference-lookup thread,
  edited Source to `ケイト` and Target to `Kate` (screenshot
  `04_source_fixed.png` confirms the form state right before Save),
  clicked Save. **On-disk glossary file read directly afterward**:
  `ケイト` present as a new `status: confirmed` character term with
  `confirmed_target: "Kate"`, `origin: "user"` -- and the pre-existing
  `鉄パイプ` `suggested` term untouched, confirming the coordinator's
  write didn't disturb unrelated existing data.
  `log_correlator.assert_clean()` for the Save click's time window:
  clean, and the expected `"Added glossary term via right-click for
  novel 777777777: 'ケイト' -> 'Kate'"` INFO line confirmed present at
  the exact click timestamp -- positive confirmation, not just absence
  of errors. Whole-session log swept for `ERROR`/`CRITICAL`: none found.
  Dialog closed via its own real Save button throughout (never
  `windowclose`). App terminated via `kill -TERM` on the tracked PID,
  confirmed dead. The synthetic novel's glossary file was backed up
  before this verification and restored to its exact original content
  afterward. Xvfb/fluxbox confirmed torn down cleanly after the run.

**Net result**: `open_word_glossary_popup()`'s Save path now routes
through `GlossaryCoordinator.upsert_confirmed()`; on-disk behavior is
unchanged from the user's perspective, confirmed both by test and by a
real live write. One real, pre-existing gap found and documented (no
auto-refresh call from this dialog) -- not fixed here, out of this
step's scope.

**Not done in this step, deliberately, per the guardrails**: no changes
to `open_glossary_dialog()` or `open_term_review_dialog()` (3c/3d), no
extraction-vs-dialog race fix (3e), no `extracted_episode_urls` schema
work (3f), no final harness/sweep confirmation (3g), and no fix for the
`notify_edited()`/auto-refresh gap found above. Stopped here as
instructed rather than reading ahead.

### 2026-07-29: Phase 3a -- `GlossaryCoordinator` built standalone, zero behavior change

Per the Phase 3 sub-plan's guardrails below: self-contained, did not read
ahead into 3b-3g, stopped at this step's own checkpoint.

**What was built**: `pyplayground/webnovels/glossary_coordinator.py`,
a new `GlossaryCoordinator` class implementing Phase 1 section 4's
proposed interface (`load()`, `save_snapshot()`, `upsert_confirmed()`,
`reject()`, `is_rebuild_running()`/`start_rebuild()`, `notify_edited()`).
Line references in Phase 1's original proposal had shifted since that
investigation (`save_and_close()` proposed at l.1736-1791, actually at
l.2210-2264 now; `reject_selected()` similarly shifted to ~l.2481-2492)
-- confirmed via `grep` against the real file before lifting anything,
not assumed from the old references.

**Logic lifted verbatim, not redesigned**:
- `save_snapshot()` is `open_glossary_dialog()`'s `save_and_close()`
  merge-on-divergence logic (`alphapolis_reader.py:2210-2264`) --
  re-check `updated_at` against what was loaded at open time, merge by
  `source` on divergence, only letting the caller's copy win for
  `edited_sources` (not every source in a stale full snapshot), with
  `deleted_sources` popped last so explicit deletes survive the merge.
  Copied logic exactly; only the surrounding shape changed (a class
  method taking `opened_at`/`local_terms`/`edited_sources`/
  `deleted_sources`/`honorific_policy` as explicit parameters instead of
  reading them from a dialog's closure).
- `reject()` is `open_term_review_dialog()`'s `reject_selected()`
  real-delete-by-identity logic (`alphapolis_reader.py:2481-2492`) --
  matches by object identity (`t is not term_identity`), same as the
  original; documented explicitly in the method's docstring that this
  only works correctly against a term object obtained from this same
  coordinator's own `load()` call, not an independently-reloaded copy.
- `upsert_confirmed()` wraps `glossary.upsert_confirmed_term()`
  reload-then-write, matching `open_term_review_dialog()`'s
  `confirm_selected()`'s write shape.

**New in this step, no existing equivalent to lift**:
`is_rebuild_running()`/`start_rebuild()` generalize
`open_glossary_dialog()`'s dialog-local `rebuild_state = {"running":
False}` dict (`alphapolis_reader.py:2132`) into coordinator-owned state
that will be visible across all three dialogs and
`_do_fetch_and_translate()` once wired (Phase 3e depends on this being
shared, not dialog-local). `start_rebuild()` wraps
`build_glossary_for_novel()` on a background thread, same pattern as
`open_glossary_dialog()`'s existing `rebuild_glossary()`, but leaves any
UI-thread marshaling (e.g. Tk's `root.after()`) to the caller, since the
coordinator has no widget/event-loop reference of its own.
`notify_edited()` is a documented no-op placeholder in this step --
Phase 1's proposed forwarding-to-a-registered-callback behavior is 3b-3d's
job, not built here, since there is no dialog wired to it yet to register
one.

**Not wired into any dialog, confirmed via `git diff` scope check**:
`open_glossary_dialog()`, `open_term_review_dialog()`,
`open_word_glossary_popup()`, and `_do_fetch_and_translate()` are
byte-for-byte unchanged -- `alphapolis_reader.py` does not appear in this
step's diff at all. This is the step's own explicit requirement, not
just a side effect: `GlossaryCoordinator` exists and is fully tested, but
nothing calls it yet.

**Tests**: new `tests/webnovels/test_glossary_coordinator.py`, 12 tests,
all against the coordinator directly (no Tk, no dialog harness --
deliberately, since nothing is wired to a dialog yet):
- `TestSaveSnapshotMergeOnDivergence` (3): the exact same three scenarios
  as `test_alphapolis_reader.py`'s `TestGlossaryDialogMergeOnDivergence`
  (concurrent-confirm-survives-an-unrelated-edit, no-divergence-saves-
  normally, explicit-delete-wins-over-divergence), same fixtures,
  confirming the lifted logic behaves identically to the dialog it was
  copied from -- not just "passes some test," the same regression
  coverage re-derived against the new call shape.
- `TestUpsertConfirmed` (2), `TestReject` (2): correctness of the
  reload-then-write and delete-by-identity paths.
- `TestRebuildTracking` (4): `is_rebuild_running()` correctly reports
  `True` while a background rebuild runs and clears on completion
  (via a real background thread gated by a `threading.Event`, not a
  synchronous stand-in), a second `start_rebuild()` call while one is
  already running is confirmed a genuine no-op (the mocked
  `build_glossary_for_novel()` is call-counted, not just assumed not to
  fire again), and a raised exception inside the background worker still
  clears `_rebuild_in_progress` rather than leaving it stuck `True`.
- `TestNotifyEdited` (1): confirms the current no-op placeholder doesn't
  raise.

**Checkpoint, per the Phase 3 sub-plan below -- confirmed, not assumed**:
- Full `tests/webnovels/` suite: **252 passed** (up from 240 before this
  task -- exactly the 12 new coordinator tests, zero regressions), 1
  pre-existing unrelated Python 3.14/`mock`/threading segfault deselected
  (same one noted in the Phase 2 audit entry, confirmed still unrelated
  to this change), 6 live-display UI-automation tests erroring only
  because no Xvfb display was up for that particular offline run (not a
  real failure -- see the live check below, which ran the same suite
  successfully against a real display).
- `black`/`isort`/`flake8` clean on both new files.
  `mypy`: one "missing return type annotation" note on
  `start_rebuild()`'s nested `worker()` closure, consistent with this
  file's/`alphapolis_reader.py`'s existing untyped-nested-closure
  convention -- not fixed here, same treatment as every prior session
  touching this codebase.
- **Live sanity check**, via `pyplayground/webnovels/ui_testing/
  run_ui_tests.sh xvfb` (not manual `xdotool`): ran
  `test_menu_smoke.py`'s full 6-test suite against the real app and the
  real novel 375266002 -- all four toolbar dialogs (Load Novel, Glossary,
  Review Terms, Settings) opened and closed cleanly, context menu
  discovery still worked, all 6 passed. Screenshots visually inspected
  (not just the passing assertions): `toolbar_glossary_after.png` shows
  the real Glossary dialog rendering 8 real confirmed terms with Save/
  Cancel/Add Term/Add Character/Delete/Rebuild Glossary all present, and
  `toolbar_review_terms_after.png` correctly shows "No unconfirmed terms
  to review for this novel" (consistent with every term in that novel's
  glossary already being confirmed, per the Glossary dialog screenshot).
  App stdout log swept for `ERROR`/`CRITICAL`: none found. Xvfb/fluxbox
  confirmed torn down cleanly after the run (`pgrep` empty for both).

**Net result**: `GlossaryCoordinator` exists, is fully tested in
isolation, and changes nothing about how any dialog currently behaves --
exactly this step's scope, no more.

**Not done in this step, deliberately, per the guardrails**: no wiring
of any dialog through the coordinator (3b-3d), no extraction-vs-dialog
race fix (3e), no `extracted_episode_urls` schema work (3f), no final
harness/sweep confirmation (3g). Stopped here as instructed rather than
reading ahead.

## Phase 3 sub-plan (2026-07-29) -- broken into checkpointed chunks

Phase 3 carries more real risk than Phase 2: three dialogs' worth of live
Tk state and event bindings, plus Phase 1's dependency map showing
bidirectional coupling (A<->C, B<->C) that Phase 2 didn't have to
navigate. Split into small, sequential, independently-committable
sub-steps rather than one task, so a problem in any one step is cheap to
stop at, revert, and retry -- not something that unwinds hours of
combined work.

**Guardrails, apply to every sub-step below:**

- Commit at the end of every sub-step that passes its own checkpoint,
  before starting the next one. A clean commit boundary is what makes
  "come back to this" actually cheap.
- If a sub-step hits unexpected behavior (a test that shouldn't fail
  does, a live-verification screenshot looks wrong, anything not
  explicitly anticipated in that sub-step's scope) -- stop. Do not
  attempt a fix that spans into the next sub-step's territory. Document
  what was found, leave the working tree at the last good commit or a
  clearly-marked broken state, and report back rather than pushing
  forward speculatively.
- Each sub-step is self-contained: read this plan, do that one step, verify
  its own checkpoint, stop. Do not read ahead and pre-implement a later
  step "while you're in there."
- Live verification (`pyplayground/webnovels/ui_testing/`, screenshot +
  log per action, never `windowclose`) is required at the checkpoint
  marked for it, not optional even if unit tests pass -- same standard
  as Phase 2.

### 3a. Build `GlossaryCoordinator` standalone -- zero behavior change

Create `glossary_coordinator.py` per Phase 1's proposed interface
(`load()`, `save_snapshot()`, `upsert_confirmed()`, `reject()`,
`is_rebuild_running()`/`start_rebuild()`, `notify_edited()`). Lift the
real `save_and_close()` merge-by-source logic
(`open_glossary_dialog()`, l.1736-1791) and `open_term_review_dialog()`'s
Confirm/Reject logic verbatim -- do not redesign either. **Do not wire
this into any dialog yet.** Unit-test the coordinator directly, in
isolation.

**Checkpoint**: coordinator exists and is fully tested standalone. No
dialog's behavior has changed at all -- confirm via full suite pass and
a quick live sanity check that the app behaves identically to before
this step.

### 3b. Wire `open_word_glossary_popup()` through the coordinator

Simplest dialog (single immediate write, no snapshot/merge complexity)
-- lowest-risk first real integration.

**Checkpoint**: this one dialog's Save path goes through
`coordinator.upsert_confirmed()`. Live-verify: right-click a word, Save,
confirm on-disk write is correct via the coordinator path, screenshot +
log per the standing verification standard.

### 3c. Wire `open_term_review_dialog()` through the coordinator

Same write shape as 3b (immediate-write), moderate additional risk from
being a second call site.

**Checkpoint**: Confirm/Reject both route through the coordinator.
Live-verify both actions.

### 3d. Wire `open_glossary_dialog()` through the coordinator

Highest-risk dialog conversion -- carries the actual merge-on-divergence
logic being centralized. This is the step most likely to surface
something Phase 1 didn't fully anticipate.

**Checkpoint**: re-run the existing `TestGlossaryDialogMergeOnDivergence`
regression test (already proves this exact logic works pre-refactor --
must still pass unchanged in meaning, even if its construction needs
updating for the new call path). Live-verify the stale-form-bug and
merge-on-divergence scenarios still behave correctly through the
coordinator.

### 3e. Extraction-vs-dialog race fix

Add per-novel rebuild tracking (`is_rebuild_running()`/`start_rebuild()`)
to the coordinator; wire `_do_fetch_and_translate()`'s
`build_glossary_for_novel()` call (Group A, per Phase 1's finding) to use
it; have the three write paths from 3b-3d check/defer appropriately.

**Checkpoint**: live-reproduce the original race sequence from `DESIGN.md`'s
background-extraction investigation entry and confirm it no longer
silently overwrites.

### 3f. Non-incremental extraction fix

Add `extracted_episode_urls` (plain additive field, per Phase 1's
recommendation -- confirm no schema-version bump is actually needed
before assuming one is, same discipline as every prior schema decision
in `DESIGN.md`). Wire into `build_glossary_for_novel()`.

**Checkpoint**: live-verify a second rebuild against an unchanged episode
set does not re-process already-extracted episodes.

### 3g. Final harness/test confirmation and full sweep

Confirm (per Phase 1's note that no fragile harness currently exists for
glossary-dialog tests) this still holds after all the above wiring --
don't assume. Full suite, full live sweep across all three dialogs one
more time, in one session, as final confirmation the whole phase holds
together, not just each piece individually.

**Checkpoint**: Phase 3 status entry appended, same format as Phase 2's.

### 2026-07-28: Phase 2 audit -- re-verified against real code, not a restatement of the original claim

Reissued as an explicit audit rather than a re-run of Phase 2 from scratch,
since inspecting the actual repository state first (`ReaderRenderer` already
present at `alphapolis_reader.py:641`, `conftest.py` already present, the
tracked diff already matching the shape the original entry below describes)
showed the extraction had already landed. This entry exists to confirm that
landing directly against the real code rather than trusting the prior
entry's own claims about itself -- the standing discipline this whole
refactor doc is built on (`git diff` scope checks, grep-before-assuming)
applied to auditing a previously-written status entry, not just to writing
a new one.

**The four things this audit checked, each against real code, not the
prior entry's prose:**

1. **The three Phase-1-flagged entanglements, all confirmed intact:**
   - `_render_interleaved_content()` (`alphapolis_reader.py:932`) and
     `_render_translated_view()` (`:987`) both still call `load_glossary()`
     directly and pass the *unfiltered* dict to `_apply_needs_review_spans()`
     -> `find_glossary_term_spans()` (`:1122`) -- confirmed via direct read,
     not just the inline comments claiming it. `build_mask_targets()`
     (glossary.py's confirmed-only filter) is grep-confirmed to appear
     exactly once in this file, at `fetch_and_translate()`'s hot path
     (`:1655`, Group A's territory) -- nowhere in `ReaderRenderer`.
   - `_on_needs_review_click()` (`:1128-1151`) confirmed calling
     `self.app.open_word_glossary_popup(word, "", context=source_line)`
     (`:1151`) -- a real call through the back-reference, not a stale
     reference to a method that moved or was renamed. `open_word_glossary_popup`
     confirmed still defined on `ReaderApp` at `:2653`.
   - `open_retranslate_popup()`'s Accept handler (`:3016-3061`) confirmed
     writing through `self.renderer._rendered_spans` (`:3035-3036`) and
     `self.renderer._translated_line_index_by_span` (`:3048`,`:3053`), and
     `self.episode["translated_lines"]` (`:3049-3052`) -- all three
     writes present and reading correctly off the renderer back-reference,
     not a dangling reference to a removed `ReaderApp` attribute.
2. **`TestAcceptSurvivesModeSwitch`**: confirmed present at
   `tests/webnovels/test_retranslation_dialog.py:249`, run in isolation
   (not just counted as part of a full-suite total):
   `TestAcceptSurvivesModeSwitch::test_accepted_retranslation_survives_switching_to_translated_and_back`
   -- **1 passed**.
3. **`current_url` initialization**: confirmed `self.current_url = None`
   at `ReaderApp.__init__`, `alphapolis_reader.py:1272` -- read directly,
   not taken on the prior entry's word.
4. **`conftest.py`'s `fake_reader_app` fixture**: independently re-derived
   `ReaderRenderer`'s actual `self.app.*` dependency surface via
   `grep`/`awk` across the full `class ReaderRenderer:` body (not
   `ReaderRenderer.__init__`'s signature alone, which only takes one
   parameter, `app` -- the real surface to check is every attribute its
   methods read off that back-reference): `episode`, `current_url`,
   `text`, `open_word_glossary_popup`, `root`, `_save_settings`. All six
   are present on `_FakeReaderApp` (`tests/webnovels/conftest.py:64-89`).
   No stale or missing attribute found -- the fixture's own docstring
   claim ("grep-confirmed against every `self.app.` call site... not
   guessed") holds up against an independent re-derivation, not just a
   repeated assertion.

**All four checked out clean -- no gaps found, nothing needed fixing.**
Full `tests/webnovels/` suite re-run for context: 240 passed (1 deselected
-- `TestFetchAndTranslateDuplicateGuard::test_two_concurrent_calls_for_the_same_url_only_fetch_once`,
a pre-existing Python 3.14/`unittest.mock`/threading interpreter-level
segfault unrelated to this refactor, confirmed reproducing identically
whether or not any of this session's changes are present -- not a
Phase-2-introduced regression, and out of scope to fix here).

**Live verification, screenshot-first, via `pyplayground/webnovels/ui_testing/`
exclusively** -- no ad hoc bash `xdotool`, no `windowclose`/`close_window()`
anywhere, per the standing tracked risk (`DESIGN.md`'s 2026-07-28
WM_DELETE_WINDOW entry). Display owned by
`pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb-keep` (built as this
task's own prerequisite, see that script and its `agents-ui-testing.md`
section); all interaction via `xdo_helper`/`log_correlator`, not raw
`subprocess`/`xdotool` calls. Reused the existing synthetic novel
(`novel_id=777777777`, cache file
`02f76635d1b8e6c6af97e85a5493a5592758e79aab1d7bc0e810411a362d7235.json`,
glossary `~/.config/alphapolis_reader/glossaries/777777777.json`) from the
original Phase 2 entry below -- confirmed still on disk, still the same
two-line/`needs_review_flags=[False, True]` shape, cache-hit short-circuits
before any browser/network access, same as that entry.

- **All four view modes, screenshotted and visually inspected (not just a
  passing test/log check) -- all four correct**: Original shows only the
  two Japanese source lines; Translated shows only the two English lines
  with the needs-review span (`鉄パイプ`) correctly amber/underlined
  within "He was holding a 鉄パイプ."; Both shows the original section,
  a "---- Translation ----" divider, then the translated section with the
  same needs-review styling preserved; Interleaved shows each source line
  immediately followed by its translation, same needs-review styling
  intact. Radio-button selection state in each screenshot matches the
  clicked mode. Screenshots: `mode_original.png`, `mode_translated.png`,
  `mode_both.png`, `mode_interleaved.png`.
- **Needs-review click flow**: clicked the amber-underlined `鉄パイプ` span
  in Interleaved mode via `xdo_helper.click()`. The real Add-to-Glossary
  dialog opened (screenshot `needs_review_dialog2.png`, taken after
  waiting out the background reference-lookup thread rather than the
  first, still-loading screenshot) with `Source (original)` correctly
  pre-filled `鉄パイプ`, `Target` correctly blank, Google/LLM/Meaning/
  Characters/Alternatives reference sections all populated coherently --
  confirming `ReaderRenderer._on_needs_review_click()` ->
  `self.app.open_word_glossary_popup()` still works end-to-end through a
  real running app, not just the harness-level check in item 1 above.
  `log_correlator.assert_clean()` for this action's time window: clean.
  Closed via the dialog's own real Cancel button.
- **Right-click-to-add-glossary flow**: drag-selected the source line
  "鉄パイプを持っていた。" in Interleaved mode via `xdo_helper.drag_select()`,
  right-clicked via `xdo_helper.click(..., button=3)`, found the popup via
  `xdo_helper.find_popup_by_name("!menu")` (the confirmed Tk-specific
  technique), screenshotted the root window (`context_menu.png`) showing
  both "Add to Glossary..." and "Retranslate this line..." positioned
  correctly beside the selection -- confirming `_on_text_right_click()`'s
  hybrid Group B/C/D behavior (renderer-owned span/mode reads via
  `self.renderer`, direct `self.` calls into Group C/D dialogs) still
  works. Clicked "Add to Glossary...": the real dialog opened
  (`add_glossary_dialog2.png`) with `Source (original)` correctly
  pre-filled with the selected line, reference sections populated.
  `log_correlator.assert_clean()` for this action's time window: clean.
  Closed via the dialog's own real Cancel button.
- **Whole-session log check**: `grep -E " - (ERROR|CRITICAL) - "` against
  the full session's log file (`logs/app_log_20260728_200104.log`,
  covering startup through both flows) returned zero matches -- both the
  per-action `assert_clean()` checks above and a full-session sweep agree.
- App shut down via `kill -TERM` on the tracked PID (confirmed terminated,
  not left orphaned) -- no `windowclose`/`close_window()` used anywhere in
  this verification, per the standing tracked risk. Xvfb/fluxbox torn down
  afterward via manual `kill -TERM` on the PIDs `run_ui_tests.sh xvfb-keep`
  reported, since `xvfb-keep` deliberately doesn't tear down on its own
  exit (that mode's whole purpose, see `run_ui_tests.sh`).

**Net result: the existing Phase 2 status entry below was accurate.**
Nothing required fixing. This entry is the audited confirmation of that
entry, not a re-statement of it -- every claim above was checked against
real code/a real running app during this task, not carried forward from
the original entry's own words.

### 2026-07-28: Phase 2 -- rendering extracted into `ReaderRenderer`

Executed directly from Phase 1's proposal, per that entry's construction-
pattern decision (composition with an explicit back-reference, not
mixins). Phase 1's line numbers all matched the real file exactly at the
start of this task (file unchanged in between) -- confirmed via `grep`
before moving anything, not assumed.

**What moved**: a new `ReaderRenderer` class, inserted immediately before
`class ReaderApp` (`alphapolis_reader.py:641`), constructed as
`self.renderer = ReaderRenderer(self)` inside `ReaderApp.__init__`
(l.1281, right before the toolbar code that wires `self.renderer.view_mode`
into the Original/Translated/Both/Interleaved radio buttons). Every method
and attribute in Phase 1's Group B list moved verbatim: `apply_appearance()`,
`_apply_page_width()`, `increase_font()`, `decrease_font()`,
`increase_image_width()`, `decrease_image_width()`, `toggle_dark_mode()`,
`_available_fonts()`, `_pick_default_font()`, `_make_photo_image()`,
`_render_content()`, `_render_interleaved_content()`,
`_render_translated_view()`, `_render_translated_content()`,
`_render_translated_content_from_translated_lines()`,
`_apply_needs_review_spans()`, `_on_needs_review_click()`,
`_on_view_mode_change()`, `render_text()`, `_span_at_index()`,
`_translated_span_after()`, plus the attributes `font_size`,
`image_width`, `dark_mode`, `line_height`, `paragraph_spacing`,
`page_width_pct`, `text_align`, `view_mode`, `font_family`,
`_photo_images`, `_rendered_spans`, `_review_terms_by_span`,
`_translated_line_index_by_span`. The module-level `build_interleaved_pairs()`
stayed module-level (it's a pure function, not a method -- no reason to
attach it to the class).

**`self.text` deliberately did NOT move.** Grep-confirmed before deciding:
the `tk.Text` widget itself is read from ~15 call sites outside Group B
(`ReaderApp.__init__`'s own construction/key-bindings, `load_episode()`'s
"Loading..." placeholder, `apply_appearance()`'s tag configuration, key
bindings for Page Up/Down) -- it stays a `ReaderApp`-owned attribute,
constructed in `__init__` same as before. `ReaderRenderer` exposes it via
a `text` property (`self.app.text`) rather than duplicating the reference,
so every Group B method's `self.text.foo()` call kept working unchanged
with zero call-site edits inside the moved methods themselves.

**The three known entanglements, preserved exactly, with real (not
Phase-1-estimated) line references now that the move is done:**

1. `_render_translated_content_from_translated_lines()` (`ReaderRenderer`,
   l.984) and `_render_interleaved_content()` (l.928) both still call
   `load_glossary()` directly and pass the unfiltered dict to
   `find_glossary_term_spans()` via `_apply_needs_review_spans()` --
   confirmed unchanged, `ReaderRenderer` imports `glossary.py` functions
   at module level exactly as `ReaderApp` did before (this file's imports
   weren't touched at all, only where the calling code lives).
2. `_on_needs_review_click()` (`ReaderRenderer`, l.1149) calls
   `self.app.open_word_glossary_popup(word, "", context=source_line)` --
   Group C's dialog method, still on `ReaderApp`, reached via the explicit
   `self.app` back-reference. Verified this actually works, not just
   compiles: live `xdotool` click on a needs-review span opened the real
   Add-to-Glossary dialog correctly pre-filled (see Live verification
   below) -- the cross-group call survived the module boundary.
3. `open_retranslate_popup()`'s Accept handler (`ReaderApp`, still at
   roughly the same relative position, `_do_fetch_and_translate()`-through-
   `go_next()` region) now writes to
   `self.renderer._rendered_spans`/`self.renderer._translated_line_index_by_span`
   explicitly (both call sites updated, not left pointing at a
   now-nonexistent `ReaderApp` attribute -- confirmed via `py_compile` and
   `flake8` finding zero undefined-name errors after the edit, plus the
   `TestAcceptSurvivesModeSwitch` regression test, see below). This is the
   D-writes-into-B's-tracking-structure-and-A's-episode-dict coupling
   Phase 1 flagged as the messiest three-way case -- confirmed still
   correct after the move.

`_on_text_right_click()` (the hybrid method) stayed on `ReaderApp` exactly
as Phase 1 recommended -- not forced into `ReaderRenderer`. Its two
renderer-owned reads (`self.renderer._span_at_index()`/`_translated_span_after()`)
and its `self.renderer.view_mode.get() == "interleaved"` gating check were
updated to go through the back-reference; its two Group C/D calls
(`self.open_word_glossary_popup(...)`, `self.open_retranslate_popup(...)`)
were left as direct `self.` calls, unchanged, since both still live on
`ReaderApp`.

**Opportunistic fix**: `current_url` is now initialized to `None`
explicitly in `ReaderApp.__init__` (l.1264), rather than left absent
until `display_episode()` first sets it. Every existing `hasattr(self,
"current_url")` guard elsewhere in the file was left in place (not
mechanically stripped -- out of scope for this task, and harmless now
that the attribute always exists), but no new reader added to this file
during this task needed one.

**Test migration, done in this phase, not deferred**: new
`tests/webnovels/conftest.py` (confirmed no `conftest.py` existed under
`tests/webnovels/` before this task) providing `headless_text_widget`
(the real-`tk.Tk()`-not-withdrawn pattern every prior harness's own
`_make_widget()` duplicated, deduplicated once), `fake_reader_app` (a
`_FakeReaderApp` exposing exactly what `ReaderRenderer.__init__`/its
methods read via `self.app` -- `root`, `text`, `current_url`, `episode`,
`open_word_glossary_popup`, `_save_settings`, grep-confirmed against
every `self.app.` site in `ReaderRenderer` before writing the fixture),
`renderer` (a real `ReaderRenderer` built against `fake_reader_app`), and
`reader_app_shell` (a `_ReaderAppShell` for tests needing real
`ReaderApp` methods -- `open_word_glossary_popup`,
`open_retranslate_popup`, `_on_text_right_click`, `_prefill_for_word` --
bound alongside a real `ReaderRenderer`, for the harnesses that mixed
Group A/C/D methods with Group B state).

All hand-rolled harnesses named in this doc's "why this started" section,
plus every structurally-identical sibling found while doing this
migration (not just the three originally named), were deleted and
replaced with real-class construction via the fixtures above:
`test_alphapolis_reader.py`'s `_RenderHarness`, `_RightClickHarness`, and
`_DispatchHarness`; `test_retranslation_display.py`'s
`_InterleaveHarness`; `test_retranslation_dialog.py`'s `_SpanHarness`,
`_RetranslateMenuHarness`, `_NeedsReviewAndRetranslateHarness`,
`_AcceptSurvivesModeSwitchHarness`, and `_PopupGuardHarness`. All three
test files stayed as separate files, per Phase 1's sequencing note --
only harness *construction* changed, not which file a given test lives
in. `test_retranslation_display.py`'s `TestDefaultViewMode` (a
source-inspection regression guard) was updated to `inspect.getsource(
ReaderRenderer.__init__)` instead of `ReaderApp.__init__`, since
`view_mode`'s default now lives there.

**`TestAcceptSurvivesModeSwitch` -- the required regression check named
in Phase 1's migration-order refinement, confirmed passing.** Ran
specifically, not just as part of the full suite:
`test_retranslation_dialog.py::TestAcceptSurvivesModeSwitch::test_accepted_retranslation_survives_switching_to_translated_and_back`
PASSED. This is the concrete proof the B/A/D three-way coupling around
`_translated_line_index_by_span` still works with the new module
boundary -- the test drives the real `ReaderApp.open_retranslate_popup()`
(via `reader_app_shell`) against a real `ReaderRenderer.render_text()`/
`_translated_span_after()`, asserts the Accept write lands in
`episode["translated_lines"]`, then rebuilds via `render_text()` in
Translated mode and back in Interleaved mode, confirming the correction
survives both switches.

**Full verification**:

- `tests/webnovels/` full suite: 241 passed (up from 231 before this
  task -- net gain from fixture/harness consolidation details, no test
  coverage lost; every test that existed before this task still exists
  and still passes, none were deleted, only their internal construction
  changed). 4 pre-existing `PytestUnhandledThreadExceptionWarning`
  warnings in `test_term_review_dialog.py` (a file untouched by this
  task) -- confirmed pre-existing by running that file alone against a
  clean `git worktree` checkout of the commit this task started from,
  not introduced by this extraction.
- `black`/`isort`/`flake8` clean on `alphapolis_reader.py` and all four
  touched/added test files.
- `mypy`: 418 errors on `alphapolis_reader.py`, consistent with the
  file's existing untyped-method convention (the new `ReaderRenderer`
  methods are untyped, same as the `ReaderApp` methods they were copied
  from) -- not fixed here, same treatment as every prior session
  touching this file.
- **Live `xdotool` verification**, real app launched against a synthetic
  cached episode (`novel_id=777777777`, two lines, one with a real
  `suggested`-status glossary term for `鉄パイプ` and
  `needs_review_flags=[False, True]`, matching the established pattern
  from `DESIGN.md`'s prior visual-verification entries) --
  cache-hit short-circuits before any real browser/network access, same
  as those entries:
  - All four view modes (Original, Translated, Both, Interleaved)
    screenshotted and confirmed rendering correctly and identically to
    pre-extraction behavior, including the needs-review span's
    amber/underline styling appearing correctly in both Translated and
    Interleaved modes.
  - Clicked the needs-review span (`鉄パイプ`) in Interleaved mode: the
    real Add-to-Glossary dialog opened via `ReaderRenderer._on_needs_review_click()`
    -> `self.app.open_word_glossary_popup()`, correctly pre-filled
    `Source (original): 鉄パイプ`, with the LLM reference lookup
    (meaning, character breakdown, alternatives) populated correctly --
    confirming the B->C cross-group call survives the module boundary in
    a real running app, not just in the automated harness.
  - Right-click menu on drag-selected original text in Interleaved mode:
    confirmed live by the user watching the session directly. Full-screen
    root-window screenshotting of this transient Tk `Menu` popup initially
    failed against the session's normal display -- `import -window root`,
    `xwd -root`, and Python's `mss` (three independent tools) all either
    errored or returned a solid-black image when reading that display's
    root window, root-cause confirmed as the display running under
    Wayland/XWayland (`loginctl` confirmed `Type=wayland`) rather than a
    lack of skill with any one tool -- XWayland's root window isn't backed
    by a real composited framebuffer the legacy X11 image-fetch path can
    read, while individual **top-level app windows'** own buffers remained
    perfectly screenshotable throughout (used for every other screenshot
    in this task). Root-caused and re-verified properly: started a real,
    standalone `Xvfb :99` X server (no Wayland involved at all) alongside
    the normal session, relaunched the same synthetic-episode app against
    `DISPLAY=:99`, and `import -window root` worked immediately and
    cleanly there -- confirming the diagnosis, not just working around it.
    The resulting screenshot shows the actual right-click menu positioned
    correctly beside the drag-selected source line, listing both "Add to
    Glossary..." and "Retranslate this line..." together, exactly as
    `TestRetranslateMenuGating`'s three passing tests (against the real,
    unmodified `_on_text_right_click()`) already predicted -- live and
    automated evidence agree, and this time the live evidence includes an
    actual saved screenshot, not just a verbal confirmation.

**Not done in this pass**: no extraction of Group C (three glossary
dialogs) or Group D (retranslation dialog) -- both stay on `ReaderApp`
for now, confirmed via `git diff` scope check that
`open_glossary_dialog()`, `open_term_review_dialog()`,
`open_word_glossary_popup()`, and `open_retranslate_popup()` are
unchanged except for the specific renderer-back-reference call-site
edits documented above. No `GlossaryCoordinator`, no
`extracted_episode_urls` schema work (both Phase 3, per the existing
plan). No fix to `_on_text_right_click()`'s hybrid nature beyond
updating its two renderer-reads to go through `self.renderer` --
it still lives on `ReaderApp`, still references both `open_word_glossary_popup`
and `open_retranslate_popup` directly, exactly as Phase 1 recommended
leaving it until Groups C/D are real components too.

### 2026-07-28: Phase 1 -- investigation and proposal (no code changes)

Full read of `alphapolis_reader.py` (3072 lines), `glossary.py` (705
lines, function surface only), `build_glossary.py`'s
`build_glossary_for_novel()`, and all three test files named in this
doc's "why this started" section, done directly rather than delegated,
since the value of this phase is in getting the cross-group dependency
list right -- a summarized version would just move the re-derivation
work to Phase 2. All line numbers below are against
`alphapolis_reader.py` as of this commit unless another file is named.

#### 1. Method/attribute map, grouped by actual concern

**Group A -- Core app shell** (browser lifecycle, episode load/cache/
navigation, state persistence, startup):

- Module-level: `_extract_novel_id()`, `_cache_path()`,
  `load_cached_episode()`, `save_cached_episode()`,
  `load_reader_state()`, `save_reader_state()`, `update_reader_state()`,
  `_image_cache_path()`, `load_cached_image()`, `fetch_image_bytes()`,
  `pack_into_chunks()`, `translate_chunk()`, `translate_lines()`,
  `BrowserWorker` (own class, not `ReaderApp`), `_resolve_image_url()`,
  `_extract_content()`, `parse_episode()`, `main()`.
- `ReaderApp` methods: `__init__` (partial -- see cross-group notes),
  `_load_backend()`, `_save_backend()`, `_save_settings()`,
  `fetch_and_translate()` (l.1107), `_do_fetch_and_translate()` (l.1146),
  `load_episode()` (l.1224), `refresh_current_episode()` (l.1278),
  `_confirm_clear_cache()`, `clear_cache()`, `prefetch()` (l.2043),
  `display_episode()` (l.2061), `go_prev()`, `go_next()`,
  `open_load_url_dialog()`, `open_settings_dialog()`, `set_status()`,
  `show_error()`.
- `ReaderApp` attributes: `root`, `browser`, `target_lang`, `backend`,
  `episode`, `cache`, `_fetch_in_progress`, `_restore_scroll_pos`,
  `current_url` (set in `display_episode()`, read everywhere via
  `hasattr(self, "current_url")` guards -- **note**: never initialized
  in `__init__`, only ever set the first time an episode loads; every
  dialog method defends against its absence with a `hasattr` check
  rather than it being `None` by default), `_prefetching`, `_loading`,
  `url_var`, `prev_btn`, `next_btn`, `status_label`, toolbar/window
  widgets built in `__init__`.

**Group B -- Rendering** (view-mode renderers, span tracking,
appearance/theming, image handling):

- Module-level: `build_interleaved_pairs()`.
- `ReaderApp` methods: `apply_appearance()`, `_apply_page_width()`,
  `increase_font()`, `decrease_font()`, `increase_image_width()`,
  `decrease_image_width()`, `toggle_dark_mode()`, `_available_fonts()`,
  `_pick_default_font()`, `_make_photo_image()` (l.2085),
  `_render_content()` (l.2118), `_render_interleaved_content()`
  (l.2140), `_render_translated_view()` (l.2209),
  `_render_translated_content()` (l.2241),
  `_render_translated_content_from_translated_lines()` (l.2278),
  `_apply_needs_review_spans()` (l.2340), `_on_needs_review_click()`
  (l.2377), `_on_view_mode_change()`, `render_text()` (l.2406),
  `_span_at_index()` (l.2512), `_translated_span_after()` (l.2528),
  `build_review_term_map()` (module-level, but conceptually rendering
  support -- only consumer is the unused-by-production-code path noted
  in DESIGN.md Section 6).
- `ReaderApp` attributes: `font_size`, `image_width`, `dark_mode`,
  `line_height`, `paragraph_spacing`, `page_width_pct`, `text_align`,
  `view_mode`, `font_family`, `_photo_images`, `text` (the `tk.Text`
  widget itself), `_rendered_spans`, `_review_terms_by_span`,
  `_translated_line_index_by_span`.

**Group C -- Glossary dialogs** (all three surfaces):

- `open_glossary_dialog()` (l.1357-1797, ~440 lines) -- the full term
  editor: honorific policy, Treeview + form, Add/Delete, Rebuild
  Glossary (calls `build_glossary_for_novel()`), Clear Glossary, and
  `save_and_close()`'s merge-on-divergence re-check-before-write logic
  (l.1736-1791).
- `open_term_review_dialog()` (l.1799-2041, ~240 lines) -- the bulk
  review queue: lists `status != STATUS_CONFIRMED`, per-term
  Confirm (writes via `upsert_confirmed_term()`) / Reject (real delete).
- `open_word_glossary_popup()` (l.2575-2809, ~235 lines) -- the
  right-click/needs-review-click popup: Google/LLM reference guesses,
  `explain_term()` call, Save writes via `upsert_confirmed_term()`.
- `_maybe_refresh_after_glossary_edit()` (l.1288) -- shared by all
  three dialogs' close paths.
- `ReaderApp` attributes: `_glossary_popup`, `_word_guess_cache`.
- Imports from `glossary.py` used only by this group:
  `DEFAULT_HONORIFIC_POLICY`, `HONORIFIC_POLICIES`, `STATUS_CONFIRMED`,
  `STATUS_SUGGESTED`, `TERM_TYPE_CHARACTER`, `TERM_TYPE_GENERAL`,
  `best_candidate_for_term`, `load_glossary`, `make_confirmed_term`,
  `save_glossary`, `upsert_confirmed_term`. Plus
  `build_glossary_for_novel` (from `build_glossary.py`).

**Group D -- Retranslation dialog**:

- `open_retranslate_popup()` (l.2811-2989, ~180 lines) -- popup calling
  `retranslate_line_with_hint()`, Accept/Discard, the
  `_translated_line_index_by_span` write-through-to-episode-dict fix.
- `ReaderApp` attributes: `_retranslate_popup`.
- Menu-gating logic living in `_on_text_right_click()` (Group B's
  right-click handler; see cross-group dependency below) that decides
  whether "Retranslate this line..." appears.

#### 2. Cross-group dependencies (the part that determines difficulty)

This is not a clean four-way split. Concretely, by pair:

**B <-> C (rendering <-> glossary), the heaviest coupling:**

- `_render_translated_content_from_translated_lines()` (B) and
  `_render_interleaved_content()` (B) both call `load_glossary()` (C's
  primary dependency) directly and pass the *unfiltered* glossary dict
  into `find_glossary_term_spans()` (glossary.py, but conceptually
  owned by whichever group ends up owning "what does this rendered
  line need to look like") via `_apply_needs_review_spans()` (B).
  Comment at l.2178-2180 and l.2230-2235 both explicitly justify this
  as "full glossary, not build_mask_targets()'s unconfirmed-only
  filter" -- rendering needs read access to raw glossary state that
  bypasses the confirmed/suggested distinction the dialogs otherwise
  enforce.
- `_on_needs_review_click()` (B) calls `open_word_glossary_popup()` (C)
  directly -- a rendering-triggered event opens a glossary-group
  dialog. This is the single most direct B->C call.
- `_maybe_refresh_after_glossary_edit()` (C, shared by all three
  dialogs) calls `self.refresh_current_episode()` (A) which calls
  `self.load_episode()` (A) -- a glossary-group action triggers a full
  core-app-shell re-fetch/re-render cycle.
- All three glossary dialogs read `self.current_url` (A) via
  `_extract_novel_id()` to resolve `novel_id` -- every dialog entry
  point is gated on core-app-shell state.

**A <-> C:** `_do_fetch_and_translate()` (A) is where
`load_glossary()`, `build_mask_targets()`, `build_splice_fallbacks()`,
`update_candidate_counts()`, and `save_glossary()` are actually called
in the hot path (l.1150-1209) -- this is the *actual* location of the
extraction-vs-dialog race and the closest thing to existing
"coordinator" logic today, and it lives in Group A, not C. Any
coordinator built in Phase 3 has to either move this logic out of
`_do_fetch_and_translate()` or have Group A call into the Group C
coordinator -- there is no version of this refactor where A and C
don't talk.

**B <-> D:** `_translated_span_after()` (B, defined alongside
`_span_at_index()`) is the sole mechanism `open_retranslate_popup()`'s
gating logic (in `_on_text_right_click()`, B) uses to resolve "the
current translation of this line" -- documented explicitly at
l.2494-2500 as depending on `_render_interleaved_content()`'s exact
`_rendered_spans` append order. `open_retranslate_popup()`'s Accept
handler (D) also writes directly into
`self._translated_line_index_by_span` (a B-owned attribute) and
`self.episode["translated_lines"]` (A-owned data) to make the
correction survive a view-mode switch (l.2965-2978) -- three-way
coupling in a single method (D writes to B's tracking structure and
A's episode dict).

**C <-> D:** none directly. `open_retranslate_popup()` reads
`load_glossary()`/`format_glossary_for_prompt()` for prompt context
(l.2867-2868) but never writes glossary state and isn't gated by any
glossary dialog. This is the cleanest boundary in the file.

**A <-> D:** `open_retranslate_popup()` reads `self.current_url`,
`self.target_lang`, `self.episode` (all A). One-directional (D reads A,
never A calling into D).

**Shared, cross-cutting, belongs to none of the four cleanly:**

- `_on_text_right_click()` (l.2444-2510) is genuinely a hybrid: it's a
  Group B event handler (reads `_rendered_spans`, `_span_at_index()`),
  but its menu construction directly references both Group C
  (`open_word_glossary_popup`) and Group D (`open_retranslate_popup`,
  gated on `self.view_mode.get() == "interleaved"`, a B-owned setting).
  This single method is the most concrete evidence that "rendering,"
  "glossary," and "retranslation" are not cleanly separable Tk event
  surfaces -- whichever module owns this method has an import/call
  dependency on the other two.
- `_word_guess_cache`/`_glossary_popup`/`_retranslate_popup` popup
  dedup pattern (l.683-694, and the `<Destroy>`-bound clearing at
  l.2614/l.2855) is duplicated per-popup-kind rather than shared, but
  is small and mechanical enough that duplicating it across split
  modules costs little; not worth generalizing as part of this
  refactor.

**Net assessment**: Groups C and D split cleanly from each other. Group
B is entangled with both A (span/episode-dict writes) and C (glossary
reads for span-level highlighting) in ways that are real, load-bearing,
and documented as deliberate in the existing code -- not incidental
coupling that a mechanical split would remove. This confirms
`RETRANSLATION_DESIGN.md`'s framing (rendering reuses the glossary read
path, retranslation reuses rendering's span tracking) rather than
contradicting it, but it means Phase 2 (rendering extraction) cannot be
done as a pure "cut along B's boundary" operation -- it will need to
either (a) accept that the rendering module imports `glossary.py`
directly (already true today at the module level -- `glossary.py` has
zero imports of `alphapolis_reader.py`, so this direction is safe), or
(b) take a narrow slice of coordinator interface as a Phase 2
prerequisite. Recommendation below is (a): rendering importing
`glossary.py` functions directly is not the pattern this refactor is
trying to eliminate (that pattern is independent load/write pairs
against the *same mutable state*, not read-only lookups) -- see the
coordinator design in section 4.

#### 3. Construction pattern: composition, not mixins

**Decision: composition with explicit references, not mixins via
multiple inheritance.**

Evidence against mixins: the cross-group dependency map above shows
every pair except C<->D has *bidirectional* method calls (B calls into
C, C calls back into A, D writes into B's attributes and A's data).
Mixin composition (each concern as a class, `ReaderApp` inherits from
all of them) works cleanly when dependencies are one-directional or
absent -- it relies on `self` meaning "the same flat namespace" so any
mixin can freely call any other mixin's methods, which papers over
coupling rather than making it explicit. Given how much real,
deliberate cross-group calling already exists (documented in the
inline comments themselves, e.g. l.710-716's explicit reasoning for
why `_review_terms_by_span` is kept separate from `_rendered_spans`),
mixins would preserve today's implicit "everything is `self.foo`"
shape with a cosmetic file split on top -- not a real improvement in
tractability, and it actively obscures which module a given call is
reaching into versus staying local.

Composition makes the same calls explicit: `self.glossary_coordinator.
upsert_confirmed_term(...)` reads as a cross-module call at the call
site, `self._rendered_spans` reads as local state. This is also
what makes the coordinator's interface (section 4) meaningful as a
*seam* -- a mixin has no seam, it's still one flat `self`.

**Concrete shape proposed:**

```python
class ReaderApp:
    def __init__(self, root, browser, start_url, ...):
        ...
        self.renderer = ReaderRenderer(self)     # Phase 2
        self.glossary = GlossaryCoordinator(...)  # Phase 3
        self.retranslation = RetranslationController(self)  # Phase 4
```

`ReaderApp` itself becomes Group A (core shell) plus thin delegating
call sites where a toolbar button or event handler currently calls a
method directly (e.g. `command=self.open_glossary_dialog` becomes
`command=self.glossary.open_dialog`). Each component holds an explicit
back-reference to the owning `ReaderApp` (`self.app` or similar) for
the state it needs to read (`current_url`, `episode`, `text` widget,
`view_mode`) rather than the component reaching into a shared
namespace implicitly -- same idiom `RETRANSLATION_DESIGN.md` and
`DESIGN.md` already use for "purpose-built side table, not folded into
an existing structure" (e.g. `_review_terms_by_span` vs.
`_rendered_spans`), just applied one level up at the module-boundary
scale.

**Tradeoff, stated explicitly**: composition means every cross-group
call site in the ~180 call sites currently written as `self.foo(...)`
or `self._bar` needs to become `self.renderer.foo(...)` /
`self.glossary._bar` (or a passed-in reference) during the actual
extraction -- more mechanical churn per phase than a mixin's "just
change the class declaration line." This is the correct tradeoff for
this codebase specifically: the goal named in this doc's own "why this
started" section is making cross-cutting bugs *harder to write
accidentally*, and mixins' entire value proposition (implicit shared
namespace) is in direct tension with that goal. A mixin split would
ship a "Phase 1 complete" label without actually reducing the risk this
refactor exists to reduce.

#### 4. Glossary coordinator interface

**Reusing the real re-check-before-write/merge-by-source logic, not
redesigning it**: the logic to lift verbatim lives in
`open_glossary_dialog()`'s `save_and_close()`, l.1736-1791 specifically
l.1754-1781 (the `current_glossary.get("updated_at") != opened_updated_at`
check, `current_by_source`/`local_by_source`/`merged_by_source`
construction, and the `edited_sources`/`deleted_sources` set-based
narrowing that a live-verified bug fix (l.1762-1773's comment) proved
was necessary, not optional). This is the one piece of "coordinator"
logic that already exists and already works; every other dialog's
write path (`open_term_review_dialog()`'s immediate-write Confirm/
Reject, `open_word_glossary_popup()`'s immediate-write Save) is
*simpler* than this because they write once and don't hold a long-lived
in-memory snapshot the way `open_glossary_dialog()` does -- but that
simplicity is exactly why they were vulnerable to being overwritten by
this dialog before the fix landed, per this doc's own "why this
started" section.

**Proposed interface** (`glossary_coordinator.py`, new module in
Group C's territory):

```python
class GlossaryCoordinator:
    def __init__(self, novel_id: str):
        self.novel_id = novel_id
        self._rebuild_in_progress = False  # per-instance; app owns one per open novel

    def load(self) -> Dict[str, Any]:
        """Thin wrapper over glossary.load_glossary(self.novel_id)."""

    def save_snapshot(self, opened_at: Dict[str, Any], local_terms, edited_sources, deleted_sources, honorific_policy) -> Dict[str, Any]:
        """The open_glossary_dialog() save_and_close() logic, lifted
        verbatim: re-checks updated_at, merges by source using
        edited_sources/deleted_sources to scope which entries this
        caller's copy is allowed to overwrite. Returns the final saved
        glossary. This is the ONLY write path for a caller holding a
        long-lived in-memory snapshot (i.e. open_glossary_dialog()
        specifically)."""

    def upsert_confirmed(self, new_term: Dict[str, Any]) -> Dict[str, Any]:
        """Thin wrapper over glossary.upsert_confirmed_term(), reload-
        then-write (no snapshot to reconcile since caller never held
        one) -- used by open_term_review_dialog()'s Confirm and
        open_word_glossary_popup()'s Save, both of which write
        immediately per-action already and don't need save_snapshot()'s
        merge logic."""

    def reject(self, term_identity) -> Dict[str, Any]:
        """The real-delete-by-identity logic from open_term_review_
        dialog()'s reject_selected(), lifted as-is."""

    def is_rebuild_running(self) -> bool: ...

    def start_rebuild(self, status_cb) -> None:
        """Wraps build_glossary_for_novel() in a background thread,
        same as open_glossary_dialog()'s rebuild_glossary() today.
        Tracks self._rebuild_in_progress so a second concurrent rebuild
        request (or a fetch_and_translate() extraction-vs-dialog race,
        see below) can check it rather than firing a second real LLM
        pass."""

    def notify_edited(self, edited: bool) -> None:
        """Replaces the direct self._maybe_refresh_after_glossary_edit()
        call each dialog's close_dialog() makes today -- coordinator
        forwards to the ReaderApp-supplied callback rather than each
        dialog needing its own reference to the app for this one call."""
```

**Per-novel rebuild tracking**: `ReaderApp` (or a thin
`GlossaryCoordinatorRegistry`, if more than one novel's coordinator can
be alive at once -- checked: today only one novel is ever open at a
time in this single-window app, so a single `self.glossary` reference,
re-created when `current_url`'s novel_id changes, is sufficient; no
registry needed) holds one `GlossaryCoordinator` instance per currently-
open novel. `is_rebuild_running()`/`start_rebuild()` replace
`open_glossary_dialog()`'s local `rebuild_state = {"running": False}`
dict (l.1658) with coordinator-owned state that's visible across all
three dialogs and `_do_fetch_and_translate()` -- this is the actual
mechanism section 5 below relies on.

**Hooking into `_maybe_refresh_after_glossary_edit()`**: unchanged in
behavior, relocated in ownership. Today it's a `ReaderApp` method all
three dialogs call directly; proposed shape keeps it as a `ReaderApp`
method (it needs `self.refresh_current_episode()`, Group A) but each
dialog now calls `self.app.glossary.notify_edited(True)` ->
coordinator forwards to a callback the `ReaderApp` registered when
constructing the coordinator, rather than the dialog needing to import
or reach across to `ReaderApp` directly. This keeps the actual
refresh-triggering logic (which is Group A's concern -- it calls
`load_episode()`) out of the coordinator, while still centralizing
"was anything edited" tracking.

#### 5. Extraction-vs-dialog race and non-incremental cost: consequences of the coordinator, not separate fixes

Per DESIGN.md's 2026-07-28 background-extraction investigation entry
(referenced in this doc's Goals section): the race is that
`build_glossary_for_novel()` (triggered from `open_glossary_dialog()`'s
Rebuild Glossary button) and any of the three dialogs' direct writes
can interleave, and re-extraction re-processes every cached episode
every time (no incremental marker).

**Race, resolved as a natural consequence**: with a `GlossaryCoordinator`
per novel owning all writes, `start_rebuild()` sets
`self._rebuild_in_progress = True` for the duration of the background
thread. `upsert_confirmed()`/`reject()`/`save_snapshot()` (the other
three write paths) can check `is_rebuild_running()` before writing and
either (a) queue/defer until the rebuild's own `save_glossary()` call
completes, using the exact same re-check-before-write pattern
`save_snapshot()` already implements (compare `updated_at` before
writing, merge by source if it changed) -- no new mechanism, the
existing merge logic generalizes to this case directly since a rebuild
is just another writer with its own `updated_at` bump -- or (b) at
minimum, log a clear warning and still apply the same merge-by-source
logic rather than blind-overwriting. This falls out of centralizing
"every write path re-checks `updated_at` and merges by source" as the
coordinator's one rule, applied uniformly, rather than
`open_glossary_dialog()` being the only writer with this protection
today.

**Non-incremental cost, resolved as a natural consequence**: this
needs one real new piece of state, not present in today's schema --
a per-episode "already extracted at revision N" marker. Proposed:
`glossary["extracted_episode_urls"]: List[str]` (or a
url->extracted-at timestamp dict, if staleness-based re-extraction is
ever wanted later -- a plain list is sufficient for "skip if already
done," which is all that's asked for now). `build_glossary_for_novel()`
would filter `_load_cached_episodes_for_novel()`'s result against this
set before calling `extract_glossary_terms()`, and the coordinator's
`start_rebuild()` would be the single place that both makes this list
available to `build_glossary.py` and writes the updated set back
alongside the rest of the rebuild's `save_glossary()` call -- i.e. this
is naturally a coordinator-owned schema field precisely because
`GlossaryCoordinator` is already the module boundary between "the
reader app" and "glossary state," and `build_glossary_for_novel()`
already takes `novel_id` and returns the updated dict, so threading one
more field through its existing return value costs little. Not a fix
that needs its own separate design pass; the mechanism the coordinator
already needs for the race above (structured, versioned writes) is the
same mechanism that makes "skip already-processed episodes" a matter
of consulting one more field on the same dict, not a new subsystem.

**What Phase 3 still needs to decide for real, not answered here**:
whether `extracted_episode_urls` needs a `CACHE_SCHEMA_VERSION`-style
bump or a plain `.get(..., [])` default (this doc's own established
precedent per DESIGN.md Section 9/10 is "no migration shim, clean
cutover" for schema-shape changes -- likely applies here too, but
Phase 3 should verify against actual on-disk glossary files before
assuming, same discipline DESIGN.md applies throughout); and the exact
UI feedback when a write is deferred/merged during an in-progress
rebuild (a status-bar message per this doc's existing `set_status()`
convention is the obvious default, not decided here).

#### 6. Test reorganization

**The three fragile harnesses, named and confirmed by direct reading**:

- `tests/webnovels/test_alphapolis_reader.py:405` `_DispatchHarness` --
  stands in for `_render_translated_view()` testing; hand-builds
  `text`, `_rendered_spans`, `_review_terms_by_span`, `current_url`,
  `render_calls`, and pulls `_render_translated_view` off `ReaderApp`
  directly as an unbound-method assignment.
- `tests/webnovels/test_retranslation_display.py:63` `_InterleaveHarness`
  -- same pattern, adds `_translated_line_index_by_span`,
  `fallback_calls`, pulls `_render_interleaved_content` and
  `_apply_needs_review_spans` off `ReaderApp`.
- `tests/webnovels/test_retranslation_dialog.py:218`
  `_NeedsReviewAndRetranslateHarness` -- same four tracking attributes
  plus pulls `_translated_span_after` too.

All three construct the exact same handful of attributes
(`text`, `_rendered_spans`, `_review_terms_by_span`,
`_translated_line_index_by_span`, `current_url`) by hand, in three
separate files, and this doc's own "why this started" section already
documents three separate `AttributeError` incidents from new
`ReaderApp` attributes not being mirrored into these harnesses (most
recently `_translated_line_index_by_span` itself, per
`RETRANSLATION_DESIGN.md`'s 2026-07-27 entry, l.724-733 there).

**Proposed replacement: a real `ReaderApp` test subclass /
factory fixture, not per-harness hand-rolling.** Once Phase 2 exists
(rendering extracted into its own component, e.g. `ReaderRenderer`),
the natural fix is that `ReaderRenderer.__init__` only needs a `text`
widget and an `app` back-reference -- at that point these three
harnesses collapse into "construct a real `ReaderRenderer` against a
real headless `tk.Text` widget and a minimal fake `app` object exposing
only `current_url`/`episode`/`view_mode`," which is a *much* smaller
surface to hand-build than today's four-attributes-times-three-files
duplication, because the renderer's own `__init__` becomes the single
source of truth for what state it needs -- adding a new renderer
attribute only requires updating the fake `app` stand-in if the
renderer's `__init__` itself grows a new dependency on `app`, not three
independent test files each separately guessing which subset of
`ReaderApp.__init__`'s ~30 attributes matter.

Concretely, propose one shared fixture module,
`tests/webnovels/conftest.py` (checked: no `conftest.py` currently
exists under `tests/webnovels/` -- confirmed via directory listing
before proposing this, not assumed), providing:

```python
@pytest.fixture
def headless_text_widget():
    """Real (not withdrawn) tk.Text + root, tag_configure'd with the
    real three-tag palette -- the exact pattern all three existing
    harnesses' _make_widget() already duplicate, deduplicated here."""

@pytest.fixture
def fake_reader_app(headless_text_widget):
    """A minimal object exposing exactly ReaderRenderer's declared
    dependencies (post-Phase-2) -- NOT a hand-copied attribute list,
    but constructed by introspecting (or, more simply and robustly,
    just delegating to) ReaderApp.__init__'s own default-construction
    path for the subset of state that doesn't require a live browser/
    network. This is the actual fix: whatever ReaderRenderer's __init__
    signature declares it needs becomes the fixture's job to supply,
    so a new dependency is a signature change the fixture's own
    construction surfaces immediately (a TypeError on missing arg) --
    not a silent AttributeError three call sites later."""
```

Every one of the three existing harness classes gets deleted and
replaced by constructing the real `ReaderRenderer` (post-Phase-2)
against this fixture; the `_render_translated_view = ReaderApp.
_render_translated_view`-style unbound-method-assignment idiom goes
away entirely because the method now lives on `ReaderRenderer` and the
fixture constructs a real instance of it, not a fake stand-in
pretending to be `ReaderApp`.

**Sequencing**: this only fully pays off once Phase 2 lands (there's no
`ReaderRenderer` to construct for real before then). Proposed sequence:
Phase 2 extracts rendering *and* introduces the shared
`conftest.py` fixtures in the same phase (per this doc's own Phase 2
description: "Includes migrating/fixing that module's tests as part of
this phase, not deferred to a later catch-all"), replacing all three
harnesses at once even though two of them
(`_InterleaveHarness`/`_NeedsReviewAndRetranslateHarness`) live in
retranslation-named test files -- the harnesses are rendering-shaped
regardless of which doc's feature they were built to test, and fixing
them piecemeal per-phase would mean `test_retranslation_dialog.py`
carries a stale hand-rolled harness until Phase 4, still vulnerable to
the exact `AttributeError` pattern this whole item exists to close.
`test_alphapolis_reader.py`/`test_retranslation_display.py`/
`test_retranslation_dialog.py` themselves stay as separate files (their
existing "tracked separately on purpose" rationale, per
`RETRANSLATION_DESIGN.md`'s own framing, is about feature boundaries,
not code-module boundaries, and remains valid) -- only their internal
harness *construction* changes, not which file a given test lives in.
A later, natural rename (e.g. `test_alphapolis_reader.py`'s renderer-
specific classes moving to a `test_reader_renderer.py` once
`ReaderRenderer` is a real module) is reasonable but secondary to fixing
the harness pattern itself, and not required for Phase 2 to be
complete.

Glossary-dialog tests (`TestGlossaryDialogSelection`,
`TestGlossaryDialogAutoRefresh`, `TestGlossaryDialogMergeOnDivergence`,
`TestFetchAndTranslateDuplicateGuard`, all in
`test_alphapolis_reader.py` today per its class list) don't use a
hand-rolled harness currently (confirmed by reading the file's class
list; they test through real `ReaderApp` construction or direct
function calls) -- Phase 3 should confirm this holds before assuming no
harness-migration work is needed there, but nothing in this
investigation found a fourth fragile harness to add to the three named
above.

#### 7. Migration order for Phases 2-4

**Confirms REFACTOR_DESIGN.md's existing guess, with one refinement.**
Rendering first, glossary+coordinator second, retranslation third --
confirmed correct by the dependency map in section 2, for a reason
sharper than "seems lowest-risk": Group B (rendering) is the one that's
entangled with *both* other groups, so extracting it first forces the
composition seam (section 3) to get built and proven out against the
messiest case immediately, rather than being designed against the
easiest case (D, which has almost no back-coupling) and then
discovering it doesn't hold up once B's real dependencies get added
later. If Phase order were reversed (D or C first), the seam built for
an easy case might need rework once B's actual coupling surfaced.

**Refinement**: Phase 2 as scoped in this doc's existing Phase 2
description already includes "reusing the existing tag mechanism
without touching core app-shell logic," but section 2's finding above
(B writes into `self.episode["translated_lines"]`, an A-owned
structure, via `open_retranslate_popup()`'s Accept handler -- not
Phase 2's own code, but code Phase 2 must not break) means Phase 2's
own acceptance check should explicitly include re-running
`RETRANSLATION_DESIGN.md`'s `TestAcceptSurvivesModeSwitch` regression
test after the extraction, not just the rendering-specific test files
-- that test is the concrete, already-written proof that B/A/D's
three-way coupling around `_translated_line_index_by_span` keeps
working after the module boundary moves, and it's easy to overlook
since it lives in `test_retranslation_dialog.py`, not a
rendering-named file.

Phase 5 (revisit the core app shell) is left exactly as this doc
already frames it -- genuinely contingent on how much Groups B/C/D's
extraction shrinks Group A, not scoped further here.

#### Not done in this pass

No code changes, no test changes, no new module files -- confirmed via
`git diff` scope check that only this doc changed. No decisions made
about `extracted_episode_urls`' exact schema-versioning treatment
(flagged above as still open for Phase 3). No investigation of whether
a `GlossaryCoordinatorRegistry` is needed beyond the one-novel-at-a-time
check already done (flagged above as unnecessary given current
single-window, single-novel usage, but not re-verified against any
future multi-window design that doesn't exist yet).
