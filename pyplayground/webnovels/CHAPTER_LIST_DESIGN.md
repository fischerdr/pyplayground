# Chapter List / Jump-to-Chapter — Design Doc

Living record of decisions for this effort. Update alongside code changes,
not after — chat history is not the system of record. Seventh doc alongside
`DESIGN.md`, `RETRANSLATION_DESIGN.md`, `REFACTOR_DESIGN.md`,
`WINDOW_REDESIGN.md`, `STATUS_BAR_DESIGN.md`, and `STALENESS_DESIGN.md`,
given its own doc rather than staying as a `PICKUP_LIST.md` paragraph — this
grew enough real discussion and locked-in decisions during that session to
warrant the same investigate-then-propose treatment those docs already
received, not to imply this is more built-out than it actually is (Phase 2
implementation has not started).

Last updated: 2026-08-05

---

## Why this started

Current chapter navigation is Prev/Next only — there is no way to jump to
an arbitrary chapter, or even see the novel's chapter list at all, without
stepping through every intermediate chapter one at a time. Surfaced during
the same session that produced `STALENESS_DESIGN.md`'s Phase 1 investigation
and its own follow-up findings; a genuinely separate feature from that doc
(this is about *navigating* to chapters, not detecting whether a chapter's
*content* changed) — see `STALENESS_DESIGN.md`'s own cross-reference note
for the one place the two topics do overlap (new-chapter detection at the
novel level).

## Investigation findings (2026-08-05, moved here from `PICKUP_LIST.md`)

Two rounds of investigation, both complete, both folded in below in full
rather than summarized — this is the same discipline `STATUS_BAR_DESIGN.md`/
`STALENESS_DESIGN.md` Phase 1s already applied to their own findings.

### Round 1: is the full chapter list available cheaply?

The episode page's own `#app-cover-data` blob (the same JSON script tag
`parse_episode()` already reads for `prev_url`/`next_url`, and that
`STATUS_BAR_DESIGN.md` Phase 1 already reads for `dispOrder`/`counterText`)
only carries a handful of **neighboring** episodes, not the full list —
confirmed against a real fetch of novel 375266002's episode page:
`chapterEpisodes[].episodes[]` there held only `dispOrder` 444-446 (three
entries) out of that novel's 690 total episodes.

The novel's **main** page instead — `/novel/{novel_id}/{volume_id}`, no
`/episode/...` suffix, a URL shape `_extract_novel_id()`
(`alphapolis_reader.py:134`) already parses, so deriving it from an
already-known episode URL is a one-line string operation, not new URL
discovery — carries the *same* `#app-cover-data` blob, but populated with
**all 690 episodes**, confirmed via a live fetch of that exact URL. Each
entry: `url`, `mainTitle`, `dispOrder`, `upTime`, `counterText` (same shape
already documented in `STATUS_BAR_DESIGN.md`/`STALENESS_DESIGN.md` for the
per-episode entries on the episode page itself).

**Genuinely cheap**: one extra fetch of a URL pattern the app doesn't
currently hit, reusing the exact same JSON-parsing mechanism
`parse_episode()` already has for the current-page blob — no new scraping
target, no new selector, no per-episode fetch needed to build the list.

### Round 2: is `mainTitle` actually usable, or generic/number-only?

Spot-checked 10 episodes spread across the full 690-episode range (episode
1 through 690, spanning 2024-01-13 through 2026-08-03), not just the most
recent few, since titles could plausibly be present in some eras of a
long-running novel and absent in others:

| Index (0-based) | `dispOrder` | `mainTitle` | `episodeNo` | `upTime` |
|---|---|---|---|---|
| 0 | 1 | `ダンジョンインパクト` | 6444489 | 2024.01.13 20:43 |
| 69 | 70 | `浜辺の来襲者` | 7677989 | 2023.10.28 18:03 |
| 172 | 173 | `サバゲフィールドの植物ダンジョン4` | 7710717 | 2023.11.05 20:48 |
| 345 | 346 | `豚足ハンマー` | 7779706 | 2023.11.25 22:19 |
| 444 | 445 | `contact` | 7800089 | 2023.12.01 13:07 |
| 445 | 446 | `night sky` | 7800123 | 2023.12.01 13:19 |
| 446 | 447 | `sentimental` | 7800137 | 2023.12.01 13:27 |
| 517 | 518 | `Dungeon instructor 5` | 7964360 | 2024.01.22 10:49 |
| 621 | 622 | `One Saturday` | 9292118 | 2025.02.02 20:57 |
| 689 | 690 | `Leather suit` | 11580509 | 2026.08.03 18:32 |

Every one has a genuine, distinct, human-written title — no `"第N話"`/
"Episode N" placeholder pattern found anywhere in the sample, across both
the novel's early (2024) and most recent (2026) eras.

Cross-checked against `parse_episode()`'s own `episode_title_tag` scrape
(`.p-novel-episode__episode-title`, `alphapolis_reader.py:542`) for two of
the sampled chapters (445 "contact", 622 "One Saturday") -- exact string
match both times, confirming the novel-page `mainTitle` and the episode-
page's own title element are the same underlying data, not two sources
that could diverge.

**Titles are usable as-is — no LLM-generated short-title feature is needed
for this data.**

## Decisions locked in (via discussion, before any code)

- **Show real titles alongside chapter number, not a recomputed
  sequential list-position index.** Confirmed via wtr-lab/novelfire
  reference screenshots that sequential list-position index and the
  site's own chapter number can diverge (chapter splits, non-chapter
  entries consuming numbering slots on those sites) -- this app must key
  off Alphapolis's own `dispOrder`/chapter number directly, never a
  recount of position within whatever list happens to be in memory.
- **UI shape: a modal dialog.** Search-as-you-type filter (matching
  either title or number) over a scrollable list; current chapter
  auto-highlighted and scrolled into view on open; a sort-direction
  toggle (oldest/newest first) that's cheap since it's just reversing the
  already-in-memory list, not a re-fetch. **No pagination, no page-size
  setting, no bookmark button** -- those exist on reference sites to
  solve a server-side pagination problem this app doesn't have, since the
  full list lives in memory after one fetch; carrying them over would be
  copying reference-site UI shaped around a constraint that doesn't apply
  here.
- **Data fetch: background prefetch via `BrowserWorker`** (the existing
  dedicated Playwright thread, `queue.Queue`-based request/response pair,
  `alphapolis_reader.py:290`) when a novel loads -- an extension of the
  existing threading pattern, not a new one. In-memory cache once
  fetched, not necessarily persisted to disk -- **flagged as open, not
  assumed**: whether this list is worth writing to the on-disk cache
  (and if so, under what key/schema-version discipline, same question
  `STATUS_BAR_DESIGN.md` Phase 2 and `STALENESS_DESIGN.md` Phase 1 both
  already worked through for their own new fields) is a real Phase 2
  decision, not resolved here.
- **Explicitly out of scope: watching for new chapters appearing on the
  novel over time.** That's the same problem shape as
  `STALENESS_DESIGN.md` -- "has something changed since I last fetched
  it" -- just asked at the novel level (new chapters added) instead of
  the chapter level (this chapter's content changed) that doc already
  scopes. Tracked there, not re-decided here; see `STALENESS_DESIGN.md`'s
  own cross-reference note. `STALENESS_DESIGN.md`'s Phase 2 is currently
  blocked on resolving `upTime`'s semantics (publish-time vs.
  last-edited) -- this doc's own chapter list will surface `upTime` per
  chapter regardless, which may end up being useful data for that other
  doc's own investigation, but resolving it is not this doc's job.

### Flagged for implementation-time sanity check, not yet verified

Confirm `dispOrder` for Alphapolis episodes is genuinely gapless and
one-per-chapter, unlike the novelfire/wtr-lab reference sites (which split
or reflow numbering per their own translation pipelines, per the reference
screenshots that prompted the "key off the site's own number" decision
above). If Alphapolis's own authors ever split a single chapter into
multiple parts on the source site itself, that would plausibly show up as
consecutive `dispOrder` entries carrying a similar or shared title --
worth knowing about before implementation, not assumed away just because
this investigation's own 10-sample spot-check didn't happen to catch an
instance. Not investigated further in this pass; a real Phase 2 task, not
resolved here.

## Phases

Same discipline as the other docs' Phase 1s -- investigate real code and
the real external page before designing further, checkpoint each step,
stop and report on anything unexpected rather than pushing forward
speculatively.

### Phase 1: Investigation and concrete proposal — no code changes

Complete. See "Investigation findings" and "Decisions locked in" above --
both rounds of investigation and the resulting product decisions are
folded into this doc in full, not summarized elsewhere.

### Phase 2: Implementation -- jump-to-chapter modal, chapter-list prefetch, `up_time` persistence

Complete. See the dated entry below for full detail.

## Status

- **Phase 1**: complete (2026-08-05, investigation and proposal, plus
  locked-in UI/data-fetch decisions via discussion -- see above). No code
  changes.
- **Phase 2**: complete (2026-08-05, see dated entry below). Both phases
  of this doc now complete.

### 2026-08-05: Phase 2 -- implementation (jump-to-chapter modal, chapter-list prefetch, `up_time` persistence)

Implemented per Phase 1's locked-in decisions; no design deviation found
once actually writing the code. Work was done directly, one continuous
pass, no sub-agent delegation, per this project's own standing convention
(now written down in `PICKUP_LIST.md`'s intro paragraph).

**`_novel_main_page_url()`** (`alphapolis_reader.py:147`): derives the
novel's main page URL from an episode URL via one regex, per Phase 1's own
"one-line string operation" finding -- no new URL-discovery work.

**`BrowserWorker.fetch()` gained two new parameters, `wait_selector` and
`wait_state`** (`alphapolis_reader.py:378`), and a real bug was found and
fixed while wiring the chapter-list prefetch through it: `fetch()` was
hardcoded to always wait for `#novelBody, .p-novel-episode__text` in
`state="visible"` -- correct for every existing caller (all episode-page
fetches), but the novel main page needed for this feature has no chapter
body at all and never renders those selectors, so the first prefetch
attempt reliably timed out. `#app-cover-data` (a `<script
type="application/json">` tag) is what the main page actually offers to
wait on, but a `<script>` tag has no rendered box and can never satisfy
`state="visible"` regardless of how long the wait runs -- confirmed live,
Playwright's own timeout log showed the locator resolving to the element
33 times while still timing out, since "resolved" and "visible" are
different conditions for a non-rendered element. Fixed by adding the two
parameters (defaulting to the original episode-page values, so every
existing call site is unaffected) and having `_prefetch_chapter_list()`
pass `wait_selector="#app-cover-data", wait_state="attached"` instead,
which only requires DOM presence, not a rendered box.

**`parse_chapter_list()`** (`alphapolis_reader.py:637`): parses a novel
main page's `#app-cover-data` blob into the full chapter list, reusing the
exact JSON-parsing mechanism `parse_episode()` already has for this same
blob rather than a second, parallel path. Returns `url`/`main_title`/
`disp_order`/`up_time`/`counter_text` per chapter, fail-soft (empty list)
on missing/malformed data, same discipline as `parse_episode()`'s own
`prev_url`/`next_url` handling.

**`up_time` persisted per episode** (`alphapolis_reader.py:562-633`):
`parse_episode()` now also extracts the current episode's own `upTime`
from the same `#app-cover-data` entry already located to resolve
`prev_url`/`next_url` -- no second JSON-parsing path. Phase 1's one
deliberately-left-open persistence question is now resolved: **yes,
persist it** to the on-disk episode cache, specifically because
`STALENESS_DESIGN.md`'s own future any-change-flag workaround needs a
prior-fetch `up_time` snapshot to diff a fresh fetch against (see that
doc's own cross-reference note, and the `PICKUP_LIST.md` unblock note
added alongside this entry). Same no-`CACHE_SCHEMA_VERSION`-bump,
`.get(..., None)`-graceful-degradation pattern `STATUS_BAR_DESIGN.md`
Phase 2 already established for `page_count` -- re-confirmed against the
real on-disk cache directly rather than assumed still the right call:
`~/.cache/alphapolis_reader/` currently holds 44 files, `{4: 42, -1: 2}`
by `_cache_schema_version` (re-counted directly, not trusting
`STATUS_BAR_DESIGN.md`'s own cited 28/30-of-a-smaller-total figure, which
predates this session's additional fetches) -- bumping the version would
force 42 already-fetched-and-translated episodes to be treated as a cache
miss purely to backfill one display/diffing field, a disproportionate
cost for the same reason `page_count` avoided it. Live-confirmed via the
real on-disk cache file after a real fetch (not just asserted): the cache
file for "contact" (`178ca2c7...json`) has `"up_time": "2023.12.01
13:07"`, matching the live page's own `upTime` value exactly. The other
43 real cache files (predating this field) correctly lack the key,
confirmed via a direct sweep -- graceful degradation working as designed,
same as `page_count`'s own blank-label precedent.

**`dispOrder` gaplessness sanity check** (Phase 1's flagged, unverified
implementation-time check) -- **confirmed gapless, no evidence of an
Alphapolis-side chapter split.** Re-verified directly against a fresh live
fetch of novel 375266002's real 690-chapter main page: `disp_order` values
are exactly `1..690`, strictly gapless and already sorted ascending in the
source JSON (no in-app re-sorting needed). Checked every consecutive pair
for exact-duplicate titles (would be the strongest signal of a split): **0
found.** Checked for a shared-title-prefix-with-incrementing-trailing-
number pattern (a weaker but still worth-checking signal): 79 consecutive
pairs match, e.g. `(170, "サバゲフィールドの植物ダンジョン1",
"サバゲフィールドの植物ダンジョン2")`, `(292, "ハチャメチャ・ザ・ワールド",
"ハチャメチャ・ザ・ワールド2")`. **Read as a numbered sub-arc naming
convention the author uses (distinct `episodeNo`/`disp_order` per
installment, e.g. "Airsoft Field Plant Dungeon 1/2/3/4"), not a mechanical
chapter split** -- each entry is a genuinely separate, independently-
numbered chapter the author wrote and titled that way, not one chapter's
content divided across multiple `dispOrder` slots. No corrective action
taken or needed; `dispOrder` remains safe to key chapter identity off of
directly, per Phase 1's own locked-in decision.

**UI: jump-to-chapter modal** (`open_chapter_list_dialog()`,
`alphapolis_reader.py:1797`): a `tk.Toplevel`, modal (`win.grab_set()`,
same convention as `open_glossary_dialog()`), `ttk.Treeview` list with
`#`/`Title`/`Updated` columns, search-as-you-type filtering by title or
chapter number (`matches_filter()`), a sort-direction toggle button
("Oldest first"/"Newest first") that just reverses the already-in-memory
list, current chapter auto-highlighted and auto-scrolled into view on open
(`tree.selection_set()`/`tree.see()`). No pagination, no page-size
setting, no bookmark button, per Phase 1's explicit decision against
them. Reachable via `File > Jump to Chapter...`
(`alphapolis_reader.py:1623`) and the toolbar right-click menu
(`alphapolis_reader.py:3233`), alongside the app's other dialog launchers.
Double-click or Enter on a row navigates via `self.load_episode(url)`,
same call every other navigation path in the app already uses.

**Data fetch: background prefetch via `BrowserWorker`**
(`_prefetch_chapter_list()`, `alphapolis_reader.py:3145`): fired from
`display_episode()` (`alphapolis_reader.py:3211`, alongside the existing
`self.prefetch(ep.get("next_url"))` call), same threading pattern as that
existing per-episode prefetch -- a daemon worker thread calling into the
already-running `BrowserWorker`, whose Playwright calls must all happen on
its own dedicated thread. Keyed by `novel_id` in an in-memory dict
(`self._chapter_lists`), guarded against re-entry by
`self._chapter_list_prefetching` the same way the existing prefetch guards
itself, so navigating between chapters of the same novel doesn't re-fetch
the main page every time. **In-memory only, not persisted to disk** --
Phase 1's own flagged-open question, resolved here: the full chapter list
itself doesn't need disk persistence (it's cheap to re-fetch once per
novel-load session, unlike the per-episode `up_time` value, which does get
persisted since it's needed as a diffable snapshot across sessions, not
just within one).

**Tests**: no new unit tests added -- this phase's logic is JSON-parsing
plus Tk dialog wiring, dominated by real page structure/real on-disk cache
shape, same precedent `STATUS_BAR_DESIGN.md` Phase 2 and `WINDOW_REDESIGN.md`
Phases 2-3 already established (live verification over mocked-HTML unit
tests, for scraping/UI-wiring changes specifically). Full `tests/webnovels/`
suite (excluding `ui_automation/`): **345 passed**, unchanged from
baseline -- zero regressions. `black`/`isort`/`flake8` clean on the one
touched file.

**Live verification**, via `pyplayground/webnovels/ui_testing/
run_ui_tests.sh xvfb` (a fresh Xvfb+fluxbox session -- deliberately not
`xvfb-keep` for this pass, after a reused display accumulated ~106 stale
windows across earlier iterative runs and started causing File-menu
clicks to land incorrectly; a clean `xvfb` run resolved this immediately,
confirming it was accumulated window-manager state, not an app bug):

- Launched against novel 375266002's real, pre-existing cache for episode
  "contact." Log confirmed `Prefetched chapter list for novel 375266002:
  690 chapter(s)` shortly after the episode itself displayed.
- Opened the modal via `File > Jump to Chapter...`. Screenshot confirmed
  the full real list rendered (690 rows, genuine titles matching Phase
  1's own findings) with chapter 445 ("contact") correctly highlighted
  and scrolled to the top of the visible window on open.
- Typed "night sky" into the search box: screenshot confirmed the list
  filtered to exactly the one matching row (446, "night sky").
- Cleared and typed "446": screenshot confirmed the same single-row
  filter result via chapter number instead of title.
- Cleared search (full list + highlight restored), re-typed "446", then
  double-clicked the filtered row: screenshot immediately before the
  click confirmed exactly one row present; the app log showed
  `Displayed episode: night sky` shortly after, and a follow-up
  screenshot of the main window confirmed the URL bar, translated
  content, and status bar (`Chapter 446 / 690`) all updated to the new
  chapter -- full, correct click-to-navigate confirmed, not just a log
  line in isolation.
- `log_correlator.assert_clean()` confirmed no `ERROR`/`CRITICAL` line
  across both the search interactions and the navigation action.

One real, non-app test-script bug found and fixed during this
verification, noted for completeness: an early attempt to clear the
search field via `xdotool key ctrl+a` assumed select-all semantics: a
plain Tk `ttk.Entry` binds `Ctrl+A` to move the cursor to line-start
(Emacs-style), not select-all, so the first number-search attempt
produced the literal query `"446night sky"` (typed at cursor position 0
with the old text still present) rather than clearing it -- correctly
matched zero rows, which is right for that garbage query, not a bug in
the app's own filtering. Fixed in the test script only (`End` then
repeated `BackSpace`); no corresponding app-code issue.

**Not done in this phase, deliberately**: no staleness-comparison logic,
no "possibly updated" badge, no auto-refresh UI -- this phase only builds
and persists the chapter-list data and the jump-to-chapter modal itself.
`STALENESS_DESIGN.md` Phase 2 (separate, not yet started) is what will
later consume the now-persisted `up_time` data to actually compare and
flag changes.
