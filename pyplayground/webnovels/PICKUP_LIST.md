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

1. `WINDOW_REDESIGN.md` Phase 4 — text right-click "edit type" quick
   action for existing glossary terms. Investigation complete (2026-08-02,
   see the doc's dated entry) -- confirmed `gender`/`pronoun_style`/
   `honorific_override` are genuinely read by `format_glossary_for_prompt()`
   (not display-only, as an earlier draft assumed) and that no existing
   honorific-suffix detector exists to reuse. Implementation not started.
   Phases 2 (menu bar + button/mode reorg) and 3 (toolbar right-click
   context menu) complete as of 2026-08-02.
2. Deferred/low-priority batch (see below) — not urgent, but visible.
3. §7 web migration (`DESIGN.md`) — still just a plan, zero code.

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
  consumption, existing suffix-detection check) — complete, findings
  only, no code.
- `GLOSSARY_ARCHITECTURE.md` refreshed (2026-08-02) — was stale since
  2026-07-30; folded in `WINDOW_REDESIGN.md` Phases 2-3, `RETRANSLATION_DESIGN.md`
  Phases 4-5 (both previously mis-documented as not started), the
  collective-shout bracket fix, and the `safe_persistence.py` migration.
