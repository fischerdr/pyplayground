# Line-Level Retranslation & Display Redesign — Design Doc

Living record of decisions for this feature. Update alongside code changes,
not after — chat history is not the system of record. Companion to
`DESIGN.md` (the glossary/term-consistency redesign) but tracked
separately on purpose: this feature is about correcting arbitrary
vocabulary/idiom mistranslations (e.g. `醤油顔`, `ノーズボン` — ordinary
words the model got wrong), not about per-novel proper-noun/term
consistency. Conflating the two would repeat the same flag-means-two-
things mistake `DESIGN.md` §11 already caught once for `needs_review`.

Last updated: 2026-08-01 (Phase 4 -- accepted-correction persistence -- implemented)

---

## Why this started

Comparing translategemma's output against a reasoning-model translation
(DeepSeek) on the same real chapter surfaced concrete mistranslations of
ordinary Japanese vocabulary/idioms — not proper nouns, not glossary
terms, just words the model got wrong (`醤油顔` → nonsensical literal
"soy sauce face" instead of the idiom's actual meaning; `ノーズボン`
rendered as internally self-contradictory "not wearing underwear...
wearing black underwear"). No existing mechanism (glossary, masking)
addresses this class of error — those are both scoped to
recurring-term consistency, not general translation-quality correction.

## Design decisions locked in (via discussion, before any code)

- **Default reader view = translated-only** (not the current 3-way
  toggle's default).
- **New interleaved display mode**: original line, then its translated
  line, repeating — not a separate full-original or full-translated
  pass. Feasible with no new data: `TranslatedLine` ordering already
  guarantees `source_lines[i]` ↔ `translated_lines[i]` correspondence
  (the translation prompt contract requires preserved order/length), so
  pairing them for display needs no new alignment computation.
- **Hover-to-reveal original**: line-level only for now (hover a
  translated line, see its original line). Word/phrase-level alignment
  is explicitly deferred — real translation reordering means there's no
  natural word-to-word mapping without building actual alignment, a much
  bigger, separate feature.
- **Retranslation trigger**: select a word in the *original* line →
  triggers retranslation of that *whole line* (not just the word) — the
  word acts as **a hint passed to the model** ("pay attention to this
  word/phrase specifically"), not merely a click-target/pointer.
- **Result handling**: retranslation is **ephemeral until accepted** —
  shown as a candidate in a **popup dialog** (same pattern as the existing
  term-editor dialog, not inline in the reading pane), old vs. new,
  Accept/Discard. Nothing persists on generation, only on Accept.
- **On Accept, two separately-controllable outcomes**:
  1. Persist the corrected line to that episode's cache (new
     `line_overrides` field, per-episode, keyed by line index —
     distinct from `needs_review_flags`, distinct from glossary terms).
  2. **Optional** ("also remember this for next time"): write to a
     **new, separate, global vocabulary-notes store** — explicitly *not*
     part of `glossary.py`'s per-novel schema, since a fix to an idiom
     like `醤油顔` isn't specific to one novel's cast (this is the
     "static supplementary dictionary" idea floated earlier in
     `DESIGN.md`, now with a concrete trigger attached). Needs its own
     file (parallel to, not inside, the existing per-novel glossaries
     directory) and its own prompt-injection point, applied *in addition
     to*, not merged with, the per-novel confirmed-glossary injection.

## Explicitly deferred / to be decided later, not now

Per the user's own framing: get a basic working version through phase 1
first, tune layout/context/scope after seeing it work. These are real
open questions, not forgotten — just not being decided pre-emptively:

- Whether retranslation should see just the one line, or surrounding
  lines for context (currently: just the one line, simplest version).
- ~~Whether `line_overrides` needs a `CACHE_SCHEMA_VERSION` bump (forcing
  regeneration of all cached episodes, same cost as `DESIGN.md` §11's
  bump) or can be safely read via `.get("line_overrides", {})` with no
  correctness risk on old cache files.~~ **Resolved 2026-08-01, see phase
  4's dated entry: no `line_overrides` field was built at all.** Phase 3
  (2026-07-27) already writes an accepted correction directly into
  `translated_lines` -- the same field, same shape, a normal translation
  already populates -- so phase 4 turned out to be "persist the field
  that's already correct in memory," not "design and version a new
  field." No schema bump; `CACHE_SCHEMA_VERSION` is unchanged.
- Where exactly the global vocabulary-notes injection happens in
  prompt-building, and whether it should apply to
  `translate_chunk_with_masking()` too, or only the retranslation-with-
  hint path initially.
- Exact popup dialog field layout/wording beyond "old vs. new,
  Accept/Discard, optional remember checkbox."
- ~~Does injected context (confirmed glossary now, vocabulary notes in
  phase 5) reliably get honored on short single-line retranslation
  prompts, or is this systematically weaker than the multi-line chunk
  prompts masking was validated against?~~ **Answered 2026-07-31, see
  that dated entry: yes, reliably, on the single-line path (10/10 live).
  The chunk path is measurably weaker (7/10) but the gap has a specific,
  named cause (character-type terms with unconventional internal
  capitalization, e.g. `Hard Catch`), not a general single-line-vs-chunk
  effect** -- retracting the "systematically weaker" framing this bullet
  originally worried about. Phase 5's vocabulary-notes injection can
  proceed on the same mechanism with the specific caveat documented
  below, not a blanket "unproven" flag.

## Phases

Sequenced so each is independently useful/testable, same discipline as
`DESIGN.md`'s masking/glossary work — don't build UI for data that
doesn't exist yet, don't build the engine before there's a way to
observe its output, don't bundle a policy decision with the plumbing it
depends on.

1. **Layout + default view** (this is the current task). Default to
   translated-only view; add the interleaved original/translated
   line-pair display mode. No retranslation logic, no new data, no new
   prompt calls — purely a rendering change over data that already
   exists in the shape needed.
2. **Retranslation engine** — a pure function: line + selected
   word/phrase hint + glossary context → one candidate translation. New
   prompt template. Testable in isolation with no UI, same pattern as
   `build_mask_targets()`.
3. **Dialog + accept/discard wiring** — the popup UI, calling the phase-2
   engine, showing old vs. candidate. No persistence yet at this phase —
   accept can be a no-op or log-only until phase 4 exists, same reasoning
   as why masking's reader-UI-first ordering mattered: build the sink
   before deciding exactly what flows into it, but here the engine
   already exists by this point, so this phase is really "wire it and
   observe," not "build blind."
4. **Persistence of accepted overrides** — `line_overrides` cache field,
   the schema-bump-vs-safe-default question resolved for real (not just
   instinct), rendering updated to prefer an override when present.
5. **Global vocabulary-notes store + prompt injection** — new file, new
   schema (separate from `glossary.py`), the "remember this" checkbox
   wired to actually write to it, and injection into translation prompts
   going forward. Last, deliberately — most likely to have its own
   design wrinkles once real notes exist to look at, same reason
   count-building in `DESIGN.md` came after masking was solid rather
   than before.

## Status

- **Phase 1**: complete (2026-07-26, see dated entry below).
- **Phase 2**: complete (2026-07-26, see dated entry below).
- **Phase 3**: complete (2026-07-26, see dated entry below).
- **Phase 4**: complete (2026-08-01, see dated entry below) -- accepted
  corrections now persist to the on-disk episode cache. No new
  `line_overrides` field; reuses `translated_lines` directly. Also fixed
  a real, previously-undocumented write race found during this phase's
  own research (a stale, non-modal retranslate popup accepted after
  navigating to a different episode) -- see its own separate dated entry.
- **Phase 5**: complete (2026-07-31, see dated entry below) -- the global
  vocabulary-notes store, built directly on Phase 2's confirmed-glossary
  injection mechanism and the 2026-07-31 reliability finding's proposed
  mixed-case fix.
- **2026-07-26**: a real `needs_review` scope gap in `splice_terms()` was
  found and fixed on genuine (non-synthetic) reading -- unrelated to this
  feature, belongs to and is documented in `DESIGN.md`'s dated entry of
  the same date. Noted here only as a pointer, since the symptom (raw
  Japanese visible in Translated/Interleaved mode with no visual flag)
  could otherwise be mistaken for a phase 1-3 rendering bug by a reader
  of this doc.

### 2026-07-26: Phase 1 (layout + default view) — implemented

**Default view changed**: `ReaderApp.__init__`'s `view_mode` default was
`"both"`, not `"translated"` as this doc's "Design decisions locked in"
section assumed at the time it was written — grep-confirmed before
changing it, not assumed. Now defaults to `"translated"` when no saved
setting exists; a user's existing saved preference (including `"both"`)
is unaffected, since this only changes the fallback default, not a forced
migration.

**New interleaved mode added, not a replacement**: a fourth radio button
("Interleaved") alongside the existing Original/Translated/Both three,
each source line immediately followed by its translated line, repeating
for the whole episode.

**1:1 correspondence verified, not assumed**, per this doc's own stated
discipline and matching every prior `DESIGN.md` task's standard: grep-
confirmed `parse_episode()` builds `ep["lines"]` as `[item["text"] for
item in content if item["type"] == "text"]` — i.e. `ep["lines"][i]`
corresponds by construction to the i-th *text* item in `ep["content"]`
(which also contains image items `ep["lines"]` excludes).
`translate_lines()`/`translate_chunk()` preserve input order/length by
contract. So `source_lines[i]` ↔ `translated_lines[i]` correspondence
holds, but only when walked against `ep["content"]`'s text items
specifically, with a separate line-index counter that skips images --
not via a naive `zip(ep["lines"], ep["translated_lines"])` against
`ep["content"]` directly, which would misalign every pair after the
first image. The implementation below follows the same walk pattern
`_render_content()`/`_render_translated_content()` already use, for
exactly this reason.

**Implemented**:

- `build_interleaved_pairs(source_lines, translated_lines)` (module-level,
  pure, in `alphapolis_reader.py`): pairs the two lists by index, or
  returns `None` on a length mismatch -- the fallback signal, not an
  exception, matching `_render_translated_content()`'s existing
  length-check-and-warn pattern for the same underlying failure mode
  (a stale cache entry from before length-parity was guaranteed).
- `_render_interleaved_content(ep, original_tag, translated_tag)`:
  walks `ep["content"]` the same way the existing renderers do: a
  `line_idx` counter that only advances on text items, images handled
  identically (stubbed via `_make_photo_image()`, same as everywhere
  else). On a `None` from `build_interleaved_pairs()`, logs a warning
  (same message shape as `_render_translated_content()`'s existing
  mismatch warning) and falls back to `_render_translated_view()` --
  reusing the *existing* dispatcher, not a new fallback path, so the
  needs_review-aware behavior of the non-interleaved translated view is
  preserved in the fallback case too.
- **`needs_review` reuse, not new logic**: when `ep["needs_review_flags"]`
  is present and length-matches the paired lines, the translated half of
  a flagged pair gets the existing `"needs_review"` tag instead of
  `"translated"` -- the source half always stays `"original"`, since the
  flag describes a translation-attempt outcome, not a property of the
  source text. A length-mismatched `needs_review_flags` is ignored
  entirely (rendered as if absent) rather than risking a flag applied to
  the wrong pair.
- `render_text()`'s mode dispatch extended with an `"interleaved"` case;
  the heading block now also fires for `"interleaved"` (using the
  original-language title, same as the `"original"`/`"both"` cases,
  since there's no single "the" title to show once original and
  translated content are interleaved line-by-line in the body).

**No new data, no retranslation logic, no dialog, no `line_overrides`,
no vocabulary-notes store** -- confirmed nothing from phases 2-5 leaked
into this pass; `git diff` for this task touches only
`alphapolis_reader.py`'s rendering/dispatch code and its tests.

**Verification**:

- 11 new tests in `tests/webnovels/test_retranslation_display.py` (new
  file, deliberately separate from `test_alphapolis_reader.py` --
  matching this doc's own "tracked separately on purpose" framing, not
  mixed into the glossary-review-queue test file):
  - `TestBuildInterleavedPairs` (5): pure-function pairing, empty input,
    and both directions of length mismatch (translated shorter, and
    translated longer -- mismatch detection isn't one-directional).
  - `TestRenderInterleavedContent` (5): correct pair order via a real
    (headless) `tk.Text` widget, the length-mismatch fallback actually
    invoking `_render_translated_view()` (not just returning early),
    `needs_review` tag applied to the translated half only, a mismatched
    `needs_review_flags` being ignored rather than misapplied, and --
    the case most likely to silently break without a dedicated test --
    an image item sitting between two text paragraphs still producing
    correctly-paired, correctly-ordered output.
  - `TestDefaultViewMode` (1): a source-inspection regression guard that
    the `view_mode` default is literally `"translated"`, not `"both"`.
- **Live/visual verification**, not just unit tests, via the same
  `xdotool`/virtual-display setup used for `DESIGN.md` §6's earlier
  visual verification: real app launched (unmodified, real
  `BrowserWorker`, cache-hit short-circuits before any network access,
  same pattern as before) against a synthetic episode with a real
  `needs_review_flags` mix. Screenshot on startup confirmed the
  **Translated** radio button selected by default (not Both) with the
  toolbar showing all four modes including the new **Interleaved**
  option. Clicking **Interleaved** (real `xdotool` mouse click through
  the real widget, not a synthetic invocation) produced exactly the
  expected on-screen result: each Japanese line immediately followed by
  its English translation, in order, with the flagged pair's translated
  half rendered in the amber/underlined `needs_review` style and its
  source half in plain `original` style -- matching the unit tests'
  predictions exactly, now confirmed on a real rendered screen rather
  than only inferred from `tag_config`/`_rendered_spans` inspection.
- `black`/`isort`/`flake8` clean. `mypy`: 3 new "missing type annotation"
  errors on `_render_interleaved_content()` (320 total, up from 317),
  consistent with this file's existing untyped-method convention --
  not fixed here, same treatment as every prior session touching this
  file. `build_interleaved_pairs()` itself (the pure function) is fully
  typed and mypy-clean. Full project test suite re-run: no regressions
  (71 tests total in `tests/webnovels/`, up from 60 before this task).

**Not anticipated going in, found during this task**: none of
substance -- the 1:1 correspondence claim and the images-interleaved-
with-text shape of `ep["content"]` were both exactly as this doc's
"Design decisions locked in" section described, once actually verified
against `parse_episode()` rather than assumed. The one real design
choice made during implementation not fully specified by the task
brief: what heading to show in interleaved mode (chose the
original-language title, reasoning above) -- a minor UI judgment call,
not a scope deviation.

**Not done in this pass** (phases 2-5, unchanged): no retranslation
engine, no new prompt template, no popup dialog, no word-selection
handling, no hint-passing mechanism, no `line_overrides` field, no cache
schema changes, no global vocabulary-notes store, no hover-to-reveal.

### 2026-07-26: Phase 2 (retranslation engine) — implemented

**Function**: `retranslate_line_with_hint(source_line, current_translation,
hint, source_lang="ja", target_lang="en", glossary_text=None)` in
`llm_translate.py`, right after `explain_term()` -- the closest existing
precedent (single-item reference-style call, not a chunked translation),
same error-handling shape (`requests.exceptions.RequestException` and
empty-output both return `None`, not an exception). Pure/isolated per
scope: explicit arguments in, a string or `None` out, no reader/UI state,
no cache access, no side effects.

**Signature deviation from the task brief's suggested name, deliberate,
not an oversight**: the brief suggested a `glossary` parameter (the raw
dict). Checked `llm_translate.py`'s actual convention before matching
it, per the task's own instruction to check conventions rather than
assume: every function in this module that touches glossary content
(`translate_chunk()`, `translate_chunk_with_masking()`,
`translate_lines()`, `translate_lines_with_masking()`) takes
`glossary_text: Optional[str]` -- pre-formatted text, not a raw dict --
and `llm_translate.py` grep-confirmed to have zero imports of
`glossary.py` anywhere. That's a deliberate architectural boundary
(callers format the glossary themselves via
`glossary.format_glossary_for_prompt()` before passing it in), not an
oversight to fix -- `retranslate_line_with_hint()` matches it rather
than introducing the module's first `glossary.py` import.

**Output format: plain-text-in/plain-text-out, decided empirically, not
assumed.** Per the task's explicit instruction, tried plain text first
(sidesteps the entire class of JSON-array-escaping/malformation failures
`DESIGN.md` Sections 4/5 documented extensively for this exact model)
before falling back to a JSON-array wrapper if it proved unreliable. It
didn't need to: **4 live calls against the real translategemma server**
(3 repeats of the `醤油顔` case at `temperature=0.1`, 1 different case --
`ノーズボン`) all returned clean plain text -- no quotes, no commentary,
no markdown fences, just incidental leading/trailing whitespace
(`.strip()`'d). `strip_code_fence()` and a defensive surrounding-quote
strip are still applied (reused/added respectively) as cheap safeguards
against a failure mode not observed in testing but plausible for
free-text LLM output generally -- not because either was actually
triggered live. No JSON-array fallback was built; plain text held up on
every real call tried.

**Live verification -- the required `醤油顔` case, actual before/after
text, not just "it ran":**

- **Provenance note**: the exact source line and "current translation"
  from whatever earlier DeepSeek-comparison run originally motivated this
  doc were never available in this session (not in any cached episode on
  disk, not preserved anywhere accessible) -- re-derived instead:
  `彼は醤油顔でモテる。` (a real, freshly-constructed sentence using the
  real idiom) run through the actual production `/completion` endpoint at
  `temperature=0.1` to get a genuine, reproducible "current translation"
  baseline (`translate_chunk`-style, no hint), not a fabricated wrong
  answer.
- **Before** (baseline translation, no hint): "He is attractive because
  of his dark complexion."
- **After** (`retranslate_line_with_hint(..., hint="醤油顔")`, run via the
  actual production function, not the raw HTTP call used to design the
  prompt): "He is attractive because of his tanned complexion." --
  reproduced identically across 4 separate live calls (2 during prompt
  design, 2 more via the finished function).
- **Honest result, not just "it ran successfully"**: this is a real,
  functioning mechanism -- the hint measurably changed the output ("dark"
  → "tanned") -- but it **did not fix the underlying mistranslation**.
  `醤油顔` is an idiom for a plain/understated, traditionally-Japanese
  facial appearance (contrasted with `ソース顔`, "sauce face," for
  sharper/more Western-looking features); neither "dark" nor "tanned
  complexion" captures that meaning. A technically-different output that's
  still wrong is exactly the case this doc's own task brief warned against
  reporting as a pass, so it isn't reported as one here.
- **Second case for a fuller picture**: `ノーズボン` (`彼はノーズボンを愛用している。`,
  baseline: "He does not wear underwear and wears black underwear." --
  genuinely self-contradictory nonsense) → hinted retranslation: "He is a
  fan of briefs." This one **is** a clear, unambiguous improvement:
  incoherent contradiction became a coherent, plausible sentence, even if
  "briefs" isn't independently verified as the exact correct rendering of
  the slang term.
- **Glossary integration exercised live, not just mocked**: a real
  `format_glossary_for_prompt()` call (confirmed term `彼` → `"Kenji"`)
  was piped into a real `retranslate_line_with_hint()` call, run 5 times
  total across two sessions. **Correction to this entry's own earlier
  claim**: the first run's output did not apply the override (`"He"`,
  not `"Kenji"`), and that single result was initially written up here as
  an "observed limitation of short single-line context." Four more
  repeats of the identical call (same day, prompted by review) all
  correctly applied it (`"Kenji is attractive because of his tanned
  complexion."`, 4/4). Tally is now 4 of 5 applied correctly, 1 did not
  -- read as a low-probability outlier at `temperature=0.1`, not a
  systematic weakness, which is the opposite of what the original
  single-sample writeup concluded. Retracting the "systematic" framing
  explicitly rather than leaving it to quietly age out; see the
  "Explicitly deferred" section below for what's still actually open
  about this.

**Net read on the mechanism**: hint-guided retranslation reliably changes
the output and is a genuine, sometimes-large improvement (the
`ノーズボン` case), but is not a guaranteed fix (the `醤油顔` case) --
consistent with `DESIGN.md`'s broader finding that translategemma has no
reliable mechanism to know what it doesn't know (§1's Lanchester's Law
hallucination, same root cause class). This mechanism gives a user a
retry lever with a hint, not a correctness guarantee -- which is exactly
why phase 3's design already treats every retranslation as an ephemeral
candidate requiring explicit human Accept, not an automatic replacement.

**Verification**: 10 new tests in `tests/webnovels/test_retranslation_engine.py`
(new file, separate from `test_llm_translate.py` -- matching this doc's
"tracked separately" framing, mirroring phase 1's same choice for the
display tests): clean-response parsing, hint word present in the sent
prompt, source line and current translation both present in the sent
prompt, glossary text included when provided and its section omitted
when not, surrounding-quote stripping, code-fence stripping, empty
response returns `None`, whitespace-only response returns `None`, and a
request failure (using the real `requests.exceptions.ConnectionError`,
not a bare builtin `ConnectionError` -- confirmed via
`issubclass()` that the builtin is NOT a `RequestException` subclass and
would propagate uncaught rather than testing the actual `except` clause)
returns `None`. `black`/`isort`/`flake8` clean. `mypy` clean on
`llm_translate.py` (unchanged -- this module's existing strict-typing
discipline held for the new function with no exceptions needed). Full
project test suite re-run: no regressions (81 tests total in
`tests/webnovels/`, up from 71 before this task).

**Not anticipated going in, found during this task**: the signature
deviation (glossary_text vs. a raw glossary dict) above -- the task
brief's suggested signature didn't match this module's actual, deliberate
architectural boundary, caught by checking convention before writing
code rather than after. Also, initially: an apparent glossary-not-applied
result on the first live `彼` → `"Kenji"` test, corrected above after 4
more repeats came back 4/4 applied correctly -- see the "Glossary
integration exercised live" bullet above for the full correction, and the
"Explicitly deferred" section below for what's still genuinely open about
short-prompt context injection.

**Not done in this pass** (phases 3-5, unchanged): no dialog/popup UI, no
`line_overrides` persistence, no global vocabulary-notes store or
"remember this" mechanism. No changes to the interleaved view, the
four-mode toggle, or anything from phase 1. No changes to
`translate_chunk_with_masking()`, `build_mask_targets()`, or any
masking-path code -- confirmed via `git diff` scope check that this
task's changes are isolated to the new function, its prompt constant,
and its tests.

### 2026-07-26: Phase 3 (dialog + accept/discard wiring) -- implemented

**Trigger and mode-availability decision, stated plainly: Interleaved-only,
not offered from Original or Both.** Retranslation is offered as a new
"Retranslate this line..." item on the *existing* right-click context menu
(`_on_text_right_click()`), alongside "Add to Glossary...", rather than a
new binding -- reuses the same menu, same selection-vs-click-word
resolution logic, same dialog-opening pattern already established. It only
appears when `tag == "original"` (the click/selection was on source text,
per the design doc's locked-in trigger) **and** `self.view_mode.get() ==
"interleaved"`. Reasoning: `_render_interleaved_content()` (phase 1) is
the only renderer that appends `_rendered_spans` entries in strict
(original, translated) pairs, one pair per source line -- see its
implementation. That ordering is what a new helper,
`_translated_span_after(original_span)`, relies on to resolve "the
current translation of this line" from a clicked original-tagged span,
without adding a second span-tracking structure (mirroring how
`_review_terms_by_span` is a *separate*, purpose-built dict for its own
narrower case, not something to generalize here). "Original" and "Both"
modes both render original text, but neither pairs it with a translated
span at a resolvable list position -- "Original" renders no translated
text at all, and "Both" renders a full original pass followed by a full
translated pass with a heading in between, not per-line pairing. Extending
retranslate to those modes would need a different resolution mechanism
(most likely: reuse `build_interleaved_pairs()` against the episode data
directly rather than walking `_rendered_spans`), which is a reasonable
future extension but out of scope for "wire it, don't build blind."

**`_translated_span_after()`**: a small pure-ish helper -- only reads
`self._rendered_spans`, no other Tk state needed -- that finds the very
next `_rendered_spans` entry after a given original-tagged span. Returns
`None` if the span isn't found or has no following entry, so a malformed
call fails closed (menu item simply isn't added) rather than crashing.
Fully unit tested against a fake list, no Tk widget required.

**Engine call**: `open_retranslate_popup()` calls
`retranslate_line_with_hint()` (phase 2) unchanged, exactly as it exists
today -- confirmed the real signature before wiring
(`source_line, current_translation, hint, source_lang="ja",
target_lang="en", glossary_text=None`) rather than assuming it from the
task brief. `glossary_text` is built the same way
`open_word_glossary_popup()` builds its own glossary-touching calls:
`format_glossary_for_prompt(load_glossary(novel_id))`, called fresh
inside the background thread (not cached), so a glossary edit made
earlier in the session is picked up. `target_lang` is threaded through as
`self.target_lang` (the reader's actual configured target language, not
hardcoded `"en"`) -- a small correctness detail the task brief's
signature sketch didn't call out but the real function signature exposes.

**Dialog pattern**: same `tk.Toplevel` / background-thread-then-build-form
pattern as `open_word_glossary_popup()`, reused deliberately (per the
design doc's own locked-in decision), not reinvented. Shows Source,
Current translation, and (once the engine call returns) the Candidate
with the hint word labeled, side by side top-to-bottom rather than
left-right columns -- simpler layout, matches the existing popup's
vertical field stacking, and the design doc left exact field layout as an
open question ("Exact popup dialog field layout/wording beyond 'old vs.
new, Accept/Discard, optional remember checkbox'" -- still open beyond
this specific choice).

**"Also remember this for next time" checkbox: included and checked by
default, wired to a no-op, per the task's explicit instruction not to
omit it.** `accept_and_close()` reads the checkbox state and, if checked,
logs a debug line and does nothing else -- a `# TODO: phase 5` comment
sits directly on the no-op branch pointing at the global vocabulary-notes
store that doesn't exist yet. This was a deliberate choice stated here
explicitly, not a silent default: the alternative (omitting the control
entirely until phase 5) would have meant redesigning the dialog layout
later just to insert it, for no benefit now.

**`None`-handling, live-verified, not just unit tested.** A `None` from
`retranslate_line_with_hint()` (empty/whitespace output, or a request
failure -- both real, documented outcomes from phase 2) is shown as an
explicit inline message ("Retranslation failed -- no candidate was
returned. Try again.") in red, with **Retry** (re-runs the fetch in a new
background thread, replacing the dialog's contents in place) and
**Close** buttons -- never a silently blank dialog, never an uncaught
exception. `fetch_candidate()` wraps the engine call in a bare
`except Exception` (logged with `exc_info=True`) in addition to the
engine's own internal `RequestException` handling, since the dialog's
own glossary-loading/formatting code runs in the same background thread
and isn't otherwise guarded -- an unexpected error there degrades to the
same "no candidate" UI rather than killing the background thread
silently. Live-verified (see below) by forcing the call to raise, and
confirmed on a real rendered screen: red error text, Retry/Close both
present, no crash.

**Accept: session-only, not persisted -- explicitly not a no-op, and
explicitly not phase 4.** Stated plainly per the task's request: Accept
overwrites the specific translated line's text directly in the live
`tk.Text` widget (`self.text.delete`/`self.text.insert` over the stored
`translated_span` range) and updates the matching entry in
`self._rendered_spans` in place, so a later click on that same line
resolves consistently against the *new* text for the rest of the
session. Nothing is written to the episode dict, the on-disk cache, or
any new field -- reloading the chapter (a fresh process reading
`load_cached_episode()`) shows the original, unedited translation, since
there is no `line_overrides` field yet (that's phase 4, confirmed
untouched). This was a deliberate choice over a pure no-op: a no-op
button would make Accept and Discard visually and functionally
indistinguishable in this pass, which seemed like a worse interim
experience than "the correction visibly sticks until you leave the
chapter," while still being honest that it is not persistence.

**Live verification, via the same `xdotool`/real-display setup used for
phases 1 and prior `DESIGN.md` visual checks:**

- Seeded a synthetic cached episode (two lines, including the real
  `彼は醤油顔でモテる。` case from phase 2's own live testing) plus a
  confirmed glossary term (`ケイト` -> `"Kate"`) for a throwaway novel ID,
  and launched the real, unmodified app against it (real `BrowserWorker`,
  cache-hit short-circuits before any network access -- same pattern as
  phase 1's verification).
- Drag-selected `醤油顔` in the source line (Interleaved mode, which was
  already the default per phase 1), right-clicked, and confirmed
  "Retranslate this line..." appears on the context menu alongside "Add
  to Glossary...".
- Clicked it: the dialog opened against the real, live translategemma
  server (`http://flyyn:10001`, confirmed reachable first) and rendered
  correctly -- Source, Current translation ("...dark complexion."), and
  Candidate ("...tanned complexion.", the same output phase 2's entry
  already documented for this exact case), hint label, the "remember"
  checkbox checked by default, the session-only note, and Accept/Discard
  buttons all present and correctly laid out, confirmed via screenshot.
- Clicked Accept: the dialog closed, the status bar showed "Retranslation
  applied for this session (not saved)", and the rendered line in the
  main window visibly updated from "dark" to "tanned complexion" --
  confirmed via screenshot, not just inferred. The app's log file
  confirmed the expected `INFO` line: `Retranslation accepted
  (session-only, not persisted) for line: ... -> ...`.
- Confirmed session-only, not persisted: after Accept, read the on-disk
  cache file directly (`load_cached_episode()`) while the app was still
  running -- it still showed the original, un-retranslated text. Accept
  never touches the cache; only the live widget/`_rendered_spans` are
  mutated.
- Live-verified the `None` case by monkeypatching
  `retranslate_line_with_hint()` to raise inside a minimal Tk harness
  driving the real `open_retranslate_popup()` method (not a synthetic
  invocation of the branch in isolation) and screenshotting the result:
  the red "Retranslation failed" message and Retry/Close buttons rendered
  correctly, matching the design.
- One real mistake made and caught during this verification, worth
  recording honestly rather than omitting: an early attempt to automate
  clicking "Accept" via a second `xdotool` right-click-and-select sequence
  (intended as a retry after a screenshot-timing miss) actually landed on
  a *second* "Retranslate this line..." invocation instead of dismissing
  the first, producing two stacked dialogs on screen simultaneously. Both
  were showing correct, independent content (not a shared-state bug --
  each was its own `tk.Toplevel` with its own closures), but the
  duplication itself was an artifact of imprecise xdotool retry sequencing
  during verification, not a defect in the dialog code. Killed and
  restarted the app cleanly before continuing, per the user's direction,
  and completed verification against a single clean session afterward.

**Test coverage**: 7 new tests in `tests/webnovels/test_retranslation_dialog.py`
(new file, same "tracked separately" precedent as phases 1/2):
`TestTranslatedSpanAfter` (4): correct next-span resolution for the
first and a later pair, not-found returns `None`, last-entry-with-no-
successor returns `None` rather than raising. `TestRetranslateMenuGating`
(3): "Retranslate this line..." is offered on original text in
Interleaved mode, is *not* offered when right-clicking the translated
half of the same pair, and is *not* offered in a non-Interleaved mode
even on original text -- directly exercising the mode-availability
decision above, not just asserting it in prose. The full popup flow
(background thread, engine call, Accept/Discard button wiring) is
live-verified above rather than re-verified as an automated test, same
reasoning phase 2 gave for not writing an automated test against the
live server. `black`/`isort`/`flake8` clean on both the new file and
`alphapolis_reader.py`. `mypy`: 32 new "missing type annotation" errors
(352 total, up from 320), consistent with this file's existing
untyped-method convention -- not fixed here, same treatment as every
prior session touching this file. Full project test suite re-run: no
regressions (88 tests total in `tests/webnovels/`, up from 81 before this
task).

**Not anticipated going in, found during this task**: none of substance
in the production code -- the existing right-click/dialog/span-tracking
machinery was exactly as documented, once actually read
(`_on_text_right_click()`, `open_word_glossary_popup()`,
`_span_at_index()`, `_rendered_spans`) rather than assumed. The one
process-level snag (the duplicate-dialog verification mistake above) was
caught during live testing itself, not left in the record as a silent
retry.

**Not done in this pass** (phases 4-5, unchanged): no `line_overrides`
cache field, no persistence surviving a reload or app restart -- verified
above, not just asserted. No global vocabulary-notes store; the "remember
this" checkbox is inert, wired to a logged no-op with a `# TODO: phase 5`
marker, not functional. No changes to `retranslate_line_with_hint()`,
`translate_chunk_with_masking()`, `build_mask_targets()`, or phase 1's
display/mode code -- confirmed via `git diff` scope check.

### 2026-07-27: Accept did not survive a same-session view-mode switch -- found live, fixed

A suspected, previously-unverified data-loss bug, investigated and
confirmed real: an accepted retranslation in Interleaved mode was
silently discarded the moment the user switched to a different view mode
(Translated/Both/Original) within the *same reading session* -- not the
already-known, expected-to-be-lost-on-reload case documented in the
phase 3 entry above, but a strictly worse case: losing the correction on
a single button click, with no reload or restart involved.

**Step 1 (code reading, confirmed against the actual current code, not
assumed from this doc's own phase 3 prose)**: `accept_and_close()`
(`alphapolis_reader.py`, in `open_retranslate_popup()`) mutated only the
live `tk.Text` widget (`self.text.delete`/`self.text.insert` over the
`translated_span` range) and the matching entry in
`self._rendered_spans` -- exactly as phase 3 documented, nothing drifted.
Separately, `render_text()` -- called by `_on_view_mode_change()` on
every Original/Translated/Both/Interleaved radio click -- unconditionally
does `self.text.delete("1.0", "end")` and `self._rendered_spans = []`,
then re-renders everything fresh from `self.episode`/`ep` via
`_render_content()`/`_render_translated_view()`/
`_render_interleaved_content()`, none of which read `_rendered_spans` or
anything Accept touched. This makes the bug mechanical, not
probabilistic: `self.episode["translated_lines"]` was never written by
Accept, so any mode switch was guaranteed to discard the correction, not
just likely to.

**Step 2 (live reproduction, `xdotool` against the real app)**: seeded a
synthetic cache-hit episode (the same `彼は醤油顔でモテる。` /
"...dark complexion." case from phase 2/3's own live testing, for
continuity with prior verification). Switched to Interleaved, drag-
selected `醤油顔`, right-clicked, opened "Retranslate this line...",
Accepted the candidate ("...because of his dark complexion."). Screenshot
confirmed the corrected text on screen and the expected status-bar
message. Switched to Translated mode: **confirmed data loss** --
screenshot shows the line reverted to the original "...with a dark
complexion.", not the correction. Switched back to Interleaved:
confirmed the correction did not reappear either -- it was not merely
hidden in the other mode, it was permanently gone for the rest of the
session, matching the code-level analysis exactly (there was never a
second copy of the corrected text anywhere except the widget that had
just been wiped).

**Step 3 (fix, implemented and live-verified)**: Accept now also writes
the correction into `self.episode["translated_lines"][line_idx]` --
the shared in-memory structure every render mode reads from -- not just
the transient widget/`_rendered_spans`. Resolving `line_idx` reliably
(rather than re-deriving it from `source_line` text, which would be
ambiguous if the same source line occurs more than once in a chapter)
required a new side table, `self._translated_line_index_by_span`:
`(start, end) -> line_idx`, populated by `_render_interleaved_content()`
at the exact point it already has `line_idx` in scope (building
`_rendered_spans`' translated-half entries from `pairs[line_idx]`, itself
built via `build_interleaved_pairs(ep["lines"], ep["translated_lines"])`
-- so `line_idx` is guaranteed to be the correct index into
`ep["translated_lines"]`, not inferred). Same "separate, purpose-built
span-keyed side table" pattern phase 3 already used for
`_review_terms_by_span`, not a new mechanism. Reset alongside
`_rendered_spans`/`_review_terms_by_span` in `render_text()`, same
lifecycle. `accept_and_close()` looks up the index via the *original*
`(start, end)` span key (before the widget edit moves `end`), writes
`translated_lines[line_idx] = candidate`, and re-keys the side table
to the new `(start, new_end)` range so a second Accept on the same line
within the same render cycle would still resolve correctly. Both failure
paths (no index found for the span; index out of range against the
current `translated_lines` length) degrade to a logged warning rather
than a crash or a silent no-op, so a future structural change that
breaks this invariant would be loud, not silently wrong again.

**Session-only boundary confirmed unchanged, not touched by this fix**:
`self.episode` is in-memory only; nothing in this fix writes to
`save_cached_episode()`, the on-disk cache, or any new field. Verified
live -- after Accept, read the on-disk cache file directly while the app
was still running: still the original, un-retranslated text. Reloading
the chapter or restarting the app still reverts the correction, exactly
as phase 3 intended -- that boundary is phase 4's territory and is
correctly untouched here; only the same-session cross-mode-switch
behavior changed.

**Live verification, via the same `xdotool` setup as prior tasks**:
reproduced the fixed sequence end-to-end against the real app: Accept in
Interleaved (screenshot confirms on-screen correction), switch to
Translated (screenshot confirms the correction, not the original, is
shown), switch to Both (screenshot confirms both the original-language
pass and the corrected translated pass are consistent), switch back to
Interleaved (screenshot confirms the correction is still there). On-disk
cache re-checked afterward and still shows the original text, confirming
the session-only boundary held throughout.

**Test coverage**: one new regression test,
`TestAcceptSurvivesModeSwitch::test_accepted_retranslation_survives_switching_to_translated_and_back`
in `test_retranslation_dialog.py`, driving the real `render_text()` and
`open_retranslate_popup()` methods (not reimplemented) against a real
headless `tk.Text` widget -- selects the translated span via the real
`_translated_span_after()`, opens the real popup, finds and invokes the
real Accept button, then asserts both that `self.episode["translated_lines"]`
was updated directly and that a full `render_text()` rebuild in
Translated mode (then back in Interleaved mode) still shows the
correction. Confirmed load-bearing: reverted the fix and re-ran the
test, which failed at exactly the "episode dict was updated" assertion
(`'He is popular with a dark complexion.' == 'He is popular because of
his dark complexion.'`); re-applied the fix and confirmed it passes
again. One test-infrastructure detail worth recording: `open_retranslate_popup()`'s
background thread normally schedules `build_form()` via
`self.root.after(0, ...)`, which races real Tk C-level state outside a
running `mainloop()` (`RuntimeError: main thread is not in main loop`)
-- resolved in-test by patching `threading.Thread` to run its target
synchronously in the calling thread, since `retranslate_line_with_hint()`
is already mocked to return deterministically and there is no real
concurrency behavior being tested here; this is a test-harness
workaround only, not a change to production threading behavior.

Adding the new `_translated_line_index_by_span` attribute to
`ReaderApp.__init__()` and `render_text()`'s per-render reset required
updating two pre-existing test harnesses in
`test_retranslation_dialog.py`/`test_retranslation_display.py`
(`_NeedsReviewAndRetranslateHarness`, `_InterleaveHarness`) that mix in
the real `_render_interleaved_content()` but construct their own
`__init__` rather than inheriting `ReaderApp`'s -- both were missing the
new attribute and failed with `AttributeError` until added; not a
behavioral regression, a mechanical consequence of adding a new instance
attribute that hand-built harnesses don't get for free.

Full `tests/webnovels/` suite re-run: 231 passed (up from 224), no
regressions. `black`/`isort`/`flake8` clean on all three touched files.
`mypy`: 403 errors, confirmed identical before and after this change via
`git stash` comparison -- zero new errors introduced.

**Not done in this pass**: no changes to phase 4/5 scope (still no
`line_overrides` cache field, still no persistence surviving reload/
restart, still no vocabulary-notes store) -- this task was specifically
the same-session cross-mode-switch bug, kept separate from persistence
per the task's own explicit framing. No changes to
`retranslate_line_with_hint()`, `translate_chunk_with_masking()`,
`build_mask_targets()`, or the menu-gating/dialog-opening logic --
confirmed via `git diff` scope check, same discipline as phase 3.

### 2026-07-31: glossary-context reliability re-tested properly -- 10/10 single-line, 7/10 chunk-path, quantified with a named failure pattern

Investigation only, no code changes. Replaces the "Explicitly deferred"
section's one-data-point placeholder (4/5 repeats of a single `彼` →
`"Kenji"` case, against Qwen3-14B chat-completions -- a different model
than production) with a real answer: a real test set, run against the
actual production model (`mradermacher/translategemma-12b-it-GGUF:Q4_K_M`,
confirmed live via `/v1/models` immediately before testing) and the actual
production function (`retranslate_line_with_hint()`), not a standalone
HTTP call built to resemble it.

**Test set construction, and an honest limitation of it.** Novel
375266002's real, currently-confirmed glossary
(`~/.config/alphapolis_reader/glossaries/375266002.json`, grep-checked
fresh rather than assumed from memory) has exactly 3 `status: "confirmed"`
terms: `ケイト` → `"Kate"` (character), `バッターボックスに立` →
`"batting box"` (term), `ハードキャッチ` → `"Hard Catch"` (character,
despite the skill-name-shaped source text -- glossary's own type tag,
not a mistake made here). Grepping all 14 cached episodes for this novel
for verbatim occurrences of these 3 terms found exactly **one** real hit
(`バッターボックスに立`, in the "contact" episode) -- `ケイト` and
`ハードキャッチ` appear in zero cached source lines. This glossary is
evidently seeded/test data (consistent with the `"Test Novel"` title
already visible in its own file, and with this doc's phase 3 entry using
a synthetic `ケイト`→`"Kate"` term for its own live UI verification), not
organically extracted from real reading. Rather than block on finding a
novel with richer real confirmed-term coverage, built 10 test cases using
the one real cached line as-is (case 1) plus 9 constructed sentences using
the same 3 confirmed terms and other real character names already present
in this novel's glossary as suggested/unconfirmed entries (`ルリ`/Ruri,
`橘`/Tachibana) for narrative plausibility -- documented here as
constructed, not represented as organic reading. Varied deliberately
across: term type (character name vs. general term), single vs. multiple
occurrence within one line, line length/complexity (short/medium/long,
plus one dialogue-quote-embedded case), and one case with two different
confirmed terms co-occurring in the same line to check whether hinting one
term causes the model to also honor an unhinted second confirmed term
present in the same glossary context.

**Step 2 result -- `retranslate_line_with_hint()`, single-line path:
10/10.** Every case, including the multi-occurrence and dual-term cases,
produced the confirmed `confirmed_target` string verbatim in the output.
The one real cached-line case (`バッターボックスに立` → `"batting box"`
in a 81-character, name-dense sentence) succeeded cleanly, matching the 9
constructed cases -- no evidence the real-vs-constructed distinction
mattered to the outcome. The dual-term case (case 9, hint on `ケイト`)
also spontaneously honored the second, unhinted confirmed term
(`バッターボックスに立` → `"batting box"`) despite only one term being
named in the hint -- the glossary context in the prompt was applied
generally, not narrowly scoped to just the hinted word.

**Step 4 result -- `translate_chunk_with_masking()`, chunk-shaped path:
7/10, same 10 source lines, same `glossary_text`, `mask_targets=[]`**
(correct equivalent for confirmed terms: `glossary.py`'s masking rule only
masks `status != "confirmed"` terms, so these 3 confirmed terms are never
masked on either path -- both rely purely on `glossary_text` prompt
injection, isolating prompt-shape as the only real variable between step 2
and step 4). All 3 misses were the same term: `ハードキャッチ` →
`"Hard Catch"` came back lowercased (`"hard catch"`) in all 3 lines that
used it (cases 5, 6, 10); `ケイト`→`"Kate"` and
`バッターボックスに立`→`"batting box"` were honored 7/7 across every
chunk-path case that used them, with correct casing every time.

**Pattern found, not random: casing on one specific term, not term type or
line shape in general.** The failure correlates cleanly with which
*specific* confirmed term is present (`ハードキャッチ`/`Hard Catch`),
not with term type (the other character-type term, `ケイト`/`Kate`, was
honored 3/3 on the chunk path), not with occurrence count (case 10's
double-occurrence line failed both instances identically -- consistent
substitution, not a first-vs-second-occurrence split), and not with line
length (case 5's short line failed the same way as case 6's long one).
Best-supported explanation: `"Hard Catch"` is capitalized like a proper
skill/move name, but its glossary line renders as plain prose
(`- ハードキャッチ -> Hard Catch (keep honorific)`) with nothing marking
the capitalization as load-bearing, and in the chunk path this one term
has to compete for the model's attention against a whole paragraph's
worth of ordinary translation decisions rather than being the sole,
explicitly-hinted focus the single-line prompt gives it
(`"Pay particular attention to accurately translating this word/phrase:
{hint}"`). The single-line path never lowercased it (cases 5, 6, 10 -- the three
`ハードキャッチ` cases -- all 3/3 correct on the hinted path), consistent
with the explicit per-line hint being the load-bearing difference, not
some deeper chunk-path defect in glossary injection generally (the other
2 confirmed terms were honored at 100% on both paths).

**Net read, replacing the old "4/5, probably noise" placeholder:** the
single-line, explicitly-hinted path (`retranslate_line_with_hint()`) is
reliable at 10/10 on this test set and is not the weaker case this doc's
open question worried it might be. The chunk path, run without a specific
per-term hint, is measurably weaker (7/10) but the weakness is
term-specific (unconventional capitalization inside an otherwise-plain
glossary gloss) rather than a general property of multi-line JSON-array
prompts losing injected context -- the doc's original worry ("short
single-line prompts are systematically weaker") is not what this data
shows; if anything the opposite (single-line, hinted path outperformed
chunk path here).

**Caveat on sample size, stated plainly:** 10 cases, one glossary, one
novel, one session, `temperature=0.1` (low but nonzero) -- this is a real
measurement, not a proof. In particular the "always exactly lowercased,
never something else" pattern for `ハードキャッチ` across 3/3 misses is
suggestive but not confirmed as deterministic without repeat trials of
the same case (phase 2's own earlier entry already documents a case where
a single trial's apparent finding didn't hold up under repeats -- the same
caution applies here and repeats were not run this session due to time,
not because it was assumed unnecessary).

**Proposed next steps, not implemented here (measurement only, per task
scope):**

1. If phase 5's vocabulary-notes injection reuses the chunk-path prompt
   shape for confirmed-style entries, consider flagging terms with
   internal capitalization (mixed-case multi-word terms specifically,
   like `Hard Catch`) for either (a) the single-line hinted retranslation
   path preferentially, since it measured 100% on exactly this term, or
   (b) a light prompt reinforcement for that class of term specifically
   (e.g. `(keep this exact capitalization)` appended in
   `format_glossary_for_prompt()`'s parenthetical for terms whose
   confirmed_target contains internal uppercase mid-word) rather than a
   blanket prompt-engineering change applied to all confirmed terms.
2. Before leaning further on this finding: repeat the 3 `ハードキャッチ`
   chunk-path cases several more times each to confirm the miss is
   deterministic-per-term rather than this session's particular sample,
   the same correction this doc's phase 2 entry already had to make once
   for a different case.
3. Accepting the limitation as-is (chunk-path casing drift on
   unconventionally-capitalized terms, correctable via the existing
   phase-3 Accept/Discard-and-retry-via-hint flow, which already measured
   100%) is also a reasonable scope decision for phase 5 if 1-2 are judged
   not worth the complexity -- not a recommendation made here, just noted
   as the do-nothing option's actual cost given what this data shows.

### 2026-07-31: Phase 5 (global vocabulary-notes store) — implemented

**Interface decision, stated plainly: module-level functions in a new
`global_vocabulary.py`, no class.** `GlossaryCoordinator` exists because
it holds real per-call state (`novel_id`, `_rebuild_in_progress`) needed
across its methods -- the global store has no per-novel scoping (one
file, process-wide) and no backgrounded operation (every write is an
instant reload-then-save, the exact shape `GlossaryCoordinator.upsert_confirmed()`/
`reject()`/`clear()` already use as thin wrappers over `glossary.py`'s
own module functions). A `GlobalVocabularyCoordinator` class would have
had a no-op `__init__` and zero instance attributes -- pure ceremony.
`global_vocabulary.py` plays the role `glossary.py` plays (module
functions + a dumb JSON file), not the role `glossary_coordinator.py`
plays; there is nothing here that needs a coordinator layer, because
nothing here needs scoping or shared cross-call state.

**Storage**: `~/.config/alphapolis_reader/global_vocabulary.json` --
a single flat file, sibling to (not inside) `GLOSSARY_DIR`. Schema:
`{"updated_at": str, "entries": [{"source", "target", "note", "added_at",
"updated_at"}, ...]}`. Deliberately no `status`/`candidates`/`origin`/
`type` fields -- both write paths (the retranslation dialog's checkbox,
the glossary dialog's "Apply Globally" action) are human-confirmed-only;
there is no LLM-extraction/review-queue path feeding this store the way
`build_glossary.py` feeds per-novel `STATUS_SUGGESTED` entries, so every
entry that exists here is trusted on write. Dedup key: `source`, same
precedent as `upsert_confirmed_term()`. `upsert_global_entry()` reloads
the store fresh immediately before writing -- the same discipline
`GlossaryCoordinator`'s simple write methods use, verified by a real
concurrent-write test (`test_reloads_fresh_before_write`: a second
writer's addition, written directly to disk between two
`upsert_global_entry()` calls in the same test, survives).

**Precedence rule**: `format_global_vocabulary_for_prompt(store,
current_novel_glossary)` excludes any entry whose source is
`STATUS_CONFIRMED` in the current novel's own glossary -- per-novel
confirmed terms always win over a same-source global note. An
unconfirmed (merely `STATUS_SUGGESTED`) per-novel term does *not*
suppress the global note, only a real confirmation does. Verified both
by unit test and live: the combined prompt built during live
verification below correctly excluded `バッターボックスに立` (already
per-novel-confirmed) from the global block while including a different
global-only entry for the same session.

**Mixed-case reinforcement, narrowed rule (a real decision point, not the
literal broad rule originally sketched)**: `glossary.mixed_case_note()`
fires only on targets with 2+ capitalized words (e.g. `"Hard Catch"`),
not on any target that merely mixes upper/lower case. This deliberately
exempts ordinary single-capitalized words/names (e.g. `"Kate"`), which
the 2026-07-31 reliability finding showed were already honored 100% with
no reinforcement needed -- the broader literal rule would have added
prompt noise to every ordinary capitalized name with no evidence it
helps there. Shared by both formatters (`glossary.format_glossary_for_prompt()`
and `global_vocabulary.format_global_vocabulary_for_prompt()`) via one
function living in `glossary.py`, rather than duplicated or split across
a third shared module -- `global_vocabulary.py` already imports
`STATUS_CONFIRMED`/`MAX_TERMS_IN_PROMPT` from `glossary.py`, so one more
import added no new dependency edge.

**Whole-line-vs-single-term UI wrinkle, resolved with a second small
popup, not silent derivation.** The retranslation dialog's "remember
this" checkbox (`accept_and_close()`, `alphapolis_reader.py`) corrects a
whole line (`candidate`), not a clean term pair -- silently writing
`hint_word -> candidate` (a full sentence as "target") would pollute the
global store with nonsensical lookup-table rows. When checked, Accept
now opens `_open_remember_globally_popup()`: Source pre-fills from
`hint_word` (the word/phrase the user already flagged), Target pre-fills
via a word-level `difflib.SequenceMatcher` diff between the
pre-correction and corrected translation when the diff is a single
contiguous replacement (`_diff_single_substring()`), else is left blank
with an explicit "(could not auto-detect -- please fill in)" hint. The
user must confirm/edit before Save Globally writes anything -- a
pre-fill, not an auto-decision, same idiom as this file's existing
click-to-use reference buttons.

**Real bug found and fixed during implementation, not just in testing**:
the sub-popup was originally parented on the retranslation popup's own
`Toplevel` (`win`). `accept_and_close()` destroys `win` immediately after
opening the sub-popup as part of its existing (unchanged) session-apply
flow -- since a Tk `Toplevel`'s children are destroyed along with it,
this silently killed the "Remember Globally" popup before a user could
ever interact with it, defeating the whole fire-and-forget design. Fixed
by parenting the sub-popup on `self.root` instead. Caught by a
unit test attempting to locate the popup after Accept (`StopIteration`
on an empty search), then confirmed and reproduced live (see below)
before the fix, and confirmed fixed live afterward.

**"Apply Globally" action and the click-to-use reference field**: added
to `open_glossary_dialog()`'s `build_form()`, right after the Note field.
Both are `type=="term"`-only per the design's scope decision (character
entries never globally eligible -- a name is only correct for one
story). The reference field (`Global: {target}` button, or a greyed
`Global: (none)` label) is shown for every term-typed row regardless of
status; the "Apply Globally" button is additionally gated on
`status==STATUS_CONFIRMED` (an unconfirmed row has no `confirmed_target`
yet worth promoting). Same `ttk.Button`-when-available/`ttk.Label`-when-not
idiom as `open_word_glossary_popup()`'s Google/LLM reference buttons,
reused a third time in this codebase for the same "click to use, don't
silently auto-fill" pattern.

**Call-site wiring: only the two live-reader paths, not all four
existing `format_glossary_for_prompt()` call sites.** `_do_fetch_and_translate()`
(the main chunk-translation hot path) and `open_retranslate_popup()`'s
`fetch_candidate()` were wired; `alphapolis_translate.py` (standalone CLI)
and `compare_translations.py` (Google-vs-LLM quality comparison) were
deliberately left unwired -- both are dev/debugging tools whose purpose
is isolated, reproducible measurement against exactly the per-novel
glossary, and silently injecting a second data source would make that
purpose murkier, not better. A small independent follow-up if CLI parity
is ever wanted. Implemented as a standalone `format_global_vocabulary_for_prompt()`
call, concatenated by each wired call site with `format_glossary_for_prompt()`'s
output (`glossary_text + "\n\n" + global_text` when both are non-empty)
-- not a parameter added to `format_glossary_for_prompt()` itself, keeping
per-novel rendering and cross-store precedence independently testable and
matching the existing "callers pre-format and concatenate" boundary
`llm_translate.py` already relies on (that module still has zero import
of either `glossary.py` or `global_vocabulary.py`).

**Live verification, via a real running app under Xvfb+fluxbox (`DISPLAY=:99`,
`run_ui_tests.sh xvfb-keep`) against novel 375266002's real seeded
glossary and the real production model (`mradermacher/translategemma-12b-it-GGUF:Q4_K_M`,
confirmed live via `/v1/models`), not a synthetic harness:**

- **Scenario A (Apply Globally)**: launched the app against episode
  7800089 (a real cache hit, "Displayed episode:" confirmed in the log).
  Opened the Glossary dialog, selected the confirmed `type=="term"` row
  (`バッターボックスに立` -> `"batting box"`) -- screenshot confirmed a
  real, clickable `Global: (none)` label (greyed) and an "Apply Globally"
  button present. Clicked it; a confirmation messagebox appeared
  (dismissed via Return). Read `global_vocabulary.json` directly (not
  just trusted the UI) -- confirmed the entry `{"source":
  "バッターボックスに立", "target": "batting box", ...}` was written,
  with the app log showing the matching `INFO` line and no ERROR/CRITICAL
  output. Re-selected the same row afterward: the reference field now
  showed a real, dark/enabled `Global: batting box` button (not the
  earlier greyed placeholder), confirming the reference field reflects a
  just-written entry without needing a dialog reopen. Separately selected
  the confirmed *character*-typed row (`ハードキャッチ`, despite its
  skill-name-shaped source) and confirmed via screenshot that neither the
  reference field nor "Apply Globally" appear at all for a character
  row -- the character-exclusion rule holds live, not just in a unit
  test.
- **Scenario B (retranslation dialog's "remember this" checkbox)**:
  switched to Interleaved mode, drag-selected `バッターボックスに立つの`
  in the real source line, right-clicked, selected "Retranslate this
  line..." -- a real live call to translategemma returned a genuine
  candidate ("...stood Katsuo-kun..." vs. the baseline "...was
  Katsuo-kun..."). "Also remember this for next time" was checked by
  default; clicked Accept. Confirmed live (full-screen root capture, not
  a per-window screenshot, since Tk `Toplevel` windows in this Xvfb setup
  don't always report accurate window-relative geometry through the
  per-window screenshot path) that the "Remember Globally" popup opened
  as **its own independent top-level window**, not a child destroyed
  along with the retranslation popup -- the exact bug described above,
  confirmed both broken (before the `self.root` reparenting fix) and
  fixed (after) via this same live sequence. Source pre-filled correctly
  (`バッターボックスに立つの`); Target correctly showed "(could not
  auto-detect -- please fill in)" for this particular correction (a
  multi-word, non-single-contiguous diff against the baseline -- the diff
  heuristic's honest blank-fallback case, not a bug). Typed a target
  (`"stood at the plate"`), clicked Save Globally -- the app log recorded
  the real `INFO` write, and `global_vocabulary.json` showed the new
  entry alongside Scenario A's, both present. Zero ERROR/CRITICAL log
  lines across the entire session.
- **Scenario C (a subsequent real translation call actually reflects a
  global note, not just that the prompt string contains it)**: seeded one
  more global entry directly (`テスト用語` -> `"Hard Catch"` -- the exact
  same target string the 2026-07-31 reliability finding's chunk-path
  miss was about, deliberately reused so this check closes the loop on
  that finding specifically) and constructed a short test sentence
  (`彼はテスト用語を成功させた。`) using it. Built the real combined
  `glossary_text` exactly as `_do_fetch_and_translate()`/`fetch_candidate()`
  now do (`format_glossary_for_prompt(novel_glossary)` + `"\n\n"` +
  `format_global_vocabulary_for_prompt(load_global_vocabulary(),
  novel_glossary)`) and confirmed by inspection that the precedence
  exclusion held in this real combined string too: the per-novel-confirmed
  `バッターボックスに立` entry from Scenario A did **not** appear in the
  global block, exactly as the precedence rule requires, while the
  distinct `バッターボックスに立つの`/`テスト用語` global-only entries
  did. Ran the real `retranslate_line_with_hint()` (the single-line,
  hinted path) 5 times: **5/5 correctly returned "Hard Catch" with exact
  casing**, e.g. `"He succeeded at Hard Catch."` every time. Ran the same
  sentence through the real `translate_chunk_with_masking()` (the chunk
  path, `mask_targets=[]` since this term is not per-novel-confirmed and
  therefore never masked) with the same combined `glossary_text`, 5
  times: **5/5 also correctly returned "Hard Catch" with exact casing**,
  e.g. `"He succeeded in the Hard Catch."` -- a genuine, direct empirical
  answer to the 2026-07-31 finding's open question (proposed next step
  #1): the mixed-case reinforcement note **does** measurably close the
  chunk-path gap for this term, at least on this sample (5/5 vs. the
  earlier unreinforced 0/3 for the same target string). Caveat stated
  plainly, matching this doc's own established discipline: 5 repeats of
  one sentence is a real result, not a large-sample proof -- worth
  broader confirmation later if this mechanism is leaned on further, not
  assumed settled from one session.

**Not done in this pass**: no `line_overrides` cache-persistence field
(Phase 4, still not started, unaffected by this work). No CLI-path
wiring (`alphapolis_translate.py`/`compare_translations.py`), per the
scope decision above. No broadening of the mixed-case rule beyond the
narrowed 2+-capitalized-word test -- the literal any-upper-and-lower
version discussed during planning was explicitly rejected in favor of
the narrower rule, per direct instruction, not left as an open question.

**Test coverage**: `tests/webnovels/test_global_vocabulary.py` (new, 17
tests): load/save roundtrip, missing/corrupt file handling, upsert
dedup-by-source, upsert reload-fresh-before-write (a real concurrent-write
simulation, not just a mock-call-count assertion), `get_global_entry`
hit/miss, and `format_global_vocabulary_for_prompt()`'s precedence
(confirmed-exclusion, suggested-non-exclusion, `None`-novel-glossary
path), mixed-case reinforcement, and note rendering.
`tests/webnovels/test_glossary.py` extended (+6): `mixed_case_note()`'s
narrowed rule including an explicit `"Kate"`-does-not-trigger regression
guard, and `format_glossary_for_prompt()` carrying the same reinforcement
for per-novel confirmed terms. `tests/webnovels/test_glossary_coordinator.py`
extended (+5, new `TestGlobalVocabularyReferenceAndApplyGlobally` class):
drives the real, unmodified `open_glossary_dialog()` end-to-end through
its actual Treeview selection and buttons -- Apply Globally absent for
character rows, absent for unconfirmed term rows, present and writes via
`upsert_global_entry()` for confirmed term rows, reference button/label
shown correctly for entry-exists vs. entry-missing. New
`tests/webnovels/test_retranslation_remember_globally.py` (12 tests):
`_diff_single_substring()`'s single-contiguous-replacement detection
(including the real `醤油顔`/`ノーズボン`-style before/after examples
from Phase 2's own live testing) and the ambiguous-diff blank-fallback
case, plus the full checkbox-to-popup flow driven through the real
`accept_and_close()`/`_open_remember_globally_popup()` methods (via
`conftest.py`'s `_ReaderAppShell`, extended with a new
`_open_remember_globally_popup = ReaderApp._open_remember_globally_popup`
binding) -- checkbox gating, Source/Target pre-fill (both the
successfully-diffed and the correctly-blank cases), Save Globally's real
`upsert_global_entry()` call with user-edited (not just pre-filled)
values, Skip writing nothing, and the outer session-apply behavior
proceeding independently of the sub-popup's outcome either way.

Full `tests/webnovels/` suite re-run (excluding the separate, always-manual
`ui_automation/` directory, unaffected by this change): 320 passed, no
regressions. `black`/`isort`/`flake8` clean on every touched file.
`mypy`: `global_vocabulary.py` and `glossary.py` both clean (zero errors);
`alphapolis_reader.py` went from 418 to 444 errors (+26), consistent with
this file's existing, previously-documented untyped-method convention --
not fixed here, same treatment as every prior phase entry touching this
file.

**Not anticipated going in, found during this task**: the sub-popup
parenting bug described above (a real, live-reproduced data-loss-shaped
bug -- the "remember this" write path would have silently never worked
in practice, since the popup meant to collect the term pair was destroyed
before a user could ever see it) was not anticipated by the plan and was
caught by a unit test before it was ever run live, then confirmed and
fixed against the real app. The `SequenceMatcher`-based diff heuristic's
character-level-vs-word-level distinction (character-level diffing
splits a clean word-for-word substitution like "dark"->"tanned" into a
spurious insert+delete pair, since the two words share a letter) was
also not anticipated and was caught by the diff helper's own unit tests
failing against real phase-2 before/after examples, not assumed correct
from the implementation alone.

### 2026-08-01: stale-popup write race — found during phase 4 research, fixed

Found while re-deriving phase 4's design, not something phase 4's brief
asked for directly, and documented separately per the discipline this
doc already follows for out-of-scope-but-real findings (e.g. phase 3's
mode-switch bug, phase 5's sub-popup parenting bug).

**The bug**: `open_retranslate_popup()` is a plain, non-modal
`tk.Toplevel` (no `grab_set()`), and neither `load_episode()` nor
`go_prev()`/`go_next()` close it on navigation. So: open the popup for
episode A, navigate to a different episode B (Previous/Next remain
clickable the whole time), click Accept on the still-open popup for A --
at that point `self.current_url`/`self.episode` refer to B, not A, but
the popup's `source_line`/`candidate`/`translated_span` still describe
A's content.

**Why this was harmless before phase 4 and is not harmless now**:
phase 3's in-memory write (`self.episode["translated_lines"][line_idx] =
candidate`) already had this exact race, but writing A's correction into
whatever `self.episode` happens to be at click time was a session-scoped
inconvenience at worst -- it could corrupt B's in-memory display for the
rest of the session, but nothing on disk was ever at risk, since nothing
was written to disk at all. Phase 4 makes Accept call
`save_cached_episode(self.current_url, self.episode)` -- so the same
race, unaddressed, would silently write A's correction into B's cache
file under B's own cache key (or, if `line_idx` happened to be
out-of-range for B, would be caught by the existing bounds check and
merely logged, but a same-length coincidence would not be caught at
all). This is a real persistence-corruption risk a purely in-memory
write never had.

**Fix**: `open_retranslate_popup()` now captures `popup_opened_for_url =
self.current_url` and `popup_opened_for_episode = self.episode` once, at
open time. `accept_and_close()` re-checks both, fresh, at the moment
Accept is actually clicked (`self.current_url != popup_opened_for_url or
self.episode is not popup_opened_for_episode`) -- if either has changed,
**both the in-memory and on-disk write are skipped entirely**, a warning
is logged, and the status bar tells the user why ("Retranslation not
saved -- you navigated to a different chapter"). No attempt is made at a
partial/soft write into whatever might still be reachable; per explicit
direction, an unclear, half-defined fallback is worse than a clean skip.

**Two checkpoints, deliberately not equally live, stated as an accepted
tradeoff rather than left as an implicit gap**: `build_form()` (candidate
render time) shows a courtesy UI hint -- if already stale when the
candidate finishes loading, the "different chapter" message is shown and
Accept is rendered disabled. This check does **not** re-poll while the
popup sits open and idle; if the user opens the popup, leaves it looking
fresh, navigates away, and never causes `build_form()` to re-render, the
button can keep showing enabled indefinitely. This is intentional, not
an oversight: `accept_and_close()`'s own check, run fresh at the instant
Accept is clicked, is the actual authoritative gate, and every write
(in-memory and disk) is conditioned on it, never on the button's
disabled/enabled UI state. Verified directly, not just asserted: a unit
test forces the button back to enabled after the popup has already gone
stale (`accept_btn.state(["!disabled"])`, bypassing the courtesy check
entirely) and confirms the write is still correctly blocked --
`accept_and_close()`'s check does not depend on Tk's own disabled-widget
click-guard either.

**Rejected alternative, stated with reasoning, not silently dropped**:
making `load_episode()`/`go_prev()`/`go_next()` close any open
retranslate popup on navigation, removing the race at its source instead
of guarding the one place it matters. Rejected because those three
methods are the most heavily-exercised code paths in the entire app --
every single load in every session goes through them -- and adding
popup-teardown logic there for a narrow edge case (a user deliberately
navigating away while a correction dialog sits open) is disproportionate
risk to currently-solid, high-traffic code, compared to a guard placed
exactly where the actual consequence (a bad write) would occur.

**Test coverage**: `TestAcceptStalePopupGuard` in
`tests/webnovels/test_retranslation_dialog.py` (4 tests): Accept
correctly disabled when the episode was already stale before the popup's
candidate finished rendering; the realistic case -- Accept correctly
*not* disabled at render time, then the episode changes while the popup
sits open, and `accept_and_close()`'s own check still blocks the write
(this is the test that actually proves the authoritative-gate claim, not
just the UI courtesy); a URL-only change (same episode object,
hypothetically, but a different `current_url`) also blocks the write;
and the disabled-state-bypass test described above. All four confirmed
load-bearing by reverting the phase 4 fix and re-running (see phase 4's
own dated entry for the combined revert-and-rerun result covering both
this fix and the base persistence fix together).

**Not done in this pass**: no live/xdotool reproduction of this specific
race -- covered by the unit tests above, which drive the real
`open_retranslate_popup()`/`accept_and_close()` methods end-to-end
against a real (headless) Tk widget tree, not a reimplementation of the
guard logic. Live verification for this phase focused on the base
persistence-across-restart scenario (see phase 4's dated entry); a
live reproduction of navigate-while-popup-open was judged lower value
given the unit tests already exercise the exact same code path a live
click would.

### 2026-08-01: `safe_persistence.py` foundational design -- implemented and migrated

`pyplayground/utils/safe_persistence.py`'s two helpers (`atomic_write()`,
`verify_before_write()`) are implemented and every call site from the
original design's migration plan has been moved onto them, in order,
each step's acceptance bar confirmed before the next. Relevant to this
doc specifically: `open_retranslate_popup()`'s stale-popup guard above
(capture `current_url`/`episode` at popup-open, re-verify fresh at
Accept) is now routed through `verify_before_write()` --
`accept_and_close()` supplies `reload_current` (re-reads
`self.current_url`/`self.episode`), a `markers_match` callback
reproducing the exact `!=`/`is not` comparison this guard always used,
and an `on_divergence` callback that is the original skip-and-warn logic,
verbatim (logs the same warning, returns a sentinel the caller uses to
skip both the in-memory and on-disk write and show the same status-bar
message). `TestAcceptStalePopupGuard`'s tests in
`tests/webnovels/test_retranslation_dialog.py` pass unmodified against
the migrated code -- confirming this was a relocation of mechanism, not
a behavior change.

`save_cached_episode()` (used by this guard's Accept path, via
`config_utils.save_json_config()`) is also now atomic end-to-end: no
direct `open(path, "w")`/`path.write_text()` remains anywhere in this
write path.

Live-verified under Xvfb + fluxbox against the real running app: a real
right-click -> "Retranslate this line..." -> Accept flow, with the
resulting on-disk episode-cache write confirmed atomic via `strace`
attached to the live app process (`openat()` of the uniquely-named temp
file, immediately followed by `rename()` onto the real cache file) --
not simulated, the actual syscalls made by a real user action. The
correction landed under the correct episode's cache key with clean app
logs (no ERROR lines), confirmed by re-reading the resulting JSON file
directly. See `DESIGN.md`'s matching dated entry for the full account,
including the parallel live verification of a real Glossary Save through
`GlossaryCoordinator.save_snapshot()`.

### 2026-08-01: Phase 4 (accepted-correction persistence) — implemented

**Design decision, re-derived rather than assuming the original sketch
was still right (per this task's own explicit instruction): no
`line_overrides` field.** The doc's original phase 4 sketch (see the
"Explicitly deferred" section, now updated) proposed a new, separate
cache field to hold accepted overrides. Re-reading phase 3's actual,
already-shipped mechanism first (rather than building the sketch as
originally written) showed that's no longer the right design:
`accept_and_close()` already writes
`self.episode["translated_lines"][line_idx] = candidate` directly --
the exact field a normal translation populates, in the exact dict object
`_do_fetch_and_translate()` builds, caches, and had already been handing
to `save_cached_episode()` (just not calling it again after Accept). A
separate field would only be justified if the original MT output needed
to stay distinct from the correction for a revert/audit need -- no such
requirement exists or was requested. So phase 4 turned out to be almost
entirely "call `save_cached_episode()` after Accept, reusing what's
already correct in memory," not "design and persist a new field."

**No `CACHE_SCHEMA_VERSION` bump.** `DESIGN.md` §11's v3→4 bump
(`needs_review_flags`) was required because that field is a *second,
separately-indexed* `List[bool]` that must stay length/order-synchronized
with `translated_lines` -- a stale or absent value there is a silent
misalignment risk, not "no flag." This change adds no field and changes
no shape: `translated_lines` is still exactly the `List[str]`, same
length as `lines`, it always was; only some of its string contents now
differ from what a fresh translation alone would have produced. Old
cache files need no migration and are read exactly as before.
`CACHE_SCHEMA_VERSION` stays at `4`.

**The stale-popup write race found during this task's own research is
documented as its own dated entry immediately above** (2026-08-01,
"stale-popup write race") -- a real, previously-undocumented risk that
phase 3's in-memory-only write never had to guard against, closed as
part of this phase's implementation, not left for later.

**Write trigger and cost, verified rather than assumed cheap**:
`save_json_config()` (`pyplayground/utils/config_utils.py:113-143`,
what `save_cached_episode()` calls) is a direct `open(path, "w")` +
`json.dump()` -- **not atomic**, no temp-file-plus-rename. This was
already true of every cache write in this codebase before this change;
what changes is the *consequence* of hitting it, not the mechanism.
Before phase 4, a crash mid-write could only happen during the
once-per-fresh-episode `_do_fetch_and_translate()` path, losing at most
one episode's translation -- annoying but cheap to regenerate. After
phase 4, the same crash can happen on every Accept click, and the file
being written at that point can also hold *other, unrelated,
already-accepted corrections and hard-won `needs_review`/glossary-derived
state* for that same episode -- a mid-write crash now risks losing more
than just the write that triggered it. This is a genuine, heightened (not
new, but heightened) risk carried forward, stated here explicitly rather
than buried as "same risk profile, just more often." Fixing it (atomic
temp-file-plus-rename writes) is out of scope for this task and remains
open.

The write itself is synchronous, on the Tk main thread, inside the
Accept button's callback -- a full-episode `json.dump()` briefly blocks
the UI. Judged acceptable for a deliberate, infrequent user action, same
cost class as every other synchronous dialog action already in this
file. **Trigger: immediate write on Accept**, after the stale-popup
guard passes and the existing in-memory write completes -- matches the
"instant reload-then-save" pattern already established for
`GlossaryCoordinator`/`global_vocabulary.py`. No debouncing; this is not
a hot path.

**Status message and docstrings updated to match reality**: the popup's
note now reads "Accept saves this correction to the episode cache"
(previously "session-only... persistence isn't built yet"); the
post-Accept status bar now reads "Retranslation saved" on success (was
"...applied for this session (not saved)"), or, for the stale-popup
case, "Retranslation not saved -- you navigated to a different chapter".
`open_retranslate_popup()`'s and `_open_remember_globally_popup()`'s
docstrings, both of which described Accept as session-only per phase 3's
then-accurate state, are updated to describe the real, current behavior.

**Test coverage**: `TestAcceptPersistsToCache` in
`tests/webnovels/test_retranslation_dialog.py` (3 tests) -- the load-
bearing one (`test_correction_survives_a_full_reload_from_cache`) drives
the real Accept button, then calls `load_cached_episode()` fresh (a
genuinely separate read, not a re-inspection of the same in-memory
`episode` object `TestAcceptSurvivesModeSwitch`'s phase-3 test already
covers) and confirms the correction is present -- this is the actual
"survives a restart" check, since a real restart also starts from a
fresh `load_cached_episode()` call in a brand-new process with no
reference to any prior in-memory state. A sibling test stubs out
`save_cached_episode()` and confirms the reload then correctly finds
nothing, proving the first test is a real check and not a tautology. A
third confirms the status message. Plus the 4-test
`TestAcceptStalePopupGuard` class documented in the finding above. All 7
new tests (plus the pre-existing 11 in this file) confirmed
**load-bearing together**: reverted the phase 4 production changes to
`alphapolis_reader.py` via `git diff`/`git checkout`/`git apply` and
re-ran -- 5 of the 6 tests whose pass/fail depends on the fix (all
except the stub-based negative-control test, which is correct either
way) failed with exactly the expected assertion mismatches, then passed
again once the fix was restored.

**Live verification**, via `run_ui_tests.sh xvfb-keep` against the real
app and novel 375266002's real cached episode 7800089 (the same
`バッターボックスに立` line used in prior phase 2/5 live sessions):

- Launched the app (cache hit, "Displayed episode: contact" confirmed in
  the log), screenshot before: baseline text "In the batting box **was**
  Katsuo-kun...".
- Switched to Interleaved, drag-selected `バッターボックスに立つの` in
  the source line, right-clicked, "Retranslate this line..." -- a real
  live translategemma call returned a genuine candidate ("...**stood**
  Katsuo-kun..."), and the popup's note correctly read "Accept saves
  this correction to the episode cache" (confirming the updated wording
  is live, not just present in source). Unchecked "remember this" (out
  of scope for this verification) and clicked Accept.
- App log recorded `Retranslation accepted and saved for line: ...`;
  status bar showed "Retranslation saved"; on-screen text updated to
  "...**stood** Katsuo-kun...". Read `load_cached_episode()` directly
  (fresh Python process, not the running app) and confirmed the on-disk
  file already contained the corrected text -- proof the write actually
  landed, not just that the UI claimed success.
- Killed the app via `proc` `SIGTERM` (escalated to `SIGKILL` after a
  timeout) -- never `xdotool windowclose`/`windowkill`, per this
  project's own documented Playwright/EPIPE crash finding.
- Relaunched a **brand-new process** against the identical episode URL
  (same cache key, no retranslation triggered in this second process at
  all). Screenshot confirmed the corrected text ("...stood Katsuo-kun...")
  was present on screen immediately on load, sourced entirely from the
  on-disk cache written by the first process -- the actual, real
  restart-survival proof this phase exists to deliver. Zero
  ERROR/CRITICAL log lines across both process runs.
- Did not separately live-reproduce the stale-popup race (see that
  finding's own "Not done in this pass" note for why the unit tests were
  judged sufficient).

`black`/`isort`/`flake8` clean on both touched files. `mypy`:
`alphapolis_reader.py` went from 444 to 447 errors (+3), consistent with
this file's existing, previously-documented untyped-method convention --
not fixed here, same treatment as every prior phase entry touching this
file. Full `tests/webnovels/` suite (excluding the always-manual
`ui_automation/` directory): 326 passed, up from 320, no regressions.

**Not done in this pass**: no atomic (temp-file-plus-rename) cache
writes -- the heightened-but-pre-existing non-atomicity risk documented
above is carried forward, not fixed, and remains open for a future pass.
No changes to `save_cached_episode()`/`load_cached_episode()`/
`CACHE_SCHEMA_VERSION` themselves -- reused exactly as they already
existed. No changes to phase 5's global-vocabulary-store scope.
