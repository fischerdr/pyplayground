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
derail whatever's actively in progress. No sub-agent delegation by
default — work directly, don't spin up sub-agents to parallelize or
delegate investigation/implementation steps unless explicitly told to
for a specific task.

Read `INDEX.md` first for what each design doc is for.

---

## Now (active)

Nothing active. See Recently closed below for what just wrapped up.

## Someday-Maybe (parked — revisit only on a concrete trigger, not a schedule)

- §7 web migration (`DESIGN.md`) — full Tkinter → web rebuild (FastAPI
  backend skeleton, shared-secret auth for home-network reachability,
  5 phases through review-queue UI and a config/styling panel). Sat in
  this file's "Now" tier the entire 2026-08-02 through 08-05 session
  span as a plan with zero code, while six real improvements shipped on
  the current Tkinter UI in that same window (window/menu redesign,
  toolbar right-click, type-quick-edit, status-bar counts, the `<ruby>`
  fix, the `「」` fix) — the current UI is solid and actively improving,
  no active pressure toward a rebuild. Trigger to revisit: a genuine
  need for reachability beyond the current machine (§7's own stated
  target — "reachable on home network, not just localhost"), or the
  Tkinter UI hitting a real limitation nothing short of a web rewrite
  can address. Not "it would be nice to have."

- Cross-chapter context carryover (MT survey doc, mirrors
  `bilingual_book_maker`'s `--use_context`; targets DITING's stated
  discourse-coherence weak point). Not scoped — open: what counts as
  context, prompt injection point, cost/latency tradeoff. Builds on
  existing masking/prompt infrastructure.
- Quality-estimation gating for retranslation (MT survey's Stage 4
  recommendation) — auto-flag likely-bad lines instead of full-chapter
  Refresh. Not scoped — open: signal to use (LLM-judge pass? heuristic
  like suspiciously-short output relative to source?), threshold,
  trigger (automatic vs. button). Builds on `RETRANSLATION_DESIGN.md`'s
  already-complete manual pipeline.
- Hot/new novel browsing (site discovery, distinct from load-by-URL) —
  larger scope: new scraping targets, likely a new UI area. Not scoped
  at all.

- `（）` inner-monologue parenthesis loss (missing closing `）`/stray
  quote on some whole-line `（...）` cases, and spurious quote-wrapping
  of bracket-free narration in some episodes) — investigated twice
  (`DESIGN.md` §13, 2026-08-04 and 2026-08-05). Confirmed real in the
  original cache, confirmed NOT the `「」` issue's `_clean_output()`
  mechanism, chunk-boundary-position hypothesis directly ruled out via
  instrumented live re-translation. But the failure did **not**
  reproduce on demand -- 7 live re-translation attempts (both current
  and pre-`「」`-fix prompt versions) against the two known-affected
  lines from the original report all came back correctly balanced.
  Conclusion: likely a rare, non-deterministic model sampling artifact,
  not a discoverable code-level bug -- no confirmed mechanism exists to
  target with a fix, so none was attempted (guessing at a fix for a
  non-reproducing artifact would risk papering over a symptom with no
  evidence it addresses the real cause). Trigger to revisit: a new,
  concretely reproducible instance (i.e. a case that fails consistently
  across multiple re-runs, not just once in an old cache entry) --
  until then, parked, not actionable. Distinct from the closed `「」`
  half of this investigation, see Recently closed.
- WAF-constraint re-verification (`STALENESS_DESIGN.md` Phase 1,
  2026-08-05) — a live test found the documented plain-HTTP 202 WAF
  challenge (the entire justification for `BrowserWorker`/Playwright,
  per `GLOSSARY_ARCHITECTURE.md`) did not reproduce: GET, HEAD, and
  no-UA GET all returned 200 with full content, once. Potentially
  high-value if it holds (Refresh currently costs ~2-4.5 minutes per
  `STATUS_BAR_DESIGN.md`'s own measurement) -- but this is a single
  test session's result, explicitly not treated as durable by the
  investigation that found it, and it surfaced as a tangent inside an
  unrelated Phase 1, same shape as the repo-split and multi-model-
  comparison entries above. Not touching `BrowserWorker` or the
  production docstring on this alone. Trigger to revisit: repeated
  testing across varied conditions/time confirms the result holds, OR
  `STALENESS_DESIGN.md` Phase 2 actually needs this resolved to proceed
  (its own cost analysis is currently blocked on this exact question).
  Counterpoint, worth weighing against any future "simplify away from
  Playwright" impulse: even if Alphapolis' own WAF has genuinely lapsed,
  `novelfire_library_pw.py` already demonstrates this project needs real
  browser automation for at least one source (Cloudflare JS challenge +
  login, hybrid Playwright-then-`requests.Session` cookie handoff,
  confirmed by reading that module's own docstring and auth code) — so
  `BrowserWorker` likely stays justified architecturally regardless of
  what's confirmed about Alphapolis specifically. This finding is about
  Alphapolis's current behavior, not a case for removing Playwright from
  the project generally.
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
- `STALENESS_DESIGN.md` — Phase 1 (investigation + proposal) complete
  (2026-08-05). Found a real signal (`upTime` per episode, inside
  `#app-cover-data`'s JSON blob) but its semantics (publish-time vs.
  last-edited) could not be confirmed either way; also found the
  documented plain-HTTP WAF challenge (`alphapolis_reader.py`'s own module
  docstring, the reason `BrowserWorker`/Playwright is required at all)
  does not currently reproduce on a live re-test (GET, HEAD, and no-UA
  GET all returned 200 with real content) -- surprising, flagged, not
  resolved. UI question (auto-refresh vs. badge vs. something else) left
  open. Phase 2 not started, contingent on resolving `upTime`'s semantics
  first.

## Opportunistic only (fix only as a side effect of touching that file for something else — never scheduled standalone)

- Stale docstring on `_render_translated_content_from_translated_lines()`.
- `GlossaryCoordinator.is_rebuild_running()`/`start_rebuild()` line-spacing
  sanity check (likely nothing, just confirm no stub/decorator oddity).

## Recently closed (for continuity, trim this section periodically)

- `CHAPTER_LIST_DESIGN.md` — both phases complete (2026-08-05). Phase 2:
  jump-to-chapter modal (search-as-you-type by title/number, current
  chapter auto-highlighted/scrolled on open, sort-direction toggle, no
  pagination), background `BrowserWorker` prefetch of the novel's full
  690-chapter list keyed by novel_id, `up_time` persisted per episode to
  the on-disk cache (no `CACHE_SCHEMA_VERSION` bump, same graceful-
  degradation pattern as `page_count`). `dispOrder` confirmed gapless
  1..690 with no evidence of an Alphapolis-side chapter split (79
  shared-prefix-numbered titles found, read as a genuine numbered
  sub-arc naming convention, not a split). A real `BrowserWorker.fetch()`
  bug found and fixed along the way: it was hardcoded to wait for
  episode-page-only selectors in `state="visible"`, which a `<script>`-
  tag selector (needed for the novel main page) can never satisfy — now
  takes `wait_selector`/`wait_state` parameters. 345/345 tests, lint
  clean, live-verified end to end (modal open, both search modes,
  click-navigation) via a fresh Xvfb session.
- `STALENESS_DESIGN.md` unblock: its any-change-flag workaround needs a
  prior-fetch `up_time` snapshot to diff a fresh fetch against — that
  data is now real and persisted (`CHAPTER_LIST_DESIGN.md` Phase 2,
  above), which is a concrete unblock worth revisiting. Not auto-
  promoting `STALENESS_DESIGN.md` to Now here — that's a separate
  decision.
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
- `<ruby>`-wrapped status-window term fragmentation (`_extract_content()`
  emitting single-character "lines" for filler-dot `<ruby>` emphasis
  markup, e.g. `<ruby>塩<rt>・</rt></ruby>`) — surfaced via the new
  `STATUS_BAR_DESIGN.md` paragraph-count field flagging an outlier
  count, but a pre-existing extraction bug, not caused by that field.
  Investigated, general-fix (b) scoped and deliberately not adopted
  (proven furigana-content-loss risk), targeted fix (a) implemented
  instead (2026-08-04) — four-episode live-HTML verification (2 fixed,
  2 confirmed byte-identical no-op on real furigana), 344/344 tests
  passing, new regression fixture added. Full history in `DESIGN.md`
  §13's `2026-08-03`/`2026-08-04` entries.
- Single-speaker `「」` dialogue-quote loss (43.9% of surveyed dialogue
  lines lost all quote marking in translation, root cause:
  `_clean_output()`'s double-quote strip is structurally unable to tell
  a correctly-quoted whole-line dialogue translation apart from the
  JSON-double-wrap artifact it was built to undo) — fixed (2026-08-04)
  by instructing single quotes (`'...'`) for `「」`-sourced dialogue in
  `TRANSLATION_PROMPT`, sidestepping the ambiguity rather than trying to
  resolve it in `_clean_output()` (left untouched). Live re-translation
  against the real production path confirmed recovery on every
  previously-dropped case tested, no regression on the
  already-working embedded-dialogue case; one honest compliance gap
  found (model used curly double quotes instead of single quotes on one
  longer line) that does not reproduce the original content-loss bug.
  345/345 tests passing, new regression test added. Distinct bug from
  the `（）` inner-monologue parenthesis issue, which remains open (not
  reproducible on demand, no fix attempted -- see Someday-Maybe above).
  Full history in `DESIGN.md` §13's `2026-08-04` entries.
