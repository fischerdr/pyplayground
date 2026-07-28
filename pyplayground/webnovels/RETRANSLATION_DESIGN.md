# Line-Level Retranslation & Display Redesign — Design Doc

Living record of decisions for this feature. Update alongside code changes,
not after — chat history is not the system of record. Companion to
`DESIGN.md` (the glossary/term-consistency redesign) but tracked
separately on purpose: this feature is about correcting arbitrary
vocabulary/idiom mistranslations (e.g. `醤油顔`, `ノーズボン` — ordinary
words the model got wrong), not about per-novel proper-noun/term
consistency. Conflating the two would repeat the same flag-means-two-
things mistake `DESIGN.md` §11 already caught once for `needs_review`.

Last updated: 2026-07-27 (Accept survives same-session view-mode switch, found and fixed)

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
- Whether `line_overrides` needs a `CACHE_SCHEMA_VERSION` bump (forcing
  regeneration of all cached episodes, same cost as `DESIGN.md` §11's
  bump) or can be safely read via `.get("line_overrides", {})` with no
  correctness risk on old cache files. Instinct: the latter, since unlike
  `needs_review_flags` (which needed strict length-parity with
  `translated_lines` to render correctly), an override is purely
  additive — a missing one just means "no override, render normally."
  Instinct only — must be verified against actual rendering logic before
  building on it, not assumed.
- Where exactly the global vocabulary-notes injection happens in
  prompt-building, and whether it should apply to
  `translate_chunk_with_masking()` too, or only the retranslation-with-
  hint path initially.
- Exact popup dialog field layout/wording beyond "old vs. new,
  Accept/Discard, optional remember checkbox."
- **Does injected context (confirmed glossary now, vocabulary notes in
  phase 5) reliably get honored on short single-line retranslation
  prompts, or is this systematically weaker than the multi-line chunk
  prompts masking was validated against?** Phase 2's live testing (see
  its dated status entry) found the glossary override applied correctly
  in 4 of 5 identical repeats of one case (`彼` → `"Kenji"`) -- the one
  miss looks like ordinary sampling noise at `temperature=0.1`, not a
  systematic issue, but 5 repeats of a single case is not enough to
  close this either way. Matters beyond phase 2 specifically because
  phase 5's vocabulary-notes injection is the same shape of risk (inject
  context into a prompt, trust the model to honor it) on the same
  short-prompt structure -- phase 3/5 should not assume this is settled
  without a few more repeats, ideally across more than one term/case,
  before leaning on it.

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
- **Phases 4–5**: not started.
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
