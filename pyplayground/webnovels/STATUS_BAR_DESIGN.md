# Status Bar Additions — Design Doc

Living record of decisions for this effort. Update alongside code changes,
not after — chat history is not the system of record. Fifth doc alongside
`DESIGN.md`, `RETRANSLATION_DESIGN.md`, `REFACTOR_DESIGN.md`, and
`WINDOW_REDESIGN.md`, split out of `WINDOW_REDESIGN.md` specifically
(rather than tracked as a section there) because that doc reached 1283
lines — past `INDEX.md`'s own ~500-line split guideline — once its four
phases were fully written up.

Last updated: 2026-08-03

---

## Why this started

Two status-bar additions — a page-count/chapter-position indicator, and
word/paragraph counts (original + translated) — were named as overlapping
real estate when `WINDOW_REDESIGN.md`'s own discussion started (see that
doc's "Why this started": "This also directly overlaps two already-queued
pickup-list items — the still-pending four-mode-to-two-mode reduction,
and the page-count/word-count status-bar additions"). The mode-reduction
item was folded into `WINDOW_REDESIGN.md` and resolved there. The
page-count/word-count item was not — it never got a phase written into
that doc's four-phase plan, and was silently dropped rather than
explicitly deferred. This doc exists to give it the same investigate-then-
propose treatment the other four docs already received, not to imply
either addition is more locked-in than it actually is.

**Kept as two separate additions, not one combined feature**, per this
doc's own framing: page-count/chapter-position answers "where am I in
the novel" (a navigation/orientation fact, independent of content);
word/paragraph counts answer "how much is in this chapter, in each
language" (a content-shape fact, independent of position in the novel).
Different data sources, different update triggers (position changes only
on navigation; content counts change whenever the chapter's translated
content changes, e.g. after a Refresh), and no shared implementation
surface found during Phase 1's investigation (see below) — bundling them
would be an arbitrary UI grouping, not a natural one.

## Decisions locked in (via discussion, before any code)

- **No `Web/Web+/AI` tabs or model-attribution badge.** Phase 1 confirmed
  these are not part of Alphapolis' own page chrome; discussion has now
  confirmed they were never part of the actual request either — incidental
  to a wtr-lab reference screenshot (a different site), not something this
  app needs. Out of scope entirely, not merely deferred. (The
  multi-model-translation-comparison idea that screenshot separately
  prompted is tracked as its own, not-yet-scoped Someday-Maybe item — see
  `PICKUP_LIST.md`, not this doc; it's a distinct feature, not a status-bar
  addition.)
- **Character-vs-word non-comparability across languages is acceptable,
  not a blocker.** Original-language side: character count (a raw
  `sum(len(t) for t in ep["lines"])`, per Phase 1's finding that no
  existing counting utility needed to be reused or extended). Translated
  side: word count (`str.split()`-based). The two numbers measure
  different things and are not meant to be compared against each other
  directly — each is meaningful on its own side, which is sufficient.

## Phases

Same discipline as `WINDOW_REDESIGN.md`/`REFACTOR_DESIGN.md`'s phased
sub-plans — investigate real code (and, where relevant, the real external
page) before designing further, checkpoint each step, commit at each
checkpoint, stop and report on anything unexpected rather than pushing
forward speculatively.

### Phase 1: Investigation and concrete proposal — no code changes

Two independent investigation threads, since the two features have
different data sources (an external page fetch vs. this app's own
already-parsed episode structure):

1. **Page-count/chapter-position**: fetch a real Alphapolis episode page
   directly and confirm what `.p-novel-episode__page-count` actually
   represents — chapter position within the novel's total serialization
   (the assumption), or something else (e.g. pagination within one long
   episode). Confirm by comparing the same value across two adjacent
   episodes of the same novel, checking whether it moves the way the
   position hypothesis predicts. Separately, confirm via the same page
   fetch whether `Web/Web+/AI` source-switching tabs and a per-chapter
   model-attribution badge (both named in a reference screenshot) are
   part of Alphapolis' own page chrome, or something else — a factual
   "what's on the page" check only; whether to include them in this
   app's own status bar is a separate, unresolved product question.
2. **Word/paragraph counts**: confirm the shape of `parse_episode()`'s
   `content` list (already documented at a narrative level in
   `GLOSSARY_ARCHITECTURE.md`'s "How it all fits together" section) to
   determine what "paragraph count" would actually enumerate, with a
   real episode's text/image item split as a concrete example. For the
   original-language (Japanese) count specifically — character count vs.
   word count, given no whitespace word boundaries — investigate only
   whether any character-counting utility already exists to reuse; leave
   the actual character-vs-word decision itself unresolved.

**Checkpoint**: proposal appended to this doc, no code changed, both
named open questions (chrome-tab/badge inclusion, character-vs-word
count) explicitly left open rather than silently decided.

### Phase 2: Implementation (not yet scoped)

Deliberately not detailed here — depends entirely on Phase 1's proposal
and the two open questions above actually getting resolved through
discussion first. `WINDOW_REDESIGN.md`'s own Phase 1 similarly left later
phases only lightly sketched until its own Phase 1 findings existed to
scope them against.

## Status

- **Phase 1**: complete (2026-08-03, investigation and proposal only, see
  dated entry below). No code changes.
- **Phase 2**: complete (2026-08-03, page-count/chapter-position +
  word/paragraph-count status-bar additions, see dated entry below). Both
  phases of this doc now complete.

### 2026-08-03: Phase 1 -- investigation and proposal (no code changes)

#### 1. Page-count/chapter-position: confirmed against two real, live-fetched pages

Fetched `https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089`
("contact") and its real `next_url`-linked successor,
`.../episode/7800123` ("night sky"), directly via a standalone Playwright
script (not through the app's own `BrowserWorker`, to keep this
investigation self-contained) -- not assumed from a cached sample or a
screenshot alone.

**`.p-novel-episode__page-count` is confirmed to be chapter position
within the novel's total serialization, not pagination within a single
episode.** Real HTML, episode "contact":

```html
<div class="p-novel-episode__page-count">
    445 / 689
</div>
```

Real HTML, episode "night sky" (the very next episode via `next_url`):

```html
<div class="p-novel-episode__page-count">
    446 / 689
</div>
```

The numerator incremented by exactly 1 between two directly-adjacent
episodes; the denominator (total novel-wide episode count) stayed fixed
at `689`. This matches the position hypothesis precisely and rules out
per-episode pagination (which would reset or behave independently per
episode, not track a monotonic novel-wide sequence). Cross-checked
against a second, independent data source on the same page rather than
trusting the div text alone: `#app-cover-data` (the same JSON blob
`parse_episode()` already reads for `prev_url`/`next_url`,
`alphapolis_reader.py:462-477`) includes a `dispOrder` field per episode
in its `chapterEpisodes[].episodes[]` list:

```json
{"episodeNo": 7800047, "dispOrder": 444, "mainTitle": "pile into", "counterText": "1,830文字"}
{"episodeNo": 7800089, "dispOrder": 445, "mainTitle": "contact",   "counterText": "3,085文字"}
{"episodeNo": 7800123, "dispOrder": 446, "mainTitle": "night sky", "counterText": "3,288文字"}
```

The current episode ("contact")'s `dispOrder` (`445`) matches the
page-count div's numerator (`445`) exactly -- two independent fields on
the same page agree, not a coincidental match to one field alone. A live
full-page screenshot (viewport render, not just raw HTML) additionally
confirms `445 / 690` is rendered directly under the chapter title, in
the same visual location a reference screenshot described -- one digit
off from the raw-HTML fetch's `689` (`690` in the screenshot, taken
minutes later), consistent with this being a live, novel-wide counter
that can tick up between requests as new episodes publish elsewhere on
the site, not a static or per-fetch-inconsistent value. Confirmed this
volatility doesn't undermine the position-tracking conclusion -- the
numerator still tracks *this specific episode's* fixed position, the
denominator is simply a live total that can grow.

**A genuinely useful adjacent finding, not asked for but directly
relevant to scoping Phase 2**: `#app-cover-data`'s per-episode
`counterText` field (e.g. `"3,085文字"` = `"3,085文字"`, "3,085
characters") is Alphapolis' *own* pre-computed original-language
character count for that episode -- already present in data this app's
`parse_episode()` already fetches and partially reads (for
`prev_url`/`next_url`), but does not currently extract this field.
Directly relevant to the word/paragraph-count investigation below: this
is a second, real candidate character-count source (Alphapolis' own
number) distinct from computing one locally via `sum(len(t["text"])
for t in content if t["type"] == "text")`. Confirmed both exist and are
close but not identical for "contact": Alphapolis reports `3,085`; this
investigation's own `len()`-sum over the real cached episode's parsed
`content` gives `3,069` (see section 2 below) -- a small, unexplained
discrepancy (likely whitespace/punctuation-counting convention
differences between the site's own counter and a raw `len()` sum, not
investigated further here since resolving it is part of the
character-vs-word design question this entry deliberately leaves open).

**`Web/Web+/AI` source-switching tabs and a per-chapter model-attribution
badge: confirmed NOT part of Alphapolis' own page chrome.** Searched the
full raw HTML of both fetched pages for any translation/AI/source-switch-
related text:

```bash
grep -oiE "translat|翻訳|source.*switch|ai.*translat" episode1.html
```

Zero matches, on either page. The only "Web" match anywhere in the page
is an unrelated site-wide navigation label
(`<span class="l-global-nav__web-contents-text">Web<br>コンテンツ大賞</span>`
-- "Web Contents Award," a site contest link, nothing to do with
translation sourcing) -- confirmed by reading the surrounding HTML
directly, not assumed from the substring match alone. A full-page
viewport screenshot (`real_page.png`, this investigation's own artifact)
independently confirms no such tabs or badge are visually present
anywhere on the real rendered page. **This is a factual finding only --
whether this app's own status bar should still show something in that
shape (e.g. reflecting this app's own backend/model choice, which *is*
a real, already-existing setting -- `BACKEND_GOOGLE`/`BACKEND_LLM` per
`GLOSSARY_ARCHITECTURE.md`) is a separate, unresolved product question,
deliberately left open here, not decided.** The reference screenshot
that named these elements most likely depicted either a different site
entirely, or a mocked/aspirational concept for this app's own UI --
which one is immaterial to this doc's own scope; what matters is that
Alphapolis' real page doesn't already provide this chrome for the app
to simply surface, so building it (if wanted at all) would be new,
this-app-owned UI, not a passthrough of source-page content.

#### 2. Word/paragraph counts: `content` shape confirmed against a real episode, no existing counting utility found

**`parse_episode()`'s `content` list shape**, confirmed directly by
reading `_extract_content()` (`alphapolis_reader.py:400-426`) and
`parse_episode()` (`alphapolis_reader.py:429-487`) rather than
re-deriving from `GLOSSARY_ARCHITECTURE.md`'s narrative description
alone (that description -- "a mixed `content` list, text and image items
interleaved, in the order they actually appear on the page" -- is
accurate but doesn't specify the per-item dict shape, which is what
"paragraph count" needs to enumerate against): each item is either
`{"type": "text", "text": str}` or `{"type": "image", "src": str}`, built
by walking `body.descendants` in document order
(`alphapolis_reader.py:414-425`). `ep["lines"]` (used throughout the rest
of the pipeline, e.g. `build_mask_targets()`/masking/translation) is a
derived, text-only, flattened view: `[item["text"] for item in content if
item["type"] == "text"]` (`alphapolis_reader.py:451`) -- confirmed by
direct comparison against a real cached episode that `len(lines) ==
len(text items in content)` exactly (63 == 63, see below), i.e. `lines`
drops no text items and adds none.

**Concrete example, the real cached episode for "contact"**
(`~/.cache/alphapolis_reader/b526...json`, the same episode used
throughout `GLOSSARY_ARCHITECTURE.md`'s own real-data examples):

| Metric | Value |
|---|---|
| Total `content` items | 64 |
| `type: "text"` items | 63 |
| `type: "image"` items | 1 |
| `lines` list length | 63 (confirmed == text item count) |
| Sum of `len(text)` across all text items (original-language characters) | 3,069 |
| `translated_lines` count | 63 (confirmed == source line count, 1:1) |
| Naive `str.split()` word count across all `translated_lines` | 1,280 |

This confirms "paragraph count" has an unambiguous, already-available
answer for both languages: `len(ep["lines"])` (or equivalently, the
count of `type: "text"` items in `content`) for the original side,
`len(ep["translated_lines"])` for the translated side -- and, per
`GLOSSARY_ARCHITECTURE.md`'s own documented invariant (the two lists are
always the same length, translation preserves line count 1:1), these two
numbers are always equal in practice, so "paragraph count" doesn't
actually need a language-specific answer the way character/word count
does. A real, separate "how many paragraphs have an image between them"
question (i.e. `content`'s image-item count specifically) is answered by
the same already-parsed data (1 image item in this example) but wasn't
asked for by this investigation's brief and isn't proposed here as part
of the count display -- noted only because the data to answer it already
exists too, at no extra parsing cost, if ever wanted.

**No existing character-counting or word-counting utility function
exists anywhere in this codebase to reuse.** Grepped specifically for
this, not inferred from absence in docs:

```bash
grep -rn "char.*count|word.*count|len(line)|len(text)|character_count|charcount" pyplayground/webnovels/*.py
```

Every real match is an incidental `len(...)` call inline in unrelated
logic -- chunk-size budgeting in `llm_translate.py`
(`n_predict` sizing, chunk-packing thresholds,
`alphapolis_reader.py:498`'s chunking docstring), a link-density ratio
check in `alphapolis_translate.py`, and `compare_translations.py`'s
`avg_line_length` (a translation-quality-comparison script metric, not a
reusable utility and not imported by `alphapolis_reader.py`/`glossary.py`
at all). None of these are a general-purpose "count characters/words in
this text" helper with a name or docstring suggesting it's meant to be
reused for a UI display. **This means a word/paragraph-count status-bar
feature would need genuinely new counting logic (however trivial that
logic turns out to be) -- there is nothing existing to wire up, only
plain-Python primitives (`len()`, `str.split()`) or Alphapolis' own
pre-computed `counterText` field (see section 1's adjacent finding
above) to build on.** The original-language character-vs-word question
this investigation was asked to leave open (Japanese has no whitespace
word boundaries, so "word count" for the original side isn't a
well-defined `str.split()` operation the way it is for English
`translated_lines`) is exactly the design question this finding sets up
for Phase 2 to resolve, once discussed -- not answered here.

#### 3. Proposal, pending resolution of the two open questions above

Given both open questions are explicitly unresolved, this section
proposes mechanism only, not a finished design -- consistent with this
doc's own "Decisions locked in" section currently being empty.

- **Data source for page-count**: `parse_episode()` would need a new
  field extracted from `.p-novel-episode__page-count`'s text (a simple
  `soup.select_one(...).get_text(strip=True)` plus a `"445 / 689"` ->
  `(445, 689)` split-and-parse, the same idiom already used for every
  other single-value scrape in that function, e.g. `title_tag`/
  `author_tag`/`episode_title_tag` at `alphapolis_reader.py:453-459`) --
  no new scraping mechanism, just one more selector alongside the
  existing ones. This would need a `CACHE_SCHEMA_VERSION` bump
  (`alphapolis_reader.py:118`, currently `4`) or a `.get(..., None)`
  default for already-cached episodes predating the field, per this
  project's established no-migration-needed precedent (confirmed
  applicable here the same way `REFACTOR_DESIGN.md` Phase 1 confirmed it
  for `honorific_policy`-shaped fields) -- which of the two (version bump
  vs. plain default) is itself a small implementation detail for Phase 2
  to confirm against actual on-disk cache files before assuming, same
  discipline `REFACTOR_DESIGN.md`'s own Phase 3 sub-plan applied
  throughout.
- **Data source for word/paragraph counts**: no scraping needed at all --
  `len(ep["lines"])`/`len(ep["translated_lines"])` for paragraph counts,
  and either a local `sum(len(t) for t in ep["lines"])`-style character
  count or Alphapolis' own `counterText` (would require threading that
  field through from `#app-cover-data`'s parse, which `parse_episode()`
  doesn't currently keep beyond `prev_url`/`next_url`) for the
  original-language count -- the choice between "compute locally" and
  "reuse Alphapolis' own number" is itself downstream of the still-open
  character-vs-word decision (Alphapolis' `counterText` is a character
  count only; if word count is wanted instead for consistency with the
  translated side's word count, Alphapolis' number can't directly serve
  that even though it's readily available). For the translated side,
  `str.split()`-based word counting is unambiguous and needs no new
  design discussion.
- **Placement**: both this doc's own framing (page-count is a navigation
  fact, word/paragraph counts are a content fact) and the existing status
  bar's current shape (`alphapolis_reader.py:1466-1469`, one
  `ttk.Label` docked to the window bottom, presently used only for
  transient action messages like "Term added to glossary" via
  `set_status()`) suggest these are two independent, permanent labels
  alongside (not replacing) the existing transient-message label, rather
  than one combined display -- consistent with this doc's own "kept
  separate" framing in "Why this started." Exact packing/layout is a
  Phase 2 concern, not decided here.

#### Not done in this pass

No code changes -- confirmed via `git status`/`git diff` scope check
that only this doc (plus `INDEX.md`/`PICKUP_LIST.md` pointer updates, per
this task's own instruction) changed. No decision made on either open
question (chrome-tab/badge inclusion, character-vs-word count) -- both
explicitly left for discussion, not silently resolved one way. No
`CACHE_SCHEMA_VERSION` version-bump-vs-default decision made for the
proposed page-count field -- flagged for Phase 2 to confirm against real
on-disk cache files, not assumed here.

### 2026-08-03: Phase 2 -- page-count/chapter-position + word/paragraph counts (implementation)

Implemented per Phase 1's proposal. Both product questions Phase 1 left
open are now resolved via discussion and recorded in "Decisions locked
in" above before this phase started: no `Web/Web+/AI` tabs or
model-attribution badge (confirmed never actually part of the request,
out of scope entirely); character-vs-word non-comparability across
languages accepted as fine, not a blocker. No sub-agent delegation used
-- one self-contained feature, no independent sub-tasks.

**`CACHE_SCHEMA_VERSION` decision, confirmed against real on-disk cache
files before assuming, per Phase 1's own flagged uncertainty**: checked
all 30 real files under `~/.cache/alphapolis_reader/` --
`{-1: 2, 4: 28}` (28 of 30 already at the current version, 4). Since
`load_cached_episode()` (`alphapolis_reader.py:173`) does an *exact*
equality check (`episode.get("_cache_schema_version") != CACHE_SCHEMA_VERSION`)
rather than a missing-key-tolerant default, bumping the version would
force all 28 already-fetched-and-translated real episodes to be treated
as a cache miss and refetched/re-translated from scratch -- a real,
disproportionate cost for adding one display-only field. **Chose plain
default, no version bump** (`CACHE_SCHEMA_VERSION` stays `4`) -- same
no-migration-needed precedent this project already established for
`honorific_policy`-shaped fields (per `REFACTOR_DESIGN.md` Phase 1
section 5, confirmed applicable here the same way). Every read site
uses `ep.get("page_count")` (`alphapolis_reader.py:1741`), which
evaluates falsy/`None` for any episode cached before this field existed
-- confirmed this degrades gracefully (blank label, no error) via live
verification below, not just reasoned about.

**Page-count/chapter-position**: `_parse_page_count()`
(`alphapolis_reader.py:429-445`), a new small helper parsing a
`.p-novel-episode__page-count` element's text (`"445 / 689"`) into
`(445, 689)` via a plain regex (`^(\d+)\s*/\s*(\d+)$`), returning `None`
on any non-matching shape rather than raising -- same fail-soft
discipline every other single-value scrape in `parse_episode()` already
uses. Wired into `parse_episode()` itself
(`alphapolis_reader.py:449-517`): `page_count_tag = soup.select_one(".p-novel-episode__page-count")`
(`alphapolis_reader.py:482`), same idiom as `title_tag`/`author_tag`/
`episode_title_tag` immediately above it, and `"page_count": page_count`
added to the returned dict.

**Word/paragraph counts**: `_update_status_bar_counts()`
(`alphapolis_reader.py:1706-1752`), a new `ReaderApp` method. Paragraph
count is `len(ep.get("lines") or [])` -- one number, not separate
original/translated counts, per Phase 1's confirmed 1:1 invariant
(no language-specific logic needed, as proposed). Original-language
character count is `sum(len(t) for t in lines)`; translated word count
is `sum(len(t.split()) for t in translated_lines)` -- both exactly the
plain-Python primitives Phase 1's proposal specified, no new scraping,
no reused/extended utility (none existed to reuse, per Phase 1's own
finding).

**Placement**: two new permanent `ttk.Label`s in the existing status bar
(`alphapolis_reader.py:1493-1517`), `page_count_label` and
`content_count_label`, both packed `side="right"` -- deliberately on the
opposite side from the existing `status_label` (left-packed, unchanged,
still used only for `set_status()`'s transient action messages) so the
two new permanent labels never compete for the same run of text or get
silently overwritten by a transient message. Kept as two separate
labels rather than one combined string, matching this doc's own
"kept separate" framing (`page_count_label`: `"Chapter 445 / 690"`;
`content_count_label`: `"63 paragraphs | 3069 chars (orig) | 1280 words
(translated)"`) -- visually distinct, not bundled.

**Update triggers**: both labels are updated from one single call site,
`_update_status_bar_counts(ep)` called from `display_episode()`
(`alphapolis_reader.py:2839`) -- confirmed by reading `display_episode()`'s
own callers that this one hook covers both required triggers without
needing two separate wiring points: `display_episode()` fires on every
navigation (`load_episode()` -> `_do_fetch_and_translate()` or a cache
hit -> `display_episode()`, for Prev/Next/Load) and after Refresh
(`refresh_current_episode()` clears the cache then calls
`load_episode()`, which re-fetches and calls `display_episode()` again
once translation completes) -- exactly matching this doc's own
"page-count updates only on navigation; word/paragraph counts update
whenever the chapter's translated content changes (navigation, and
after Refresh)" requirement, since both labels are simply recomputed
from the freshly-displayed `ep` dict every time regardless of why
`display_episode()` fired.

**Tests**: no new unit tests added -- this phase's logic is a small
regex-based scrape plus arithmetic over already-parsed data, and its
correctness is dominated by real page structure/real cache-file shape
(exactly the kind of thing confirmed via live fetches and real on-disk
files below, not a mocked-HTML unit test), consistent with
`WINDOW_REDESIGN.md` Phases 2/3's own precedent of relying on live
verification for UI-wiring/scraping changes over new unit coverage. Full
`tests/webnovels/` suite (excluding `ui_automation/`): **340 passed**,
unchanged from baseline. `black`/`isort`/`flake8` clean on the one
touched file.

**Live verification**, via `pyplayground/webnovels/ui_testing/
run_ui_tests.sh xvfb-keep` (real Xvfb+fluxbox on `:99`, `windowclose`
never used, app terminated via `kill -TERM`). Unlike prior phases'
glossary-file writes, this session's real cache-file mutations
(`page_count` backfilled, translations regenerated) were left in place
rather than restored afterward -- Refresh always mutates the on-disk
cache by design, this is the intended, permanent effect of the action
under test, not a synthetic test artifact to clean up:

- Launched against novel 375266002's real, pre-existing cache for
  episode "contact" (`page_count` absent, predating this phase's code).
  Screenshot confirmed the page-count label correctly blank and the
  content-count label correctly showing `63 paragraphs | 3069 chars
  (orig) | 1280 words (translated)` -- an exact match to Phase 1's own
  "contact" baseline (63 paragraphs, 3,069 original characters),
  confirming both the pre-existing-cache degradation path and the count
  arithmetic itself in one screenshot.
- Clicked Refresh (a real fetch + real LLM translation, ~2 minutes):
  page-count label updated to `Chapter 445 / 690` after completion.
  Cross-checked directly against an independent, separate live fetch of
  the same URL run through the real `parse_episode()` function outside
  the running app: `parse_episode()`'s `page_count` returned `(445,
  690)` -- exact match, confirming the in-app value isn't just
  internally consistent but matches the real page.
- Clicked Next (real navigation to `episode/7800123`, "night sky" --
  the exact second episode Phase 1's own investigation fetched,
  `dispOrder: 446`): page-count label correctly blank again (this
  episode's cache also predated the field), content counts correctly
  showed `68 paragraphs | 3289 chars (orig) | 1530 words (translated)`
  for the new chapter.
- Clicked Refresh again on "night sky" (~4.5 minutes, a longer chapter):
  page-count label updated to `Chapter 446 / 690` -- matching Phase 1's
  own `dispOrder: 446` finding for this exact episode, and the same
  `690` denominator as "contact" (same novel, consistent total).
- Clicked Previous (real navigation back to "contact," now itself
  already refreshed earlier in this session): page-count label correctly
  showed `Chapter 445 / 690` again, confirming the field survives both
  the in-memory `self.cache` path and a disk-cache round-trip, not just
  a fresh fetch.
- Whole-session log swept for `ERROR`/`CRITICAL` after every action
  individually and once at the end covering the full session: none
  found (one `WARNING` per chapter for an already-documented,
  expected sentinel-splice case, unrelated to this phase).

**Not done in this phase, deliberately, per the prompt's explicit scope
boundary**: no `Web/Web+/AI` tabs or model-attribution badge UI (now
recorded as fully out of scope in "Decisions locked in," not merely
deferred); no multi-model-translation-comparison feature work (tracked
separately, unscoped, in `PICKUP_LIST.md`'s Someday-Maybe tier -- a
distinct future feature, not part of this status-bar work).
