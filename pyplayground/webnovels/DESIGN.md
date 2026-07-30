# Glossary & Reader Redesign — Design Doc

Living record of decisions for the glossary/term-consistency rework and the
Tkinter → web migration. Update this alongside code changes, not after —
chat history is not the system of record.

Last updated: 2026-07-29 (documented known limitation: no multi-spelling/variation support in the term data model)

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
- **Classification drift between `explain_term()` and `build_glossary.py`'s
  extraction**: found via the 2026-07-27 dedup fix — the two code paths
  can independently assign different `type` values to the same source
  word (e.g. `オレ` classified as `character` at extraction time, `term`
  when `explain_term()` re-evaluates it live), with no shared source of
  truth. `upsert_confirmed_term()` neutralizes the specific consequence
  this caused (a duplicate entry on manual save), but the underlying
  disagreement itself is unresolved and untouched — it could plausibly
  surface in a different shape elsewhere (e.g. if any future code path
  trusts `type` as stable/consistent across a term's lifetime). Not
  urgent, no known live instance beyond the one just fixed — tracked here
  so it isn't lost once that specific bug is filed away as closed.

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

### 2026-07-29: known limitation — no support for multiple source spellings resolving to one confirmed term

The glossary matches terms by literal `source` string only.
`build_mask_targets()` and the masking/splicing pipeline it feeds
(§4/§10) all operate on exact substring matches against a term's single
`source` field — there is no mechanism for a second, alternate spelling
of the same entity to resolve to the same `confirmed_target`.

**This is not a new discovery — it's a known omission from day one, now
confirmed to matter in practice.** §2's original reference-UX
screenshots (the existing MTL site studied at the very start of this
redesign) explicitly showed a **Variation** field in its term editor,
built for exactly this case. This project's term data model (§3, §9)
never carried a `Variation`-equivalent field forward into the schema
that was actually implemented — an omission, not a regression.

**Concrete evidence it matters**: during Phase 3's real-data
verification (novel `375266002`, 2026-07-29), a character confirmed as
`ケイト` → `Kate` did not get masked/translated consistently in an
episode where the same character was instead written as `糧品瑠羽`
(kanji) rather than `ケイト` (katakana). The confirmed term simply
doesn't apply to the alternate spelling — not a bug in the masking
logic itself, which is working exactly as designed against a single
`source` string; the gap is that the schema gives it only one string to
match against per term.

**Not urgent, not blocking anything currently queued.** If a fix is
ever considered later (not scoped now, no plan attached to this entry):
the natural shape is a `variations: List[str]` field on each term,
checked alongside `source` in `build_mask_targets()`'s lookup.

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

### 2026-07-27: Dedup bug in the manual "Add to Glossary" save path found and fixed — currently-live, blocking a confirmed term

**Found**, following directly from the previous entry's `needs_review` fix
(which is what surfaced the live `オレ` glossary state in the first place):
`オレ` existed twice in novel 375266002's real glossary — once as
`character`-typed (the original `build_glossary.py` LLM extraction, old
pre-Section-9 schema shape, no `status` field), once as `term`-typed,
`status: confirmed`, `confirmed_target: "Me"` (a later manual save via the
"Add to Glossary" dialog). The leftover unconfirmed duplicate was still
causing `build_mask_targets()` to mask `オレ` on every translation despite
the human having explicitly confirmed a translation for it — not a
cosmetic data-shape issue, a live, currently-active masking bug.

**Root cause, confirmed by tracing the actual code path, not assumed.**
`open_word_glossary_popup()`'s `save_and_close()` (the single save
function behind both the right-click "Add to Glossary..." menu item and
`_on_needs_review_click()` — both call `open_word_glossary_popup()`, there
is no second dialog/save path) always builds a fresh term via
`make_confirmed_term()` and hands it to `merge_terms()`. `merge_terms()`
dedupes on `(type, source)` (§9), a deliberate, documented tradeoff for
its actual use case (bulk-merging fresh LLM extraction results, where a
`character` and a `term` entry coincidentally sharing source text are
allowed to coexist as different things nobody has reviewed yet — see
`TestMergeTerms.test_same_source_different_type_both_kept`, which already
covers and locks in exactly this `オレ` case as *intended* behavior for
that function). The dialog itself carries **no reference to any existing
glossary entry** — confirmed via reading `open_word_glossary_popup()` in
full — only the `source_prefill`/`target_prefill` text strings that
seeded the form. `type_var`'s pre-selection comes from `explain_term()`'s
live classification each time the dialog opens, which doesn't necessarily
agree with whatever type the original LLM extraction guessed (`オレ` is an
ordinary pronoun; `explain_term()` reasonably classifies it as a general
term, not a character, even though the original extraction had guessed
`character`). So a human opening the dialog for an already-extracted term,
seeing "Term" pre-selected, and saving — completely ordinary usage, no
mistake on the human's part — silently created a second, differently-typed
entry instead of updating the first, because `merge_terms()`'s dedup key
never matched.

**Fix location: the manual dialog-save path only.** Per the task's own
explicit instruction and this doc's established precedent of not touching
a function's documented, deliberate behavior for a use case it wasn't
designed for — `merge_terms()`'s `(type, source)` key and its bulk-LLM-
extraction behavior are unchanged, still correct for that call site
(`build_glossary.py`'s extraction still uses it, still needs "character"
and "term" entries with the same source text to be allowed to coexist as
unreviewed candidates). Added `upsert_confirmed_term(existing, new_term)`
to `glossary.py` instead: dedupes on `source` alone (ignoring `type`
entirely) and, on a collision, **replaces every existing entry for that
source** with the new one — not just the first found, not merged
field-by-field. `open_word_glossary_popup()`'s `save_and_close()` now
calls this instead of `merge_terms()`.

**Reconciliation rule, stated explicitly**: on save, the newly-confirmed
entry always wins over any existing entry(ies) for the same source,
regardless of the existing entry's type or status. Same trust principle
`make_confirmed_term()` already documents ("a human typed this
deliberately, trusted on entry"), extended to mean this also overrides a
stale prior entry rather than merely coexisting with it — a human
confirming a source word is confirming *that word*, not "that word
considered as a character specifically, as opposed to as a general term."

**One-time data cleanup, performed as part of this task, not a schema
migration**: reconciled novel 375266002's real on-disk glossary directly.
Confirmed via a full scan that `オレ` was the *only* duplicated source in
that file (12 other terms, all still old-shape/unconfirmed — no other
live conflicts exist yet). Ran the actual reconciliation
(`upsert_confirmed_term()` against the real file, keeping the one
`status: confirmed` entry and discarding the stale `character`-typed
one), verified via `load_glossary()` immediately after: exactly one `オレ`
entry remains (`type: term`, `status: confirmed`,
`confirmed_target: "Me"`), term count 13 → 12. This is fixing genuinely
duplicated data under the *current* schema, not a schema-shape migration
— no `CACHE_SCHEMA_VERSION`/glossary-shape change involved, unlike §9-§11's
established no-backward-compat-shim precedent for old *shapes*.

**Live/practical verification, not just data-shape verification** — the
actual thing this bug was breaking: ran `build_mask_targets(["オレは彼を見た。"],
glossary)` against the real, now-reconciled on-disk glossary file.
Before the fix: `[(0, "オレ")]` (still masked, despite being confirmed).
After: `[]` — `オレ` no longer masked, matching a human's actual confirmed
choice for the first time.

**Test coverage**: 6 new tests in `tests/webnovels/test_glossary.py`
(`TestUpsertConfirmedTerm`): no-existing-entry appends normally,
same-type collision replaces, **the exact live bug reproduced directly**
(character-typed old-shape entry with no `status` field + a `term`-typed
confirmed save → single resulting entry with the new type/status/target,
not two), the practical `build_mask_targets()` consequence (source no
longer masked after upsert), a defensive multiple-stale-duplicates case
(collapses to one even if more than one somehow existed), and an
unrelated-sources-untouched case. `TestMergeTerms`'s existing
`test_same_source_different_type_both_kept` — which documents and locks
in `merge_terms()`'s own, unchanged, intentional behavior for this same
`オレ` scenario — was left as-is, confirming `merge_terms()` itself was
correctly not touched. `black`/`isort`/`flake8` clean (a resulting unused
`merge_terms` import in `alphapolis_reader.py`, no longer called anywhere
in that file, was removed rather than left as dead-but-harmless). `mypy`
clean on `glossary.py`; `alphapolis_reader.py` unchanged at 352 errors
(no new untyped code). Full project test suite re-run: no regressions
(98 tests total in `tests/webnovels/`, up from 92 before this fix).

**Not done in this pass**: no changes to `merge_terms()` itself, its
`(type, source)` dedup key, or `build_glossary.py`'s extraction path,
which still uses `merge_terms()` unchanged and correctly. No changes to
the full glossary editor dialog (`open_glossary_dialog()`'s
`save_and_close()`) — traced and confirmed unaffected: it edits an
in-memory term list by index directly (`commit_selected_form()`,
`terms.append()`/`del terms[index]`), never calls `merge_terms()` or any
dedup-key logic, so this bug class isn't reachable from that path. No
`CACHE_SCHEMA_VERSION` bump (see reasoning above — this is a data fix,
not a shape migration).

**Not anticipated going in, found during this task**: the trigger
mechanism specifically — the task brief anticipated "a manual save should
have updated the first entry, not created a second" as the general shape
of the bug, but the *reason* a type mismatch occurred at all
(`explain_term()`'s live re-classification not necessarily agreeing with
`build_glossary.py`'s original extraction-time classification for the
same word) wasn't something either doc had previously called out as a
source of drift between the two pipelines.

### 2026-07-27: `needs_review` span-level highlighting and click resolution — implemented

Changes `needs_review` from line-level to span-level, per §6/§11's
original implementation: both visual highlighting (only the exact
masked-term text gets amber/underline, not the whole line) and click
resolution (clicking a specific highlighted term opens the dialog for
*that* term, not always the line's first one).

**Confirmed current (pre-change) behavior directly in code before
starting, not assumed from the docs alone**: grep/read-confirmed
`_render_translated_content_from_translated_lines()` applied
`"needs_review"` as the tag for the entire inserted line
(`line_tag = "needs_review" if translated.needs_review else tag`, then
`self.text.insert("end", line_text + "\n", line_tag)`), and
`_on_needs_review_click()` always resolved to `words[0]` from
`build_review_term_map()`'s per-line word list, "consistent with...
always resolves to a single word per click, not a batch action" (its own
prior docstring, now out of date). Both confirmed as real, current
behavior, not inferred.

**New function**: `find_glossary_term_spans(translated_line, glossary)` in
`glossary.py`, right after `build_mask_targets()`. Locates the character
span(s) of each glossary term's source string as they literally appear in
an already-translated/spliced line. New logic, not a call into
`build_mask_targets()` -- different input shape (one already-translated
line's text, not a list of pre-translation source lines) and, critically,
a different filtering rule.

**The critical correctness requirement, implemented and specifically
tested**: `find_glossary_term_spans()` does **not** filter by glossary
`status`, unlike `build_mask_targets()`. `needs_review_flags[i] == True`
is a historical fact about translation time (§11) -- a term's status can
legitimately change afterward (e.g. confirmed later), and the exact same
raw spliced substring is still sitting in the exact same already-cached
line regardless. Filtering to unconfirmed-only here would silently stop
highlighting/resolving a term the moment it's confirmed. Verified directly
with a dedicated test
(`test_needs_review_span_resolves_even_after_term_confirmed_post_caching`
in `test_alphapolis_reader.py`, plus
`test_confirmed_status_does_not_exclude_a_term_from_span_search` in
`test_glossary.py`): a `STATUS_CONFIRMED` term still resolves for both
span highlighting and click, through the real render + click path, not
just the pure function in isolation.

Same overlap/ordering discipline as `build_mask_targets()` (longer
sources matched first so a term that's a substring of another doesn't get
fragmented; results returned in line-position order) -- reused as a
*model*, not called directly, per the task's explicit instruction, since
the input shape and filtering rule are both different.

**Rendering changes**: both
`_render_translated_content_from_translated_lines()` and
`_render_interleaved_content()` now insert a needs_review=True line's text
with the ordinary base tag (`"translated"`) first, then call a new shared
helper, `_apply_needs_review_spans(line_start, line_text, source_line,
glossary)`, which locates the term span(s) via
`find_glossary_term_spans()` and layers `"needs_review"` on top of only
those spans via `self.text.tag_add()` -- not by re-inserting the text
with a different tag. Confirmed directly (not assumed) that Tk gives the
later-added tag priority for conflicting display attributes: a small
isolated check (`tag_add()` after `insert()`'s tag) showed
`tag_names()` returning `('translated', 'needs_review')` in that order,
and Tk's own rule is that the later tag in the list wins -- so
`needs_review`'s amber/underline correctly overrides `translated`'s blue
over just the matched span, with the rest of the line unaffected.

**Click resolution**: `_review_terms_by_span` (previously line-level:
`(start, end) -> ([masked words], source_line)`, one entry per flagged
*line*) is now span-level: `(start, end) -> (word, source_line)`, one
entry per individual matched-term *span*, populated by
`_apply_needs_review_spans()` using each span's own Tk indices (not the
whole line's). `_on_needs_review_click()` now resolves to whichever
span's range contains the click position -- naturally correct per-term
resolution, not a special case, since the dict key is already the exact
span. `build_review_term_map()` (the old line-level pure function) was
left in place, unused by the renderer now but still a valid, independently
tested public function -- not deleted, since removing a tested function is
outside this task's scope and wasn't traced for other callers.

**`_rendered_spans`' one-pair-per-line invariant preserved, confirmed by
inspection and by a dedicated test, not just by not touching the code that
builds it.** `RETRANSLATION_DESIGN.md`'s `_translated_span_after()`
depends on `_render_interleaved_content()` appending exactly one
`(original, translated)` pair per source line to `_rendered_spans`, in
that strict order. `_apply_needs_review_spans()` never appends to
`_rendered_spans` -- only to the separate `_review_terms_by_span` dict
(same purpose-built-dict precedent as before, not multiplied into
`_rendered_spans`) -- so the invariant holds structurally, not just by
convention. Required regression test added
(`TestNeedsReviewLineAlsoRetranslateTarget` in
`test_retranslation_dialog.py`): a line that is both a needs_review
span-highlight target *and* a valid retranslation click target, run
through the real `_render_interleaved_content()`, confirming
`_translated_span_after()` still resolves the correct translated span
*and* `_review_terms_by_span` resolves the correct term span,
independently, on the same line.

**A real, separate bug found live during this task's own xdotool
verification, fixed as found-not-planned**: repeated clicks on two
different highlighted terms on the same line -- while diagnosing an
initial coordinate-targeting miss during verification -- opened two
independent `Add to Glossary` popups stacked on screen simultaneously,
each with its own background lookup thread. Not scoped to span-level
highlighting specifically (the same class of bug applies to
`open_retranslate_popup()` too, and would have existed before this task
via any repeated click), but directly interfered with verifying this
task's own change and was fixed with the same rigor as planned work, per
this project's standing rule. Added `self._glossary_popup`/
`self._retranslate_popup` tracking attributes (`None` when no popup of
that kind is open); both `open_word_glossary_popup()` and
`open_retranslate_popup()` now check for an existing, still-alive
(`winfo_exists()`) popup of their own kind at the top and `lift()`/
`focus_force()` it instead of creating a duplicate. Cleared via a
`<Destroy>` binding on the `Toplevel` itself (guarded with
`e.widget is win`, since Tk's `<Destroy>` bubbles from every destroyed
child widget, not just the window) rather than patching every exit path
(Save, Cancel, Accept, Discard, window-manager close) individually --
fires correctly regardless of how the window closes. Verified live: two
clicks on two different terms on the same line, without closing the
first dialog, correctly left exactly one popup open, still showing the
*first* click's term unchanged. 3 new tests in
`test_retranslation_dialog.py` (`TestPopupSingleInstanceGuard`): a second
call reuses the existing glossary popup, the guard clears after the
popup is destroyed (a fresh call then opens a new one), and the same
reuse behavior for the retranslate popup.

**Live verification, via the same `xdotool`/real-display setup used for
every prior visual claim in both docs:**

- Seeded a synthetic cached episode (`novel_id=888888`) with a single
  line containing two distinct masked terms (`オレ` and `鉄パイプ`, both
  `suggested`-status) and `needs_review_flags=[True, False]`, launched the
  real, unmodified app against it in **Translated mode**.
- Screenshot confirmed: only the exact substrings `オレ` and `鉄パイプ` show
  amber/underline styling; every other word in the same line ("Because
  of", "he was holding a") and the entire second, unflagged line ("Kate
  turned around.") render in plain blue -- span-level, not line-level,
  confirmed visually, not just via `tag_ranges()` inspection.
- Clicked `鉄パイプ`'s highlighted span: the real `Add to Glossary` dialog
  opened with **`Source (original): 鉄パイプ`**.
- Closed it, then clicked `オレ`'s highlighted span on the *same line*:
  opened with **`Source (original): オレ`** -- a different, correct term
  from a different click position on the same line, the core claim this
  task needed to demonstrate on a real rendered screen.
- Clicked both spans again without closing the first popup: confirmed via
  `xdotool search` that only one `Add to Glossary` window existed, still
  showing the first click's term (`オレ`) -- the popup-dedup fix verified
  live, not just via its unit tests.

**Test coverage**: 7 new tests in `test_glossary.py`
(`TestFindGlossaryTermSpans`): single-term span location, multiple
occurrences of the same term found separately with no overlap corruption
(the `オレ オレ` splice-fallback case), the critical confirmed-status
requirement, no-match, empty-glossary, longer-source-before-shorter-
substring overlap discipline, and multiple different terms on one line in
position order. 3 new/updated tests in `test_alphapolis_reader.py`
(needs_review tag now confirmed span-level not line-level, the
confirmed-after-caching regression test, plus updated `TestRenderTranslatedView`
tests reflecting the `glossary`-not-`mask_targets` parameter change). 1
new test in `test_retranslation_display.py`
(`test_needs_review_span_only_covers_matched_term_text`). 1 new test in
`test_retranslation_dialog.py`
(`TestNeedsReviewLineAlsoRetranslateTarget`, the required
needs_review/retranslate interaction regression) plus the 3
`TestPopupSingleInstanceGuard` tests for the found-live popup-dedup fix.
`black`/`isort`/`flake8` clean on all touched files. `mypy` clean on
`glossary.py` (unchanged, fully typed); `alphapolis_reader.py` at 355
errors (up from 352), consistent with the file's existing untyped-method
convention -- the 3 new/changed methods (`_apply_needs_review_spans()`
plus the popup-guard additions to two existing methods) account for the
delta, not fixed here, same treatment as every prior session touching
this file. Full project test suite re-run: no regressions (111 tests
total in `tests/webnovels/`, up from 98 before this task).

**Not anticipated going in, found during this task**: the popup-dedup bug
above -- surfaced only because live click-verification happened to
involve retrying a coordinate miss, not something the task brief called
out. Otherwise, the actual implementation matched the task brief closely:
the dependency check, the critical-correctness requirement, the
`_rendered_spans` isolation constraint, and the required regression test
were all exactly as scoped, no surprises in the core logic itself.

**Not done in this pass**: no changes to `merge_terms()`,
`upsert_confirmed_term()`, or the dedup bug (closed, prior entry). No
changes to the classification-drift open item added to §8 (untouched, as
instructed). `build_review_term_map()` was not deleted, only left unused
by the renderer -- a possible future cleanup, not attempted here since it
wasn't traced for other callers and deleting a tested public function is
outside this task's scope.

### 2026-07-27: `splice_terms()` falls back to a suggested candidate instead of raw source text — implemented

When a masked term has no `confirmed_target`, `splice_terms()` previously
always spliced the literal raw source word back in as the fallback
(both on the sentinel-missing recovery path and, since the prior entry's
fix, the clean-splice path too). Now it falls back to the term's
best-ranked `suggested` candidate when one exists, only falling back to
raw source text when the term genuinely has no candidate yet.

**The boundary this does and doesn't cross, confirmed unchanged**:
`format_glossary_for_prompt()` is untouched and still filters to
`STATUS_CONFIRMED` only (§9's locked decision) -- a `suggested` term
still contributes nothing to how the model actually translates. This is
strictly a post-hoc display fallback for text that's already been masked
and already went untranslated; it changes what a reader *sees* for an
unresolved term, not what the model is told to do. `needs_review=True`
still fires unconditionally whenever a line has any mask targets,
unchanged from the prior entry's fix -- confirmed by test
(`test_fallback_used_instead_of_raw_word_on_clean_splice`,
`test_fallback_used_on_missing_sentinel_path_too`, both assert
`needs_review is True` alongside the new fallback text) and by the live
check below. The fallback quality changed; the trust/review gate did not.

**Candidate-selection rule, stated precisely rather than left to
iteration order**: `best_candidate_for_term()` (new, `glossary.py`) picks
highest `count` first (per §3's own framing: "popularity is the
disambiguation signal, not any single model's one-shot guess"). On a
count tie, `origin` breaks it: `ORIGIN_USER` beats `ORIGIN_MT` beats
`ORIGIN_LLM` -- a human-entered candidate is more trustworthy than a
machine-translation reference, which is more trustworthy than a raw
one-shot LLM guess, even at equal usage counts. If both count and origin
tie, the first matching candidate in the term's own `candidates` list
wins -- falls out of Python's stable sort on the `(-count, origin_rank)`
key, not a separate rule. An origin not in the known three (future
addition) sorts last rather than raising, for forward compatibility.

**Where this lives, and why -- the architectural boundary confirmed, not
assumed.** `llm_translate.py` has zero imports of `glossary.py`
(re-confirmed directly, matching the same boundary
`retranslate_line_with_hint()`'s docstring already documents from the
retranslation-dialog work). `splice_terms()` therefore doesn't look up
candidates itself -- it takes a new, purely additive `fallbacks:
Optional[Dict[str, str]] = None` parameter, a plain word-to-display-text
map built by the caller. `build_splice_fallbacks(mask_targets, glossary)`
(new, `glossary.py`) builds that map, using `best_candidate_for_term()`
per distinct masked word, falling back to the word itself when the
glossary has no matching term or the term's `candidates` list is empty.
Threaded through `translate_chunk_with_masking()` and
`translate_lines_with_masking()` as an optional parameter each (default
`None`, behaving identically to before when omitted -- every existing
caller/test that doesn't pass it is unaffected, confirmed by the full
suite passing unchanged before any test updates were needed).
`fetch_and_translate()` (`alphapolis_reader.py`) builds `fallbacks` from
the same `glossary` snapshot `mask_targets` was just computed against,
right before calling `translate_lines_with_masking()`.

**The "term confirmed between chunk translation and fallback running"
case, verified rather than left unchecked, per the task's explicit
instruction.** Not reachable in normal flow: `build_mask_targets()` only
includes words for `status != STATUS_CONFIRMED` terms, and
`build_splice_fallbacks()` is called against the exact same in-memory
`glossary` variable within the same `fetch_and_translate()` call --
no reload happens in between, so a word belonging to an already-confirmed
term cannot appear in `mask_targets` in the first place. Checked the
hypothetical anyway: even a stale-snapshot edge case wouldn't produce a
wrong value, since `make_confirmed_term()` always constructs a confirmed
term's sole candidate identical to its `confirmed_target` -- confirmed by
a dedicated test
(`test_confirmed_term_returns_its_own_confirmed_target`, asserting
`best_candidate_for_term(term) == term["confirmed_target"]`).

**Live verification against novel 375266002's real glossary and real
cached content, not just unit tests.** `オレ` (the dedup fix's earlier
subject) is now `STATUS_CONFIRMED` in the real glossary -- correctly no
longer a mask target at all, so it couldn't demonstrate this fallback.
Used `鉄パイプ` instead (a real term in the same glossary, previously an
old pre-Section-9-shape entry with no `candidates` field): upgraded it to
a `suggested`-status entry with one real candidate
(`"iron pipe"`, `origin=llm`) to have something with an actual candidate
to demonstrate against -- left as this (reasonable, real) upgrade rather
than reverted, per direction. Ran `build_mask_targets()` +
`build_splice_fallbacks()` against the real on-disk glossary, then
`splice_terms()` with a simulated sentinel-missing model output:

- **Before** (no `fallbacks`, old behavior): `"He was holding it. 鉄パイプ"`
  -- raw untranslated Japanese, `needs_review=True`.
- **After** (`fallbacks` built from the real glossary): `"He was holding
  it. iron pipe"` -- readable English fallback, `needs_review=True`
  unchanged.
- **Zero-candidates case, confirmed unchanged**: ran the same check
  against `ダンジョン能力者` (a real term in the same glossary, still in its
  original old shape with no `candidates` field at all).
  `build_splice_fallbacks()` correctly mapped it to itself
  (`{"ダンジョン能力者": "ダンジョン能力者"}`), and `splice_terms()` produced the
  identical raw-source-text fallback as before this change --
  `"He was a person. ダンジョン能力者"`, `needs_review=True`.

**Test coverage**: 7 new tests in `test_glossary.py`
(`TestBestCandidateForTerm`: single candidate, highest-count wins,
count-tie broken by origin order, count-and-origin tie falls back to
list order, no-candidates returns `None`, missing `candidates` key
returns `None`, a confirmed term's candidate matches its own
`confirmed_target`) plus 5 more (`TestBuildSpliceFallbacks`: candidate
found and used, no glossary entry falls back to the word itself, empty
candidates list falls back to the word itself, duplicate words across
lines computed once, multiple distinct words in one map). 5 new tests in
`test_llm_translate.py` (`TestSpliceTerms`: fallback used on clean
splice, fallback used on missing-sentinel path, a word absent from
`fallbacks` uses the raw word, omitting `fallbacks` entirely preserves
original behavior, an empty `fallbacks` dict behaves the same as
omitting it) plus 2 more in `TestTranslateLinesWithMasking` confirming
`fallbacks` threads through the chunking wrapper unmodified (not
re-indexed like `mask_targets` -- it's keyed by word, not line index) and
that omitting it preserves original behavior end-to-end through mocked
HTTP. `black`/`isort`/`flake8` clean on all touched files. `mypy`: one
real, fixed error in `glossary.py` (`best_candidate_for_term()`
returning `Any` from a `str | None`-declared function via
`dict.get()`'s untyped return -- fixed with an explicit `str()` cast, not
suppressed), otherwise clean; `glossary.py` remains fully typed and
`mypy`-clean end to end, matching its existing strict-typing discipline.
`llm_translate.py` clean (unchanged). `alphapolis_reader.py` unchanged at
355 errors (the two-line `fetch_and_translate()` addition sits inside an
already-untyped method). Full project test suite re-run: no regressions
(130 tests total in `tests/webnovels/`, up from 111 before this task).

**Not anticipated going in, found during this task**: none of substance
-- the task brief's architectural boundary instruction (don't have
`splice_terms()` reach into `glossary.py`) matched exactly what tracing
`llm_translate.py`'s actual imports confirmed was already the established
convention, and the "verify the confirmed-term-race is unreachable"
instruction turned out to be checkable directly from
`build_mask_targets()`'s own documented rule rather than requiring new
investigation.

**Not done in this pass**: no changes to `format_glossary_for_prompt()`
or `build_mask_targets()`'s masking trigger rule -- confirmed via `git
diff` scope check that neither was touched. No promotion/auto-confirm
logic (§8, separate, unstarted). No bulk-review UI (the larger,
separate "pre-detect before reading" feature this was explicitly scoped
alongside but not part of) -- not started.

### 2026-07-27: Bulk term-review dialog — implemented

A new Tkinter dialog (`open_term_review_dialog()`, "Review Terms..." in
the toolbar) to confirm or reject a novel's unconfirmed glossary terms in
one sitting, instead of one right-click at a time while reading. Note on
scope provenance: §7 phase 4 originally described "the candidate picker"
as web-migration-only, future work -- this task deliberately builds it in
Tkinter now, per explicit direction, not a reinterpretation of §7's
sequencing; §7 itself is unchanged.

**Reused vs. extended, decided and stated, not defaulted.** Considered
extending `open_glossary_dialog()` (the existing general term editor --
already lists every term with a Treeview + side form, close to this
task's shape) rather than building a new dialog. **Decided against
extending it**: that dialog lists every term of every status and its Save
always confirms on any edit (no distinct Reject-as-delete, no candidate
picker, no "only show what needs review" filter) -- a genuinely different
purpose and trust model from "review the unconfirmed backlog, with a real
delete option and ranked-candidate quick-pick." Overloading one dialog
with both would blur that distinction in the UI. Built a new, standalone
dialog instead, but reused its concrete patterns rather than inventing
new ones: the Treeview-list-plus-side-form layout, `load_glossary(novel_id)`
for loading, and the "click a candidate to use as Target" reference
pattern from `open_word_glossary_popup()`'s Reference/Alternatives
section (candidates listed as `ttk.Button`s ranked by count, clicking one
fills the Target field -- same idiom, not a new one).

**Confirm reuses `upsert_confirmed_term()` -- verified, not assumed.**
`confirm_selected()` builds a fresh term via `make_confirmed_term()`
(preserving character-only fields when type is `character`, same pattern
as `open_word_glossary_popup()`'s save handler) and writes it via
`upsert_confirmed_term(glossary.get("terms", []), new_term)` -- the same
function the dedup-bug fix put behind the manual "Add to Glossary"
dialog, not a third write path. Confirmed this actually happened, not
just that the code calls the right function name: live-verified against
the real glossary that a confirmed term's resulting candidate has
`origin: "user"` (which only `make_confirmed_term()` produces -- the
original `suggested` candidate had `origin: "llm"`), proving the write
went through the real confirm path rather than some other code writing a
differently-shaped entry.

**Reject is a real delete, not a status change** -- removes the term from
`glossary["terms"]` entirely (filtered by object identity, `t is not
term`, so it can't accidentally remove a different term that happens to
share the same source string). Reasoning, stated in the method's own
docstring: `build_mask_targets()` masks anything that isn't
`STATUS_CONFIRMED`, so a "rejected" status would still be masked forever
with no path back to un-flagging it -- a real delete is the only
option that actually stops it from being treated as an unreviewed term
going forward. Confirmed via a `messagebox.askyesno()` prompt naming the
exact term and stating plainly that it removes the term entirely, before
acting.

**Design decisions made explicitly, not defaulted on:**

- **No "confirm all"/bulk-select.** Recommended against per the task
  brief's own framing, and implemented that way: strictly one-at-a-time
  review, faster iteration through the list (select, glance at
  candidates, Confirm/Reject, move to the next row) rather than batch
  trust. A bulk-confirm button would reintroduce exactly the "trust
  unreviewed model output" failure Section 1 documents as the original
  motivation for this whole redesign (Lanchester's Law hallucination,
  mundane compounds entering the glossary unreviewed) -- the entire point
  of the `suggested` review gate is that nothing skips human judgment,
  and a bulk-confirm button is a direct hole in that gate.
- **No rejection-blocklist.** A term rejected here can be re-suggested by
  a future `build_glossary.py` extraction run on the same novel and
  reviewed again -- accepted as a reasonable v1 tradeoff (re-reviewing an
  occasional re-suggested term is cheap; building and maintaining a
  separate blocklist mechanism before there's real usage data on how
  often this actually recurs is premature). A real future addition, not
  an oversight.
- **Type editing needs no special handling beyond what Confirm already
  does.** Changing Type on a still-`suggested` term (directly relevant to
  §1/§8's `character`-vs-`term` misclassification problem -- `explain_term()`'s
  live classification and `build_glossary.py`'s extraction-time guess can
  disagree, per the dedup-fix's §8 entry) just flows the corrected
  `type_var` value straight into `make_confirmed_term()`'s `term_type`
  argument on Confirm, identical to every other manual-confirm path in
  this file (`open_word_glossary_popup()`, `open_glossary_dialog()`'s
  inline edit). No separate code path, no special-casing needed --
  confirmed by a dedicated test
  (`test_type_change_then_confirm_uses_new_type`).

**A real gap found and fixed during this task's own live verification,
not part of the original design.** The first implementation filtered the
tree to `status == STATUS_SUGGESTED` exactly. Live-checked against novel
375266002's real glossary before considering this done and found: 9 of
its 10 unconfirmed terms are old, pre-Section-9-shape entries with no
`status` field at all (`status` reads as `None`, not `"suggested"`) --
exactly the terms most in need of review, and the narrower filter
silently hid all of them, showing only 1 term (`鉄パイプ`) instead of 10.
Fixed by matching `build_mask_targets()`'s own broader, already-correct
rule (`status != STATUS_CONFIRMED`, not `status == STATUS_SUGGESTED`) --
consistent with the same principle the `needs_review` span-highlighting
fix and the `best_candidate_for_term()` confirmed-term-race note both
already established this session: don't assume a narrower status check
is equivalent to the broader "not yet confirmed" one without checking
against real data.

**Live verification, against novel 375266002's real glossary and a real
cached episode, not synthetic fixtures.** Before this task: 12 terms, 10
reviewable (`オレ` confirmed from the earlier dedup fix, `鉄パイプ`
`suggested` with one real `llm`-origin candidate from the candidate-
fallback task, the other 9 old-shape/unconfirmed). Launched the real,
unmodified app via `xdotool` against the real, unmodified toolbar and
dialog:

- Screenshot confirmed the widened toolbar (1090 -> 1220) renders the new
  "Review Terms..." button with no clipping, alongside the already-
  working span-level `needs_review` highlighting from the prior task.
- Opened the dialog: all 10 reviewable terms listed (confirmed the
  old-shape-terms fix directly, not just via its own unit test), `鉄パイプ`
  correctly showing its best candidate (`iron pipe`) and count (1), the
  other 9 showing no candidate/count 0. `オレ` correctly absent.
- Selected `鉄パイプ`: side form showed `Source: 鉄パイプ`, `Type: term`,
  `Target` pre-filled `iron pipe`, one candidate button
  (`iron pipe (x1, llm)`). Clicked **Confirm**: the row disappeared from
  the list (9 remaining), form cleared. Verified via `load_glossary()`
  immediately after: `鉄パイプ` now `status: confirmed`,
  `confirmed_target: "iron pipe"`, and -- the proof this went through
  `upsert_confirmed_term()`/`make_confirmed_term()` and not some other
  path -- its candidate's `origin` is now `"user"`, not the original
  `"llm"`.
- Selected `ダンジョン能力者`: side form showed empty Target, no candidate
  buttons (genuinely zero candidates). Clicked **Reject**: a
  `messagebox.askyesno()` prompt appeared naming the exact term and
  stating it removes the term entirely, confirmed via screenshot. Clicked
  Yes: the row disappeared (8 remaining). Verified via `load_glossary()`
  immediately after: 12 -> 11 total terms, `ダンジョン能力者` completely
  absent from the file (a real delete, not a status flip), `オレ` and
  `鉄パイプ` both still present and correctly confirmed.

**Test coverage**: 8 new tests in new file `test_term_review_dialog.py`
(`TestTermReviewDialogListing`: lists suggested terms and excludes
confirmed, old-shape no-status terms are also listed [the live-found
gap's regression test], zero-reviewable-terms shows the empty state;
`TestTermReviewDialogConfirm`: writes via `upsert_confirmed_term()` and
persists, an edited Target value is used instead of the best candidate,
type-change-then-confirm uses the new type; `TestTermReviewDialogReject`:
removes the term entirely, and a declined confirmation prompt leaves the
glossary unchanged) -- all driven against the real bound method and a
real (headless) Tk widget tree, `load_glossary()`/`save_glossary()`
mocked so no filesystem access happens, same pattern as
`TestPopupSingleInstanceGuard`. `black`/`isort`/`flake8` clean.
`mypy`: `alphapolis_reader.py` at 403 errors (up from 355) -- the new
dialog's closures account for the delta, consistent with the file's
existing untyped-method convention, not fixed here. Full project test
suite re-run: no regressions (138 tests total in `tests/webnovels/`, up
from 130 before this task; one pre-existing, unrelated flaky background-
thread warning in `test_retranslation_dialog.py` confirmed via `git
stash` to predate this task).

**Not anticipated going in, found during this task**: the old-shape-terms
filter gap above -- the task brief's own listing requirement ("suggested-
status terms") was taken at face value initially, and only caught by
actually running the dialog against real, current glossary data before
calling it done, rather than trusting the synthetic unit tests (which all
used `make_suggested_term()`, so none of them would have caught a
narrower-than-intended status filter).

**Not done in this pass**: no auto-promotion/threshold logic (§8,
unrelated). No rejection-blocklist mechanism (named above as future
work, not this task). No changes to masking, splicing, or the reading
pane -- confirmed via `git diff` scope check that only
`alphapolis_reader.py` (new dialog, toolbar button, window width) and
the new test file changed; `glossary.py`/`llm_translate.py` untouched.

### 2026-07-27: `translate_chunk()` error-recovery test-coverage gap closed; `n_predict` root-cause theory investigated and inconclusive

A user-submitted live-test review of a real log
(`app_log_20260727_085853.log`, novel 375266002 episode `7800123`, chunk
3/10) correctly identified, verified line-by-line against the actual
current code, three genuinely untested defensive-recovery paths in
`_translate_chunk_once()`/`translate_chunk()`:

1. `json.JSONDecodeError` on a truncated/malformed response ->
   `_translate_chunk_once()` returns `None` (llm_translate.py's parse-
   failure handling).
2. `translate_chunk()`'s length-mismatch-triggered per-line retry.
3. The per-line retry itself returning a non-identical, wrong-length
   array (the live log's exact `expected a JSON array of 1 string(s),
   got list of length 2`) -- correctly *not* collapsed by the single-line
   dedup guard (which only collapses identical duplicates, per its own
   docstring), correctly falling through to a `None` return and then to
   `translate_chunk()`'s `"[translation failed: ...]"` placeholder.

Every existing test in `test_llm_translate.py`/`test_llm_translate_core.py`
at the time mocked `requests.post` to return clean, correctly-shaped JSON
only -- confirmed by reading the mock helpers, not assumed. All three of
the review's specific claims (function names, line numbers, the exact
behavior of the dedup guard and the retry path) checked out exactly
against the real code.

**The review's proposed root cause (`n_predict` too small once prompt
overhead -- context prefix + glossary prefix -- is accounted for) was
investigated live rather than acted on directly, and turned out not to
hold up.** Mechanically, `n_predict` in llama.cpp's `/completion` API
caps only the *generated response* length; it doesn't share a budget
with the prompt, so "prompt overhead eats into the response budget" isn't
how the parameter actually works. More directly: computed the exact
`n_predict` value used for the real failing chunk (chunk 3 of episode
`7800123`) by reproducing the actual chunk-packing logic against the
cached episode -- `1252` tokens -- and compared it against the observed
failure (truncation at 928 *characters*, far fewer than 1252 tokens'
worth of English text). This alone made the budget-too-small theory look
unlikely. Confirmed further by re-running the exact same chunk live
against the real server, 3 times total across two episodes (`7800123`'s
chunk 3 specifically, and all 11 chunks of `7800232`, per direction to
investigate before deciding): every single chunk came back
`stop_type="eos"` (the model's own natural end-of-sequence token, not
`"limit"` which would mean `n_predict` was hit, not `"word"` which would
mean the `stop: ["\n\n\n"]` sequence fired) with `tokens_predicted` far
under the cap every time (e.g. `214` of `1252` on the exact chunk that
failed live). **The original failure did not reproduce even once.**

**Conclusion, stated at the confidence level the evidence actually
supports**: `n_predict` does not appear to have been the actual
constraint in the original failure (the model finished generating on its
own, well under the cap, every time this was re-run) -- but a
non-reproducing failure can't be conclusively ruled out either. Most
likely explanation: a genuinely rare, non-deterministic model hiccup,
even under `temperature=0.1` (near-greedy but not perfectly deterministic
sampling, consistent with this doc's own §4 finding that fixed-seed
near-greedy decoding still shows occasional non-reproducible variance on
this stack). **`n_predict`'s formula is deliberately left unchanged by
this task** -- changing a budget calculation to "fix" a failure mode that
live re-runs suggest it didn't actually cause would be exactly the kind
of unverified fix this project's discipline has repeatedly avoided
elsewhere (§4/§5's careful root-cause corrections). If this recurs with
better evidence (e.g. a captured raw response showing `stop_type:
"limit"`), that would be the trigger to revisit the budget formula with
an actual confirmed cause in hand, not this investigation's absence of
one.

**Test coverage**: the three gaps closed with 2 new tests added directly
to the user's own broader, pre-existing `test_llm_translate_core.py`
(84 tests total, up from 82) rather than a separate new file -- an
initial standalone file covering the same three gaps was written first,
then found to duplicate `test_llm_translate_core.py`'s already-more-
thorough coverage of the same paths (that file already had
`test_json_parse_failure_returns_none`, `test_length_mismatch_returns_none`,
`test_single_line_dedup_does_not_collapse_different_entries`,
`test_multi_line_failure_retries_per_line`, and
`test_per_line_partial_failure`); the two genuinely new additions were
merged in instead of keeping duplicate files:
`test_truncated_json_array_from_live_log_returns_none` (the literal
truncated string from the real log, not just a synthetic "not json"
string) and `test_per_line_retry_returning_non_identical_array_falls_back_to_placeholder`
(the live log's specific non-identical-2-element nested-retry-failure
shape, distinct from the existing partial-failure test's plain-non-JSON
failure). `black`/`isort`/`flake8` clean on the added tests (one
pre-existing line-length issue and a few pre-existing docstring-style
flake8 findings elsewhere in that file predate this task and were left
untouched, not in scope for this pass). Full project test suite
re-run: no regressions.

**Not done in this pass**: no change to `n_predict`'s formula or any
other production code in `llm_translate.py`'s translation logic itself --
investigated and deliberately left alone per the reasoning above (see
"log_context" below for the one production change actually made). No fix
attempted for the unrelated duplicate-`fetch_and_translate()`-call
pattern also visible in the same live log (the same episode URL fetched
twice within ~1 second, several times across the log) -- noticed during
this investigation but out of scope for what was asked; likely
`prefetch()` racing with a navigation-triggered fetch for the same URL,
not investigated further here.

**`log_context`: episode/URL now included in every warning/error this
code logs, per explicit user request during this same investigation.**
Diagnosing the original failure required manually cross-referencing a
bare `Chunk 3/10: ...` log line's timestamp against a separate, earlier
`Fetching and translating episode: <url>` line elsewhere in the file to
figure out which episode it even belonged to -- real friction hit
directly during this task, not a hypothetical. Added an optional
`log_context: str = ""` parameter, threaded through the full call chain
(`translate_lines()` / `translate_lines_with_masking()` ->
`translate_chunk()` / `translate_chunk_with_masking()` ->
`_translate_chunk_once()`), prefixing every warning/error/info log line
in that chain with `[<log_context>]` when non-empty. Empty string by
default -- every existing call site and test that doesn't pass it is
unaffected (confirmed: full suite passes unchanged before any test
updates were needed for this specific change). `alphapolis_reader.py`'s
own `translate_lines()` wrapper and all three of its call sites in
`fetch_and_translate()` (the masked-translation path, the plain-
translation path, and the title/episode-title call) now pass
`log_context=url` -- the real episode URL is now on every relevant log
line going forward.

**A second real live failure, surfaced by the user mid-task
(`app_log_20260727_121419.log`, episode `7800089`, chunk 9/9,
`Invalid \escape: line 6 column 4`), checked against the fix above and
the existing recovery logic rather than assumed to need new handling.**
This is a different, already-documented failure class from the original
truncation case -- an unescaped backslash inside a JSON string value,
the same corruption class `DESIGN.md` Sections 4/9 document extensively
for this model (`「」` dialogue markers translating into literal
unescaped quote/backslash characters). Confirmed directly: this string
shape reproducibly raises `json.JSONDecodeError` when parsed, meaning it
hits the exact same `except json.JSONDecodeError` branch in
`_translate_chunk_once()` already covered by this task's own tests (the
specific escape character involved doesn't change which code path
fires, only what `json.loads` raises on). The log's own next line
confirms the existing recovery worked correctly here too:
`Chunk 9/9: retrying as 5 individual line(s) after length mismatch`,
followed by `Translation complete: 63 lines` -- no placeholder text, full
recovery. No new test needed for this specific case beyond what already
exists; recorded here as a second, independent real-world confirmation
that the already-existing (and now better-logged) recovery path handles
more than one distinct malformed-JSON failure shape correctly.

**Test coverage (log_context specifically)**: 2 new tests in
`test_llm_translate.py`'s new `TestLogContext` class -- a logged failure
includes the `[<log_context>]` prefix when provided, and omitting
`log_context` entirely produces no prefix (preserving every existing log
message's exact prior format). `black`/`isort`/`flake8` clean. Full
project test suite re-run: no regressions (224 tests total in
`tests/webnovels/`, up from 222 before this addition).

### 2026-07-27: `open_glossary_dialog()` stale-form-on-row-switch bug -- found and fixed, live-verified

A glossary rebuild session on novel 375266002 surfaced a live,
screenshot-confirmed bug in the plain term-list editor opened via
"Glossary..." (`open_glossary_dialog()`): selecting a different row in the
Treeview did not refresh the side form's Source/Target/Type/Note fields --
the form kept showing the previously-selected term's values (e.g.
`ハードキャッチ` selected with correct form data, then `オレ` selected
with the form still showing `ハードキャッチ`'s values). Not cosmetic: if a
user selected row A, didn't notice the form was stale, edited a field, and
hit Save, row A's field values could be committed under row B's identity
-- silent data corruption in the on-disk glossary. Zero prior test
coverage existed for `open_glossary_dialog()`.

**Step 0 (git history check, done before any live reproduction) --
not already fixed.** `git log -L1252,1420:pyplayground/webnovels/alphapolis_reader.py`
showed the last commit touching this dialog's selection-handling lines was
`7aa6e31` ("Add candidate/status term data model to glossary"), which
predates every commit made earlier today (span-level highlighting, the
fallback-to-best-candidate change, the bulk term-review dialog,
`log_context` threading). Nothing in that range had been touched since,
so "already fixed by a later commit" was ruled out cheaply and the bug
needed live reproduction and a real fix, not just reconfirmation.

**Root cause: hypothesis 2 (fires, but repopulates via a stale-index
commit that corrupts the wrong row), not hypothesis 1 (missing binding)
or hypothesis 3 (async/threaded race).** A static read of `on_select` /
`on_select_with_commit` / `commit_selected_form` / `build_form` didn't
show an obvious defect -- `on_select` does call `build_form(terms[index],
index)` on every `<<TreeviewSelect>>`, and no exception was ever printed
to stderr during live reproduction, ruling out a silently-failing/missing
binding (hypothesis 1). `build_form()` and everything it calls are
synchronous -- grep-confirmed no `threading.Thread()` call anywhere in
this code path, unlike `rebuild_glossary()`'s worker thread elsewhere in
the same dialog -- so a background-thread race (hypothesis 3, the
popup-stacking bug's symptom class) was not the mechanism either, and was
confirmed absent via a dedicated fast-sequential-selection test (see
below) rather than assumed absent from the code shape alone.

The actual defect: `commit_selected_form()` (called first, inside
`on_select_with_commit`, to save any in-progress form edits before the
form gets rebuilt for the new row) read `tree.selection()` to determine
which row to save into. Verified directly against a minimal Tk harness
(two-row Treeview, a bound `<<TreeviewSelect>>` handler logging
`tree.selection()`): **by the time `<<TreeviewSelect>>` fires, Tk has
already updated `tree.selection()` to the newly clicked row.** So
`commit_selected_form()` was saving the still-on-screen *previous* term's
field values into the *newly selected* row's `terms[index]` dict --
corrupting it -- before `build_form()` ever ran to rebuild the form from
that (now-corrupted) row. `build_form()` then displayed the just-corrupted
term, which looked from the outside identical to "the form didn't
refresh," but was actually two bugs compounding: a wrong-target commit
followed by a correctly-functioning rebuild off bad data.

**Fix**: added `displayed_index: Dict[str, Optional[int]] = {"value":
None}`, a mutable container (same pattern as the existing `dirty`/
`rebuild_state` trackers in this dialog) recording which row's data the
form currently on screen was actually built from. `build_form()` sets it;
`clear_form()` resets it to `None`. `commit_selected_form()` now commits
against `displayed_index["value"]` instead of a freshly re-read
`tree.selection()`, so it always targets the row the on-screen values
actually belong to, regardless of what the Treeview's selection has
already moved to by the time the event fires. `on_select()` itself is
unchanged -- it still correctly reads the (now-current) `tree.selection()`
to decide which row to build the form *from*; only the *commit* side was
wrong.

**Delete checked directly, not assumed safe.** `delete_selected()` reads
`tree.selection()` from a button-click handler, not from
`<<TreeviewSelect>>` -- a button click is a separate event from the
selection change that precedes it, so by click time `tree.selection()`
already correctly reflects the clicked row with no analogous race.
Verified directly (not just reasoned about) via
`test_delete_removes_the_currently_selected_row_not_a_stale_one`: selects
row A then row B, clicks Delete, confirms row B (not A) is the one
removed. No fix needed here -- same root-cause class checked and found not
to apply, per the task's explicit instruction not to assume it's fine
just because it wasn't in the original report.

**Test coverage**: 6 new tests in `tests/webnovels/test_alphapolis_reader.py`'s
new `TestGlossaryDialogSelection` class, via a new `_GlossaryDialogHarness`
stand-in (only `self.current_url`/`self.root`/`self.set_status()`, grep-
confirmed as everything `open_glossary_dialog()` touches on `self` --
not a full `ReaderApp`, matching the existing harness pattern in this
file). `open_glossary_dialog` is bound straight off `ReaderApp`, so this
exercises the real, unmodified method; selection changes are driven via
real `tree.selection_set()` calls (confirmed to trigger the same virtual
`<<TreeviewSelect>>` event a real click does, not a synthetic shortcut)
against a real Tk `Treeview`/`Entry` widgets, not withdrawn:

- Single selection populates the form correctly.
- Switching selection (A then B) refreshes the form to B's data -- the
  exact bug scenario. **Verified this test actually catches the bug**:
  reverted the fix (`git stash` on just the source file) and reran --
  3 of the 6 new tests failed with the form showing A's data after
  selecting B, confirming the tests are load-bearing, not just
  incidentally passing.
- Multiple sequential selections (5 selections across 3 rows, not just
  one before/after pair) each refresh correctly.
- The exact corruption scenario from the bug report: select A
  (`ハードキャッチ`), select B (`オレ`), edit B's Target field, Save --
  asserts via the mocked `save_glossary()` call that B's `confirmed_target`
  reflects the edit and A's is unchanged.
- Fast-sequential selection with no intervening `root.update()` between
  `selection_set()` calls (per the race hypothesis, tested explicitly
  rather than only via slow deliberate single selections) -- final
  selection's data lands correctly, no staleness.
- Delete-safety regression, per the paragraph above.

`black`/`isort`/`flake8` clean. `mypy`: fixed one new error the change
introduced rather than accepting it -- `displayed_index = {"value": None}`
without an explicit annotation made mypy infer `Dict[str, None]`, which in
turn made it treat `index is not None` as always-false and flag the
`commit_selected_form()` body as unreachable code; adding the explicit
`Dict[str, Optional[int]]` annotation resolved it cleanly. Net result:
403 errors before and after on `alphapolis_reader.py` (baseline
unaffected, zero new errors), matching how this file's pre-existing
untyped-method mypy baseline has been treated in every prior session
rather than introducing inconsistent typing discipline on 2 of ~70+
methods. Full project test suite re-run: no regressions (230 tests total
in `tests/webnovels/`, up from 224 before this task; the 4 pre-existing
`test_term_review_dialog.py` thread-cleanup warnings are unrelated and
predate this change, confirmed via `git stash`).

**Live verification**, per this doc's established `xdotool`/`DISPLAY=:0`
pattern (real, unmodified `python -m pyplayground.webnovels.alphapolis_reader
<url>`, pointed at a cache-hit episode URL for novel 375266002 so
`fetch_and_translate()`'s cache check short-circuits before any
browser/network access is actually used):

- Slow, deliberate single selections: selected `ハードキャッチ`
  (screenshot: form correctly shows "ハードキャッチ" / "demanding
  catch"), then selected `オレ` (screenshot: form correctly updates to
  "オレ" / "Me" -- the exact sequence from the original bug report,
  previously broken, now correct).
- Fast-sequential selection pass (per the race hypothesis, not skipped):
  three rows clicked back-to-back with minimal delay
  (`鉄パイプ`→`オレ`→`ハードキャッチ`) -- final screenshot shows the form
  correctly matching the last-clicked row, no staleness or
  cross-contamination from the earlier clicks in the sequence.
- Full select-A/select-B/edit/Save scenario against the real,
  production on-disk glossary for novel 375266002: selected
  `ハードキャッチ`, selected `オレ`, edited `オレ`'s Target field to
  "I", clicked Save, then read the on-disk glossary JSON directly
  (equivalent to `load_glossary()`) -- confirmed `オレ` -> `"I"` and
  `ハードキャッチ` -> `"demanding catch"` (unchanged). The production
  glossary was restored to its original values (`オレ` -> `"Me"`)
  immediately after this check, since this was real data, not a
  synthetic fixture.
- Both windows involved (`Alphapolis Reader` main window, `Glossary`
  dialog) hit the same two-window-ID gotcha this doc's 2026-07-26 entry
  documented (a `mutter-x11-frames`-owned decoration window alongside the
  real client window) -- resolved the same way, cross-checking
  `xdotool getwindowpid`/`xwininfo` geometry to identify the real content
  window before clicking/screenshotting it.

**Not touched, per explicit task scope**: `open_term_review_dialog()`
(a separate dialog with its own, already-batch-vs-immediate-write
inconsistency tracked as a distinct future item, not this bug's root
cause), the batch-vs-immediate-write inconsistency between the two
dialogs itself, and no candidate-display additions to
`open_glossary_dialog()`.

### 2026-07-27: all per-novel glossary files and cached episodes deleted at the user's request

`~/.config/alphapolis_reader/glossaries/*.json` and
`~/.cache/alphapolis_reader/*.json` deleted (app confirmed not running
first). Accumulated schema/dedup artifacts and test/verification
residue across a long session — no data worth preserving. All findings
documented above (the `オレ`/`鉄パイプ` extraction errors, the
Lanchester's-Law hallucination, the stale-form bug's live verification
against novel 375266002's real glossary, etc.) remain valid as written;
only the underlying on-disk files are gone. Novel 375266002 (and any
other novel previously loaded) will regenerate its glossary and episode
cache from scratch — fresh scrape, fresh `build_glossary.py` extraction
— on next read, now running under the fixed `open_glossary_dialog()`
code above and with none of this session's prior data or bugs carried
forward.

### 2026-07-27: auto-refresh the displayed episode after a glossary edit -- implemented

**Confirmed cost of the existing "Refresh" button before designing
anything, per the task's own explicit prerequisite** (not assumed from
its name): `refresh_current_episode()` deletes both the in-memory
(`self.cache.pop(url, None)`) and on-disk (`_cache_path(url).unlink()`)
cache entries for the current episode, then calls `load_episode(url)`.
With no cache hit left, `fetch_and_translate()` falls through to its
real path: a genuine `self.browser.fetch(url)` network fetch plus a
real LLM translation pass over every line. This is the full, expensive
pipeline, not a cheap re-render -- confirmed live below, not just from
reading the code (a real re-translation of a real 9-paragraph chapter
took roughly 100 seconds against the local translategemma server).

**Why "auto-refresh" can only mean this, not something cheaper**:
`needs_review` flags and span-level term highlighting are computed once
at translation time and cached (`translated_lines`/`needs_review_flags`
in the on-disk cache shape, per `DESIGN.md` Section 11) -- they are not
re-derived live from current glossary state on every render. Confirming
or rejecting a term in either dialog changes nothing about an
already-translated, already-open episode's cached content or on-screen
text. The only way to make the display reflect the edited glossary is
to re-run translation against it, i.e. call
`refresh_current_episode()` -- there is no cheaper "just re-render"
path available, and building one (re-deriving highlighting live on
every render) was explicitly out of scope for this task.

**Design decision, stated explicitly, not defaulted into: debounce to
dialog close, not per Confirm/Reject/Save action.** Given the confirmed
cost above, firing a full re-scrape + re-translate after every
individual edit in a multi-term Review Terms session (e.g. confirming
5 terms in a backlog in one sitting) would mean 5 expensive passes
instead of one. Both dialogs now call a single shared method,
`_maybe_refresh_after_glossary_edit(dialog_novel_id, edited)`, exactly
once, from a single close path per dialog (bound to `WM_DELETE_WINDOW`
*and* invoked directly by every button that ends the dialog session --
Save, Cancel, Close, and the destroy-then-reopen paths inside Clear
Glossary/Rebuild Glossary -- so the check fires exactly once regardless
of *how* the dialog was closed, not just for one specific button; a
button bound straight to `win.destroy()` would silently bypass
`WM_DELETE_WINDOW`, since that protocol only fires for the window
manager's own close action).

**Scope, both conditions required, per the task's explicit narrowing:**

- **At least one actual edit must have happened.** Opening and closing
  either dialog with zero Confirm/Reject/Save actions must not trigger
  anything. `open_glossary_dialog()` tracks this via a new
  `disk_write_happened` flag, deliberately separate from the
  pre-existing `dirty` flag (which tracks in-memory edits that Cancel
  can still discard with no disk write at all -- conflating the two
  would have made a `dirty`-but-Cancelled session incorrectly trigger a
  refresh). Set only at the three points that actually call
  `save_glossary()`: `save_and_close()`, `clear_glossary()`, and a
  successful `rebuild_glossary()`. `open_term_review_dialog()` needs no
  such distinction -- every Confirm/Reject already writes to disk
  immediately (per its own design, documented in this doc's bulk
  term-review entry), so a plain `edited` flag set on either action is
  sufficient and correct.
- **The dialog's novel must match the *currently displayed* episode's
  novel, re-checked at dialog-close time, not dialog-open time.** Both
  dialogs already pin `novel_id` from `self.current_url` once, at open
  time (confirmed in the prior write-timing investigation into these
  same two dialogs). But the main window's displayed episode can change
  independently while either dialog stays open, so
  `_maybe_refresh_after_glossary_edit()` re-derives
  `_extract_novel_id(self.current_url)` fresh at the moment the dialog
  actually closes and compares it against the dialog's pinned
  `novel_id` -- editing novel A's glossary must never refresh novel B's
  episode just because B happens to be on screen when the dialog
  closes.

**Live verification, via the same `xdotool` setup as prior tasks,
against the real app and real novel 375266002 (which turned out to be
a real, scrapable Alphapolis chapter -- "うちの冷蔵庫がダンジョンになった",
confirmed live, not a synthetic fixture for this part):**

- Opened Review Terms, confirmed one `suggested` term (`ハードキャッチ`).
  Cache file's mtime confirmed unchanged immediately after Confirm --
  no refresh fired yet, debounce holding as designed.
- Closed the dialog: the on-disk cache file for the episode was deleted
  within the same action (direct proof `refresh_current_episode()`
  actually ran, not inferred), the main window immediately showed
  "Loading..." and the status bar showed live translation progress
  (`Translating... 1/9`, `4/9`, ...), and the chapter finished
  re-scraping and re-translating successfully end-to-end (real title,
  real author, real paragraphs, a real embedded image) roughly 100
  seconds later.
- Repeated with the exact rapid-fire scenario from the task: added
  three fresh `suggested` terms, confirmed all three back-to-back in
  one Review Terms session (verified via screenshot after each Confirm
  that the tree correctly shrank and the cache file's mtime stayed
  unchanged throughout all three), then closed once. The cache file was
  deleted exactly once, immediately after the single Close click -- not
  after any of the three Confirms -- and the main window again showed a
  single, complete re-translation cycle to completion. Three edits, one
  refresh, confirmed live, not just in the mocked test below.
- One process-level artifact during setup, caught and handled rather
  than left silent: two `xdotool` clicks aimed at the "Review Terms..."
  toolbar button both registered (a retry-timing miss, same class as
  the duplicate-dialog artifact recorded in the retranslation dialog's
  phase 3 entry), producing two independent, correctly-populated
  `Review Terms` windows. Closed the extra one via its own real Close
  button before continuing with a single clean dialog instance -- not a
  defect in this task's code, an `xdotool` interaction artifact.

**Tests** (in `tests/webnovels/test_alphapolis_reader.py`'s new
`TestGlossaryDialogAutoRefresh` and `tests/webnovels/test_term_review_dialog.py`'s
new `TestTermReviewDialogAutoRefresh`, both driving the real bound
dialog methods against real headless Tk widgets, `refresh_current_episode()`
stubbed to a call-recording spy rather than mocking the auto-refresh
logic itself):

- Zero edits (Cancel / Close with no Confirm/Reject) triggers no
  refresh, for both dialogs.
- A Save that wrote to disk triggers exactly one refresh, for
  `open_glossary_dialog()`.
- Three Confirms in one `open_term_review_dialog()` session followed by
  one Close trigger exactly one refresh, not three -- the specific
  scenario named in the task, and the one live-verified above.
- Editing a novel's glossary while the main window displays a different
  novel does not refresh the displayed episode, for both dialogs (using
  the real, unmocked `_extract_novel_id()` against two genuinely
  different URLs, not a fixed-return stub -- an earlier draft of this
  test used a fixed-return mock and could not actually distinguish
  "same novel" from "different novel," passing regardless of whether
  the guard worked; caught before finalizing, not left in as a false
  positive).

Confirmed load-bearing the same way as the prior two tasks: with the
implementation stashed out, both new test files fail to even *collect*
(`AttributeError: type object 'ReaderApp' has no attribute
'_maybe_refresh_after_glossary_edit'`), since the test harnesses mix in
the new method directly -- restored and confirmed all pass again
afterward.

Full `tests/webnovels/` suite re-run: 237 passed (up from 231), no
regressions. `black`/`isort`/`flake8` clean on all touched files.
`mypy`: 412 errors, up from the 403 baseline -- the 9 new errors are
exclusively "missing type annotation" on the new nested `close_dialog()`
closures and the new `_maybe_refresh_after_glossary_edit()` method
itself, consistent with this file's existing untyped-method convention
(the sibling method it calls, `refresh_current_episode()`, is likewise
untyped) -- not fixed here, same treatment this file's mypy baseline
has received in every prior session.

**Not done in this pass**: no cheaper "re-derive highlighting live"
rendering path -- out of scope, per the task's own framing (auto-refresh
can only mean re-translation, given how `needs_review`/span highlighting
are actually computed). The pre-existing cross-dialog stale-overwrite
write-timing inconsistency between `open_glossary_dialog()` (batch-on-
Save) and `open_term_review_dialog()` (immediate-per-action) -- live-
reproduced and confirmed real earlier in this session but not yet fixed
or written up as its own dated entry -- remains open and untouched by
this task; this task's `disk_write_happened`/`edited` flags read
whatever each dialog already writes, they do not change either
dialog's write-timing model itself.

### 2026-07-27: cross-dialog stale-overwrite bug -- confirmed real via live reproduction, NOT fixed (open)

**Status, stated plainly upfront: this is a known, live-reproduced bug
that was investigated in this session but never fixed.** Recording it
here now specifically so it is not lost -- it was mentioned only as an
aside in the auto-refresh entry above, not given its own entry, which
made it too easy to miss on a later skim of this doc.

**The bug**: `open_glossary_dialog()` loads a full in-memory snapshot of
the glossary once, at dialog-open time, and writes it back to disk in
one shot on Save (`save_and_close()`). `open_term_review_dialog()`,
opened separately, writes to disk immediately on every individual
Confirm/Reject, using its *own* separate in-memory snapshot loaded at
its own open time. If both dialogs are open on the same novel at once
-- opening the Glossary dialog, then opening Review Terms on top of it
and confirming a term there -- the Glossary dialog's snapshot has no
way to know about that Confirm. Saving from the still-open Glossary
dialog afterward writes its own stale snapshot back over the file,
silently reverting the Review Terms Confirm with no error, no warning,
and no indication anything was lost.

**Confirmed real, live, not just reasoned about from the code**:
reproduced the exact sequence via `xdotool` against the real app and a
real on-disk glossary file for novel 375266002 -- opened Glossary,
opened Review Terms on top, confirmed `ハードキャッチ`
(`status: suggested` -> `confirmed`, written to disk immediately,
confirmed via direct file read), switched back to the still-open
Glossary dialog (whose Treeview still showed `ハードキャッチ` as
`suggested`, proving its snapshot was already stale), edited an
unrelated term (`オレ`)'s Target field, and clicked Save. The on-disk
file after that Save showed the `オレ` edit landed correctly, but
`ハードキャッチ` had been silently reverted back to
`status: suggested, confirmed_target: null` -- the exact pre-Confirm
state, `updated_at` timestamp reverted along with it. This is real data
loss with no user-visible indication it happened.

Separately confirmed **not** a problem: switching the active novel in
the main reader window while either dialog is open does not misdirect
either dialog's writes -- both pin `novel_id` from `self.current_url`
into a closure at dialog-open time and never re-derive it, verified via
two independent live reproductions (one per dialog) that a save while a
different novel was displayed still wrote to the correct, originally-
intended novel's file.

**Also relevant, found by the user live on-screen during this
investigation (not by this session's own testing) and unrelated to the
write-timing bug above**: `open_glossary_dialog()`'s window is created
with `win.transient(self.root)` but never `win.grab_set()` -- it is not
modal. The main window and other dialogs (e.g. Review Terms) remain
fully interactive while it's open, which is what makes the reproduction
above possible in the first place: a modal Glossary dialog would
prevent a user from ever having Review Terms open at the same time. Not
fixed or scoped here -- recorded because it's very likely the actual
root enabler of the bug above, and any fix design should account for
it (see "what's still needed" below).

**Why this was investigated but left unfixed**: the session's live
`xdotool` interaction hit real friction reproducing the initial
scenario (overlapping dialog windows, one accidental `windowkill` that
crashed the single-process Tk app entirely, several stray/duplicate
agent processes from an earlier delegation misstep) -- confirming the
bug took priority and consumed the available investigation time before
a fix was designed or implemented. This is an honest gap, not a
deferred-on-purpose scope decision like the "not done in this pass"
notes elsewhere in this doc.

**What's still needed** (not started):

- A fix decision between the two approaches named when this bug was
  first scoped: (a) `open_glossary_dialog()` re-checks for external
  changes before its Save actually writes, or (b) convert it to the
  same immediate-write-per-edit model `open_term_review_dialog()`
  already uses. (b) needs a real answer for what Cancel means under an
  immediate-write model before it can be chosen safely -- not
  hand-waved.
- Given the modality finding above, adding `win.grab_set()` to
  `open_glossary_dialog()` (and/or `open_term_review_dialog()`) is
  worth evaluating as an alternative or companion fix -- it wouldn't
  fix stale-snapshot writes from a *sequential* open-edit-close-reopen
  pattern, but it would close off the specific overlapping-dialogs
  reproduction path entirely, which may be a simpler, more robust fix
  than reconciling two independent in-memory snapshots.
- Regression test(s) for the exact reproduction sequence above, written
  to fail pre-fix and pass post-fix, same standard as every other fix
  in this doc.
- Live re-verification of the fixed sequence via `xdotool`, same
  standard as every other fix in this doc.

**Status update, 2026-07-28: fixed and live-verified.** Everything above
this line is preserved as originally written -- the bug description and
reproduction stand as the record of what was found. What follows is the
resolution.

**Approach chosen: (a), re-check-before-write, not (b).** (b) (converting
`open_glossary_dialog()` to immediate-write-per-edit) was rejected
because its prerequisite -- a real answer for what Cancel means under
immediate-write -- does not have a good answer for this specific
dialog. `commit_selected_form()` already runs on *every* row-selection
change, not just on an explicit save action; under immediate-write, that
would mean a disk write on every row click, with no clean point left to
"commit" an in-progress edit short of redesigning the form to autosave
per-keystroke or per-field-blur -- a materially larger UX/structural
change than this bug warrants, and one that would silently break this
dialog's long-standing, documented "edit anything, Save commits
everything" contract (Section 9). (a) is small, local, and additive:
`save_and_close()` now reloads the glossary fresh immediately before
writing and compares `updated_at` against what was captured at dialog-open
time. On divergence, it merges by `source` (a stable, comparable key both
dialogs already use) instead of aborting -- aborting would lose
everything typed in the dialog session with no easy way to reapply it.

**A real bug found in the merge logic itself during live re-verification,
not a hypothetical concern.** The first implementation, on divergence,
applied the dialog's *entire* local snapshot over the freshly-reloaded
on-disk terms (`merged_by_source.update(local_by_source)` for every
source in the dialog's in-memory copy). This reproduced the original bug
through the merge path itself: `local_by_source` still contains every
term the dialog loaded at open time, including ones the user never
touched, so a term confirmed concurrently by Review Terms -- present in
the dialog's stale snapshot as `suggested` -- got silently overwritten
right back to `suggested` by the merge, exactly as if no fix existed.
Caught via the live reproduction below (first attempt), not by
inspection. Fixed by adding `edited_sources`, a set of every `source`
actually visited/edited via `save_form_to_term()` (which runs on every
row-selection commit and on Save, matching this dialog's existing
`dirty`-tracking granularity) or added via `add_term()`. The merge now
only lets the dialog's local copy win, per source, for entries in
`edited_sources` -- every other source falls through to the freshly-
reloaded on-disk value untouched. A term explicitly removed via Delete is
tracked in a separate `deleted_sources` set and popped from the merge
result last, so an explicit delete still wins even if the same source
also exists, untouched, in the newer on-disk snapshot.

**Modality added as a companion, confirmed live it does not replace the
merge fix.** `win.grab_set()` added to `open_glossary_dialog()` only
(not `open_term_review_dialog()` -- that dialog already writes
immediately, so it was never the one holding a stale snapshot, and
making it modal too would block the legitimate case of checking it while
the Glossary dialog is open, which isn't the bug). Confirmed live: with
the Glossary dialog open, clicking "Review Terms..." on the main window
does nothing -- no window opens, closing off the original overlapping-
dialogs reproduction path entirely. Because this closed off the exact UI
path used for the original reproduction, re-verifying the merge fix
itself required simulating the concurrent writer directly (writing to
the glossary file on disk while the modal dialog was open, the same
effect `open_term_review_dialog()`'s `confirm_selected()` has), rather
than opening a second dialog through the UI -- confirming, live, exactly
the point made when this bug was first scoped: modality prevents the
*interactive* overlap, it does not by itself fix a *sequential* stale-
snapshot write (open dialog, something else writes to the file some
other way, Save anyway) -- the re-check-before-write/merge logic is what
actually closes that gap, modality is defense-in-depth on top of it.

**Live re-verification, via the same `xdotool` setup as every prior fix
in this doc, following Step 4's window-management discipline explicitly
adopted for this task to avoid the prior session's specific failures**
(polling for window/process existence rather than assuming readiness,
never `windowkill` on the app's own windows, closing only via the app's
real UI or a process-level `kill` on an unresponsive process, confirming
exactly one `alphapolis_reader` process before and after each launch):

- First attempt (pre-merge-logic-fix): opened Glossary, simulated a
  concurrent Confirm write to the on-disk file (matching what Review
  Terms' `confirm_selected()` does), edited an unrelated term in the
  still-open Glossary dialog, clicked Save. On-disk file showed the
  unrelated edit landed correctly, but the concurrent Confirm was
  reverted -- **the bug reproduced through the merge path itself**, which
  is what surfaced the `edited_sources` gap above. Recorded honestly as
  a real failed attempt, not smoothed over.
- Second attempt (post-`edited_sources`-fix), same sequence: opened
  Glossary fresh, confirmed via live screenshot that "Review Terms..."
  is inert while the modal dialog is open, simulated the concurrent
  Confirm write, edited a different unrelated term (`鉄パイプ`) in the
  still-open dialog (its Treeview still showed the concurrently-confirmed
  term at its old, stale status, confirming the snapshot really was
  stale), clicked Save. On-disk file read directly afterward: **both
  changes present** -- the dialog's own edit applied correctly, and the
  concurrently-confirmed term remained confirmed, not reverted. App log
  confirmed the merge branch fired
  (`... changed on disk while this dialog was open ... merging by source
  instead of overwriting`). The resulting auto-refresh (per the prior
  entry in this doc) then ran a full, real re-translation to completion,
  confirmed via screenshot before the app was closed.
- The previously-confirmed novel-switch safety (both dialogs pin
  `novel_id` at open time) and the auto-refresh debounce (prior entry)
  were not disturbed by this fix -- neither was touched, and the full
  test suite (below) confirms no regression in either area.

**Tests**, in `tests/webnovels/test_alphapolis_reader.py`'s new
`TestGlossaryDialogMergeOnDivergence` (driving the real, unmodified
`open_glossary_dialog()` against a real headless Tk widget tree, with
`load_glossary()` mocked via `side_effect` to return a different,
already-diverged dict on the dialog's second call -- simulating a
concurrent writer without needing two real Tk dialogs open at once):

- The exact original reproduction sequence: edit an unrelated term,
  Save -- the concurrent Confirm must survive, not revert. This is the
  regression test that failed against the pre-fix code (see below).
- No divergence (`updated_at` unchanged between open and Save) saves
  normally, with no merge needed -- confirms the merge path doesn't
  fire when it shouldn't.
- An explicit Delete of one term survives a divergent-Save merge even
  when that same term also exists, untouched, in the fresher on-disk
  copy -- covers the `deleted_sources`-wins-last case directly, not just
  by inspection.

Confirmed load-bearing the same way as every prior fix in this doc: with
the implementation stashed out, the original-reproduction test failed
cleanly (`assert load_glossary_mock.call_count == 2` -- `1 == 2`, since
`save_and_close()` never reloaded without the fix) -- restored and
confirmed all three pass again.

Full `tests/webnovels/` suite re-run: 240 passed (up from 237), no
regressions. `black`/`isort`/`flake8` clean on both touched files.
`mypy`: 412 errors, confirmed identical before and after this change via
`git stash` comparison -- zero new errors introduced (the new
`edited_sources`/`deleted_sources` tracking and the merge logic itself
are additions to already-untyped nested closures, consistent with this
file's existing convention).

**Not done in this pass**: no changes to `open_term_review_dialog()`
itself (still writes immediately per action, unchanged, and deliberately
not made modal -- see the modality reasoning above). No changes to the
auto-refresh logic from the prior entry, confirmed undisturbed by the
full suite re-run. The "what's still needed" list above is now fully
addressed; nothing from it remains open.

### 2026-07-28: duplicate `fetch_and_translate()` calls -- confirmed real, fixed and live-verified

Picks up the side-finding recorded (not investigated) in the `n_predict`/
`log_context` entry above: "the same episode URL fetched twice within
~1 second, several times across the log ... likely `prefetch()` racing
with a navigation-triggered fetch for the same URL, not investigated
further here." This closes that item.

**Step 1 (code reading, confirmed against the actual current code): the
original hypothesis was correct, mechanism confirmed exactly.**
`prefetch()` already guards itself against re-entering for a URL it's
already prefetching (`if ... url in self._prefetching: return`), and
`load_episode()` guards against overlapping loads via a single global
`self._loading` flag -- but neither guard covers the actual gap: a URL
`prefetch()` is currently fetching, racing a *different* call path
(`load_episode()`, via a `Next` click) for that same URL. The trigger:
`display_episode()` calls `self.prefetch(ep.get("next_url"))`
immediately after an episode finishes loading, to warm the next
chapter in the background. If the user clicks `Next` while that
background prefetch is still running for the same URL that's about to
become the navigation target, `go_next()` -> `load_episode(next_url)`
calls `fetch_and_translate(next_url)` directly, with no check against
`self._prefetching` or any per-URL in-flight state at all. Both calls
see a cache-miss (neither has written to `self.cache`/disk yet) and
both proceed to run the full pipeline independently.

**Step 2 (live reproduction, `xdotool` against the real app, real
novel 375266002, cache entries invalidated via a schema-version bump
rather than deleted so the reproduction exercises exactly the
cache-miss path `fetch_and_translate()` actually checks): reproduced on
the first deliberately-timed attempt.** A first, untimed attempt missed
the window entirely (waited for the prefetch to fully finish before
clicking `Next`, which by definition can't race it) -- corrected by
watching the log for episode N's "Episode translated successfully" line
(the exact moment `display_episode()` fires `prefetch()` for episode
N+1) and clicking `Next` immediately at that moment. Log evidence:

```text
07:14:44 - Episode translated successfully: contact
07:14:44 - Fetching and translating episode: .../7800123 (backend=llm)
07:14:45 - Parsed 68 paragraph(s) ... from .../7800123
07:14:45 - Translating 68 lines in 10 chunks ...
07:14:48 - Fetching and translating episode: .../7800123 (backend=llm)
07:14:49 - Parsed 68 paragraph(s) ... from .../7800123
07:14:49 - Translating 68 lines in 10 chunks ...
```

Two independent `fetch_and_translate` entries for the identical URL, 4
seconds apart -- both parsed the page independently (both "Parsed 68
paragraph(s)"), both started their own real chunked LLM translation
pass. Let to completion: both finished
(`Episode translated successfully: night sky` appears twice), one
simply overwriting the other's cache/disk write with a second,
independently-produced (and, since LLM output isn't perfectly
deterministic, potentially slightly different) translation.

**Step 3 (cost quantified with direct evidence, not assumed): the
expensive case, confirmed, not the cheap cache-hit case.** Both log
lines show a genuine chunked translation start (`Translating 68 lines
in 10 chunks`), not an immediate return -- both calls ran the real
`self.browser.fetch(url)` network scrape and the real
`translate_lines()` LLM pass against `translategemma`, independently
and in full, at whatever the model's real per-chunk latency is for
that chapter (this specific chapter took roughly 95 seconds end to end
for the *first* of the two duplicate passes alone). Two real network
scrapes, two real full translation passes, for identical content --
100% wasted work on the losing call, not the cheap case.

**Fix**: an in-flight-request guard, chosen as simplest-and-correct
given what Step 1 found -- the two racing call paths
(`load_episode()`/`Next` and `prefetch()`) both already funnel through
`fetch_and_translate()` regardless of caller, so that single method is
the correct choke point rather than trying to reconcile
`self._loading`/`self._prefetching` (two separate, differently-scoped
flags that were never meant to coordinate with each other). Added
`self._fetch_in_progress: Dict[str, threading.Event]`, a
url -> in-progress marker. `fetch_and_translate()` now splits into
itself (the guard) and a new `_do_fetch_and_translate()` (the actual
work, unchanged in substance, just renamed and extracted). A second
concurrent call for a URL already in `self._fetch_in_progress` waits on
that URL's `Event` instead of duplicating the fetch/translate, then
returns the winning caller's now-cached result. If the winning caller
fails (an exception during fetch/translate), the losing caller falls
through to attempting the fetch itself after waking, rather than
returning `None`/stale data -- same outcome as if no in-flight call had
existed, not a new failure mode.

**A pre-existing type-annotation inaccuracy in this file, surfaced by
this change but not introduced or fixed by it, worth recording
plainly.** `load_cached_episode()` is declared `-> dict` but its actual
implementation returns `None` on a cache-miss/stale-schema case (used
correctly, and checked for, everywhere it's called). `mypy` infers from
the declared (inaccurate) signature that `cached` can never be `None`,
concludes the `if cached is not None:` branch always taken, and flags
the new in-flight-guard code immediately after it as `unreachable` --
a false positive: the guard demonstrably runs (both the new regression
test and the live reproduction below prove it). Not fixed here --
correcting `load_cached_episode()`'s signature to
`Optional[dict]` is a real, separate, pre-existing type-accuracy gap
unrelated to this task's scope, and this file's mypy baseline has
consistently been left alone in every prior session absent a reason to
touch that specific line.

**Live re-verification with the fix, same timing-precise reproduction
technique as Step 2, against a fresh invalidated-cache pair:**

```text
07:27:03 - Episode translated successfully: contact
07:27:03 - Fetching and translating episode: .../7800123 (backend=llm)
07:27:04 - Parsed 68 paragraph(s) ... from .../7800123
07:27:04 - Translating 68 lines in 10 chunks ...
07:27:06 - fetch_and_translate(.../7800123) already in progress on
           another call -- waiting for it instead of duplicating the
           fetch/translate
07:28:38 - Translation complete: 68 lines
...
07:28:39 - Episode translated successfully: night sky
```

Exactly one `Translating 68 lines in 10 chunks` entry, one `Episode
translated successfully`, and the second (`Next`-click) caller's own
log line shows it hit the wait path instead of re-fetching. Confirmed
via screenshot that the waiting caller received the correct, complete
result once released -- the main window displayed episode 2's real
title, real translated paragraphs, and correctly re-enabled
Previous/Next controls; no stall, no error, no blank/partial content.

**Tests**, in `tests/webnovels/test_alphapolis_reader.py`'s new
`TestFetchAndTranslateDuplicateGuard` (driving the real, unmodified
`fetch_and_translate()`/`_do_fetch_and_translate()` against a fake
`browser.fetch()` that blocks on a `threading.Event` until released,
so the test can force two calls to genuinely overlap -- both see a
cache-miss, deterministically -- rather than relying on wall-clock
timing luck the way the live reproduction necessarily did):

- Two threads calling `fetch_and_translate()` for the same URL, the
  second started only once the first has genuinely entered
  `browser.fetch()` (matching the real race's actual precondition:
  both calls see a cache-miss because the winning call hasn't finished
  yet). Asserts `browser.fetch()` is called exactly once (not twice),
  the real translation pass runs exactly once (`llm_translate_lines`
  called twice *per successful run*, by this function's own design --
  once for the body, once for the title/episode_title -- so the
  assertion is `== 2`, not `== 4`, checked explicitly with that
  reasoning stated in the test itself so a future reader doesn't
  mistake the "2" for a bug), and both callers receive the identical
  episode dict object (`results[0] is results[1]`), not two
  independently-produced copies.

Confirmed load-bearing the same way as every prior fix in this doc:
with the implementation stashed out, the test file failed to even
*collect* (`AttributeError: type object 'ReaderApp' has no attribute
'_do_fetch_and_translate'`), since the harness mixes in the new method
directly -- restored and confirmed it passes again.

Full `tests/webnovels/` suite re-run: 241 passed (up from 240), no
regressions. `black`/`isort`/`flake8` clean on both touched files.
`mypy`: 414 errors, up from the 412 baseline -- one is the new
`_do_fetch_and_translate()` method being untyped (consistent with this
file's existing convention), the other is the `load_cached_episode()`
signature-inaccuracy false-positive documented above, not a real defect
in the new code.

**Not done in this pass**: no change to `load_cached_episode()`'s
return-type annotation (a separate, pre-existing gap, not this task's
scope -- see above). No change to `prefetch()` or `load_episode()`
themselves beyond what was needed to route both through the new guard
-- confirmed via `git diff` scope check that only `fetch_and_translate()`
was split/guarded and one new `__init__` attribute was added, nothing
in the prefetch-triggering or navigation logic itself changed.

### 2026-07-28: old-flat-shape term display -- checked and confirmed moot; candidate display in `open_glossary_dialog()` -- decided against

Two related, previously-deferred display items, checked/decided
together per the same task.

**Item 1 (surfacing old flat `target` values as read-only context in
Review Terms): checked first, confirmed moot, not built.** The 2026-07-27
wipe entry ("all per-novel glossary files and cached episodes deleted")
did not leave the glossary directory empty, as a quick skim might
suggest -- both files present on disk right now
(`375266002.json`, `888888887.json`) were created *after* that wipe, by
this session's own later test/verification work. Checked every term in
both files directly, not assumed: **all 9 terms across both files are
already in the new §9 `candidates` shape** (`'candidates' in t` true
for every single one; zero terms with a bare `target` string and no
`candidates` list). A third file found via a filesystem-wide search
(`/tmp/.../scratchpad/glossary_before_repro.json`) is a leftover
scratchpad artifact from an earlier task, not a path the app itself
ever reads, and was checked anyway for completeness -- also all
new-shape.

**Conclusion: item 1 is currently moot.** No old-flat-shape term exists
anywhere on disk the app would load, right now, for any novel. Building
read-only display logic for a data shape with zero live instances would
have been speculative work against a hypothetical, not a real gap --
skipped per the task's own explicit instruction not to do that.
`test_old_shape_terms_with_no_status_field_are_also_listed`
(`test_term_review_dialog.py`, pre-existing) already covers the
*code path* that would handle an old-shape term if one existed, via a
synthetic fixture -- appropriate, since a unit test exercising a code
path doesn't require live production data to justify existing, unlike
building new user-facing display logic would. `test_zero_reviewable_terms_shows_empty_state`
(also pre-existing) covers the actual current real-world case directly.
Both re-run and confirmed passing, no new tests needed.

**Live verification**, via the same `xdotool` setup as every prior task
in this doc (this time with deliberately longer waits between each
step -- window-existence polling extended, and an explicit pause after
each simulated click before checking whether it landed -- since this
environment sometimes requires a manual approval click or has a
mouse-movement/screenshot permission prompt that needs a moment to
clear before a window appears; a prior attempt within this same task
undercounted that and had to retry the same click): launched the real
app against novel 375266002's real, current, all-new-shape glossary,
opened Review Terms. Screenshot confirms it renders correctly and shows
the accurate empty state -- "No unconfirmed terms to review for this
novel." -- with the column headers present and no error, matching what
direct file inspection already predicted. This is the live confirmation
that the moot conclusion holds in the running app, not just on disk.

**Item 2 (candidate display in `open_glossary_dialog()`): decided
against, explicitly, not defaulted into.** `open_glossary_dialog()`
remains the plain, raw list/form editor -- edit anything, batch-save on
Save, no candidate ranking. Reasoning: this codebase already has three
dialogs touching glossary terms, each with one clear, distinct job --
`open_glossary_dialog()` (raw editing, any term, any status),
`open_term_review_dialog()` (backlog review, ranked candidates, real
Confirm/Reject), and `open_word_glossary_popup()` (in-context single-
term lookup with live reference/alternatives). Adding candidate display
to `open_glossary_dialog()` too would duplicate a feature that already
has a dedicated, purpose-built home in the review dialog, and would
blur exactly the distinction `open_term_review_dialog()`'s own
docstring already gives as the reason it was built as a *separate*
dialog in the first place rather than an extension of this one. Three
dialogs with three jobs stays clearer than two dialogs each trying to
do a bit of both.

**Not done in this pass**: no display-logic changes to either dialog --
item 1 turned out to have nothing to display for, and item 2 was a
"don't build this" decision. No changes to `glossary.py`'s schema or
any term-shape handling -- confirmed via `git diff` scope check that
this task touched only `DESIGN.md`.

### 2026-07-28: background glossary extraction -- investigated (Steps 1-2), proposal only (Step 3), nothing implemented

Investigation-first task, deliberately: confirm extraction's real cost
and `merge_terms()`'s real safety before proposing any auto-trigger
mechanism, and do not implement anything -- this entry records
findings and a proposal, not a shipped feature.

**Step 1: extraction is confirmed NOT incremental -- the single most
important finding here, exactly as flagged going in.**
`build_glossary_for_novel()` (`build_glossary.py`) calls
`_load_cached_episodes_for_novel(novel_id)` (line 376), which
unconditionally returns *every* cached episode belonging to that
novel -- there is no field anywhere in the episode dict or the
glossary dict recording "extraction has already run against this
episode." The result is only capped by `max_episodes` (default 20,
most-recently-cached-first), not by what's new since the last run.
Every call -- whether the "Rebuild Glossary" button today, or any
future auto-trigger -- re-runs a real `extract_glossary_terms()` LLM
call for every episode in that (up to 20-deep) slice, every single
time, including episodes already processed in a prior run.
`merge_terms()` deduping on `(type, source)` means re-extracted terms
that already exist just get silently dropped on merge (see Step 2),
so re-processing is not *unsafe* -- but it is genuinely wasted,
growing LLM cost every time it runs, confirmed by reading the actual
loop logic (`build_glossary.py:392-419`), not inferred from the
function's name or docstring.

**Step 2: the `merge_terms()` safety claim holds, confirmed directly
against current code -- and one real gap found and named, at the
`build_glossary_for_novel()` level, not inside `merge_terms()` itself.**
`merge_terms()` (`glossary.py:622-655`) builds `known_keys` from
`existing` up front and only appends a new term if its `(type,
source)` key isn't already present (lines 647-654) -- it never
modifies, replaces, or drops an existing entry. This matches the
docstring exactly, confirmed by reading the logic, not taken on the
doc's word.

**The gap**: `build_glossary_for_novel()` calls `load_glossary(novel_id)`
exactly **once**, before its per-episode extraction loop starts (line
385), and only writes back via `save_glossary()` once, after the
entire loop finishes (line 425) -- and this function runs on a
background thread specifically so it doesn't freeze the UI while
making "one LLM call per episode" (confirmed via `rebuild_glossary()`'s
own docstring in `alphapolis_reader.py`), which for up to 20 episodes
can run for minutes (a single episode's *translation* alone was
independently measured elsewhere in this doc at ~90-100 seconds; a
20-episode extraction run is a comparable or longer order of
magnitude). If a user manually confirms a term via
`open_term_review_dialog()` or the right-click Add-to-Glossary popup
*while that background extraction is still running*, that manual write
lands on disk immediately (both paths write through
`upsert_confirmed_term()`/`save_glossary()` synchronously) -- but the
extraction thread's in-memory `glossary` variable was loaded before
that write and is never refreshed mid-loop. When extraction finishes
and does its own single `save_glossary()` call, it writes back its own
stale in-memory copy, silently overwriting and discarding the manual
confirmation that happened during the run. Checked directly whether
the UI actually allows this: `rebuild_glossary()`'s
`set_dialog_controls_enabled(False)` only disables controls within the
*same* `open_glossary_dialog()` instance that started the rebuild --
it does not touch `open_term_review_dialog()` or the right-click
popup, both separate windows with no awareness of a running
background rebuild. The gap is real and reachable through the existing
UI today, not a theoretical one requiring true-simultaneous timing --
structurally the same class of bug as the cross-dialog stale-overwrite
bug found and fixed earlier in this doc, just between extraction and a
manual dialog instead of between two manual dialogs. Named plainly per
the task's instruction, even though for a single user clicking through
chapters at normal reading speed the actual window to hit it (having a
review dialog open and confirming a term in the middle of a multi-
minute background rebuild) is narrow, not something to block this
investigation on fixing here.

**Step 3: proposal, not implemented.** Given Step 1's finding
(non-incremental, real and growing per-call cost) and the slot-
contention concern named when this was originally scoped (the LLM
server has limited concurrent slot capacity, documented elsewhere in
this doc's `-np 2`/`--kv-unified` investigation) -- triggering
extraction immediately after every single episode's translation
completes would compete with the *next* chapter's translation for that
same shared slot if the user navigates quickly, exactly the risk named
up front.

**Recommendation: an idle trigger, not a per-episode trigger.** Start
(or reset, on every subsequent episode load) a single cancellable Tk
timer (`self.root.after(N * 1000, ...)`) in `display_episode()`;
firing `build_glossary_for_novel()` in the background only after N
seconds with no further navigation, not immediately per-episode. This
means extraction only actually runs once the user has stopped actively
flipping through chapters, not fighting translation for the shared LLM
slot mid-read-session. It also keeps the mechanism appropriately
simple for what the task specifies this is -- a single-user, single-
machine tool with no concurrent-reader contention to design against: one
timer, no queue, no per-episode bookkeeping beyond what already exists.

**This recommendation is explicitly contingent on Step 1's finding
being addressed first, as its own separate task -- not bundled into
whatever implements the trigger.** Auto-triggering extraction on an
idle signal without first making it incremental would still mean every
idle period re-runs a full (up to 20-episode) re-extraction pass,
which is wasteful regardless of how well-timed the trigger is. Per the
task's explicit instruction, that incremental-extraction fix is named
here as a prerequisite, not attempted in this pass.

**Not done in this pass, deliberately, per the task's own scope**: no
trigger mechanism implemented. No fix to extraction's non-incremental
behavior. No fix to the `build_glossary_for_novel()`-vs-manual-dialog
race named in Step 2 (named, not fixed -- narrow enough in practice for
a single user that it doesn't block this investigation, but real).
Confirmed via `git diff` scope check that this task touched only
`DESIGN.md` -- no code changes.

---

### 2026-07-28: WM_DELETE_WINDOW crashes the whole app under Xvfb -- confirmed real via live reproduction, NOT fixed (open)

Found while building and live-verifying `pyplayground/webnovels/ui_testing/`
(the new agent-driven UI testing module, see `agents-ui-testing.md`) against
the real running app under a dedicated Xvfb display. Not a testing-tooling
quirk to route around silently -- a real, reproducible full-application
crash triggered by an otherwise-ordinary window-close request.

**Reproduction, confirmed directly, multiple times**: launch the app under
Xvfb (`Xvfb :99` + `fluxbox`), open any Toplevel dialog (Load Novel tested
explicitly; Glossary/Review Terms/Settings not individually re-confirmed but
share the same Toplevel/WM_DELETE_WINDOW mechanism), then send a
WM_DELETE_WINDOW close request via `xdotool windowclose <dialog-window-id>`.
The entire process dies. The app's own stdout/stderr (captured via
`launch_and_track(stdout_log=...)`) shows:

```text
X Error of failed request:  BadWindow (invalid Window parameter)
  Major opcode of failed request:  10 (X_UnmapWindow)
  Resource id in failed request:  0x<varies per run>
node:events:487
      throw er; // Unhandled 'error' event
Error: write EPIPE
    at WriteWrap.onWriteComplete [as oncomplete] (node:internal/stream_base_commons:87:19)
```

The crashing window id varies run to run -- not a fixed stale handle, a real
X_UnmapWindow hitting a window some client no longer considers valid, at the
moment WM_DELETE_WINDOW is processed.

**Isolation performed to narrow the cause, not just observed and reported**:

1. **Ruled out Xvfb/fluxbox themselves as the cause.** A minimal standalone
   Tk script (a root window, one button opening a Toplevel with its own
   Cancel button calling `.destroy()`) was run against the exact same live
   Xvfb display. `xdotool windowclose` against that dialog closed it cleanly
   with no crash. The display and window manager are not the trigger.
2. **Ruled out the dialog-close mechanism in general.** Clicking the real
   app's own dialog Cancel/Close button (which calls Tk's `.destroy()`
   directly -- confirmed for Load Novel, Glossary, Review Terms, and
   Settings, all four) closes the dialog and leaves the app running fine.
   Only the WM_DELETE_WINDOW protocol path (`xdotool windowclose`) crashes it,
   not window-closing as a concept.
3. **Ruled out live Playwright fetch activity as a precondition.** The crash
   was reproduced against a cache-hit episode load, where
   `fetch_and_translate()` returns from `load_cached_episode()` before ever
   calling into the `BrowserWorker`/Playwright request path (see
   `fetch_and_translate()`, `pyplayground/webnovels/alphapolis_reader.py`).
   The crash does not require an in-flight fetch, only that the process's
   `BrowserWorker` thread (and its headless Chromium child, started
   unconditionally in `main()` before the Tk window even exists) is alive at
   all.

**What is implicated, not yet confirmed as root cause**: the app's
`BrowserWorker` launches Chromium via Playwright's Node.js driver
(`headless=True`, see `BrowserWorker.run()`). The Node.js EPIPE and the
`X_UnmapWindow`/`BadWindow` error strongly suggest Playwright's Node driver
process holds its own X11 connection to the same `DISPLAY` (plausible even
in headless mode, e.g. via a sandboxing or GPU-capability check at Chromium
launch), and that connection's handling of an X protocol event triggered by
WM_DELETE_WINDOW is what actually crashes -- not anything in the Tk app's
own code. This is a plausible mechanism, not a confirmed one.

**Explicitly NOT yet answered, and this matters for prioritization**:

- **Does this reproduce outside Xvfb** (a real XWayland desktop session)?
  Not tested -- doing so requires a human-supervised real-desktop session
  (see `agents-ui-testing.md`'s Guardrail section), which this investigation
  did not have available. If it reproduces there too, this is a severe,
  user-facing crash bug in ordinary use (closing a dialog the normal way,
  if the OS/WM ever sends WM_DELETE_WINDOW instead of routing through a
  button handler) and should be re-prioritized above anything else queued.
  If it is genuinely Xvfb-only, it is most likely a cheap environment-level
  fix (give `BrowserWorker`'s Chromium/Node driver its own isolated
  `DISPLAY`, separate from whichever Xvfb instance is used for UI testing)
  rather than an app bug to chase further.
- **Exact mechanism inside Playwright's Node driver** -- not traced further
  than the isolation above. Would need instrumenting or straceing the Node
  process specifically, not the Python process, to pin down.

**Not done in this pass, deliberately**: no fix attempted. No workaround
beyond documenting it and having `pyplayground/webnovels/ui_testing/`'s own
test suite avoid `windowclose`/WM_DELETE_WINDOW against this app entirely
(closing every dialog via its own real Cancel/Close button instead -- see
`xdo_helper.close_window()`'s docstring and `test_menu_smoke.py`). Left open
here specifically so it doesn't get lost the way an earlier finding this
session briefly did.

---

### 2026-07-29: synthetic test-fixture novels used the real alphapolis.co.jp domain with fabricated novel IDs -- confirmed real, fixed

**The problem, stated plainly**: every synthetic test fixture built during
Phase 2/3's live verification (novel IDs `777777777` and, from an earlier
session, `888888887`) used episode URLs of the shape
`https://www.alphapolis.co.jp/novel/<fake-id>/1/episode/<n>` -- a
fabricated novel ID under the **real** Alphapolis domain, not a
non-resolving placeholder. This repo's own `alphapolis_translate.py`
docstring states plainly that Alphapolis' `robots.txt` disallows
automated access and that this codebase's scraping is meant for
personal, one-off use, not repeated/bulk automated requests. Every time
one of these fixtures' on-disk cache got wiped (deliberately, e.g. by
`refresh_current_episode()`'s auto-refresh path after a glossary edit,
or as a side effect of an aborted live-verification run) and the app
was subsequently launched against that URL, `fetch_and_translate()`'s
cache-miss path runs unconditionally into `_do_fetch_and_translate()`,
which logs "Fetching and translating episode: ..." and then calls
`self.browser.fetch(url)` -- a real Playwright/Chromium navigation
against the real Alphapolis site -- with nothing in between that could
short-circuit it. A fabricated ID doesn't make this any safer: the
request still leaves this machine and reaches Alphapolis' real
infrastructure before failing (with a 404 or similar), which is exactly
the kind of automated request the site's own policy asks not to be
made, however small in volume.

**Confirmed, not assumed, that this actually happened, and more than
once**: grepped every `logs/app_log_*.log` file from this session for
`"Fetching and translating episode"` lines. Found **5 separate
occurrences** against
`https://www.alphapolis.co.jp/novel/777777777/1/episode/1` (2026-07-29,
across several live-verification runs in Phase 3's own checkpoints,
each one a case where this fixture's cache had been wiped -- by an
auto-refresh, or by an aborted/killed run -- and a subsequent launch or
retry hit the cache-miss path before the cache was restored). Every
other fetch logged this session was against the real novel
`375266002` -- legitimate, expected traffic. No other fabricated novel
ID (`999999998`, `999999997`, `12345`) ever triggered a real fetch
attempt in this session's logs. Each of the 5 log files ends
immediately at or shortly after the fetch-attempt line, consistent with
the app being killed (via this session's own `kill -TERM`/`kill -9`
cleanup calls, used because the app appeared stuck) before any response
was logged -- meaning the exact server-side outcome of each request
(whether it reached Alphapolis, what it received back, or whether the
connection was torn down mid-flight by the kill) is not knowable from
these logs alone. The blast radius is bounded (at most 5 attempted
connections, all extremely short especially where killed quickly) but
real, not zero, and not previously flagged as its own issue -- the one
prior mention (`REFACTOR_DESIGN.md`'s Phase 3d entry) noted the
resulting Playwright timeout as an expected consequence of refreshing a
"non-existent" URL without registering that "non-existent" here meant
"a fake path on a real site," not "a URL that cannot be reached at
all."

**A second, independent instance of the same pattern found during the
retroactive sweep, not just the one already known**: `888888887`, a
synthetic novel fixture predating this conversation (a "novel-switch
repro" scenario, unreferenced by any current test or source file --
confirmed via `grep -rn "888888887"` across the whole repo returning
zero hits), had two cached episodes on disk, both also using
`https://www.alphapolis.co.jp/novel/888888887/...`. Neither had
actually triggered a fetch this session (no matching log lines), but
both carried the identical latent risk the moment their cache aged out
or got wiped.

**Fix**: rebuilt all fixture cache entries for both `777777777` (3
episodes) and `888888887` (1 episode, consolidating two slightly
differently-shaped stale duplicates into one canonical entry) under
`https://www.example.invalid/...` instead -- `example.invalid` is
reserved by RFC 2606 specifically for this purpose (guaranteed to never
resolve in DNS, unlike a real domain returning a 404, which still
requires a live round-trip to reach). Confirmed directly, not assumed:
`socket.gethostbyname("www.example.invalid")` raises `gaierror`
immediately, and a real `requests.get()` against it fails with a local
`NameResolutionError` before any packet leaves the machine. Rebuilt via
`save_cached_episode()` (the real production function), not by hand-
editing JSON, so the cache schema/hashing is exactly what the app would
have produced itself. `_extract_novel_id()`'s regex
(`r"/novel/(\d+)/"`) matches on path structure only, not domain, so the
novel ID still resolves correctly (`777777777`/`888888887`) against the
new URLs -- confirmed directly, not assumed.

The old real-domain cache files for `777777777` were deleted outright
(by the user, directly). The old real-domain cache files for
`888888887` were invalidated in place (this repo's established
technique for cache invalidation without deletion, per
`agents-ui-testing.md`'s own documented pattern: overwrite with a
mismatched `_cache_schema_version` and a placeholder in the `url`
field) rather than deleted, since this session's own tooling permissions
don't allow `rm`. Confirmed this is actually sufficient, not just
assumed: `_load_cached_episodes_for_novel()` (the function
`build_glossary_for_novel()` uses to enumerate a novel's cached
episodes) does **not** check `_cache_schema_version` at all, so an
invalidated entry still surfaces in its results -- but with the `url`
field overwritten to a non-URL placeholder string containing no real
domain, `_extract_novel_id()`/any fetch attempt reading that field finds
nothing fetchable, closing the risk even though the file itself
remains present.

**Full sweep confirmed clean**: checked every cache file under
`~/.cache/alphapolis_reader/` for any remaining entry combining
`alphapolis.co.jp` with a known-fabricated novel ID (`777777777`,
`888888887`, `999999998`, `999999997`, `12345`, `99999`) -- none found.
Checked every glossary file under
`~/.config/alphapolis_reader/glossaries/` for an embedded `url` field --
confirmed glossary files never carry one (per `glossary.py`'s schema),
so they carry no independent fetch risk regardless of novel ID.

**Live-verified the fix, not just the file contents**: launched the
real app against the new `https://www.example.invalid/novel/777777777/1/episode/1`
URL under `pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb-keep`
-- cache-hit succeeded, episode displayed and rendered correctly
(screenshot confirmed, URL bar showing the new domain), whole-session
log swept for `ERROR`/`CRITICAL`: clean. App terminated cleanly via
`kill -TERM`, Xvfb/fluxbox torn down afterward.

**Not done in this pass**: no change to any source file -- this was
purely an on-disk test-fixture data issue, not a code defect. No
retroactive fix attempted for whatever Alphapolis-side state the 5 real
requests may have left (rate-limit counters, access logs, etc.) -- out
of this repo's control and not something to speculate about further.
Going forward, any new synthetic test-fixture novel created in this
repo should use `example.invalid` (or another RFC 2606 reserved
non-resolving domain) from the start, not a fabricated ID under the
real Alphapolis domain.

### 2026-07-29: fetch-failure exceptions were never logged via `logger.error()` -- confirmed real, fixed

**How found**: while investigating what a user actually sees when
`_do_fetch_and_translate()`'s Playwright fetch fails (timeout, DNS
failure, HTTP error), traced the full exception-handling chain --
`BrowserWorker.run()`'s inner try/except puts `("error", traceback)` on
a queue, `BrowserWorker.fetch()` re-raises it as a `RuntimeError`, and
`load_episode()`'s inner `worker()` (`alphapolis_reader.py`, ~line
1739) is where it's actually caught. That handler did show a real,
visible Tk error dialog (`show_error()`) with the full traceback and
set the status bar to "Error" -- not a silent hang, and not a generic
unhelpful message. But it only called `print(full_trace,
file=sys.stderr)`, never `logger.error(..., exc_info=True)`, in direct
violation of this project's own mandated logging pattern (every
exception must be logged, not just printed).

**Why this matters beyond one call site**: this session's entire
testing methodology -- `log_correlator.assert_clean()`,
`wait_for_log_line()`, every Phase 3 dual-verification checkpoint --
assumes a clean structured log means nothing went wrong. This finding
proved that assumption false for an entire category of real failures:
a fetch error produced zero trace in `logs/app_log_*.log`, only in an
ephemeral stderr stream nothing captures or checks. `assert_clean()`
would report "clean" on a run that had actually failed -- a blind spot
in the safety net itself, not a peripheral bug.

**Scope check performed before fixing**: grepped the whole
`pyplayground/webnovels/` tree for the same
`print(traceback.format_exc(), file=sys.stderr)` /
`print(full_trace, file=sys.stderr)` pattern in background-thread/
worker exception handlers, not just the one call site the investigation
happened to look at. Found five real gaps in `alphapolis_reader.py`,
all missing `logger.error(..., exc_info=True)` entirely:

- `_make_photo_image()` (~line 861) -- failed episode image load.
- `_do_fetch_and_translate()`'s image-prefetch loop (~line 1689) --
  failed image prefetch mid-translation.
- `load_episode()`'s `worker()` (~line 1741) -- the original finding,
  the fetch-failure path a user actually hits.
- `prefetch()`'s `worker()` (~line 2526) -- silent-by-design background
  prefetch, but a failure here previously left literally zero trace
  anywhere in the app's own structured log.
- `main()`'s `BrowserWorker()` startup failure (~line 3107) -- app
  fails to start Playwright/the browser at all.

One additional site (`glossary_coordinator.py`'s `start_rebuild()`
worker) already had a correct `logger.error(..., exc_info=True)` call
alongside its `print()` -- left untouched, already correct. A sixth
`print(..., file=sys.stderr)` in `build_glossary.py`'s CLI argument
parser was confirmed out of scope -- that's user-input validation in a
CLI entry point (`sys.exit(2)` on bad input), exactly the case
`CLAUDE.md` exempts ("print() ... except CLI tools"), not a swallowed
background-thread exception.

**Fix**: added `logger.error(f"...", exc_info=True)` immediately
alongside the existing `print(..., file=sys.stderr)` at each of the
five gaps -- additive, not a replacement; the existing user-facing
`show_error()` dialog behavior and the stderr output (still useful when
running from a terminal) are both left exactly as they were.

**Regression test**: added
`TestLoadEpisodeFetchFailureLogging.test_fetch_failure_is_logged_via_logger_error`
(`tests/webnovels/test_alphapolis_reader.py`) -- a minimal
`_LoadEpisodeHarness` drives the real, unmodified `load_episode()`
against a `fetch_and_translate` stand-in that raises, and asserts via
`caplog` that a `logger.error()` record was actually produced, with
`exc_info` set. Confirmed load-bearing: reverted
`alphapolis_reader.py`'s fix via `git stash`, re-ran the test, watched
it fail cleanly (`assert []` -- no error records at all), then restored
the fix.

**Live-verified the fix, not just the unit test**: reproduced the same
real Playwright DNS failure from the original investigation (an
invalidated cache entry for novel `777777777`'s episode 1 under
`https://www.example.invalid/...`) under
`pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb-keep`. Before
the fix, the structured log's last line was always
`[_do_fetch_and_translate] - Fetching and translating episode: ...`,
with the actual failure appearing nowhere in it. After the fix, the
same run's log now contains a real
`ERROR - [worker] - Failed to load episode https://www.example.invalid/... : Browser fetch failed:`
line immediately following, with the full nested traceback attached via
`exc_info=True` -- confirmed directly by reading the log file, not
assumed. App terminated cleanly via `kill -TERM`, cache file restored
from backup, Xvfb/fluxbox torn down afterward.

**Verification**: `black`/`isort`/`flake8` clean on both touched files;
full `tests/webnovels/` suite passes (273 passed; the only failures
were 6 pre-existing `ui_automation` environment errors from a stale
duplicate window ID left on a different Xvfb display by unrelated
manual testing, confirmed unrelated by checking no `Alphapolis Reader`
window existed on the display this session actually used).

**Not done in this pass, queued separately**: the error dialog itself
(`show_error()`) still shows a raw, unfiltered, ~40-line double-nested
Python/Playwright traceback with the actual root cause
(`net::ERR_NAME_NOT_RESOLVED`, etc.) buried at the very end, requiring
scrolling to find. This is a real but lower-stakes UX issue -- it
doesn't undermine the log-based safety net the way the missing
`logger.error()` call did, since the dialog was never silent to begin
with. No urgency; worth trimming to a user-friendly summary (with the
full trace kept available, collapsed/secondary) whenever there's a
natural moment for UI polish, not fixed here.
