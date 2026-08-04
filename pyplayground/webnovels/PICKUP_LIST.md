# Pickup List

Living, tiered task list. Update this file directly when items move
tiers, get done, or get added — don't let it drift back into only
existing in chat.

**How this works, carried over from a long prior session (for a new
agent/session picking this up cold):** items are tiered, not flat, on
purpose — flat lists don't signal what's actually worth chasing right
now versus what's a "someday" idea. Before adding anything new, check:
is this already built? Is this expected/working-as-designed behavior
being mistaken for a new finding? Only genuinely new, unbuilt ideas get
added. Small side-findings that aren't blocking anything go straight to
Someday-Maybe or Opportunistic without discussion — don't let them
derail whatever's actively in progress.

Read `INDEX.md` first for what each design doc is for.

---

## Now (active)

1. `STATUS_BAR_DESIGN.md` — both phases complete as of 2026-08-03
   (page-count/chapter-position indicator, word/paragraph counts). No
   active work remains on this doc; see Recently closed below.
2. `WINDOW_REDESIGN.md` — all four phases complete as of 2026-08-02
   (menu bar/button reorg, toolbar right-click menu, text right-click
   type-quick-edit). No active work remains on this doc; see Recently
   closed below.
3. Deferred/low-priority batch (see below) — not urgent, but visible.
4. §7 web migration (`DESIGN.md`) — still just a plan, zero code.

## Someday-Maybe (parked — revisit only on a concrete trigger, not a schedule)

- `DESIGN.md` §8 promotion/threshold logic — revisit only if a real
  review backlog becomes an actual observed friction point.
- LLM layer refactor (multi-endpoint, health/slots, metrics) — revisit
  only if a specific new model actually needs infrastructure the
  ad hoc evaluation scripts didn't. Also the eventual home for: a
  richer/multi-backend approach to `explain_term()`-style meaning
  generation, if the current output ever feels too thin in practice.
- Regex post-process fallback for JSON malformation (direction 2) —
  trigger: only if the shipped bracket-stripping fix doesn't hold up in
  real production use.
- `ざわざわ`-style onomatopoeia transliteration quality — a separate,
  smaller translation-quality issue noted in passing, not corruption.
- Flag-while-reading marker feature (a lighter "notice now, fix later"
  companion to the retranslate popup's "stop and fix now" flow) — new
  scope, needs its own design pass if prioritized.
- Migrate to its own git repo — revisit only if something concrete
  actually breaks from being in the monorepo, not "it's gotten big."
- Per-term honorific auto-detection (pre-filling `honorific_override`
  from a suffix/adjacency check at term-creation or type-change time) —
  explicitly scoped out of `WINDOW_REDESIGN.md` Phase 4, not forgotten.
  Trigger: revisit only once a second source-language scraper actually
  exists in the pipeline and there's real non-Japanese text to validate
  a detector against -- confirmed (Phase 4's investigation) that no
  detector exists today in any form, and that building one now would be
  guessing at a shape with nothing but Japanese to test it on.
- Multi-model translation comparison (compare how different models
  translate the same lines/page side-by-side) — sourced from discussion
  of the wtr-lab reference screenshot that also (incorrectly, per
  `STATUS_BAR_DESIGN.md` Phase 1/2) suggested `Web/Web+/AI` tabs were
  relevant to the status-bar work. Not yet scoped or designed at all --
  no trigger condition set yet either, since one can't be picked
  meaningfully before this gets its own design pass (what "compare"
  means here -- side-by-side view, a scoring/voting mechanism, which
  models, whether it touches the glossary/masking pipeline at all -- is
  entirely open).

## Opportunistic only (fix only as a side effect of touching that file for something else — never scheduled standalone)

- Stale docstring on `_render_translated_content_from_translated_lines()`.
- `GlossaryCoordinator.is_rebuild_running()`/`start_rebuild()` line-spacing
  sanity check (likely nothing, just confirm no stub/decorator oddity).

## Recently closed (for continuity, trim this section periodically)

- Windowclose crash — resolved: confirmed Xvfb/Playwright-specific via a
  real supervised desktop test, not a production risk, no fix needed.
- Short-line JSON-malformation (collective-shout brackets) — implemented,
  tested, live-verified, closed.
- `safe_persistence.py` foundational atomic-write + verify-before-write
  helpers — implemented and migrated across all four write call sites.
- `RETRANSLATION_DESIGN.md` — all 5 phases complete.
- `REFACTOR_DESIGN.md` Phase 3 (a-g) — complete.
- `INDEX.md` built.
- `WINDOW_REDESIGN.md` Phase 2 (menu bar + button/mode reorg) — complete.
- `WINDOW_REDESIGN.md` Phase 3 (toolbar right-click context menu) —
  complete.
- `WINDOW_REDESIGN.md` Phase 4 investigation (honorific-field
  consumption, existing suffix-detection check, source-language
  assumptions across the pipeline) — complete, findings only, no code.
- `WINDOW_REDESIGN.md` Phase 4 implementation (text right-click
  "Change Type" quick action, with an inline Gender pick for General ->
  Character) — complete, live-verified against the real glossary file.
  All four `WINDOW_REDESIGN.md` phases now closed.
- `GLOSSARY_ARCHITECTURE.md` refreshed (2026-08-02) — was stale since
  2026-07-30; folded in `WINDOW_REDESIGN.md` Phases 2-3, `RETRANSLATION_DESIGN.md`
  Phases 4-5 (both previously mis-documented as not started), the
  collective-shout bracket fix, and the `safe_persistence.py` migration.
- `STATUS_BAR_DESIGN.md` created and Phase 1 (investigation + proposal)
  complete (2026-08-03) — split out of `WINDOW_REDESIGN.md`. Confirmed
  live against two real Alphapolis episode pages that the page-count div
  is genuine novel-wide chapter position (not per-episode pagination),
  and that the `Web/Web+/AI` tabs/model-attribution badge a reference
  screenshot named are not part of the real page. Confirmed `content`'s
  text/image item shape and that no character/word-counting utility
  exists yet to reuse.
- `STATUS_BAR_DESIGN.md` Phase 2 (page-count/chapter-position indicator
  and word/paragraph counts) — complete (2026-08-03), live-verified
  against real Alphapolis pages and real on-disk episode caches (page-
  count cross-checked against an independent direct page fetch, exact
  match; graceful blank-label degradation confirmed for pre-existing
  cache entries lacking the new field, no `CACHE_SCHEMA_VERSION` bump).
  Both `STATUS_BAR_DESIGN.md` phases now closed.
