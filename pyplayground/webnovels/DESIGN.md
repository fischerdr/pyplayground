# Glossary & Reader Redesign — Design Doc

Living record of decisions for the glossary/term-consistency rework and the
Tkinter → web migration. Update this alongside code changes, not after —
chat history is not the system of record.

Last updated: 2026-07-26

---

## 1. Why this started

A glossary rebuild on novel 375266002 (Alphapolis, current `build_glossary.py`
extraction pipeline) surfaced several failure classes:

- **Factual hallucination**: `ランチェスターの法則` (Lanchester's Law) extracted
  as "Pareto principle" — a confident, wrong factual substitution, not a
  translation error.
- **No recurrence filter**: one-off slang (`世紀末モヒカンムーブ`) and mundane
  literal compounds (`鉄パイプ` → "iron pipes") entered the glossary
  alongside real character names, with no signal distinguishing
  "needs cross-chapter consistency" from "translated the same way every time
  anyway."
- **Real-world references treated as novel terminology**: "Article 204 of
  the Penal Code" extracted as a term needing a fixed translation.
- **Translation errors propagating uncorrected**: names transliterated
  during translation (Keito/Rinai) got baked into the glossary as ground
  truth, which then got re-injected into future prompts as "use these exact
  translations," reinforcing the error rather than catching it.
- **Unreliable type classification**: `オレ` (a pronoun) typed as
  `character`; `音夢くん` (a person's name) typed as `term`.

Root cause split into four threads:
1. **Model choice** — `translategemma-12b-it` is translation-tuned, not
   general-purpose; it has no reliable mechanism to say "I don't know this"
   on factual/classification tasks.
2. **No recurrence/worthiness gate** before something enters the glossary.
3. **Translated (possibly wrong) text trusted as ground truth** for names,
   with no review checkpoint.
4. **Type classification inferred implicitly** by the extraction model
   rather than constrained or human-confirmed.

## 2. Reference UX (screenshots of an existing MTL site's term system)

Clarified the actual target shape, which reframes threads 2–4:

- Terms are **FROM → TO with a ranked candidate list**, not a single fixed
  target. The reference tool shows usage-count badges (e.g. 23 vs 1) next
  to alternative translations — popularity is the disambiguation signal,
  not any single model's one-shot guess.
- Term editor supports **Variation**, **Wild Char**, case sensitivity,
  and a **"This Novel Only" toggle** (global vs. per-novel scope).
- Confirmed terms are **highlighted inline** in translated output
  (bold/colored spans), with a separate system/user/patch styling tier.

**Decision:** per-novel scope only for now (no global/cross-novel terms) —
keep the data model simpler until per-novel is solid.

## 3. Term data model (target shape)

```json
{
  "source": "维多教授",
  "type": null,
  "candidates": [
    {"target": "Professor Victor", "count": 23, "origin": "user"},
    {"target": "Professor Vito",   "count": 4,  "origin": "mt"},
    {"target": "Professor Weiduo", "count": 1,  "origin": "llm"}
  ],
  "confirmed_target": "Professor Victor",
  "status": "confirmed",
  "gender": null,
  "pronoun_style": null,
  "honorific_override": null
}
```

- `status` is the review gate: only `confirmed` terms get injected into the
  translation prompt via `format_glossary_for_prompt()`. `suggested` terms
  (from LLM extraction or an unresolved click-pick) sit in a queue.
- **Two term-creation paths:**
  1. *Highlight → Add Term* (manual): `status: confirmed` immediately,
     one candidate at count 1, `origin: user`. No ambiguity — trusted on
     entry.
  2. *Click an untranslated/inconsistent term*: look up existing
     `candidates` for that source string, ranked by count.
     **History-first, live-query fallback**: if no history exists, query
     Google Translate + one LLM pass for a starting candidate set (not 3
     guesses from the same model — likely to just be 3 flavors of the same
     wrong guess). Picking a candidate increments its count.
- **Type/gender/pronoun fields stay `null` until a human sets them** —
  dropped the idea of the extraction model reliably inferring
  `character` vs `term`; extraction can pre-fill a *suggested* type as a
  hint in the editor, but it's advisory only.
- **Count-building loop**: after every episode translation, match output
  against each term's existing candidates and increment counts for
  whatever actually appears — lets consistency reinforce a candidate
  organically without manual confirmation of every occurrence.

## 4. Sentinel masking (validated, implemented)

**Goal**: mask a term span before translation, translate around it, splice
the original back in — so unreviewed/unconfirmed terms can be left
untranslated and flagged for review instead of the model guessing.

**Format comparison** (tested via `test_sentinel_survival.py`, reusing the
production `TRANSLATION_PROMPT`/JSON-array shape from `llm_translate.py`):

| Format | Example | Survival (translategemma) |
|---|---|---|
| Opaque placeholder | `⟦TERM_1⟧` | **15/15 (100%)** |
| Bracket-inline | `⟦1:るりちゃん⟧` | 0% — model translates/drops the enclosed word |
| XML tag pair | `<t1>るりちゃん</t1>` | 0% — same failure |

**Decision: opaque placeholder.** A translation-tuned model treats
bracket/XML wrapping as translatable content, not inert scaffolding — only
a fully opaque token survives.

**Hardening required**: translategemma normalizes the sentinel's bracket
glyphs (`⟦⟧` U+27E6/27E7 → ASCII `[]`) in at least one observed case.
Splice-back regex must tolerate bracket-glyph variants and fullwidth-digit
normalization, not just the exact canonical glyphs.

**Qwen3-14B-Instruct (no chat template, raw `/completion`) — rejected for
this path.** Single-sentinel/single-line input: fine. Any chunk with 2+
sentinels across multiple lines: **systematic, reproducible empty-string
output** (`["", ""]`) — not stochastic, not chain-of-thought leakage (ruled
out via reuse of production `parse_json_response()`, which already
tolerates trailing content after a valid JSON value). Confirmed via
repeated runs on both the 2-sentinel and 5-sentinel stress cases. Root
cause: raw completion mode with no chat template doesn't give the model a
usable structure for multiple unfamiliar tokens in short untemplated
Japanese text. Fix would require migrating call sites from `/completion` to
`/v1/chat/completions` with `enable_thinking: false` — deferred as a
separate, deliberate decision, not pulled into the masking path.
Locked decision: **translategemma + opaque placeholder for
`translate_chunk_with_masking()`.** Qwen3 remains a candidate for
`build_glossary.py` extraction / `explain_term()` specifically (single-item
calls, no sentinel masking) — untested for that narrower use, separate
question.

**Two-tier fallback** (implemented):
- Sentinel present but reformatted (glyph/digit normalization) → handled
  transparently by the tolerant regex, no special casing.
- **Missing sentinel**, line otherwise non-empty → splice in the raw
  source word unstyled at that position, `needs_review = True`.
- **Empty line** (whole-line content loss, not just a missing marker) →
  retry the chunk once. If still empty, fall back to the unmasked raw
  source line, `needs_review = True`. (Retry has a hard floor — no
  indefinite retry loop.)

**Status as of 2026-07-25**: `TranslatedLine`, `mask_terms()`,
`splice_terms()`, `translate_chunk_with_masking()` added to
`llm_translate.py`. Wraps `translate_chunk()` without changing its
signature — purely additive. Passes black/isort/flake8/mypy. Verified live
against translategemma on the 4-sentinel and 5-sentinel cases from the test
suite — 5/5 spliced cleanly, `needs_review=False` throughout, matching the
isolated test result end-to-end through the production path.

**Real-chunk verification (beyond the test suite)**: the cases above all
reuse `test_sentinel_survival.py`'s hand-picked fixtures, so a further check
was run against actual cached episode text (`~/.cache/alphapolis_reader/`)
with names/positions the test suite never selected —
`_load_cached_episodes_for_novel`-style content, not synthetic sentences:

- 9-line chunk, natural occurrences of two character names (one repeated
  3x, one appearing alongside it in the same line): all 4 sentinels spliced
  cleanly, `needs_review=False` throughout, including the two-different-
  names-in-one-line case landing correctly with no cross-contamination.
- 8-line chunk with a name/honorific variant (`タチバナさん` and the bare
  surname `橘` for the same person, 3 masked instances total): 2/3 spliced
  cleanly; 1 instance (`タチバナさん` in a longer sentence) was dropped by
  the model and correctly caught by the missing-sentinel fallback —
  `needs_review=True`, raw word appended. Confirms the missing-sentinel path
  isn't just a theoretical branch — it fires on real content, exactly as
  designed, with no crash and no silent data loss. (The append-at-end
  fallback placement isn't positionally accurate for a mid-sentence drop,
  a known limitation noted where `splice_terms()` is implemented — the word
  is recovered and flagged, just not necessarily in its original position
  within the line.)
- No empty-line (`["", ""]`) collapse observed on translategemma in either
  real chunk, consistent with the isolated stress-test result.

**Not yet wired** (deliberately deferred — see §6):
- No `mask_targets` producer in `build_glossary.py` (nothing decides which
  terms get masked for a given chunk yet).
- No reader UI consumption of `needs_review`.

### 2026-07-25 update: Qwen3-14B retested via `/v1/chat/completions` + `--jinja`

Server relaunched with `--jinja --reasoning-format deepseek`, tested via the
new companion script `test_sentinel_survival_chat.py` (separate from
`test_sentinel_survival.py` — different endpoint/transport, kept as two
files intentionally; see that script's docstring). Full run:
`--thinking both`, all 3 sentinel formats, all 5 test cases,
`qwen3_chat_results.json`.

**Bracket-inline and XML-tag formats: ruled out definitively, not just for
raw `/completion`.** 0% survival under both `thinking=False` and
`thinking=True` with the proper chat template applied. This rules out "it
just needed a template" as the explanation for the earlier 0% result — the
model genuinely treats bracket/XML-wrapped content as translatable text
regardless of transport. No further investigation needed on these two
formats, on this model, on any transport.

**Opaque placeholder: a *different* failure mode than the one that
originally disqualified Qwen3, and it's a worse fit for this corpus.**
The original raw-`/completion` rejection was a clean, reproducible
empty-string collapse (`["", ""]`) on 2+-sentinel chunks. That did **not**
reproduce a single time in this run. Instead, the dominant failure is
**unescaped literal quote characters inside JSON string values** — e.g.
`'[""Look, ⟦TERM_1⟧! It\'s so red and big!""]'` — almost certainly Japanese
`「」` dialogue markers being translated into literal `"` without escaping
as `\"`. This is a distinct failure class from the empty-string collapse
and needs to be tracked as such:
- It is **not** rescued by `parse_json_response()`'s trailing-content
  tolerance (`raw_decode()`), since the malformation is internal to the
  JSON value, not junk appended after a valid one.
- It correlates with dialogue-bearing lines specifically, which is most
  lines in this corpus — a structurally worse failure rate to expect in
  production than the isolated stress-test numbers suggest.
- `opaque_placeholder` survival with this failure mode counted in:
  **5/12 (42%) at `thinking=False`, 2/12 (17%) at `thinking=True`.**

**Sampling confound on the `thinking=True` numbers — do not read
"thinking is worse" from this run.** Every request (both scripts) sends a
fixed `"temperature": 0.1` for determinism. Qwen's own documentation
explicitly warns against near-greedy decoding specifically in thinking
mode, describing it as causing this kind of degradation (repetition/
malformed output). The `thinking=True` leg of this test was therefore run
under a sampling setting the model's own docs say not to use for that mode
— the 17% vs. 42% gap is confounded, not a clean thinking-on-vs-off
comparison. If that comparison is wanted later, it needs a variant using
Qwen's recommended thinking-mode sampling (temp 0.6 / top-p 0.95 /
top-k 20) for the `thinking=True` leg specifically.

**One clean positive finding**: `reasoning_content` separation via
`--reasoning-format deepseek` worked correctly — no leakage into `content`
in any of the 15 `thinking=True` responses. That specific integration
concern (raised when `--jinja` was first reintroduced) is resolved.

**Net effect on the locked decision**: no change.
**translategemma + opaque placeholder remains the decision for
`translate_chunk_with_masking()`**, now disqualifying Qwen3 for this path
on two independent grounds (empty-string collapse under raw `/completion`,
quote-escaping corruption under the proper chat-templated endpoint) rather
than one.

**Relevant to the still-unrun §5 validation**: extraction/`explain_term()`
calls are also JSON-array-output calls, on the same model. The
quote-escaping failure mode is not sentinel-specific — it's plausible it
also affects those calls on any dialogue-containing input, independent of
masking. Worth checking for this specific symptom (malformed JSON from
unescaped embedded quotes, not just "did parsing fail") when that
validation is finally run, not just whether extraction accuracy improved
on the original Lanchester's-Law-style errors.

## 5. Model notes

- `translategemma-12b-it` (existing): translation-tuned, validated for
  chunk translation + sentinel masking. Not reliable for
  factual/classification tasks (Lanchester's Law hallucination).
- `Qwen3-14B-GGUF:Q8_0` (port 10002): candidate for extraction/
  `explain_term()`. Tested and rejected three times now — twice for
  sentinel-masked chunk translation (§4), and now for extraction (below).
  **No longer a live candidate for this codebase; see 2026-07-25 finding.**
- `Qwen3.6-35B-A3B` (MoE, considered, not pursued): larger total capacity,
  built-in thinking mode. Requires `/v1/chat/completions` +
  `enable_thinking` control to use correctly — bigger integration change
  than a model swap. Shelved pending Qwen3-14B results.

### 2026-07-25 finding: Qwen3-14B fails glossary extraction across every tested configuration; specific failure content is not stable (root cause unresolved)

Run via new standalone script `test_qwen3_extraction_validation.py`
(distinct from both sentinel scripts — this exercises `build_glossary.py`'s
extraction prompt, not `translate_chunk_with_masking()`, a different code
path entirely). Reused `_build_extraction_prompt()` verbatim (imported, not
re-transcribed) against `/v1/chat/completions` with `--jinja` active and
`thinking=False` (per §4's sampling-confound note — near-greedy decoding at
`temperature=0.1` is documented by Qwen as unsafe specifically in thinking
mode, so `thinking=False` was used as the primary condition throughout, not
switched).

**Episode(s) tested**: "provocation" (cache file `c574a6...eead.json`,
episode URL on file in that cache entry) — grep-confirmed to be the actual
source of every error in the original bad glossary (`ランチェスターの法則`,
`オレ`, `鉄パイプ`, `刑法204条`, `世紀末モヒカンムーブ` all present in its
source text). The Keito/Rinai mistransliteration's source names were traced
to line 31 of this same episode: **桂名 and 仁菜 — kanji names, not
katakana** as this doc's earlier prose shorthand implied; correcting that
here since tracing the exact source span was necessary to check the
transliteration. Cross-checked against a second, unrelated episode ("hard
catch", `42c67f...5a5d.json`).

**The established finding, stated at the level of confidence the evidence
actually supports: extraction fails — the model does not produce a valid
`{"terms": [...], ...}` extraction object — across every configuration
tested so far.** `parse_json_response()` either gets a JSON value of the
wrong shape or, once a `max_tokens` cap was added mid-investigation, output
that hits `finish_reason: "length"` without ever producing valid JSON at
all. This alone is the actionable result: **Qwen3-14B-GGUF:Q8_0, under
near-greedy decoding, is not currently usable for this extraction task**,
independent of why.

**An earlier version of this finding claimed the failure content was fixed
and hallucinated independent of input — that claim is retracted, not just
softened.** The initial observation (first server config, `--kv-unified`
active): every run, both test episodes, both thinking modes, returned
byte-identical output resembling an unrelated translation-with-XML-
sentinels task (a fabricated "Kate/Ruri/Otomo-kun/Professor Vito" scene
that appears nowhere in the actual prompt — verified via exhaustive
case-insensitive search of the full assembled prompt, not just the source
section). Four checks were run against that specific server config
(cache-hit via `n_prompt_tokens_processed`, server-health sanity call,
clean single-request harness re-test, cross-episode reproduction) and none
explained it away, which supported treating it as a stable model property.

**It wasn't.** The server was then restarted with `--kv-unified` removed
(the specific mechanism suspected — this flag lets llama-server's `-np 2`
parallel slots share one KV-cache pool, a documented category of
cross-request-contamination risk). Re-running the *exact same request* —
same prompt, same `cache_prompt: false`, same everything except the
now-missing flag — produced **a different degenerate output**: no longer
the Kate/Ruri content, but a short garbage prefix (`"Assistant 1"`)
followed by hundreds of repeated space characters, run twice, both times
hitting the `max_tokens` cap (`finish_reason: "length"`) rather than a
natural stop token. `cached_tokens: 0` confirmed no cache reuse on these
runs.

**What this does and doesn't tell us**: the *specific content* of the
garbage output is not a fixed, input-independent model property — it
changed when `--kv-unified` was removed, which disproves the original
framing. What's still true across both configurations is that extraction
genuinely fails and the model falls into some kind of degenerate/
repetitive non-answer rather than performing the task. **Root cause is
unresolved, not determined**: this data can't distinguish "removing
`--kv-unified` fixed a real cross-request contamination bug, and the
`Assistant 1`/space-padding output is a separate, unrelated repetition-loop
tendency" from "the same underlying repetition-loop pathology exists in
both configurations, and the KV-cache pooling/layout just perturbs which
garbage attractor state it lands in." Distinguishing those would require
further isolation not done here (dropping `-ctv`/`-ctk` quantized KV cache
next, then `-np 1` as a full isolator) — not pursued, since the practical
decision (below) doesn't depend on which is true, and this was scoped as a
measurement task, not a debugging/upstream-bug-report task. If this is ever
filed against llama.cpp, that isolation would need to be completed first.

**Operational note, independent of root cause**: neither this script nor
`test_sentinel_survival_qwen3.py` originally sent a `max_tokens`/token cap
on `/v1/chat/completions` requests. A repetition-loop failure has no
natural stop token, so an uncapped request can consume a shared
llama-server slot (`-np 2` here) for the full context window — observed
directly: one uncapped run against the restarted server ran 15+ minutes
before the client-side timeout was exceeded, with the server itself still
reporting `is_processing: true` partway through. Both scripts now set
`max_tokens` (1024 for extraction, 512 for the sentinel test's short
translated lines) so a future repetition-loop fails fast and visibly
instead of quietly occupying a shared slot.

**This is a mitigation, not a fix.** Capping tokens makes a repetition-loop
failure cheap and fast to detect instead of slow and expensive to discover
— it does not make the model able to do the task. "Safe to run against"
and "usable for extraction" are separate claims; only the first is true
here.

**This is a different, more severe failure than anything previously
documented for this model.** The empty-string collapse (§4, raw
`/completion`) and the unescaped-quote JSON corruption (§4, 2026-07-25
chat-completions update) were both failures *of form* — the model
attempted the right task and the output broke somewhere in formatting or
sentinel handling. This is closer to a failure of task engagement — across
every configuration tried, no genuine extraction attempt on the actual
input was ever observed. §5's original validation plan (check parse
success and whether the Lanchester's-Law-style errors are fixed) could not
be executed, because there was no successful parse to evaluate against the
original errors in any run.

**Net effect on `Qwen3-14B-GGUF:Q8_0` candidacy**: this closes the
remaining open validation from §8. All three tested task shapes
(sentinel-masked translation via raw `/completion`, sentinel-masked
translation via `/v1/chat/completions`, and glossary extraction via
`/v1/chat/completions`, across two server KV-cache configurations) have
failed to produce valid, on-task output. See §8 for the resulting
resolution of "is Qwen3-14B worth pursuing further" — the practical
conclusion (not viable for this codebase as currently configured) holds
regardless of the unresolved root-cause question above.

## 6. Deferred scope (explicit, not forgotten)

- ~~`build_glossary.py`: decide how low-confidence/unconfirmed extractions
  become `mask_targets` for `translate_chunk_with_masking()`~~ —
  **resolved, see §10**: `build_mask_targets()` implemented in
  `glossary.py` as a pure function per the §9 trigger rule
  (`status != confirmed`). Still not wired into any live translation
  call site — that remains open, see §10.
- ~~Reader UI: consume `needs_review` — distinct highlight style from
  confirmed terms, click opens the term editor pre-filled~~ —
  **resolved, see the 2026-07-25 entry below**: rendering + click handler
  implemented in `alphapolis_reader.py`. Tested against synthetic
  `TranslatedLine` data only — live/end-to-end verification is blocked on
  wiring `translate_chunk_with_masking()` into `translate_lines()`'s call
  sites, a separate, later task (not this one).
- ~~Recurrence/promotion logic~~ — **split, per the same separable-things
  pattern as every prior step here**: the count-building loop half is
  **resolved, see §12**. The promotion-threshold half (§8: "how many
  appearances... or is promotion always manual?") remains genuinely open
  — not answered by §12, not attempted there. No term currently gets
  auto-promoted from `suggested` to `confirmed`; §12 only makes counts
  accurate, it doesn't act on them.

### 2026-07-25: Reader UI consumption of `needs_review` — implemented (step 1 of 3)

Step 1 of the sequence named in §10's "not something to default into"
close: reader UI for `needs_review` first, wiring second, count-building/
promotion third. Steps 2 and 3 are separate, later tasks — not started
here.

**No live data path exists yet.** `translate_chunk_with_masking()` still
has zero production callers (§10 unchanged on that point), so there is no
real `List[TranslatedLine]` this feature can be exercised against
end-to-end. Everything below was built and tested against
hand-constructed synthetic `TranslatedLine` data. Live verification
(actually seeing a needs-review span appear from a real masked-translation
run) is blocked on step 2.

**Implemented, in `alphapolis_reader.py`:**
- `build_review_term_map(translated_lines, mask_targets)` (module-level,
  pure): reconstructs which source word(s) triggered `needs_review` on
  each flagged line. Necessary because `TranslatedLine` itself carries no
  positional/source-word data — just `text` and a whole-line
  `needs_review` bool (see `splice_terms()`'s docstring) — so a click
  handler can't recover "which term" from a `TranslatedLine` alone; this
  reconstructs that association from the same `mask_targets` list passed
  to `translate_chunk_with_masking()`.
- `_render_translated_content_from_translated_lines()`: sibling to the
  existing `_render_translated_content()` (which reads
  `ep["translated_lines"]` as plain strings) — takes
  `List[TranslatedLine]` directly and applies a new `"needs_review"` Tk
  tag (amber/orange + underline, distinct in both hue and decoration from
  `"translated"`'s blue, not just a shade difference) instead of the plain
  tag when a line is flagged. Reuses the same tag-over-character-range
  mechanism as every other span, per §7's existing approach — no separate
  rendering path. Not called from `render_text()` yet (no data to feed it;
  see above).
- `_on_needs_review_click()`: left-click handler (`tag_bind`, not the
  existing right-click menu) on `needs_review` spans specifically, opening
  the **existing** `open_word_glossary_popup()` dialog — no new dialog
  built. Pre-fills `Source` with the masked term; `Target` is left blank
  (the raw source word was a splice-back fallback, not a translation
  guess — prefilling `Target` with it would misrepresent an untranslated
  placeholder as a proposed English target); `context` is the term's
  actual Japanese source sentence (from `ep["content"]`, not the rendered
  English line), matching what the existing right-click flow passes for
  `explain_term()`'s disambiguation. A line with multiple flagged terms
  opens the dialog for the first one, consistent with the existing
  right-click flow's single-word-per-click behavior.

**Bug found and fixed in pre-existing code, not just the new path.**
While building headless-Tk tests for the above, `self.text.index("end")`
was found to always report one line *past* where `.insert("end", ...)`
actually places new text (Tk's mandatory trailing newline makes `"end"`
perpetually "one ahead" of the real insertion point). This wasn't a
theoretical concern — confirmed live against the real, unmodified
`_render_content()`: **the first paragraph of every rendered episode
never resolved via `_span_at_index()`, so right-click → Add to Glossary
silently did nothing on it**, and every subsequent paragraph's tracked
span was shifted by one line versus where its tag actually landed. Fixed
by using `"end-1c"` (the actual insertion point) in all four capture
sites: the two pre-existing ones in `_render_content()`/
`_render_translated_content()`, and the two new ones in
`_render_translated_content_from_translated_lines()`, which had copied
the same (broken) pattern. Regression-tested specifically (see below) so
the fix is demonstrated on the old code path, not just assumed from the
new path working.

**Verification**: 14 tests in `tests/webnovels/test_alphapolis_reader.py`
(new file — no prior test coverage existed for this module):

- `TestBuildReviewTermMap` (7): the pure function, fully unit tested.
- `TestRenderAndClick` (4): tag application and click-to-term resolution
  against a real (headless, but not `withdraw()`'d — a withdrawn window
  never gets real geometry in this environment, which breaks
  `bbox()`/`dlineinfo()`) `tk.Text` widget, via a minimal stand-in object
  exposing only what the methods touch on `self` (not a full `ReaderApp`,
  which requires a live browser/Playwright object to construct). Bound
  methods pulled directly off `ReaderApp`, not reimplemented, so this
  tests the actual code.
- `TestRightClickRegression` (3): the pre-existing right-click flow
  specifically, proving the `end-1c` fix resolved the first-paragraph bug
  rather than just happening to not trigger it in the needs-review tests.

`black`/`isort`/`flake8` clean. `mypy`: 4 new "missing type annotation"
errors on the two new methods, consistent with the file's existing
untyped-method convention (72 such errors already present file-wide) —
not fixed here, matching how this codebase's `mypy` baseline has been
treated in prior sessions rather than introducing inconsistent typing
discipline on 2 of ~70+ methods. Full project test suite re-run: no
regressions (55 tests total in `tests/webnovels/`, up from 41 before this
task).

**Not verified**: actual visual rendering on screen (color/underline
distinguishability as a human would see it) — no interactive display
session available in this environment. Programmatically confirmed
instead: `text.tag_config()` reports `needs_review` as
`foreground="#b45309" underline=1` versus `translated`'s
`foreground="#1a56c4"` no underline, applied to the correct, distinct
line ranges — as close to verification as is possible without a real
screen, but not the same as a human confirming the two are actually easy
to tell apart at a glance.

**Not done in this pass** (steps 2/3, explicitly out of scope): no
changes to `translate_lines()` or its call sites (the reader's live
translation invocation, `alphapolis_translate.py`,
`compare_translations.py`) beyond what was needed to render/handle
`TranslatedLine` data if passed in — nothing was made to actually call
`translate_chunk_with_masking()` in production. No count-building or
promotion logic — if a needs-review term is added via the pre-filled
dialog, it lands as an ordinary `suggested`-status term via the existing
`make_suggested_term()`/dialog-save path, same as any other manual add,
nothing more. No changes to `build_mask_targets()`, `glossary.py`'s
schema, or anything in §9/§10.

### 2026-07-26: Visual/click verification of `needs_review` — closes the gap flagged above and in §11

Closes the specific, repeatedly-flagged gap from this section and §11:
`needs_review` distinguishability was previously confirmed only
programmatically (`text.tag_config()` inspection); never actually seen on
a rendered screen, never clicked through the real widget via real
mouse-event handling. This task did both, under this environment's
existing `xdotool`/virtual-display setup (`DISPLAY=:0`, confirmed live and
usable — `xdotool getdisplaygeometry` → `1920x1080`, a real Tk window
gets real, non-1×1 geometry once mapped).

**⚠️ Provenance, stated plainly so it can't be conflated with §11's
result on a later skim**: the data rendered and clicked here is
**reconstructed input run through real production code — not a replay of
§11's actual live LLM call.** §11's exact original model-output text for
this chunk was never saved to disk (only summarized: "1 of 3 sentinels
dropped, line 6"), and re-running a fresh live translation was explicitly
out of scope for this task (the point was isolating "does the UI
correctly handle already-proven data" from "does the translation
pipeline work" — collapsing them back together would defeat that). So:
the Japanese source lines are the real, unmodified lines from
`178ca2c7...eead.json` (lines 29-36, same chunk §4/§11 used); the English
wording of the 7 clean lines is hand-written prose, not the model's
actual output; but the `needs_review=True` line 6 was produced by
running that hand-written response through the **real, unmodified**
`mask_terms()`/`build_mask_targets()`/`splice_terms()` functions with the
sentinel deliberately omitted on line 6 only — genuinely exercising the
real missing-sentinel fallback code path, not a hardcoded flag. What's
verified here is "does the real rendering/click code handle a real
`needs_review=True` `TranslatedLine` correctly" — not "does translategemma
reproduce this specific failure again."

**Setup**: a synthetic novel (`novel_id=999999999`, a numeric ID that
satisfies `NOVEL_ID_RE` but won't collide with any real Alphapolis
novel), a matching `suggested`-status glossary
(`タチバナさん`/`橘` → `make_suggested_term()`, matching §11's real
glossary shape), and a pre-populated on-disk cache entry (correct
`_cache_schema_version: 4`, `translated_lines` + `needs_review_flags`
pair, matching §11's real storage shape) written directly via
`save_glossary()`/the same JSON shape `save_cached_episode()` produces.
The real app (`python alphapolis_reader.py <url>`, unmodified — not a
stand-in object, not a headless-without-display run) was launched
pointed at that URL; `fetch_and_translate()`'s existing cache-hit check
(`if cached is not None: return cached`) short-circuits before any
browser/network access, so `BrowserWorker`'s real Playwright/Chromium
launch happens (matching real app startup) but is never actually used
for a fetch on this run.

**Visual result — plain judgment, not just "the tag exists"**: **yes,
clearly and unambiguously visually distinguishable at a glance.**
Screenshot of the rendered episode (before any interaction) shows line 6
in a distinct amber/orange color with an underline, standing out
immediately against the surrounding lines' blue, non-underlined
`translated` styling — this was not a subtle or borderline call.

**Click-through result**: `xdotool` clicked the needs-review span at its
real on-screen pixel coordinates (window-relative `mousemove`/`click`
through the real widget — not `tag_bind()` invoked synthetically, not
`_on_needs_review_click()` called directly in Python). The real
Add-to-Glossary dialog opened (after its existing background
translation-guess lookup completed) with **`Source (original)` =
"タチバナさん"** — an exact match to §11's already-proven
`_on_needs_review_click()` result
(`("タチバナさん", "", "「なに言ってんすか。...")`). `Target
(translation)` correctly blank (per the existing fallback-not-a-guess
design decided in §6's original entry), `Type` correctly defaulted to
`Character`. The `context` parameter (the real Japanese source sentence)
isn't a visible dialog field, but the populated "Meaning"/"Alternatives"
reference sections (a real `explain_term()` LLM call using that context)
confirm it was passed through and produced coherent output, consistent
with the correct sentence having been used.

**Unexpected, worth recording for future UI verification, not just this
one:**

- A completely fresh single-process launch reliably produces **two**
  window IDs matching `xdotool search --name "Alphapolis Reader"`. Root
  cause identified, not left as a mystery: one ID (`getwindowpid` →
  `mutter-x11-frame`) is the Mutter window manager's decoration/frame
  window, not a second app instance — the real client window is the
  other ID. `xwininfo`/`xdotool getwindowpid` cross-checked to tell them
  apart; screenshotting both confirmed only one behavioral difference (a
  frame vs. content), not divergent app state.
- `xdotool mousemove <absolute-x> <absolute-y>` followed by
  `getmouselocation` repeatedly reported a fixed, unrelated position on
  first attempts. Root cause: **this is a real, shared display, not an
  isolated headless one** — the user's own actual mouse/keyboard activity
  (switching focus to answer clarifying questions during this task) was
  contending for the same pointer. Resolved by chaining
  `windowactivate --sync` immediately before `mousemove --window
  <id> ... click` in a single `xdotool` invocation, rather than issuing
  focus and click as separate commands with a gap between them where
  focus could be stolen back.
- A first attempt to construct the synthetic episode dict was missing
  `prev_url`/`next_url` keys, surfacing a real (if trivial) `KeyError` in
  `display_episode()` — not a bug in the app, a gap in the reconstructed
  test fixture; fixed by adding both keys (`None` is a valid, handled
  value; confirmed via `parse_episode()`'s real output shape before
  patching).

**No changes made to `needs_review` styling, the click handler, or any
rendering logic** — nothing this verification surfaced rose to "genuinely
broken," only fixture-construction gaps in the test setup itself, so
§6/§11's original implementation stands unmodified.

## 7. Web migration plan

**Current state**: Tkinter desktop app (`alphapolis_reader.py`). Paragraph-
level tags exist (`original`, `translated`, and now `needs_review` as of
2026-07-25 — see §6) — all Tk text-widget tags over character ranges, so
the tag-based rendering approach ported cleanly to a new visual state
(needs-review) without inventing a separate mechanism, some evidence this
generalizes. **Correction to an earlier version of this doc**: "confirmed-
term highlighting" was previously described here as existing already — it
does not. There is no per-term (as opposed to per-paragraph) span tagging
in the Tkinter app at all; `original`/`translated`/`needs_review` each tag
a whole rendered paragraph, not individual glossary terms within it. A
confirmed-term highlight (bold/colored individual words, per §2's
reference UX) has not been built in Tkinter, in this task or any prior
one. Phase 2 below still describes it as something to build in the web
version — that's accurate; it was never a "port," since there's nothing
to port for that specific piece.

**Target**: reachable on home network, not just localhost — this means the
backend holds Alphapolis/Novelfire session cookies and must not be treated
as trusted-network-only. Shared-secret middleware from phase 1, not a later
hardening pass.

**Phases** (sequenced so each is independently useful/testable):

1. **Backend API skeleton** — FastAPI wrapping existing modules
   (scraping, `llm_translate`, `glossary`) as JSON endpoints. Shared-secret
   auth middleware included here. No UI yet.
2. **Read-only reader page** — translated chapter + prev/next nav +
   confirmed-term highlighting only.
3. **Term interaction** — click-to-add via a `find_ja_word_at()` endpoint,
   right-click Add-to-Glossary, editor modal (parity with current Tkinter
   dialog).
4. **Review-queue UI** — candidate picker, confirmed vs. suggested
   styling, consumes `needs_review` from masking output. Revised as of
   2026-07-25 with an itemized split (grep-verified against the current
   `alphapolis_reader.py`, not assumed) of what step 1 (§6) delivered vs.
   what's still missing, since "partially exists" on its own isn't
   actionable for whoever picks this phase up later:
   - **Now exists in Tkinter, portable as "port the working pattern"**:
     `needs_review` line-level highlighting (a distinct Tk tag, amber +
     underline) and a click handler that opens the term-add dialog
     pre-filled with the flagged term. Both are `needs_review`-only —
     neither implements any part of "confirmed vs. suggested styling."
   - **Still doesn't exist anywhere, remains build-new-here**: (a)
     confirmed-term highlighting itself — grep-confirmed zero per-term
     span tagging anywhere in `alphapolis_reader.py`; the file's only
     rendering tags are the paragraph-level `heading`/`original`/
     `translated`/`needs_review`, none of which single out an individual
     glossary term within a line. (b) Any "suggested" visual styling
     distinct from confirmed. (c) The candidate picker itself (ranked
     `candidates` list, count badges per §2/§3's reference UX). (d) Any
     promotion UI (`suggested` → `confirmed`).
   Also still true regardless of the above split: the Tkinter needs-review
   feature has never been exercised against live data (§6's caveat) — the
   web version's parity target is therefore "the tested behavior"
   (synthetic-data-verified tag/click logic), not "field-proven behavior,"
   until step 2's wiring lands and gets used for real.
5. **Config/styling panel** — CSS custom properties in place of the
   Tkinter theme system.

## 8. Open questions

- Promotion threshold: how many appearances/confirmations before a
  `suggested` candidate can auto-promote to `confirmed`, if ever — or is
  promotion always manual?
- ~~`build_glossary.py`'s `mask_targets` producer: what specifically
  triggers masking a term for a given chunk~~ — **resolved, see §9**:
  v1 rule is `status != confirmed`. The producer itself (wiring this rule
  into `build_glossary.py`) is still unbuilt — only the trigger rule is
  decided.
- ~~Qwen3-14B validation for extraction~~ — **resolved, see §5's
  2026-07-25 finding**: run, and it failed to produce valid extraction
  output across every configuration tested (two server KV-cache configs).
  Note: an earlier version of this finding described the failure as
  input-independent hallucination of fixed content; that specific claim
  was retracted after further isolation showed the garbage content changes
  between configurations. Root cause remains unresolved — see §5 for the
  full correction. `explain_term()` specifically remains untested
  (different call shape, single-item lookup rather than whole-episode
  extraction) — technically still open, but given the extraction finding,
  not a priority to chase separately.
- ~~Is Qwen3-14B-GGUF:Q8_0 worth pursuing further at all~~ — **closed: no.**
  Two independent task shapes (sentinel-masked translation, glossary
  extraction), three independent failure modes, across multiple server
  configurations including `--jinja` + the highest-quality quant tried
  (Q8_0). This is not "still deciding whether to chase it further" — it's
  a completed answer: this model/quant is not the direction for this
  codebase. Reopen only if a specific new reason arises (a different
  quant, `-np 1` isolation in service of an upstream bug report, or
  Qwen3.6) — not as a default "revisit later" item. Whether the underlying
  mechanism is cache-sharing contamination (`--kv-unified`), a
  repetition-loop tendency specific to this quant, or something else was
  not conclusively
  determined (§5) — but the practical answer doesn't depend on which:
  deprioritizing "separate model for extraction" via this quant either way.
  `translategemma`-based extraction reliability (or a different
  model/quant entirely, tried fresh rather than patched) are the remaining
  paths if a second model is still wanted for this role.

## 9. Term data model migration — scope (2026-07-25)

Grep-confirmed the target shape from §3 (`status`, `candidates`,
`confirmed_target`) does not exist in `glossary.py` yet — it's still the
flat `{source, target, type, note}` shape from before this whole redesign
started. Everything downstream (`mask_targets`, confirmed-only prompt
injection) is blocked on this not existing. This is the load-bearing next
step.

**Scoped narrowly on purpose** — §3 bundles three separable things
(schema, count-building loop, promotion/gate logic). Only the first is in
scope for this pass; the other two are tracked separately (see below) so
an unvalidated gate policy doesn't ship bundled with the schema it depends
on, same mistake class avoided earlier with the masking work.

**In scope:**
- New schema only: `status` (`"confirmed"` / `"suggested"`), `candidates`
  (list of `{target, count, origin}`), `confirmed_target`. Replaces the
  flat `target` field.
- `format_glossary_for_prompt()` filters to `status == "confirmed"` only.
- `merge_terms()` updated to write new extractions as `status: "suggested"`
  with a single candidate at count 1, `origin: "llm"`.

**Explicitly out of scope (do not implement in this pass):**
- Count-building loop (scanning translated output to increment candidate
  counts) — separate item.
- Promotion/gate logic (what moves `suggested` → `confirmed`, recurrence
  thresholds, filtering out one-off/mundane extractions) — separate item,
  can't be designed sanely until real `suggested`-tagged data exists to
  look at.
- `build_glossary.py`'s `mask_targets` producer itself — the *rule* is
  decided (below), the producer is not built here.

**No backward compatibility / no migration path.** This is pre-production;
there is no existing glossary data worth preserving. Clean schema cutover
— delete/regenerate existing glossary files under the new shape. No
`.setdefault()`-style dual-read shim (contrast with the existing
`honorific_policy` precedent in `glossary.py`, which doesn't apply here
since that was a real-data migration and this isn't).

**`mask_targets` trigger rule, decided now so it doesn't re-open as a
question once the schema unblocks it**: mask any term where
`status != "confirmed"`. Simple default; not yet implemented (producer is
still future work), just no longer an open question.

**Status as of 2026-07-25: implemented.** `glossary.py` now defines
`STATUS_CONFIRMED`/`STATUS_SUGGESTED`, `ORIGIN_USER`/`ORIGIN_LLM`/`ORIGIN_MT`,
and two constructors — `make_confirmed_term()` (manual entry, trusted
immediately) and `make_suggested_term()` (LLM extraction, lands in the
review queue) — rather than callers hand-building term dicts. `note` was
kept as a top-level field on both constructors and its `format_glossary_for_prompt()`
rendering path for `TERM_TYPE_GENERAL` entries was left intact — flagged
mid-task as an easy thing to silently drop since the target shape sketched
in §3 didn't explicitly carry it forward; corrected before implementation,
not after. Covered by a regression test
(`test_confirmed_general_term_note_still_rendered`).

`format_glossary_for_prompt()` now filters to `status == STATUS_CONFIRMED`
and reads `confirmed_target` instead of the old flat `target` field.
`merge_terms()` is now status-agnostic (dedupes/appends whatever it's
given) rather than assuming everything incoming is an LLM suggestion —
necessary because it has two real call sites with different trust levels:
`build_glossary.py`'s extraction (via a new `_to_suggested_term_dicts()`
converter, wrapping raw LLM output with `make_suggested_term()`, preserving
character-only fields) and the reader's manual "Add to Glossary" popup
(via `make_confirmed_term()` directly).

**Deviation from the original scope note**: "term-editor read/write paths"
turned out to include a design call not spelled out above — the glossary
dialog's inline Save (editing an existing term's Target field and hitting
Save) now also writes `status: STATUS_CONFIRMED`, on the reasoning that a
human deliberately editing a term in this dialog is the same trust level as
"Highlight → Add Term," not a passive re-save of whatever status the term
already had. Not testable via the schema-only unit tests (it's Tkinter
UI code with no test harness in this pass) — flagging as a judgment call
made during implementation rather than a pre-agreed decision.

**No backward-compat/migration code was written**, per scope — existing
on-disk glossary files under the old flat shape will simply be read as
having no `status`/`candidates`/`confirmed_target` keys; nothing in this
pass adds a `.setdefault()` shim to paper over that, so `format_glossary_for_prompt()`
will (correctly, if bluntly) treat old-shape terms as un-confirmed and
exclude them until the file is regenerated or hand-edited.

**Verification**: 17 new tests in `tests/webnovels/test_glossary.py`
(schema shape, confirmed-only prompt filtering, note preservation,
merge/dedup/conflict behavior) — all passing. Live end-to-end check against
`build_glossary.py`'s actual extraction-output shape (not just synthetic
dicts) confirmed `_to_suggested_term_dicts()` → `merge_terms()` →
`format_glossary_for_prompt()` correctly keeps a fresh extraction out of
the translation prompt. `black`/`isort`/`flake8`/`mypy` clean on
`glossary.py` and `build_glossary.py`; `alphapolis_reader.py`'s edits
introduced zero new `mypy` errors against its pre-existing (unrelated,
310-error) baseline. Full project test suite run for regressions: no
failures introduced by this change (5 pre-existing, unrelated
`test_ansible_structure_analyzer.py` failures and 1 pre-existing,
unrelated `tests/k8s/test_validate_k8s_token.py` collection error both
predate this work, confirmed via `git stash`).

**Not done in this pass** (see explicitly-out-of-scope list above,
unchanged): count-building loop, promotion/gate logic, and the
`build_glossary.py` `mask_targets` producer itself remain future work.

## 10. `mask_targets` producer — implemented (2026-07-25)

Scoped narrowly, same pattern as §4/§9: build the decision function only,
leave production wiring for a separate, deliberate pass. Rejected the
alternative (producer + wiring `translate_lines()`'s call sites to consume
`TranslatedLine`/`needs_review`) specifically because that would ship
`needs_review` flowing through the pipeline with nothing to consume it —
§6's reader-UI item is still undone, so there's no sink for it yet, and
wiring ahead of that sink makes correctness hard to observe (nothing to
check the flag against).

**Implemented**: `build_mask_targets(lines, glossary)` in `glossary.py` —
pure function, `List[str]` + glossary dict in, `List[Tuple[int, str]]` out,
matching `translate_chunk_with_masking()`'s `mask_targets` parameter shape
exactly (no adapter needed). Applies the §9 trigger rule directly:
`status != "confirmed"`.

Handles real edge cases surfaced during implementation, not just the
straightforward case: multiple occurrences of the same term within one
line, the same term recurring across multiple lines, and overlapping
substring terms (e.g. one glossary term that's a substring of another,
like `音夢` inside `音夢くん`) — longer match wins, and results are
returned in actual line-position order (not term-registration order) so
`mask_terms()`'s sequential single-count `replace()` calls don't collide
or corrupt each other.

**Verification**: 10 new tests in `tests/webnovels/test_glossary.py`
(`TestBuildMaskTargets` — pure-function, synthetic inputs covering
confirmed-exclusion, multi-occurrence, cross-line recurrence, overlap
resolution, and a direct shape-contract check against
`translate_chunk_with_masking()`'s expected input). Beyond the unit tests,
the full `build_mask_targets()` → `translate_chunk_with_masking()` pipeline
was run live against translategemma twice: once reproducing the 5-sentinel
stress case from §4's test suite (now driven by real glossary term status
instead of a hand-picked target list), and once against real, unselected
cached episode text from the "provocation" episode (the same source used
in the §5 Qwen3 extraction validation) — correctly excluding a `confirmed`
term while masking two `suggested` terms found at their true positions in
the episode text. `black`/`isort`/`flake8`/`mypy` clean; full project test
suite re-run with no regressions (27 tests total in `tests/webnovels/`, up
from 17 after §9).

**Explicitly not done, same as scoped**: no changes to `translate_lines()`
or any of its call sites (reader, `alphapolis_translate.py`,
`compare_translations.py`). `translate_chunk_with_masking()` remains
uncalled in production — same status as it's had since §4, not a
regression, just not yet wired. When that wiring does happen, it needs a
deliberate decision on sequencing relative to §6's reader-UI item (wire
translation first and surface `needs_review` later, vs. build the reader
UI first so the wiring has somewhere real to show up immediately) — not
something to default into.

## 11. Wiring `translate_chunk_with_masking()` into production — implemented (2026-07-25, step 2 of 3)

Step 2 of the sequence named in §10/§6: reader UI first (§6, done), wiring
second (this), count-building/promotion third (not started). `mask_targets`
production, `mask_terms()`/`splice_terms()`, and the glossary schema were
not touched — called, not modified.

**Call sites, checked individually rather than assumed identical:**

- **`alphapolis_reader.py`'s `fetch_and_translate()`** — the real one that
  matters, wired. This is where the glossary is already loaded (for
  `glossary_text`) before this task, so the glossary dict was already
  in-hand; `build_mask_targets(ep["lines"], glossary)` is called
  immediately after, and `translate_lines_with_masking()` is used instead
  of `translate_lines()` only for the LLM backend and only when
  `mask_targets` is non-empty (Google Translate has no sentinel-survival
  mechanism at all — masking it would just corrupt its output, not review-
  flag anything). The title/episode_title translation (a separate,
  2-line `translate_lines()` call) was deliberately left unmasked — rare
  for a title to contain an unconfirmed glossary term, and there's no
  natural place in the UI to review-flag a title.
- **`alphapolis_translate.py`** (standalone CLI, prints translated text and
  exits) and **`compare_translations.py`** (Google-vs-LLM quality
  comparison, writes structured comparison JSON) — **left unmasked,
  deliberately, not by oversight.** Neither has any place for a
  `needs_review` signal to go: `alphapolis_translate.py` has no UI beyond
  stdout, and `compare_translations.py`'s entire purpose is measuring the
  LLM's *own* translation quality — masking would change what's being
  measured, not just how it's displayed. Neither writes to the reader's
  on-disk cache (`grep`-confirmed: no `save_cached_episode`/
  `CACHE_SCHEMA_VERSION` reference in either file), so the cache-shape
  change below doesn't affect them either.
- **`llm_translate.py`**: `translate_lines()` itself is **unchanged** —
  new sibling function `translate_lines_with_masking()` added instead,
  same pattern as `translate_chunk_with_masking()` being a sibling of
  `translate_chunk()` (§4) rather than a parameter on it. A conditional-
  return-type function (`List[str]` vs `List[TranslatedLine]` depending on
  an argument) was considered and rejected as a worse shape than two
  functions with one job each.

**The re-indexing detail that would have been a silent bug**:
`translate_lines_with_masking()` chunks its input internally (same size-
based packing as `translate_lines()`), but `mask_targets` is expressed in
line indices relative to the *whole* input, not per-chunk.
`translate_chunk_with_masking()` expects chunk-relative indices. Missing
this would either mask the wrong line in a later chunk, or raise inside
`mask_terms()` ("word not found in line") whenever a masked term fell past
the first chunk. Fixed by tracking each chunk's starting offset during
packing and re-indexing (`line_idx - chunk_offset`) before calling
`translate_chunk_with_masking()` per chunk — covered by
`test_mask_targets_reindexed_correctly_across_chunk_boundary`, which
specifically forces a chunk split so a masked term lands in the second
chunk.

**Cache storage shape — the actual design decision, not mechanical
plumbing:**

`episode["translated_lines"]` is read as plain `List[str]` in three places
outside the reader's own rendering (grep-confirmed before deciding, not
assumed): `build_glossary.py`'s extraction (`"\n\n".join(translated_lines)`),
`test_qwen3_extraction_validation.py`, and the reader's own pre-existing
`_render_translated_content()`. Storing `TranslatedLine` objects/dicts
there directly would break all of them. Two options considered:

1. **Keep `translated_lines` as plain strings; don't persist `needs_review`
   at all — recompute via `build_mask_targets()` against the current
   glossary on every render.** Simpler, no cache shape change. Rejected:
   this conflates two different questions under one flag name.
   `needs_review` as originally defined (§4) records a fact about a
   specific translation attempt — the model dropped a sentinel, or a line
   came back empty and got retried, *on that run*. Recomputing instead
   answers "does this term look unconfirmed *right now*, per current
   glossary state" — a different, live signal. Those diverge the moment a
   term gets manually confirmed after an episode was cached: the original
   translation-time failure (the surrounding sentence may still read
   awkwardly around a spliced-in raw word) becomes invisible, silently
   replaced by "nothing to flag" once the glossary catches up. A line
   where the term spliced back in cleanly and a line where it failed and
   was recovered would become indistinguishable on reload under this
   option — both just contain the raw word in English-adjacent context.
2. **Keep `translated_lines` as plain strings (unchanged, so the three
   external readers above are untouched); add a new parallel
   `episode["needs_review_flags"]: List[bool]`, same length/order.**
   Preserves the actual fact per line across reloads. Chosen.

**Implemented**: option 2. `CACHE_SCHEMA_VERSION` bumped 3 → 4 (the
existing, purpose-built mechanism for exactly this — `load_cached_episode()`
already returns `None` on a version mismatch, causing a refetch/
retranslate). **No migration/dual-read shim written**, per the established
§9/§10 precedent — old-shape cache files are simply treated as uncached,
not read-and-upgraded. `fetch_and_translate()` now stores
`ep["needs_review_flags"] = [t.needs_review for t in translated]`
alongside `ep["translated_lines"] = [t.text for t in translated]`
(or an all-`False` list when masking didn't apply, e.g. Google backend or
no unconfirmed terms present) — same length, same order, always both
present together going forward.

**Reader rendering wired**: `render_text()` now calls a new
`_render_translated_view(ep, tag)` (replacing the direct
`_render_translated_content(ep, "translated")` call) that reconstructs
`TranslatedLine` objects from the cached `(translated_lines,
needs_review_flags)` pair and dispatches to
`_render_translated_content_from_translated_lines()` (built, unused, in
§6) when that data is present and length-consistent, falling back to the
original plain-string `_render_translated_content()` otherwise (an episode
cached before this change, or the Google backend, or any length mismatch
— defensive, not just the happy path). `mask_targets` for the needs-review
click-to-add pre-fill is recomputed fresh via `build_mask_targets()` at
render time against the *current* glossary — safe to recompute here
specifically, unlike `needs_review_flags` above, since `mask_targets` in
this context is only used to resolve "which word" for the dialog, not as a
record of translation-time truth.

**Live end-to-end verification — the actual point of this task, run
against the real translategemma server, not synthetic fixtures:**

- Real episode text (`c574a6...eead.json`, lines 1-5, containing 鉄パイプ
  twice) with a real `suggested`-status glossary term for 鉄パイプ, through
  the actual `translate_lines_with_masking()` production function: both
  occurrences spliced back correctly, `needs_review=False` throughout.
- A denser real chunk (same episode, lines 24-31, containing 音夢くん x3,
  桂名, 仁菜) with 3 real `suggested` terms: all 4 mask targets spliced
  cleanly on this run.
- **The case that actually exercised `needs_review=True` live**: the
  `タチバナさん`/`橘` chunk (`178ca2c7...eead.json`, lines 29-36 — the
  same real chunk used in §4's original real-content verification) with
  both name variants as `suggested` terms. First run: 1 of 3 sentinels
  dropped (`タチバナさん` on line 6), correctly caught, flagged
  `needs_review=True`. A second run against the same chunk hit a
  *different* real failure — a JSON escaping error on the second chunk
  (`Invalid \escape`, the model emitting a literal backslash) — which
  triggered the existing empty-line retry-then-fallback path and produced
  2 flagged lines instead of 1. Confirms the two-tier fallback (§4) is
  still live and firing correctly through the new wiring, not just in
  isolation.
- **Rendered through the actual Tk code**, not just inspected as data: the
  real `TranslatedLine` results from the `タチバナさん` run were fed into
  `_render_translated_content_from_translated_lines()` — the `needs_review`
  tag applied to exactly the flagged lines, `translated` to the rest, and
  a simulated click on the flagged span resolved via
  `_on_needs_review_click()` to the correct source term
  (`("タチバナさん", "", "「なに言ってんすか。...")`) — the full
  click-to-dialog-prefill path working end-to-end on real data.
- **Full cache round-trip verified**: the real `TranslatedLine` results
  were shaped into the actual `fetch_and_translate()` storage format
  (`translated_lines` + `needs_review_flags`), serialized through
  `json.dumps`/`json.loads` (simulating the real
  `save_json_config`/`load_json_config` disk round-trip), then rendered
  via the real `_render_translated_view()` dispatch — `needs_review_flags`
  survived serialization intact, and the reconstructed `TranslatedLine`
  objects produced the identical correct tag placement as the pre-cache
  version.

**Not anticipated going in, found during this task:**

- The chunk-relative re-indexing requirement (above) — the original task
  brief didn't call this out specifically; it was implicit in
  "`mask_targets` is chunk-agnostic, chunking is internal," and would have
  been a real, silent correctness bug (wrong line masked, or a raise) if
  missed.
- The `alphapolis_translate.py`/`compare_translations.py` "leave unmasked"
  decision required actually reading both files' output-consumption code
  to confirm neither has anywhere for `needs_review` to surface, rather
  than assuming symmetry with the reader.
- A second, distinct real failure mode surfaced during live verification
  (the JSON `\escape` parse error) beyond the missing-sentinel case the
  fallback was originally designed around — not a new bug, since
  `parse_json_response()`/the retry path already handles it as "chunk
  failed, retry," but worth noting as evidence the two-tier fallback (§4)
  covers more real failure shapes than the ones it was named after.

**Verification summary**: 10 new tests (5 in new
`tests/webnovels/test_llm_translate.py` for
`translate_lines_with_masking()`'s chunking/re-indexing/failure-handling,
mocked HTTP — deterministic, no live server needed for these; 5 in
`test_alphapolis_reader.py`'s new `TestRenderTranslatedView` for the
cache-shape reconstruction/dispatch logic). Plus the live end-to-end runs
above, which are not automated tests (would require a live llama-server in
CI) but are the actual bar this task set out to clear. `black`/`isort`/
`flake8` clean on both modified files; `mypy` clean on `llm_translate.py`
(unchanged from before); `alphapolis_reader.py` at 317 errors (up from
314), all the same pre-existing "missing type annotation" class on the 3
new/modified methods, consistent with the file's untyped-method
convention — not fixed here, same treatment as prior sessions. Full
project test suite re-run: no regressions (50 tests total in
`tests/webnovels/`, up from 41 before this task).

**Not done in this pass** (step 3, explicitly out of scope): no count-
building or promotion logic. A `needs_review` term added via the
pre-filled dialog still lands as an ordinary `suggested`-status term via
the existing `make_suggested_term()`/dialog-save path — nothing more.

## 12. Count-building loop — implemented (2026-07-25)

The count-building half of §6's "Recurrence/promotion logic" bullet, split
out from the promotion-threshold half the same way every prior step here
has split a mechanical piece from a policy decision (§4's format-vs-
fallback, §9's schema-vs-promotion, §10's producer-vs-wiring). §8's
promotion-threshold question ("how many appearances... or is promotion
always manual?") is **not answered here** — this task makes counts
accurate; it doesn't act on them. No auto-promotion behavior was written,
even a minimal default — if a threshold check had started getting written,
that would have been a scope violation, and none was.

**Checked current state before assuming §11's live-verification terms were
still around**: they weren't. §11's runs used `suggested`-status terms
(masking only applies to those), so none of `鉄パイプ`/`音夢くん`/`桂名`/
`仁菜`/`タチバナさん`/`橘` ever went through `save_glossary()`. The one
real glossary file that exists on disk
(`~/.config/alphapolis_reader/glossaries/375266002.json`) is still the
original pre-§9 flat `{source, target, type, note}` shape from §1 —
`format_glossary_for_prompt()` correctly treats every term in it as
un-confirmed (no `status` key at all), so it has zero terms this loop
could act on as-is. Live verification below therefore constructs a
minimal but real confirmed-status glossary in memory rather than reusing
that file, since a term with no `status` field can't exercise a function
that specifically requires `status == STATUS_CONFIRMED`.

**Implemented**: `update_candidate_counts(source_lines, translated_lines,
glossary, needs_review_flags=None)` in `glossary.py`. For each
`STATUS_CONFIRMED` term whose `source` string appears anywhere in
`source_lines`, checks whether the corresponding `translated_lines` entry
(same index) contains that term's `confirmed_target` string as a
substring, and if so increments that specific candidate's `count` by 1 —
once per chunk per term, not once per occurrence (a term appearing twice
in one chunk still only gets a single increment, matching "which
candidate won for this translation call" rather than a raw occurrence
tally). Returns a new glossary dict — top-level dict and the `terms` list
are copied, individual term dicts that had a count change are replaced
with new dicts; unmodified term dicts are shared by reference — matching
`merge_terms()`'s existing shallow-copy convention rather than inventing a
new one.

**The three things deliberately excluded, named as real open items rather
than silently done or silently dropped:**

- **`STATUS_SUGGESTED` terms are never counted here.** A masked/suggested
  term's translated line contains the raw source word (`splice_terms()`'s
  fallback), not a model-generated translation — there is no translated
  candidate string to substring-match for those; the mechanism this
  function implements structurally doesn't apply. **Open item**: recurrence
  tracking for suggested terms (how often the term itself appears across
  chunks, independent of any candidate translation) is a real, different
  signal that could inform a future promotion policy — not attempted here.
  Deliberately not folded into this same function: doing so would have
  meant `count` meaning two different things depending on a term's status
  (occurrences-of-term vs. occurrences-of-winning-candidate), the exact
  flag-means-two-things mistake §11 caught and corrected for `needs_review`
  before it shipped. Better to leave a clean gap than repeat that.
- **Discovering a new candidate not already in a term's `candidates` list
  is out of scope.** Only pre-existing candidate strings are matched
  against; if the model produces some other phrasing entirely, nothing
  happens (silently, by design — not a bug). **Open item**: this is a real
  alignment problem (attributing an arbitrary span of translated text to a
  specific source term, with no positional/masking anchor to work from,
  since confirmed terms aren't masked) and deserves its own design pass,
  not a heuristic bolted on here.
- **`needs_review=True` lines are excluded from matching.** That
  translation attempt failed and was recovered via the missing-sentinel/
  empty-line fallback — not evidence the model successfully produced (or
  chose not to produce) any candidate translation, so it must not
  contribute to a count that exists to measure exactly that. Only matters
  in practice when a chunk mixes a masked (suggested) term's fallback-
  triggered line with an unrelated confirmed term's line in the same
  translate call; guarded via an optional `needs_review_flags` parameter
  so callers that only ever pass unmasked content (there are none yet
  besides the reader) aren't forced to thread a meaningless all-`False`
  list through.

**Wiring**: `fetch_and_translate()` calls `update_candidate_counts()`
immediately after `ep["translated_lines"]`/`ep["needs_review_flags"]` are
set, then persists via the existing `save_glossary()` path — same
integration point step 2 (§11) used. Guarded by the same precedent step 2
established for `needs_review_flags`, not decided fresh: only runs when
`glossary is not None` (i.e. LLM backend and `novel_id` resolved).
Google-backend translations never consult a glossary at all, so there's
nothing to count against and nothing new to persist.

**Verification**: 10 new tests in `tests/webnovels/test_glossary.py`
(`TestUpdateCandidateCounts` — confirmed-match increments, suggested terms
untouched, `needs_review=True` exclusion, no-match-leaves-unchanged,
target-not-found-leaves-unchanged, only-the-matching-candidate-increments
[a second, non-matching candidate on the same term stays untouched],
once-per-chunk-not-per-occurrence, unrelated-terms-untouched, original-
glossary-not-mutated, empty-input handling).

Live end-to-end verification against the real translategemma server (not
just synthetic fixtures), using the same real episode chunk as §11's
`鉄パイプ` example (`c574a6...eead.json`, lines 1-5) with a real, freshly-
constructed `confirmed`-status term for `鉄パイプ` → `"iron pipe"`:

- In-memory run: count `1` → `2` after one real translation call (the
  model produced "...crushed their hands along with the iron pipes." and
  "...docking with the iron pipes..." — both real occurrences in the
  chunk collapsed to the single expected increment, confirmed against the
  actual model output text, not assumed).
- **Full persisted-file verification**, the part synthetic tests can't
  cover: `save_glossary()` → `load_glossary()` → real translation →
  `update_candidate_counts()` → `save_glossary()` → `load_glossary()`,
  reading the actual on-disk JSON file at each step. Confirmed
  `"count": 2` in the literal file content on disk, not just the returned
  dict in memory.
- The test glossary file (`novel_id` `live_count_test`) was written to
  the real `~/.config/alphapolis_reader/glossaries/` directory as a
  necessary side effect of testing the real `save_glossary()` path (not
  a temp directory) — flagged to the user for cleanup rather than
  deleted unilaterally, since file deletion outside the repo wasn't
  pre-authorized for this task and the sandbox's own permission layer
  declined the delete when attempted.

`black`/`isort`/`flake8` clean on `glossary.py` and `alphapolis_reader.py`.
`mypy` clean on `glossary.py` (unchanged). `alphapolis_reader.py` mypy
error count unchanged from §11 (317) — the `fetch_and_translate()` edit
added no new errors since that method was already untyped. Full project
test suite re-run: no regressions (60 tests total in `tests/webnovels/`,
up from 50 after §11).

### 2026-07-26: `needs_review` scope gap found and fixed on genuine live content — first real production confirmation of masking

**Found via real, non-synthetic reading, not a test run.** A screenshot of
Translated mode against a genuinely-read episode
(`.../375266002/37695490/episode/7799961`) showed several terms (`オレ`,
`ハードキャッチ`, `鉄パイプ`, `ダンジョン能力者`, `ヤンチャボーイズ`) rendering as raw
Japanese fragments spliced into otherwise-English lines, with **no**
amber/underline `needs_review` styling — plain blue `translated` text
throughout. Two explanations were possible before investigating: a real
rendering bug in Translated mode specifically, or an ordinary translation-
quality artifact unrelated to masking. Diagnosed from the actual data
before assuming either way, per this doc's own standing discipline.

**Confirmed this is masking working correctly, twice over, independently.**
Pulled the real cache file for the episode and the real on-disk glossary
for novel `375266002`: schema version confirmed current (`v4`, ruling out
a stale-cache explanation), `needs_review_flags` present and length-
correct, and all 6 terms in question present in the glossary with
`status: None` — i.e. genuinely unconfirmed, genuinely correct
`build_mask_targets()` mask targets (§9's `status != STATUS_CONFIRMED`
rule). Separately, the user surfaced a real run's own log
(`app_log_20260726_152648.log`, a different episode of the same novel,
`.../episode/7799899`) showing `splice_terms()`'s own warning messages
firing live for the same handful of terms — the mechanism caught directly
in the act on genuine reading, not reconstructed after the fact. **This is
the first confirmation in this project's history that masking/needs_review
works end-to-end against real, non-synthetic content** — every prior
verification (this doc's own §10/§11 entries, `RETRANSLATION_DESIGN.md`'s
phases) used synthetic fixtures or scoped live tests, not organic reading.

**The same log also confirmed a second mechanism working correctly, found
incidentally while reading it for the above**: one real JSON-parse failure
(`Chunk 8/9: failed to parse JSON response (Invalid control character...)`)
— the exact "unescaped control character" failure class §4/§5 document
extensively for this model — was immediately followed by
`translate_chunk()`'s documented per-line-retry fallback firing
(`Chunk 8/9: retrying as 10 individual line(s)...`), and every one of the
10 lines recovered successfully (no `"translation failed"` placeholder
anywhere in the log; `Translation complete: 63 lines` logged clean right
after). Not a bug — the existing graceful-degradation path working
exactly as designed on a real live failure, not just its originally-
documented synthetic case.

**But the styling absence was real — a genuine scope gap, not a false
alarm, found by tracing it rather than assuming a rendering bug.** Cross-
checked the specific flagged line: `needs_review_flags[1] == False` for
`"Due to オレ's ハードキャッチ, the two were crushed."`, despite visibly
containing raw spliced Japanese. Root cause, in `splice_terms()`
(`llm_translate.py`): the function has always had two recovery paths for
a masked sentinel — sentinel found (spliced back cleanly) vs. sentinel
missing (raw word substituted as fallback) — but only set
`needs_review=True` on the missing-sentinel path. The clean-splice path
was originally treated as a non-issue (§9/§10: "spliced back cleanly,
`needs_review=False`" was the documented, intended behavior at the time).
**That framing conflated "the sentinel mechanically survived transmission"
with "the user sees translated text" — they are never the same thing.**
Splicing a masked term back in, on either path, always substitutes the
raw, untranslated source word; masking never asks the model to translate
a masked term at all. A cleanly-spliced term is exactly as unreadable to
the reader as a missing-sentinel one.

**Quantified the real scope directly against this episode's actual cache
data, not estimated**: of 64 lines, 24 contain raw spliced Japanese.
Before the fix, only 5 of those 24 were flagged (the missing-sentinel
cases) — **19 of 24, the large majority, were completely invisible to
`needs_review`**, indistinguishable from a normal, fully-translated line.

**Fix**: `splice_terms()` now sets `needs_review=True` whenever `targets`
(the term list for that line) is non-empty, regardless of which of the
two paths handled each individual term — not only on the missing-sentinel
path. The per-term missing-sentinel warning log line is unchanged (still
useful for diagnosing sentinel-survival specifically); only the returned
`needs_review` value's scope changed. `TranslatedLine.needs_review`'s
docstring and `splice_terms()`'s own docstring updated to describe the
corrected semantics. `build_review_term_map()`'s docstring (in
`alphapolis_reader.py`) also updated — it previously documented "a line
with mask_targets but needs_review=False is intentionally excluded" as a
real case; after this fix that case essentially never occurs from
`splice_terms()` output, so the comment now describes the filter as a
safety net rather than an expected exclusion. The filter logic itself is
unchanged and still correct either way.

**Cache/schema decision, stated explicitly rather than assumed**: existing
cached episodes' `needs_review_flags` were computed under the old,
narrower rule and will not retroactively show the newly-covered
clean-splice lines until re-translated. **Not bumping `CACHE_SCHEMA_VERSION`** —
the flag's shape is unchanged (`List[bool]`, same length/order), only the
policy that computes its values changed, and `RETRANSLATION_DESIGN.md`'s
own precedent treats schema bumps as warranted for shape changes, not
policy changes. Anyone wanting the fix applied to an already-cached
episode needs to hit Refresh manually (which re-fetches and re-translates,
discarding the stale cache entry) — this is not automatic.

**Live verification, not just the code diff or unit tests.** Triggered a
real Refresh (delete-cache-and-retranslate) against the exact episode from
the screenshot, through the real, unmodified app and the real
translategemma server. Confirmed via the on-disk cache file directly:
`needs_review_flags` now has 24 `True` entries, exactly matching the 24
lines independently identified as containing spliced Japanese (same index
set, both before and after — the fix changed which lines get flagged, not
which lines contain spliced content). Confirmed via `xdotool` screenshot
in **Translated mode** (the mode from the original screenshot): every
previously-plain-blue spliced line (`オレ's ハードキャッチ`, `鉄パイプ`,
`ダンジョン能力者`, `ヤンチャボーイズ`) now renders in the amber/underline
`needs_review` style, correctly distinguished from genuinely-clean lines
(`Gah...!!`, `My... fingers!...`) which remain plain blue. Also confirmed
in **Both** mode's Interleaved half via a second `xdotool` screenshot —
the translated half of each flagged pair shows the same amber/underline
styling, unflagged pairs stay plain, matching Translated mode's result
exactly (both modes share the same `_render_translated_view()` dispatch,
confirmed via code read, not just inferred from the shared call site).

**Test coverage**: updated two existing tests in
`tests/webnovels/test_llm_translate.py`
(`TestTranslateLinesWithMasking.test_single_chunk_passes_through_unmodified_mask_targets`,
`test_mask_targets_reindexed_correctly_across_chunk_boundary`) that had
asserted `needs_review is False` on a clean splice — now correctly assert
`True`, with an explanation comment rather than a silent flip. Added a
new `TestSpliceTerms` class (4 tests) directly exercising `splice_terms()`
for the first time (previously only tested indirectly through
`translate_lines_with_masking()`): clean-splice sets `needs_review=True`,
missing-sentinel still sets it `True`, no-targets-at-all stays `False`,
multiple-clean-targets-on-one-line still sets `True`. `black`/`isort`/
`flake8` clean on `llm_translate.py`, `alphapolis_reader.py`, and the
test file. `mypy` clean on `llm_translate.py` (unchanged, docstring-only
change to a fully-typed function); `alphapolis_reader.py` unchanged at
352 errors (docstring-only edit there too, no new untyped code). Full
project test suite re-run: no regressions (92 tests total in
`tests/webnovels/`, up from 88 before this fix).

**Not done in this pass**: no `CACHE_SCHEMA_VERSION` bump (see reasoning
above). No changes to `build_mask_targets()`, `mask_terms()`, the sentinel
pattern/normalization logic, or either display mode's rendering/dispatch
code — the bug was entirely in what `needs_review` gets set to, not in
how it's rendered once set, confirmed by both modes producing identical,
correct styling once the upstream flag was fixed. No changes to
`retranslate_line_with_hint()` or any `RETRANSLATION_DESIGN.md`-phase
code — this fix is squarely masking/needs_review territory (§6/§9/§11),
not the separate retranslation-quality feature; see
`RETRANSLATION_DESIGN.md`'s Status section for a one-line pointer back
to this entry.

**Not anticipated going in, found during this task**: the scope gap
itself — the task began as "is this a rendering bug or working as
designed," and the actual answer ("working as designed, but the design
had an under-scoped `needs_review` rule") was neither of the two original
hypotheses. Also not anticipated: the JSON-parse-failure recovery
confirmation, found only because the user's log happened to contain one,
not because it was being specifically looked for.

**Not done in this pass** (see the three excluded items above, and §8):
promotion/threshold logic, suggested-term recurrence tracking, new-
candidate discovery. `build_mask_targets()`, `mask_terms()`/
`splice_terms()`, and the core glossary schema were not touched.
