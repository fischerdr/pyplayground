# Glossary & Reader Redesign — Design Doc

Living record of decisions for the glossary/term-consistency rework and the
Tkinter → web migration. Update this alongside code changes, not after —
chat history is not the system of record.

Last updated: 2026-07-25

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
- Reader UI: consume `needs_review` — distinct highlight style from
  confirmed terms, click opens the term editor pre-filled (reuses the
  existing Add-to-Glossary dialog shape).
- Recurrence/promotion logic: no term currently gets auto-promoted from
  `suggested` to `confirmed` based on repeated appearance; count-building
  loop (§3) accumulates counts but promotion threshold is undecided.

## 7. Web migration plan

**Current state**: Tkinter desktop app (`alphapolis_reader.py`). Term
highlighting is Tk text-widget tags over character ranges — the
span-mapping logic (given text + glossary, produce styled spans) is pure
data transformation with no Tkinter dependency once separated from the
render call.

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
4. **Review-queue UI (new)** — candidate picker, confirmed vs. suggested
   styling, consumes `needs_review` from masking output. This doesn't exist
   in Tkinter at all; build it web-native here rather than porting a
   Tkinter version that was never built.
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
