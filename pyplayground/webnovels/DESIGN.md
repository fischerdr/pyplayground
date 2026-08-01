# Glossary & Reader Redesign — Design Doc

Living record of decisions for the glossary/term-consistency rework and the
Tkinter → web migration. Update this alongside code changes, not after —
chat history is not the system of record.

**2026-07-31: split for length.** This doc had grown to 3,560+ lines, mostly closed/fully-resolved investigation and bug-fix entries. Those moved verbatim to `DESIGN_ARCHIVE.md` (see §14's index below for what moved and where). This doc now keeps: foundational context (§1-3), the core validated design decisions (§4-5, trimmed to conclusions), current policy/status summaries for completed work (§9-12, pointing to the archive for implementation narrative), the forward-looking web migration plan (§7), the live open-questions tracker (§8), and anything genuinely still unresolved (§13). For current system behavior, `GLOSSARY_ARCHITECTURE.md` is the authoritative reference, not this doc's historical entries.

Last updated: 2026-07-31

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


### 2026-07-25: Qwen3-14B retested via `/v1/chat/completions` + `--jinja` — summary only, full writeup archived

Bracket-inline and XML-tag sentinel formats were ruled out definitively (0% survival under proper chat-template conditions too, not just raw `/completion` — this is real model behavior, not a template artifact). Opaque placeholder showed a *different* failure mode than the original empty-string collapse: unescaped-quote JSON corruption on dialogue-bearing lines (42% survival at `thinking=False`). Net effect: no change to the locked decision — translategemma + opaque placeholder remains production for `translate_chunk_with_masking()`, now disqualifying Qwen3 on two independent grounds instead of one. Full retest detail, the sampling-confound caveat, and the `reasoning_content` separation finding: `DESIGN_ARCHIVE.md`.

## 5. Model notes

- `translategemma-12b-it` (production): translation-tuned, validated for chunk translation + sentinel masking (§4). Not reliable for factual/classification tasks (Lanchester's Law hallucination, §1).
- `Qwen3-14B-GGUF:Q8_0`: **closed, not viable for this codebase.** Tested and rejected across every task shape tried — sentinel-masked translation via raw `/completion` (empty-string collapse) and via `/v1/chat/completions` (quote-escaping JSON corruption), and glossary extraction via `/v1/chat/completions` across two server KV-cache configs (garbled/repetition-loop output, root cause unresolved but conclusion doesn't depend on which). Reopen only on a specific new reason (different quant, `-np 1` isolation for an upstream bug report, or a different model generation) — not a default revisit item. Full investigation trail: `DESIGN_ARCHIVE.md`.
- `Qwen3.6-35B-A3B` (MoE, considered, not pursued): larger capacity, built-in thinking mode. Requires `/v1/chat/completions` + `enable_thinking` control. Shelved pending Qwen3-14B results, which closed negatively — status unchanged, still not pursued.
- Reference research on other self-hostable candidates (GemmaX2-28-9B, Tencent HY-MT1.5/HY-MT2, Seed-X-7B) saved separately — see pickup list item on LLM-layer review; not yet tested against this codebase's harness.

## 6. Deferred scope (explicit, not forgotten)

All three original items resolved:
- `mask_targets` producer: implemented (§10 summary below; full entry archived).
- Reader UI `needs_review` consumption: implemented and later extended to span-level highlighting (archived entries; current behavior in `GLOSSARY_ARCHITECTURE.md`).
- Recurrence/promotion logic: split — count-building implemented (§12 summary below; full entry archived); the promotion-threshold half remains genuinely open, see §8.

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

(Section-number pointers below — §5, §9-12 — now refer to the short summaries in this trimmed doc; full historical detail for each is in `DESIGN_ARCHIVE.md`.)

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


## 9. Term data model (current shape)

Migrated (2026-07-25) to the `status`/`candidates`/`confirmed_target` shape described in §3 — `STATUS_CONFIRMED`/`STATUS_SUGGESTED` constants, `make_confirmed_term()`/`make_suggested_term()` constructors, `format_glossary_for_prompt()` filtering to confirmed-only. No backward compatibility was built (pre-production data, clean cutover). Full migration scope, deviations found during implementation (the `note`-field preservation catch, the editor-Save-confirms judgment call), and verification detail: `DESIGN_ARCHIVE.md`. Current authoritative shape: `GLOSSARY_ARCHITECTURE.md`.

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


## 10. `mask_targets` producer (current behavior)

`build_mask_targets(lines, glossary)` in `glossary.py` — pure function, masks any term where `status != "confirmed"`. Handles multi-occurrence, cross-line recurrence, and overlapping-substring terms (longer match wins). Full implementation entry, edge cases, and verification: `DESIGN_ARCHIVE.md`.

## 11. Sentinel masking in production (current behavior)

`translate_chunk_with_masking()`/`translate_lines_with_masking()` wired into `_do_fetch_and_translate()`'s live translation path — real production callers, not dead code (a stale docstring once claimed otherwise; see the pickup-list item to fix it). Two-tier fallback: missing sentinel → raw word spliced in + `needs_review=True`; empty line → retry once, then unmasked fallback + `needs_review=True`. Full wiring entry and verification: `DESIGN_ARCHIVE.md`.

## 12. Count-building loop (current behavior)

`update_candidate_counts()` in `glossary.py` — increments a confirmed term's matching candidate count when its `confirmed_target` appears in real translated output for a chunk where `needs_review=False`. Does not touch `suggested` terms, does not discover new candidates, does not auto-promote anything (see §8's still-open promotion-threshold question). Full entry: `DESIGN_ARCHIVE.md`.

## 13. Currently open, unresolved findings

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

- **Does this reproduce outside Xvfb** (a real desktop session)? Tested
  2026-08-01 -- see the dated entry immediately below. Answer: no, it does
  not reproduce with a real WM_DELETE_WINDOW on the real desktop.
- **Exact mechanism inside Playwright's Node driver** -- not traced further
  than the isolation above. Would need instrumenting or straceing the Node
  process specifically, not the Python process, to pin down. Lower priority
  now that real-desktop risk is confirmed low (see below).

**Not done in this pass, deliberately**: no fix attempted. No workaround
beyond documenting it and having `pyplayground/webnovels/ui_testing/`'s own
test suite avoid `windowclose`/WM_DELETE_WINDOW against this app entirely
(closing every dialog via its own real Cancel/Close button instead -- see
`xdo_helper.close_window()`'s docstring and `test_menu_smoke.py`). Left open
here specifically so it doesn't get lost the way an earlier finding this
session briefly did.

**Status: confirmed Xvfb/Playwright-specific, real-world risk is low, staying
as documented workaround.** See 2026-08-01 entry below for the real-desktop
test that settled this.

### 2026-08-01: Real-desktop WM_DELETE_WINDOW reproduction test -- does not reproduce

Follow-up to the entry above, specifically closing its one unanswered,
prioritization-critical question. Run on the user's actual live desktop
session, not a fresh Xvfb instance: `DISPLAY=:0`, the active `seat0`/`tty2`
login session (confirmed via `who`/`loginctl list-sessions`; no `Xvfb` or
`fluxbox` process was running anywhere on the machine at the time). The
app was launched via `xdo_helper.launch_and_track()` with stdout captured,
plus the app's own `logs/app_log_*.log`. Every close action in every
scenario was a real click from the user's own mouse on the real title-bar
close button -- never simulated via `xdotool windowclose` -- since the
entire point was to test the authentic WM_DELETE_WINDOW path a human's
ordinary use actually takes, not a re-run of the simulated path already
confirmed to crash under Xvfb.

The original Xvfb reproduction's exact episode URL/state was not recorded
in this doc or `agents-ui-testing.md` and was treated as an accepted,
unrecoverable gap rather than searched for further -- justified by the
existing isolation already showing the crash reproduces on a cache-hit
load with no live fetch involved (content-independent). The saved
resume-last-read state (`~/.config/alphapolis_reader/state.json`) was used
instead.

**Four scenarios run in order, none crashed:**

1. **Baseline (idle, main window close).** App launched, left idle, user
   clicked the main window's real title-bar close X. Process exited
   cleanly; stdout/app log showed only normal startup lines, no traceback.
2. **Dialog close, idle.** Glossary dialog opened with no fetch running,
   user clicked the dialog's real title-bar close X. Main process
   remained alive and unaffected; dialog closed normally.
3. **Dialog close, active fetch.** A real (non-cached) chapter
   fetch/translation was triggered and confirmed still in progress
   (log showed translation actively chunking, no completion line yet) when
   the user closed the Glossary dialog via its real title-bar close X.
   Main process remained alive; the in-flight translation was unaffected.
4. **Main window close, active fetch.** A second real fetch was triggered
   (log confirms it was genuinely in flight -- translation of a new
   episode had started chunking with no completion line logged) and the
   user closed the *main window* itself via its real title-bar close X
   while it was running. The process did exit this time, but the shutdown
   was clean, not a crash: no coredump was generated (`coredumpctl list`
   showed nothing for this process/time window), no ABRT registration, no
   segfault/crash entry in the journal for that window, no leftover
   orphaned Chromium/Node child process (consistent with `browser.close()`
   in `on_close()` running to completion), and neither the captured stdout
   nor the app log contained the `BadWindow`/`X_UnmapWindow` or Node
   `write EPIPE` signature seen in the Xvfb case. This matches a normal
   `on_close()` -> `browser.close()` -> `root.destroy()` shutdown path, not
   the documented crash.

**Conclusion**: zero reproductions of the Xvfb crash signature across all
four scenarios on the real desktop, including the scenario closest to the
original Xvfb repro (active fetch + WM_DELETE_WINDOW). This confirms the
crash is specific to the Xvfb/Playwright/simulated-WM_DELETE_WINDOW
interaction and does not manifest in ordinary real-world use of the app.
Real-world risk from this bug is low. No fix needed beyond the existing
workaround (the UI test suite continuing to avoid `xdotool windowclose`
against this app, per the entry above). Not re-prioritized.

### 2026-08-01: `safe_persistence.py` foundational design -- implemented and migrated

`pyplayground/utils/safe_persistence.py` now holds two general-purpose
helpers, exactly as originally designed: `atomic_write()` (temp file in
the same directory as the target, `fsync()`, then `os.replace()`; unique
per-write temp filename via PID + random suffix; temp file cleaned up on
any exception before the replace) and `verify_before_write()` (capture/
reload/compare/dispatch only -- no domain vocabulary, divergence handling
always supplied by the caller as a callback).

Every direct file-write call site identified in the original design pass
was migrated onto `atomic_write()`, in the documented order, each step's
acceptance bar confirmed before moving to the next: `save_json_config()`
(`config_utils.py`, and transitively `save_cached_episode()`), then
`save_glossary()` (`glossary.py`) and `save_global_vocabulary()`
(`global_vocabulary.py`) independently, then
`GlossaryCoordinator.save_snapshot()` and `open_retranslate_popup()`'s
stale-popup guard migrated onto `verify_before_write()`, both passing
their existing divergence logic (merge-by-source; skip-and-warn) through
verbatim as callbacks. `TestGlossaryDialogMergeOnDivergence` and
`TestAcceptStalePopupGuard` both pass unmodified against the migrated
code -- confirming this was a relocation of mechanism, not a behavior
change.

New unit tests for the two helpers themselves, independent of any call
site: `tests/utils/test_safe_persistence.py` (14 tests), including a
simulated mid-write failure (`os.replace()` forced to raise) confirming
the original target file is left byte-for-byte untouched, and coverage
of `verify_before_write()`'s unchanged-marker and diverged-marker
dispatch paths with a neutral placeholder domain (no glossary/episode
vocabulary).

Live-verified under Xvfb + fluxbox against the real running app (not
simulated): a real Glossary Save (`GlossaryCoordinator.save_snapshot()`
-> `save_glossary()` -> `atomic_write()`) with the resulting temp file
directly observed on disk mid-write via a polling watcher, matching the
documented `.{name}.{pid}.{random}.tmp` pattern, with no orphan left
after a clean replace; and a real Retranslate-line Accept
(`open_retranslate_popup()`'s stale-popup guard, now routed through
`verify_before_write()`, followed by `save_cached_episode()` ->
`atomic_write()`), confirmed via `strace -e trace=rename,openat` attached
to the live app process, showing the exact `openat()` (temp file,
`O_CREAT|O_TRUNC`) followed by `rename()` sequence the design calls for.
Both writes landed correctly (valid JSON, correct content, correct
cache/glossary key) with clean app logs (no ERROR lines) both times.

### 2026-08-01: short-line JSON-malformation pattern -- quantified, confirmed real, not fixed (investigation only)

Follow-up to the two JSON-malformation failure classes `DESIGN_ARCHIVE.md`
already documents (2026-07-25: the unescaped-literal-quote corruption from
`「」` dialogue markers translated as literal `"` instead of `\"`; the
"Invalid control character" `json.JSONDecodeError` class recovered by
`translate_chunk()`'s per-line retry). Suspected but previously unquantified:
that very short lines -- onomatopoeia, single-word shouts, and especially
`「「「...」」」`-style collective-shout constructions -- are disproportionately
likely targets, versus ordinary dialogue/narration hitting the same failure
classes for unrelated reasons.

**Method**: scanned all 26 files in `~/.cache/alphapolis_reader/` (18 real
episode-scale caches with 3-77 lines each, 8 tiny 1-2 line test fixtures).
For each, compared `lines` (source) against `translated_lines` (output),
counting `[translation failed...]` placeholders and a stray-quote-artifact
regex (`""` or a bare `"` glued between word characters -- the literal shape
the archived 2026-07-25 finding shows, e.g. `'""Look, ...""'`) against every
source line, recording the source text for every flagged line. Script kept
at `/tmp/claude-.../scratchpad/scan_short_line_json.py` (scratchpad, not
committed -- one-off investigation tool, not reusable production code).

**Result, real numbers**: 1,042 lines scanned across the 18 real episodes.
**Zero** `[translation failed]` placeholders anywhere in current cache --
the per-line retry path (§ archived 2026-07-26 finding) is evidently
succeeding on every case in this corpus, so that failure class leaves no
visible trace in cached output today. **6 stray-quote-artifact lines**,
all 6 sharing one exact shape: **100% were `「「「...」」」` collective-shout
constructions** (`「「「キャアアアー！！」」」` -> `'""Kyaaa!""'`,
`「「「わぁぁああ～～！」」」` -> `'""Waaaaah!""'`, and four more of the same
form). Zero ordinary dialogue/narration lines were flagged by either check.

**Quantified against the full denominator, not just the flagged set**: of
361 lines in the corpus containing `「`/`」` at all, 138 are short enough to
classify as bracket-only/shout-shaped (stripped of brackets/punctuation,
<=12 chars) and 223 are ordinary-length bracket-bearing dialogue. The 6
corruptions come entirely from the 138-line short/shout bucket (**6/138 =
4.3%** corruption rate) against **0/223 (0%)** for ordinary-length bracket
lines. The pattern is not "any use of `「」`" -- it is specific to the
short/doubled-bracket collective-shout shape.

**Step 3 (chunk-level vs. single-line path)**: no request-level logs exist
for these cached episodes (only final cache output), so this couldn't be
checked directly against live traffic. Indirect evidence points away from
it being chunk-position-specific: every one of the 6 corrupted lines sits
embedded in an ordinary multi-line chunk between long narration/dialogue
lines that translated cleanly (confirmed by reading the surrounding source
lines directly, e.g. `01ce04390f13...` line 45's neighbors are 40+
character narration sentences with no corruption). Since zero
`[translation failed]` placeholders exist in this corpus, the per-line
retry path (which re-sends a failing line alone, isolated from its chunk)
must be running clean on some fraction of retries -- but a retry re-sending
the exact same short-shout text is exposed to the same model behavior that
produced the corruption the first time, so isolation to a single-line
request is not expected to be a reliable fix by itself. This is inference
from indirect evidence, not a confirmed trace -- flagged as the one part
of this investigation that would need live request logging to settle
properly, not asserted as fact.

**Proposed fix (not implemented, per this task's scope)**: the corruption
is the model rendering `「」` as literal `"` without escaping when the
entire line content is just repeated brackets around a short exclamation --
i.e., a masking/prompt problem, not a JSON-parsing problem (matches the
archived finding: `parse_json_response()`'s trailing-content tolerance
can't rescue this because the malformation is internal to the JSON string
value). Two candidate directions, in order of how directly they target
what Steps 1-2 actually found:

1. **Pre-normalize collective-shout lines before sending to the model** --
   detect the `「「「...」」」`-doubled shape (the same short/bracket
   classifier used for this investigation) and either strip the outer
   bracket layer before the prompt (translate the bare exclamation only,
   the brackets are decorative/emphasis in source and carry no dialogue
   content the model needs to preserve) or route it through a cheaper
   deterministic path entirely (many of the 6 examples --
   `ざわざわ…` -> "Rustling...", `キャアアアー！！` -> "Kyaaa!" -- are
   simple enough that a small onomatopoeia/exclamation lookup table might
   avoid the LLM call altogether for this specific shape).
2. **Post-process repair**: since the corruption shape is narrow and
   consistent (`""text""` wrapping), a targeted regex fixup on
   `translate_chunk_with_masking()`'s output for lines matching the
   shout-classifier could strip the doubled/stray quotes after the fact,
   without changing the prompt at all. Lower confidence this generalizes
   past the 6 examples seen -- narrower fix for a narrow, already-observed
   symptom rather than the underlying model behavior.

Both need validation against a live model run (not just this cache
snapshot) before either is built -- 6 instances across 18 episodes is a
real, confirmed signal, not yet a large enough sample to be confident a
fix generalizes.

**Not done in this pass, deliberately**: no fix implemented (task scope
was investigation and quantification only). No live model calls made --
this analysis is entirely against already-cached, already-translated
output. No check of `[translation failed]` corpus history (there is none
currently on disk) or of whether the 2026-07-25 empty-string-collapse
class shows the same short-line skew, since no instances of that class
exist in current cache to classify.

### 2026-08-01: bracket-stripping fix validated live against translategemma -- eliminates the corruption, meaning preserved (implemented and verified -- see follow-up entry below)

Follow-up to the entry immediately above, closing its "needs validation
against a live model run" gap for fix direction 1 (pre-normalize/strip the
outer `「」` layer before prompting). No sub-agent delegation -- this was
one sequential script making live HTTP calls against a single shared model
server; there was no independent, parallelizable step to hand off.

**Corpus for this test**: re-derived the candidate set directly from cache
rather than reusing the original 6 examples alone, to get a larger sample.
Tightened the classifier from the investigation's `<=12 char` heuristic to
the mechanically precise shape -- **doubled or tripled bracket layers**
(`「「...」」` / `「「「...」」」`, regex `「{2,}|」{2,}`), i.e. the actual
collective-shout construction (multiple speakers voiced via repeated
bracket pairs), not just "any short bracketed line." This found **21** such
lines across the cache (vs. 138 under the looser heuristic, which included
ordinary single-speaker short exclamations like `「なにっ！？」` that never
corrupted). Of the 21, the same 6 originally flagged as corrupt in cached
output are a subset.

**Method**: reused the real production code path directly, not a
reimplementation -- imported `TRANSLATION_PROMPT`, `LLM_ENDPOINT`,
`LLM_MODEL`, `parse_json_response()`, `strip_code_fence()`, and
`_clean_output()` from `llm_translate.py` unmodified, and built single-line
`/completion` requests with the exact same payload shape
`_translate_chunk_once()` sends (`temperature: 0.1`, matching `stop`
sequence, `n_predict` scaled the same way), just without going through the
full chunk-batching/masking machinery -- deliberately, since this validates
the prompt-shape fix itself, not the pipeline plumbing (task scope: no
production wiring). For each of the 21 lines, called the model twice: once
with the source line unmodified (matching current behavior), once with all
`「`/`」` characters stripped (`re.sub(r"「+", "", s)` then same for `」`,
i.e. "translate the bare exclamation only"). Script:
`/tmp/claude-.../scratchpad/validate_bracket_strip.py`, raw output saved to
`validate_results.json` in the same scratchpad directory (not committed --
one-off validation tool).

**Result, real numbers, live against `mradermacher/translategemma-12b-it-GGUF:Q4_K_M`
at `http://flyyn:10001`**: **13/21 (61.9%) corrupt with brackets sent to
the model unmodified** -- higher than the 6/21 (28.6%) the cached snapshot
showed, because sampling isn't perfectly deterministic run-to-run even at
`temperature=0.1`; several previously-clean cached lines (e.g.
`c574a6d5316d` idx 52/54, `` 「「「……」」」 `` -> clean `"..."` in cache) hit
a JSON parse error this run instead. **0/21 (0%) corrupt with brackets
stripped before prompting.** Every single corrupted case, including ones
the original cache scan had recorded as clean, was clean when brackets
were stripped. Confirmed not a single lucky sample: re-ran 5 of the
stripped-input cases 3x each (`temperature=0.1` still, same as
production) -- byte-identical, uncorrupted output on all 15 repeat calls.

**Real before/after examples** (source / cached-or-live-original output /
live-stripped output):

- `「「「キャアアアー！！」」」` -> live-original `'""Kyaaa!""'` (corrupt)
  -> stripped `'Kyaaa!'` (clean, same meaning)
- `「「「なんだとぉ！」」」` -> live-original `'""What the heck!""'`
  (corrupt) -> stripped `'What did you say!'` (clean, same meaning,
  arguably closer to the source than the corrupt variant's paraphrase)
- `「「ッ！？」」` -> live-original `<<PARSE_ERROR: Expecting ',' delimiter
  ...: '["""]'>>` (total parse failure, not just a stray-quote artifact --
  this line produced literal `[""" ]`, a shape `parse_json_response()`
  cannot recover) -> stripped `'Huh?!'` (clean)
- `「「「ざわざわ…」」」` -> live-original `'""Zawah, zawah...""'` (corrupt)
  -> stripped `'Zazazawa...'` (clean, but see caveat below)
- `「「「（わぁ～！）」」」` -> live-original `'"" (Waa!)""'` (corrupt) ->
  stripped `'(Wow!)'` (clean, parenthetical preserved)

**Meaning/quality comparison**: stripping the brackets did not change
translation meaning in any of the 21 cases -- the model translates the
same exclamation content whether or not the (redundant, purely
typographic) bracket layer is present, consistent with the original
proposal's reasoning that the brackets carry no dialogue content beyond
what the enclosed text already conveys. **One pre-existing quality
caveat, not caused by bracket-stripping**: `ざわざわ` (crowd-murmur
onomatopoeia) was rendered as a romanized transliteration (`Zazazawa...`)
rather than an English equivalent (`Rustling...`, which is what the
original *corrupted* cached output for this same line happened to
contain) in both the original and stripped live calls -- this is an
existing onomatopoeia-translation quality issue independent of the
corruption bug, not something this fix introduces or fixes. Flagged for
awareness, out of scope for this task.

**Fix direction 2 (regex post-process) not tested** -- direction 1
validated cleanly enough (0/21 live corruption, stable across repeats,
no meaning loss) that there was no need to fall back and test the
post-process alternative. Not ruled out for other reasons, just
unnecessary given direction 1's result.

**Proposed hook-in point (proposal only, not implemented)**:

- **Where**: `translate_chunk_with_masking()` and the plain
  `translate_chunk()`/`translate_lines()` path in `llm_translate.py`,
  immediately before each line is placed into its chunk's `lines_json`
  payload (i.e. before `_translate_chunk_once()` builds the prompt) --
  strip, translate, then re-wrap the *output* in a single `「」` pair (or
  leave unwrapped, a product decision, not a technical one) so the
  reader-facing translated line still reads as dialogue if that matters
  for rendering; this needs a product answer, not an engineering one, and
  wasn't tested here since it's downstream of the parsing fix.
- **Detection rule**: the tightened doubled-bracket regex confirmed above
  (`「{2,}|」{2,}`), not the looser `<=12 char` heuristic from the
  original investigation -- the looser rule would have applied
  bracket-stripping to 138 lines including 132 that never corrupted,
  needlessly touching content the fix doesn't need to touch. The precise
  trigger is "the line's *entire* bracket content is a doubled/tripled
  layer around a short exclamation," not "the line is short."
- **Scope note**: this was tested only via direct single-line
  `/completion` calls, not through `translate_chunk_with_masking()`'s
  full masking/sentinel/splice machinery. Before implementing, the actual
  hook-in should be checked against a chunk that mixes a doubled-bracket
  line with sentinel-masked terms on adjacent lines, since that
  interaction was never exercised here.

**Not done in this pass, deliberately**: no code changed in
`llm_translate.py` or any production call site -- validation only, per
task scope. No test suite changes. No check of whether stripping
interacts with `mask_terms()`/`splice_terms()` sentinel placement (see
scope note above). No investigation of the `ざわざわ` transliteration
quality gap beyond noting it exists.

### 2026-08-01: bracket-stripping fix implemented and verified -- sentinel interaction confirmed clean, live UI verification passed

Implements exactly the two entries above -- no redesign. No sub-agent
delegation: this was a single sequential implement/test/verify pass in one
file plus its tests, with no independent step worth parallelizing.

**Code change (`llm_translate.py`)**: added `_is_collective_shout()`
(the validated `「{2,}|」{2,}` detection, tightened from the
investigation's looser `<=12 char` heuristic per the validation entry's
proposal) and `_strip_collective_shout_brackets()`. Hooked into
`_translate_chunk_once()` at the exact point specified -- `lines` is
transformed into `prompt_lines` (brackets stripped per-line where
`_is_collective_shout()` matches) immediately before `lines_json =
json.dumps(...)` builds the payload, and every returned entry at a
matching index is re-wrapped in a single `「」` pair before being handed
back, in both of this function's return paths (the single-line
duplicate-collapse branch and the normal per-line return). Because
`translate_chunk()` and `translate_chunk_with_masking()` both funnel
through `_translate_chunk_once()` (masking calls `translate_chunk()`
internally), one hook point covers both paths named in scope without
duplicating logic -- no changes were needed in `translate_chunk()`,
`translate_chunk_with_masking()`, `translate_lines()`, or
`translate_lines_with_masking()` themselves.

**Sentinel-interaction check -- the mandatory, explicitly-flagged risk,
not skipped.** `mask_terms()` runs in `translate_chunk_with_masking()`
before `translate_chunk()`/`_translate_chunk_once()` is ever called, so by
the time the bracket-stripping hook sees a line it only needs to leave
`⟦`/`⟧` sentinel glyphs untouched -- confirmed true both by direct code
reading (the strip only touches `「`/`」` characters) and by live testing
against the real model, not just unit tests:

- Live call 1 (three-line chunk: an ordinary line with a masked glossary
  term, a doubled-bracket collective-shout line adjacent with no masking,
  another ordinary line) -- `ケイトが振り返った。` / `「「「なんだとぉ！」」」` /
  `ルリが微笑んだ。` with `mask_targets=[(0, "ケイト")]`. Result:
  `ケイト turned around.` (needs_review=True, sentinel spliced correctly),
  `「What did you say!」` (needs_review=False, clean re-wrapped output, no
  corruption), `Ruri smiled.` (needs_review=False, unaffected). Sentinel
  position/splice on line 0 was not disturbed by the bracket-stripping
  hook running on line 1 in the same chunk request.
- Live call 2 (masked term whose word sits inside the collective-shout
  line itself): `「「「鉄パイプだ！」」」` with `mask_targets=[(0, "鉄パイプ")]`.
  Result: `「鉄パイプ it is!」` (needs_review=True) -- the sentinel survived
  stripping+re-wrapping around it and spliced back correctly at the right
  position.
- Live re-check of all 6 originally-corrupted cases through the real,
  unmodified `translate_chunk()` call path (not the validation entry's
  standalone script): all 6 now return clean, re-wrapped output (e.g.
  `「「「キャアアアー！！」」」` -> `「Kyaaa!」`, `「「「なんだとぉ！」」」` ->
  `「What did you say!」`), 0/6 corrupt.

**Test coverage** (`tests/webnovels/test_llm_translate.py`, 9 new tests,
27 total in the file, all passing): `TestCollectiveShoutDetection` --
`_is_collective_shout()` correctly detects all 21 real cases from the
investigation/validation entries and correctly does NOT fire on a set of
ordinary dialogue/narration lines (single-bracket short exclamations and
long narration), confirming the narrow trigger doesn't over-fire; strip
correctness on two representative cases. `TestCollectiveShoutStripInTranslateChunk`
-- an end-to-end (mocked model) regression test running all 21 real cases
through `translate_chunk()`, asserting both that the *sent* prompt had
brackets stripped (via a mock that decodes the actual outgoing payload
rather than a fixed canned response) and that the final output is
re-wrapped with no stray-quote artifact; a matching test confirming
ordinary lines pass through completely unmodified; a mixed-chunk test
confirming only the matching line gets re-wrapped. `TestCollectiveShoutStripWithSentinelMasking`
-- the sentinel-interaction case as its own explicit test (mirroring the
live check above, mocked), plus a second test for a masked term sitting
inside the shout line itself. `black`/`isort`/`flake8` clean on both
`llm_translate.py` and the test file; `mypy` clean on `llm_translate.py`
(strict mode, no new untyped code).

**Live UI verification** (`tests/webnovels/ui_automation/test_bracket_strip_live.py`,
run via `run_ui_tests.sh xvfb`/`xvfb-keep`, never `windowclose`): re-ran
the real `translate_lines_with_masking()`/`save_cached_episode()` path
locally (no network re-fetch -- the episode's source HTML was already
scraped and cached from a prior real load) against episode
`.../375266002/37695490/episode/7801892`, whose cached lines 45/49
(`「「「キャアアアー！！」」」`) were the two originally-confirmed-corrupt
cases from the quantification entry (`""Kyaaa!""` in the old cache).
After re-translating through the fixed code, both became `「Kyaaaar!」`
in the on-disk cache. Launched the real app against this episode under
Xvfb: automated test (`test_translated_mode_shows_clean_rewrapped_output`)
screenshotted the app and confirmed `log_correlator.assert_clean()`
against the app's real log, and a direct on-disk cache check
(`test_cache_file_confirms_no_stray_quote_artifact_reached_disk`)
confirmed no `""` artifact at indices 45/49 and correct `「...」`
re-wrapping. Both passed. Followed up with an additional manual visual
check (same Xvfb session, Translated-mode view, scrolled to the relevant
lines) showing both instances rendering as clean `「Kyaaaar!」` in plain
blue (not amber/needs-review) text on screen, with no `""`-artifact
anywhere in the visible chapter. App log for this session had zero
ERROR/CRITICAL lines. Xvfb/fluxbox torn down cleanly afterward via
`run_ui_tests.sh xvfb`'s own teardown.

**Not done in this pass**: no `CACHE_SCHEMA_VERSION` bump -- same
reasoning as the 2026-07-26 `needs_review` scope-gap entry's precedent,
this is a translation-quality/prompt-shape change, not a cache shape
change; existing cached episodes with the old corrupted output will not
retroactively clean up until re-translated (Refresh). No change to
`mask_terms()`/`splice_terms()`/the sentinel format itself. No fix for
the separately-noted, pre-existing `ざわざわ`-style onomatopoeia
transliteration-vs-translation quality gap (unrelated to this bug, out of
scope).

**Status: implemented, unit-tested, sentinel-interaction verified both in
tests and live, and live-UI-verified end-to-end. Closed.**

---


## 14. Archive index

Everything below moved verbatim to `DESIGN_ARCHIVE.md` on 2026-07-31 (one stale header corrected in the process — the cross-dialog stale-overwrite entry's title still said "NOT fixed (open)" after it had actually been fixed and live-verified; corrected during the move). All closed, none actionable:

- Qwen3-14B retested via `/v1/chat/completions` + `--jinja` (2026-07-25)
- Qwen3-14B fails glossary extraction across every tested configuration (2026-07-25)
- Reader UI consumption of `needs_review` — implemented, step 1 of 3 (2026-07-25)
- Visual/click verification of `needs_review` (2026-07-26)
- Term data model migration — scope and implementation (2026-07-25)
- `mask_targets` producer — implemented (2026-07-25)
- Wiring `translate_chunk_with_masking()` into production — implemented (2026-07-25)
- Count-building loop — implemented (2026-07-25)
- `needs_review` scope gap found and fixed on genuine live content (2026-07-26)
- Dedup bug in the manual Add to Glossary save path (2026-07-27)
- `needs_review` span-level highlighting and click resolution (2026-07-27)
- `splice_terms()` candidate fallback instead of raw source text (2026-07-27)
- Bulk term-review dialog — implemented (2026-07-27)
- `translate_chunk()` error-recovery test gap closed; `n_predict` theory inconclusive (2026-07-27)
- `open_glossary_dialog()` stale-form-on-row-switch bug (2026-07-27)
- All per-novel glossary files/cached episodes deleted at user's request (2026-07-27)
- Auto-refresh the displayed episode after a glossary edit (2026-07-27)
- Cross-dialog stale-overwrite bug — fixed and live-verified (2026-07-27/28)
- Duplicate `fetch_and_translate()` calls — fixed and live-verified (2026-07-28)
- Old-flat-shape term display moot; candidate display decided against (2026-07-28)
- `open_glossary_dialog()` blank-Target bug + independent no-dirty-check bug, both fixed (2026-07-30)
- Background glossary extraction investigated — superseded by `REFACTOR_DESIGN.md` Phase 3e/3f (2026-07-28)
- Synthetic test-fixture novels used the real alphapolis.co.jp domain — fixed (2026-07-29)
- Fetch-failure exceptions never logged via `logger.error()` — fixed (2026-07-29)
