# Chapter Staleness Detection — Design Doc

Living record of decisions for this effort. Update alongside code changes,
not after — chat history is not the system of record. Sixth doc alongside
`DESIGN.md`, `RETRANSLATION_DESIGN.md`, `REFACTOR_DESIGN.md`,
`WINDOW_REDESIGN.md`, and `STATUS_BAR_DESIGN.md`, given its own doc rather
than folded into `STATUS_BAR_DESIGN.md` — same reasoning `STATUS_BAR_DESIGN.md`
itself used when it was split out of `WINDOW_REDESIGN.md`: this is a
distinct feature (already tracked as its own `PICKUP_LIST.md` Someday-Maybe
entry, not a sub-item of the status-bar work), not merely adjacent real
estate.

Last updated: 2026-08-05

---

## Why this started

Surfaced while discussing `STATUS_BAR_DESIGN.md` Phase 2's blank-label
behavior for episodes cached before the `page_count` field existed. That
blank-label behavior is intentional and staying as-is — a manual cache wipe
via Refresh is the planned path for backfilling a stale/missing field, not
an automatic detection-and-refresh mechanism. This doc exists because the
adjacent question that discussion raised — "could the app tell a user their
already-cached chapter has since changed on the source site, independent of
which fields happen to be populated" — is a genuinely separate feature, not
a sharper version of the blank-label question. Never scoped or designed
before this doc; `PICKUP_LIST.md`'s prior Someday-Maybe entry for this item
is superseded by this doc (see that file's own pointer update).

**Scope note added 2026-08-05, during `CHAPTER_LIST_DESIGN.md`'s own
investigation**: this doc's scope explicitly covers novel-level "new
chapter(s) appeared since I last checked" in addition to the
chapter-level "this specific chapter's content changed" question the doc
was originally framed around above -- the two are the same underlying
problem shape ("has something changed since I last fetched it") just
asked at a different granularity, surfaced while scoping
`CHAPTER_LIST_DESIGN.md`'s own chapter-jump feature, which explicitly
excludes new-chapter detection from its own scope and points back here
instead. Not a new Phase or a new set of findings -- Phase 1's existing
investigation (`upTime` semantics, WAF durability) applies equally to
either granularity, and Phase 2 remains blocked on the same open
question (`upTime`'s publish-time-vs-last-edited ambiguity) regardless of
which granularity is asked first.

## Decisions locked in (via discussion, before any code)

(None yet — Phase 1 below is investigation only, per this project's
established discipline of not deciding UI/product questions inside a
Phase 1 pass.)

## Phases

Same discipline as `STATUS_BAR_DESIGN.md`/`WINDOW_REDESIGN.md`'s Phase 1s —
investigate real code and the real external page before designing further,
checkpoint each step, stop and report on anything unexpected rather than
pushing forward speculatively.

### Phase 1: Investigation and concrete proposal — no code changes

Four questions, in dependency order (each later question's cost/shape
depends on the answer to the one before it):

1. **What signal exists to detect "changed" at all?** Fetch a real episode
   page directly and inspect it — HTML body, HTTP response headers, and the
   `#app-cover-data` JSON blob `parse_episode()` already partially reads —
   for anything lightweight indicating last-edit/last-modified status. Don't
   assume one exists or doesn't; report exactly what's present or absent.
2. **What would a cheap check cost, mechanically?** Current fetching goes
   through `BrowserWorker`/Playwright for a full page render, specifically
   because (per this module's own docstring, `alphapolis_reader.py:4-7`)
   plain HTTP requests were previously confirmed to get served an empty 202
   WAF challenge. Test directly whether that constraint still holds today,
   and specifically whether it applies to a HEAD-only request the same way
   it was documented to apply to full GETs.
3. **If no cheap signal exists, what would content-hashing require?** Where
   would a hash be stored (re-raises the `CACHE_SCHEMA_VERSION` question
   `STATUS_BAR_DESIGN.md` Phase 2 deliberately worked through) — and does
   computing a hash require a full fetch anyway, defeating the "cheap" goal.
4. **What should the UI do about it?** Report options, don't decide —
   auto-refresh, a "possibly updated" badge, or something else — same as
   prior Phase 1s left product questions open for discussion.

**Checkpoint**: proposal appended to this doc, no code changed, the UI
question explicitly left open.

### Phase 2: Implementation (not yet scoped)

Deliberately not detailed here — depends entirely on Phase 1's findings and
proposal, and on the UI question actually getting resolved through
discussion first. Whether Phase 2 is even worth doing at all is itself an
open question if Phase 1 finds no signal cheaper than a full refetch.

## Status

- **Phase 1**: complete (2026-08-05, investigation and proposal only, see
  dated entry below). No code changes.
- **Phase 2**: not started, contingent on Phase 1's findings and on the UI
  question being resolved through discussion.

### 2026-08-05: Phase 1 -- investigation and proposal (no code changes)

#### 1. What signal exists to detect "changed"? Confirmed against a real, live-fetched page

Fetched the same two real, live Alphapolis episode pages
`STATUS_BAR_DESIGN.md` Phase 1 used
(`https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089`,
"contact," and `.../episode/7800123`, "night sky") directly via plain
Python `urllib` (not through the app's own `BrowserWorker`, to keep this
investigation self-contained and to double as the WAF test in section 2
below) -- not assumed from a cached sample.

**No `Last-Modified` or `ETag` header is present on either page.** Full
response header dump, both GET and HEAD (see section 2 for the HEAD
request itself): `Content-Type`, `Transfer-Encoding`/`Content-Type` sizing,
`Connection`, `Date` (the response time, not the content's own
last-modified time), `Cache-Control: no-cache, private`, `Vary`,
`Set-Cookie` (an `AWSALB` load-balancer affinity cookie, unrelated to
content versioning), `Server: Apache`, `X-Cache`/`Via`/`X-Amz-Cf-*`
(CloudFront edge metadata). No conditional-request-relevant header of any
kind. `Cache-Control: no-cache, private` further confirms the site doesn't
intend downstream/shared caching of this response at all, consistent with
there being no freshness-validation header to pair with one.

**No visible last-edit/last-modified/version element exists in the raw
HTML.** Searched the full page body for every plausible marker, both
English and Japanese terms (`更新` "update," `編集` "edit," `edited`,
`updated`, `revision`, `version`, `modified`, `timestamp`, `投稿日`/`掲載日`
"posting date"): zero matches for all except a coincidental, unrelated
`version` substring inside third-party analytics/ad boilerplate JS
(`n.version = '2.0'`), confirmed by reading the surrounding code directly,
not assumed from the substring match alone. No `class="...date..."` or
`class="...time..."` HTML element exists anywhere on the page either
(confirmed via a regex sweep over every `class` attribute).

**A real signal does exist, but only inside `#app-cover-data`'s JSON
blob, not as visible page chrome: `upTime`.** Each episode entry in
`chapterEpisodes[].episodes[]` (the same list `STATUS_BAR_DESIGN.md`
Phase 1 already documented for `dispOrder`/`counterText`) carries an
`upTime` field, e.g. `"upTime": "2023.12.01 13:07"` for "contact" and
`"upTime": "2023.12.01 13:19"` for "night sky" (twelve minutes apart,
directly-adjacent episodes -- consistent with both being original
publish timestamps from the same posting session, not edit timestamps).
**This field's exact semantics -- "originally published" vs. "last
edited" -- could not be confirmed either way in this investigation**,
since no known-subsequently-edited episode was available to test against;
distinguishing the two would require either finding an episode with a
publicly visible edit history, or observing `upTime` change on a
re-fetch of a chapter independently known to have been edited (not
attempted here, out of scope for a single-session investigation). This
uncertainty is a real, load-bearing gap in this finding, not a rounding
error -- if `upTime` is publish-time-only, it is useless as a staleness
signal (it would never change after initial posting, by definition); if
it is last-edit time, it is exactly the signal this doc is looking for.
**Flagged as the one finding Phase 2 (if pursued) would need to resolve
first, before anything else in this proposal is worth building.**

A second, adjacent JSON field was also found: `currentEpisode.isEditing`
(`{"episodeNo": 7800089, "isExtraEpisode": false, "isEditing": false}`),
present on both fetched pages, both `false`. Plausibly a live
"author is mid-edit right now" flag rather than a historical
last-edited-when signal -- a different question shape ("is this being
edited at this exact moment" vs. "has this changed since I last fetched
it") -- not investigated further here since neither fetched page was
ever confirmed in a `true` state to observe what it actually gates.

#### 2. What would a cheap check cost? WAF constraint re-tested directly, found NOT to apply today

`alphapolis_reader.py`'s own module docstring (lines 4-7) states plain HTTP
requests get served an empty 202 WAF challenge, "confirmed via direct
testing" -- the documented reason `BrowserWorker`/Playwright is required
for fetching at all. **Re-tested directly rather than assumed still true,
and found this constraint does NOT currently reproduce, on any of three
independent request shapes:**

```python
# 1. Plain GET, realistic User-Agent
urllib.request.urlopen(Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"}))
# -> 200, full real HTML body (71,924 bytes, contains #novelBody,
#    contains the real chapter title "contact", contains
#    p-novel-episode__page-count -- a real, complete page, not a
#    challenge stub)

# 2. HEAD only -- the specific case this doc's brief asked about
urllib.request.urlopen(Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"}))
# -> 200, headers only (see section 1 above for the full header list)

# 3. Plain GET, no User-Agent at all (naive-bot shape)
urllib.request.urlopen(Request(url, method="GET"))
# -> 200, identical 71,924-byte body
```

All three succeeded with real content on the first attempt, no retry, no
challenge page, against the same live production URL. **This means the
documented WAF constraint has either lapsed (a site-side change since it
was last confirmed) or was narrower than its own docstring described even
at the time** -- this investigation cannot distinguish those two
possibilities, only that the constraint does not reproduce today. This is
a genuinely surprising finding relative to a load-bearing, already-shipped
architectural decision (`BrowserWorker`'s entire existence is justified by
this constraint, per `GLOSSARY_ARCHITECTURE.md`'s "Fetching and caching"
section) -- reported here exactly as observed, not smoothed over, since
the doc's own instructions require testing rather than assuming either
way.

**Practical implication for this doc's actual question ("what would a
cheap check cost"), independent of resolving the surprise above**: *if*
this finding holds beyond this one investigation session (a single
successful test is not the same as a durable guarantee -- WAF rules can be
traffic-pattern-dependent, IP-reputation-dependent, or otherwise
non-deterministic in ways a one-off manual test from this environment
cannot rule out), a HEAD-only request is trivially cheap: no Playwright
launch, no page render, no `#novelBody` wait, one round-trip, headers
only, no body transfer at all. But per section 1 above, HEAD's response
headers carry no staleness-relevant field either (no `Last-Modified`/
`ETag`) -- so even in the best case where HEAD is confirmed cheap and
reliable, **it doesn't currently return anything to check against.** The
only real signal found (`upTime`, section 1) lives inside the HTML body's
embedded JSON, which HEAD never returns -- getting `upTime` would require
at minimum a GET (not HEAD), though notably *not* necessarily a full
Playwright render, if plain-GET access is confirmed durable (see the
"genuinely surprising" caveat above) -- a plain `urllib` GET already
returned the full `#app-cover-data` blob in this investigation's own test.

#### 3. If no cheap signal exists: content-hashing and the `CACHE_SCHEMA_VERSION` question, re-examined

This section's premise from the original brief -- "if no cheap signal
exists" -- turned out to be not quite the right framing once section 2's
finding is accounted for: `upTime` (section 1) is a real signal, and per
section 2, fetching it may not require a full Playwright render if plain
GET access holds up. So the choice isn't cleanly "cheap signal" vs.
"expensive content-hash fallback" -- it's closer to "one moderately-cheap
signal exists (`upTime` via plain GET, once/if HEAD-vs-GET and the WAF
question are more durably confirmed), with real semantic uncertainty about
whether it means what's needed, versus a definitely-expensive
content-hash fallback with no semantic uncertainty at all." Both are
covered below since either could be what Phase 2 ends up needing.

**`upTime`-based check (if its last-edited semantics are confirmed)**:
would need one new episode-cache field, e.g. `cached_up_time`, populated
from `parse_episode()`'s already-read `#app-cover-data` blob (the same
blob `STATUS_BAR_DESIGN.md` Phase 1/2 already extracts `dispOrder`/
`counterText` from) at cache-write time, compared against a fresh fetch's
`upTime` on some future trigger. **Re-raises the exact
`CACHE_SCHEMA_VERSION` question `STATUS_BAR_DESIGN.md` Phase 2 already
worked through for `page_count`, and the same no-bump/graceful-degradation
answer applies here for the same reason**: `load_cached_episode()`
(`alphapolis_reader.py:173`) does an exact-equality check on
`_cache_schema_version`, currently `4`; bumping it would force every
already-cached episode to be treated as a cache miss and
refetched/retranslated from scratch purely to add one more comparison
field -- a disproportionate cost, per `STATUS_BAR_DESIGN.md` Phase 2's own
2026-08-03 real-on-disk-file check. Re-confirmed the same shape holds
today: `python3 -c` sweep of all 44 real files currently under
`~/.cache/alphapolis_reader/` shows `{4: 42, -1: 2}` -- 42 of 44 already
at the current version. A new `cached_up_time` field would use `.get(...,
None)` and degrade to "staleness unknown, not flagged" for pre-existing
entries, same pattern as `page_count`'s blank-label degradation.

**Content-hash fallback (if `upTime` turns out to be publish-time-only, or
otherwise unusable)**: would need a new field too (e.g.
`content_hash = sha256(''.join(ep["lines"]))`, computed at cache-write
time), same no-bump/graceful-degradation storage answer as above -- that
part of the original brief's premise holds regardless of which signal
ends up used. But computing a fresh hash to *compare against* requires the
same full text content `parse_episode()` already extracts, which per
section 2 requires at minimum a GET of the full page (not HEAD) --
whether that GET can stay a plain `urllib` request (cheap-ish) or must go
through the full `BrowserWorker`/Playwright render path (the ~2-4.5-minute
full-cycle cost `STATUS_BAR_DESIGN.md` Phase 2's live verification
measured for a real Refresh) is exactly the still-open WAF-durability
question from section 2 -- **this investigation cannot resolve that
distinction with confidence from a single test session**, only report
that the two are no longer confirmed to be the same cost, contrary to
what the module docstring's documented WAF finding would have implied
going into this investigation.

#### 4. The UI question -- reported, not decided

Left explicitly open, per this doc's own Phase 1 scope and the same
discipline `STATUS_BAR_DESIGN.md`/`WINDOW_REDESIGN.md` Phase 1s applied to
their own product questions. Options surfaced by this investigation, not
ranked or recommended:

- **Silent auto-refresh** on detecting a change -- highest-friction if
  wrong (an unwanted refetch/retranslate cycle costing real time and money
  per `STATUS_BAR_DESIGN.md`'s own measured 2-4.5-minute Refresh cost),
  lowest-friction if right (user never has to notice or act).
- **A "possibly updated" badge**, next to or reusing the status bar real
  estate `STATUS_BAR_DESIGN.md` already established (page-count/
  content-count labels) -- user-driven refresh, no silent cost, but adds a
  UI element and a decision the user has to notice and act on.
- **Something else** -- e.g. a check only on explicit user request (a
  button, not automatic at all), sidestepping the "how often to check"
  question entirely at the cost of never catching a change the user didn't
  think to look for.

No recommendation made here -- genuinely contingent on how confidently
sections 1-3's technical uncertainty (`upTime` semantics, WAF durability)
gets resolved, since a mechanism that turns out to require a full
Playwright refetch to even check has a very different UI cost-benefit
shape than one that's genuinely cheap.

#### Not done in this pass

No code changes -- confirmed via `git status`/`git diff` scope check that
only this doc (plus `INDEX.md`/`PICKUP_LIST.md` pointer updates, per this
task's own instruction) changed. No decision made on the UI question
(section 4) -- left explicitly open for discussion. No resolution of
`upTime`'s exact semantics (publish-time vs. last-edited) -- flagged in
section 1 as the one finding that would need resolving before any Phase 2
implementation work is worth starting; not resolved here since doing so
would require either a known-edited test episode or an extended
observation window neither of which this single-session investigation
had available. No conclusion drawn on whether the WAF constraint
documented in `alphapolis_reader.py`'s own module docstring is now stale
and should be corrected there -- that docstring is production-code
documentation for an already-shipped architectural decision
(`BrowserWorker`'s entire justification), out of scope for this doc to
unilaterally edit based on one investigation session's test results;
flagged here for whoever picks up Phase 2 (or a separate, smaller task) to
decide whether further/repeated testing warrants updating that docstring.
