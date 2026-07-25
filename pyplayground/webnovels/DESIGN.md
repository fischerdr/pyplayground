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

## 5. Model notes

- `translategemma-12b-it` (existing): translation-tuned, validated for
  chunk translation + sentinel masking. Not reliable for
  factual/classification tasks (Lanchester's Law hallucination).
- `Qwen3-14B-GGUF:Q8_0` (new, port 10002, no `--jinja`/thinking flags):
  candidate for extraction/`explain_term()`. **Not yet validated for that
  use** — only tested (and rejected) for sentinel-masked chunk translation.
  Next validation step: run `extract_glossary_terms()` against the episodes
  that produced the Lanchester's Law/Keito/Rinai errors and check both (a)
  clean JSON parse via `parse_json_response()`, (b) whether the specific
  errors are actually fixed.
- `Qwen3.6-35B-A3B` (MoE, considered, not pursued): larger total capacity,
  built-in thinking mode. Requires `/v1/chat/completions` +
  `enable_thinking` control to use correctly — bigger integration change
  than a model swap. Shelved pending Qwen3-14B results.

## 6. Deferred scope (explicit, not forgotten)

- `build_glossary.py`: decide how low-confidence/unconfirmed extractions
  become `mask_targets` for `translate_chunk_with_masking()`.
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
- Qwen3-14B validation for extraction/`explain_term()` — not yet run.
  Independent of §9; no ordering dependency either way.

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
