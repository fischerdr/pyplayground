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

### 2026-08-03: `<ruby>`-wrapped status-window term fragments `_extract_content()` into single characters -- confirmed real, distinct from the `「」` collective-shout bug, not fixed (investigation only)

Investigation of a translation-quality report against a live URL, not a
fix. Distinct root cause from the `「」` doubled-bracket collective-shout
corruption fixed above (that bug is in the *translation* prompt path,
`llm_translate.py`; this one is in the *HTML-extraction* path,
`_extract_content()` in `alphapolis_reader.py:400-426`) -- unrelated
mechanisms that happen to both involve bracket characters.

**Report**: episode
`https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7802171`
-- a character status/stat window (bracket-enclosed skill list, e.g.
`【強酸】２・【俊敏】２・...`) renders badly in Interleaved mode.
Original-side "lines" include isolated single characters/punctuation
(`【` alone, `・` alone, `】` alone, a bare kanji alone) that aren't real
source paragraphs, alongside one correctly-translated short line (`塩`
-> "Salt"). The new status-bar paragraph count (STATUS_BAR_DESIGN.md
Phase 2, `len(ep["lines"])`) reports 94 paragraphs for this chapter.

**Method**: fetched the exact URL live via a standalone Playwright script
(same launch args as `BrowserWorker.run()` -- headless Chromium, same
UA/locale, `wait_for_selector("#novelBody, .p-novel-episode__text")`),
saved to `/tmp/claude-.../scratchpad/episode_7802171.html` (not
committed -- one-off fetch). Then ran the real, unmodified
`_extract_content()` from `alphapolis_reader.py` against the fetched
`#novelBody` via BeautifulSoup to reproduce `ep["lines"]` exactly as
production would build it.

**Raw HTML found** (`#novelBody`, skill-list line): the status window is
otherwise one flat run of Japanese text with `<br>` tags separating
display lines (level, race/job, ability values, blessings, skills,
titles -- about 6-8 real display lines represented as a text run per
`<br>`-delimited segment). Within the skill list specifically, one term
is singled out and wrapped character-by-character in `<ruby>` tags, each
with an `<rt>` reading of a single `・` (dot) character -- a Japanese
typographic emphasis-dot (`傍点`) convention, not real furigana:

```html
【強酸】２・...【瞑想】・<ruby>【<rt>・</rt></ruby><ruby>塩<rt>・</rt></ruby><ruby>】<rt>・</rt></ruby><ruby>7<rt>・</rt></ruby>・【図工】・...
```

That one term is `【塩】7` ("Salt", skill level 7) -- plot-relevant: the
following narrative paragraphs are about this exact skill leveling up
from 5 to 7, which is presumably why the site's author/typesetter
emphasized it with dots.

**Fragmentation confirmed**: reproduced with a minimal standalone
BeautifulSoup repro (`body.descendants` walk matching
`_extract_content()`'s logic exactly) against just this one line. The
single logical skill-list segment produces 11 `NavigableString`
fragments where a human would read one; the `<ruby>`-wrapped term alone
turns into 8 of those fragments: `'【'`, `'・'`, `'塩'`, `'・'`, `'】'`,
`'・'`, `'7'`, `'・'` -- each `<ruby>`'s base text and its `<rt>` sibling
each yield their own `.strip()`-truncated NavigableString, since
`_extract_content()` treats every string descendant as an independent
"line" regardless of shared parent structure or adjacency. This exactly
matches the report: isolated `【`, isolated `・` (the "." in the report),
isolated `】`, isolated single kanji (`塩`), and that one kanji
fragment happens to translate correctly in isolation ("Salt") because
it's a real word standing alone, not because the extraction is correct.

**94-count check**: running the actual `_extract_content()` against the
fetched HTML reproduces exactly **94** text items, confirming the
status-bar count (STATUS_BAR_DESIGN.md Phase 2) is accurately reporting
what `ep["lines"]` already contains -- it is not itself introducing or
amplifying the fragmentation, only surfacing a pre-existing count. Of
those 94, items 19-26 (8 items) are pure noise from the one `<ruby>`
cluster; items 4-30 (27 items) cover the whole status window, which a
human skimming the rendered page would count as roughly 6-8 real lines.
So this single status window inflates the chapter's real paragraph count
by roughly 20-25 items out of 94 (~25%), entirely from one `<ruby>`
cluster plus ordinary `<br>`-per-field splitting that is arguably
correct behavior for a stat block (each stat *is* visually its own
line) -- the actual bug is narrowly the `<ruby>` fragmentation, not the
`<br>`-per-field splitting.

**Blast radius**: checked the immediately adjacent episodes in the same
novel (prev: `.../episode/7802124`, next: `.../episode/7802331`) --
zero `<ruby>` tags in either, and neither contains a status window
(`技能：`/`能力値` markers absent). The target episode itself contains
exactly one `<ruby>` cluster (4 tags, all wrapping the single emphasized
term), not one per bracketed skill entry -- most of the ~20 other
bracketed skills/titles/blessings in the same window are plain text,
undamaged. This is consistent with `<ruby>`-for-emphasis being applied
selectively by the site (or the original author's markup) to call out a
specific plot-relevant term, not a blanket per-bracket rendering
convention for status windows in general. Sample size is small (one
novel, three episodes) -- not enough to rule out other episodes/novels
using `<ruby>` more heavily, but enough to say this specific episode's
fragmentation is not caused by "status windows always use `<ruby>`
per-term" (they don't, here) -- it's caused by "any inline tag nesting
inside a paragraph, status window or not, fragments under the current
descendants-walk," and status windows just happen to be where this
draft's author chose to add emphasis markup.

**Pre-existing, not caused by the status bar**: the fragmentation lives
in `ep["lines"]` / `_extract_content()`, which predates
STATUS_BAR_DESIGN.md Phase 2 entirely. Phase 2 only added
`len(ep["lines"])` as a display count (`alphapolis_reader.py:1724`
area) -- it reads a count that was already wrong, it does not create the
wrongness. Translation quality for this chapter (isolated single
characters sent to the translator as if they were standalone lines) was
already degraded before the status bar existed; the status bar only made
the degradation visible as a suspiciously high paragraph count.

**Not done in this pass, deliberately**: no fix proposed or implemented.
No change to `_extract_content()`. No broader corpus scan across other
novels for `<ruby>` frequency -- only this novel's immediate neighbors
were checked, per the "gauge whether recurring" ask, not an exhaustive
survey. No investigation of whether `<ruby>` appears in true furigana
form (real pronunciation glosses) elsewhere in this site's narrative
prose, which would be a legitimate, unrelated use of the same tag that
any general nested-tag fix would need to not break.

**Open question for a future scoped fix**: whether to (a) special-case
`<ruby>` by concatenating its base-text children while dropping `<rt>`
content (fixes this exact case, matches the "emphasis dots are not
real content" reading), or (b) fix the general case -- coalesce adjacent
string descendants that share a common non-block ancestor before
treating a `.strip()` boundary as a real paragraph break, which would
also protect against any other inline tag (`<span>`, `<b>`, `<em>`,
etc.) doing the same thing, not just `<ruby>`. Given the narrow blast
radius found here (one cluster, one episode, of three checked), this
looks scoped enough for a small targeted fix rather than its own design
doc phase -- but that's a recommendation for the next pass, not a
decision made here.

**Status: confirmed real, root cause identified, narrow-to-moderate
blast radius characterized. Not fixed (open, investigation only).**

---

### 2026-08-03 (continued): scoping the general fix (b) -- algorithm sketched, no-op verified on truly clean episodes, but NOT a no-op on legitimate furigana; regression risk found, decision deferred

Follow-up to the entry immediately above. Scoping-only per task: sketch
fix (b) (general coalescing) concretely and test it against real cached
episodes, without yet choosing between (a) targeted `<ruby>` special-case
and (b) general coalescing.

**1. Algorithm sketch (prototype, not wired into production)**: rejected
"group strings by shared immediate parent" as the coalescing key --
inspected the actual DOM around the `<ruby>`-emphasis case and found the
fragments needing merged (`'【'`, `'塩'`, `'】'`, `'7'`, each in its own
`<ruby>`) are children of *different* `<ruby>` tags, not siblings under
one shared parent; the true correct key is "same nearest block-level
ancestor," not "same immediate parent." Working sketch instead replaces
the per-string-append loop with a buffer that accumulates raw string
content across inline tags and only flushes to a line on a block
boundary (`<br>`, or entering/leaving a `p`/`div`/`li`/etc., or an
`<img>`), with `<rt>` content skipped entirely (added to
`SKIP_TEXT_PARENTS` alongside `script`/`style`/etc.). Full prototype:
`/tmp/claude-.../scratchpad/extract_content_v2.py` (~50 lines, not
committed). Confirmed via a byte-level descendants trace
(`inspect_br_structure.py`) that this is genuinely necessary --
`技能：`, the bulk skill-list text, and the `<ruby>`-wrapped fragments
around it are literally sibling text nodes plus nested-tag text nodes
under the same `<div id="novelBody">`, with `<br>` as the only real
paragraph-boundary signal currently working "by accident" (today's code
never inspects `<br>` by name -- line splitting only happens to work
because `<br>` naturally separates BeautifulSoup's sibling
`NavigableString`s).

**2. Touch-point assessment**: contained to `_extract_content()` itself
-- no ripple into other functions. Within the function, though, it's not
a small tweak to "where strings are appended" -- it's a structural
rewrite of the loop from "append every string immediately" to "buffer
until a block boundary, then flush," because the current code has no
concept of a paragraph boundary at all (it relies on `<br>` accidentally
producing separate sibling strings). The `<br>`-per-field splitting
behavior investigation confirmed as correct-and-must-not-change is
preserved in the sketch (`br` is in `BLOCK_TAGS`, triggers a flush,
verified below) -- but it's preserved by deliberately re-implementing
the boundary explicitly, not by leaving existing logic untouched. This
is a meaningfully bigger diff than "add an `if node.name == 'ruby':`
branch," even though it stays inside one function.

**3. No-op verification -- mixed result, this is the key finding**:
tested against 5 live-refetched episodes sampled from the 27 real
cached episodes of this novel (cache holds only parsed `lines`, no raw
HTML, so all 5 were re-fetched fresh via the same Playwright approach as
the original investigation; see
`/tmp/claude-.../scratchpad/fetch_sample_episodes.py`). Before testing,
checked each sample's `#novelBody` for nested inline tags at all
(`ruby`/`span`/`b`/`em`/etc.) -- found only 2 of the 5 (`7800089`,
`7802066`) are genuinely tag-free; the other 3 were not the "no known
issues" control group they were picked to be, because 3 of 5 randomly
sampled episodes from this novel turned out to contain `<ruby>` inside
the body (see point 3a below -- itself a finding: `<ruby>` in this
novel's markup is more common than the original 3-episode neighbor
check suggested).

- **True no-op cases** (`7800089`, `7802066`, no `<ruby>`/nesting at
  all): old and new extraction produce **byte-identical** line lists
  (63/63 and 56/56 lines, zero diff). Confirms the rewrite does not
  perturb ordinary narrative chapters that never hit the bug.
- **Fragmenting cases, fix confirmed working** (`7802171` from the
  original entry, plus newly discovered `7799718` -- the emphasis-dot
  `<ruby>` pattern applied to `半妖人間`, 4 characters each individually
  wrapped, same mechanism as `塩`/lvl-7): old extraction produces 8
  single-character fragments in each; new extraction merges them back
  into the correct single line (`種族：半妖人間` / `【塩】7` inline in
  the skill list), zero single-character lines remaining in either.
  Confirms `7799718` is a second real, previously-undetected instance of
  this same bug -- it just didn't stand out because its total line count
  (81) wasn't an outlier the way 94 was.
- **Real furigana cases -- NOT a no-op, and this is a regression risk**
  (`7800177`: `<ruby>貝殻鎌<rt>シェルシックル</rt></ruby>`, a technique
  name with its katakana reading; `7801892`: same pattern for
  `岩塩打撃`/`ソルトインパクト`): here `<ruby>` is being used for its
  literal, legitimate purpose -- a kanji technique name annotated with
  its actual pronunciation/rendering. Old (buggy) extraction accidentally
  produces the kanji inline in the sentence *and* a separate orphaned
  line with just the katakana reading (`シェルシックル` as its own
  `ep["lines"]` entry) -- not correct today either, but the reading text
  at least survives somewhere. The v2 prototype's blanket "skip all
  `<rt>` text" rule **silently deletes the katakana reading entirely**;
  output collapses to just the kanji inline, reading gone. For a genre
  where techniques are frequently named with a kanji/katakana dual
  rendering (kanji meaning + foreign-loanword "cool name," a very common
  isekai convention), this is real content loss, not a wash -- naive
  fix (b) trades one quality bug (fragmentation) for a different, less
  obvious one (silent furigana deletion) on inputs the original
  investigation didn't anticipate.

**4. Effort comparison**: (a) targeted `<ruby>`-only special-case is a
small, additive change -- detect `<ruby>`, concatenate its base-text
child(ren), decide (product question) whether to keep or drop `<rt>`,
done; it does not require touching the block/line-boundary logic at
all, since it only intercepts one specific tag shape. (b) general
coalescing is not "close enough to free" -- it requires the loop
rewrite described in point 1 (a real structural change, not a small
diff) *and*, per point 3, requires solving the `<rt>` problem correctly
(distinguishing "emphasis-dot filler" from "real furigana reading," which
the raw markup does not obviously distinguish -- both use `<rt>`; the
only observed difference so far is content length/shape: single `・`
filler dots vs. multi-character katakana) before it's safe to ship,
which (a) sidesteps entirely by scoping to the one confirmed-broken
pattern. (b) also carries the general benefit the investigation
originally cited (protects against `<span>`/`<b>`/`<em>` nesting
elsewhere) but no evidence of that risk materializing was found in this
sample -- the only inline tag actually seen fragmenting real content in
this novel is `<ruby>`.

**Not done in this pass, deliberately**: no fix implemented or wired
into production, per task scope -- prototype stayed in scratchpad. No
attempt to write an `<rt>`-classification heuristic (filler-dots vs.
real furigana) -- flagged as the open blocker for (b), not solved. No
corpus-wide scan for `<span>`/`<b>`/`<em>` fragmentation risk beyond
what the 5-episode sample happened to contain -- the "general fix
protects against other tags too" benefit remains theoretical here, not
evidenced.

**Status: scoping complete, no decision made.** (a) is smaller,
lower-risk, and sufficient for every case confirmed broken so far. (b)
is more code, touches the core extraction loop more structurally than
"contained," and its main advantage (broader protection) is unproven
against this corpus while its cost (furigana content loss) is proven.
Recommendation for the next pass: lean toward (a) unless/until a real
`<span>`/`<b>`/`<em>` fragmentation case is found in the wild -- but per
task instructions, this is a recommendation, not the decision.

---

### 2026-08-04: fix (a) implemented -- targeted `<ruby>` filler-dot special case, four-episode verification passed, general fix (b) remains un-adopted

Follow-up closing the two entries immediately above. Implements fix (a)
as scoped there -- the targeted `<ruby>` special case, not the general
coalescing rewrite (b). (b) was deliberately not adopted; see its
reasoning preserved in the entry above (unproven benefit against this
corpus, proven cost of silently deleting real furigana readings) -- not
repeated or deleted here, kept for future reference if a real
`<span>`/`<b>`/`<em>` fragmentation case ever surfaces.

**Detection rule implemented**: a `<ruby>` tag matches the fix's scope
only if its `<rt>` child's stripped text is exactly a single `・`
character -- the exact signature confirmed on both real cases (nothing
looser, e.g. no length threshold or character-class heuristic). Any
other `<ruby>` shape, including real multi-character furigana readings,
falls through untouched. New helper `_is_ruby_filler_dot()` in
`alphapolis_reader.py` checks this; `_extract_content()` gained a
`skip_ids` set (to drop the matched `<rt>` string) and a `merge_eligible`
flag with one-node lookahead (`node.next_sibling`) so a filler-dot
`<ruby>`'s base text glues onto both the text run immediately before it
and any adjacent filler-dot `<ruby>` runs after it -- needed because a
naive "merge only forward from the ruby" version left the *preceding*
plain-text segment unmerged (caught and fixed during this pass; see
scratchpad debug trace). The `<br>`/block-boundary line-splitting logic
was not touched at all, confirmed by inspection (the change is entirely
within the string-handling branch of the existing loop, no new block-tag
handling added).

**Four-episode verification, live-refetched HTML (same 4 episodes named
in the scoping entry, re-used from `/tmp/claude-.../scratchpad/`)**:

- `7802171` (status-window skill list, `【塩】7`): before, 94 lines with 8
  single-character fragments (`'【'`, `'・'`, `'塩'`, `'・'`, `'】'`,
  `'・'`, `'7'`, `'・'`); after, 85 lines, zero single-character
  fragments, the skill list is one unbroken line
  (`...【瞑想】・【塩】7・【図工】...`). Full unified diff against the
  pre-fix baseline confirmed the change touches *only* that one line --
  every other line in the 94/85-line list is untouched.
- `7799718` (race-name term, `半妖人間`, newly discovered during the
  scoping pass as a second real instance of the same bug): before, 81
  lines with 8 single-character fragments (`'半'`, `'・'`, `'妖'`,
  `'・'`, `'人'`, `'・'`, `'間'`, `'・'`); after, 72 lines, zero
  single-character fragments, merges to `種族：半妖人間人間？？` (the
  trailing `人間？？` is a separate, pre-existing plain-text segment in
  the source itself -- confirmed present in the original HTML, not
  something this fix introduced).
- `7800177` (real furigana, `貝殻鎌`/`シェルシックル`) and `7801892`
  (real furigana, `岩塩打撃`/`ソルトインパクト`): confirmed byte-for-byte
  identical `_extract_content()` output before vs. after (compared full
  `content` dict lists, not just text -- includes image entries too),
  via a side-by-side import of the pre-fix function from a saved copy
  and the current one. No merge, no drop, no change of any kind.
- `7800089` and `7802066` (no `<ruby>`/nested inline tags at all):
  likewise confirmed byte-for-byte identical, as expected for episodes
  the fix's detection rule never matches.

**Test suite**: `pytest tests/webnovels/ --ignore=tests/webnovels/ui_automation`
-- **344 passed** (340 baseline + 4 new), zero failures, zero
regressions. The pre-existing Tkinter background-thread teardown
warnings seen in this run (`RuntimeError: main thread is not in main
loop` from `fetch_guesses`/`fetch_candidate` threads in
`test_retranslation_display.py`) are unrelated to this change -- same
warning count (5) as the pre-fix baseline run.

**New regression fixture**: `TestExtractContentRubyFillerDot` added to
`tests/webnovels/test_alphapolis_reader.py`, four tests against minimal
hand-constructed HTML (not live fetches, to keep the suite offline-safe)
covering: the multi-`<ruby>`-cluster merge case (7802171-shaped), the
whole-word filler-dot run case (7799718-shaped), the real-furigana
no-op case (7800177-shaped), and a plain no-`<ruby>` control. All four
pass.

**Code quality**: `black`/`isort`/`flake8` all clean on both modified
files after running `black` once to normalize quote style in the new
test file (no logic change from formatting).

**Not done in this pass, per scope**: no `<span>`/`<b>`/`<em>` handling
added. No `<rt>`-classification heuristic for ambiguous/unseen `<ruby>`
shapes -- only the exact confirmed single-`・` signature is handled;
anything else (including a hypothetical `<rt>` with two dots, or a
different filler character) falls through untouched by design, matching
the "if a real non-filler case surfaces later, that's new scoped work"
instruction. `CACHE_SCHEMA_VERSION` not bumped -- this changes how
future fetches are parsed, not the cached episode dict's shape;
existing cached episodes with old fragmented `lines` will not
retroactively clean up until re-fetched (Refresh/re-scrape), same
precedent as prior entries in this document for parsing/prompt-shape
changes.

**Status: implemented, four-episode live-HTML verification passed
(2 fixed, 2 confirmed no-op), 344/344 tests passing, new regression
fixture added. Closed.**

---

### 2026-08-04: single-speaker dialogue-bracket loss -- confirmed real, root cause identified with strong quantified evidence, distinct from the collective-shout fix (investigation only, not fixed)

Investigation of a translation-quality report against real cached
production data, not a fix. **Distinct bug from the collective-shout
bracket-stripping fix** (2026-08-01 entries above) despite superficial
similarity (both involve `「」`) -- that fix targets doubled/tripled
bracket layers (`「「...」」`, multiple speakers shouting in unison);
this report is about ordinary **single** `「...」` dialogue, which the
collective-shout detection (`_is_collective_shout()`,
`llm_translate.py:303-313`) explicitly does not match, confirmed by
reading the regex directly (`_DOUBLED_BRACKET_RE =
re.compile(r"「{2,}|」{2,}")`) rather than assuming from the doc
description -- a single line with exactly one `「` and one `」` has
zero consecutive doubled characters, so `_is_collective_shout()` returns
`False` and the line is never stripped or re-wrapped by that logic; it
passes into the prompt completely untouched. Note for anyone cross-
referencing: the collective-shout fix is live in production code today
(`_translate_chunk_once()`, `llm_translate.py:443-450`), not merely
proposed as the earlier 2026-08-01 entry's "proposal only, not
implemented" framing suggested -- it was evidently wired in at some
point after that entry was written; not re-verified when that happened,
just confirmed it's live now.

**Report**: ordinary single-speaker dialogue brackets (e.g.
`「そうだね。」`) are inconsistently rendered in translated output --
sometimes converted to English quotation marks, sometimes missing
entirely, no pattern reported yet. Makes dialogue hard to distinguish
from narration/thought in translated text.

**1. Prompt inspection**: `TRANSLATION_PROMPT` (`llm_translate.py:86-97`)
gives the model **zero explicit instruction** for how to render `「」`
-- no mention of converting to quotes, preserving as-is, or anything
else regarding dialogue-bracket punctuation at all. This alone predicts
per-line inconsistency, since the model has nothing to anchor a
consistent choice to and is left to pattern-match from its own training
distribution line by line.

**2. Real corpus survey**: surveyed every cached translated episode on
disk (`~/.cache/alphapolis_reader/*.json`, `lines`/`translated_lines`
pairs, same source used in the ruby-fragmentation investigation),
filtering to lines containing a single (non-doubled) `「`/`」` and
categorizing each `translated_lines` entry as quote-containing or not.
Script: `/tmp/claude-.../scratchpad/bracket_survey*.py` (three passes,
not committed -- one-off analysis).

- **567 single-bracket dialogue lines** surveyed across the full cache.
  **249 (43.9%) have no quote character at all** in the translation --
  the dialogue marking is completely gone, narration and dialogue read
  identically in translated output.
- Splitting by shape found a strong, clean signal:
  - **Whole-line dialogue** (source line is *only* `「...」`, nothing
    else -- 525 of 567, the dominant shape): **45.3% dropped**.
  - **Embedded dialogue** (dialogue quote sits inside a narration
    sentence, e.g. `だが...「診て見ないことには...」と返答。` -- 42 of
    567): only **21.4% dropped**.
- Within whole-line dialogue specifically, drop rate is a **monotonic
  gradient by inner-dialogue length**, not noise:
  - 0-5 chars: 88.7% dropped (n=53)
  - 6-10 chars: 73.1% dropped (n=67)
  - 11-20 chars: 52.3% dropped (n=151)
  - 21-40 chars: 28.8% dropped (n=170)
  - 41-200 chars: 19.0% dropped (n=84)
- **Concrete before/after examples, dropped** (real cache, not
  paraphrased):
  - `「うりうり！」` -> `'Uririri!'`
  - `「もぉ、ちゃんと聞いてる？それに熟れてるのは崩れやすいんだから、丁寧に扱うのよ」`
    -> `'Hey, are you really listening? Also, the ripe ones are
    fragile, so handle them carefully.'`
  - `「そうか」` -> `'I see'`
- **Concrete before/after examples, correctly quoted** (real cache):
  - `それに医師が「時間を置いてまた来るように」とだけ告げ、ようやくオレが診察を受ける番となった。`
    -> `"Then the doctor just told him to 'come back again after a
    while,' and finally it was my turn for the examination."`
  - `「見て、るりちゃん！こんなに赤くて大きいのッ！」` -> `"Look,
    Ruri-chan! It's so red and big!"`
- **A third, distinct failure shape found in passing** (not the main
  pattern, but real): 2 of 567 lines show the model's raw **Japanese**
  `「`/`」` characters surviving literally into the English output --
  `「あ…、あぁ…！？」` -> `「A-ah…!？」` and `「バカァッ！！」` ->
  `「Bakaaa!!」`. Distinct mechanism from the drop pattern (the bracket
  isn't lost, it's untranslated) -- flagged for awareness, not
  characterized further here (too small a sample, 2 cases, to say
  anything about when this happens).

**3. Root cause -- mechanistically confirmed, not just correlated**:
found `_clean_output()` (`llm_translate.py:268-281`), the only
post-processing step applied to every model output string before
caching (called from `_translate_chunk_once()`, the live production
translation path -- confirmed its only other call site,
`explain_term()` at line 760, is a wholly separate feature, glossary
term-meaning lookup, not chunk translation). Its docstring says
"stripping quotes... that some models add" and its actual logic strips
a leading+trailing `"` pair **whenever they're the first and last
characters of the whole string**:

```python
if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
    text = text[1:-1]
```

This was written to undo a different, known failure mode (the model
occasionally wraps its entire JSON *array element* in an extra
redundant quote layer as a formatting artifact, e.g. returning
`'"actual translation"'` as the array item instead of `'actual
translation'`). But it has **no way to distinguish that artifact from a
model correctly translating `「セリフ」` into English `"Dialogue"` for
a line that's entirely dialogue** -- both shapes are, structurally,
"the whole string starts and ends with `"`." Verified this directly by
feeding `_clean_output()` plausible correctly-quoted translations of
several of the real dropped source lines above (e.g. `'"Uririri!"'`,
`'"I see"'`) -- confirmed it strips them down to the exact bare/unquoted
shape seen in the real cached `translated_lines` output
(`/tmp/claude-.../scratchpad/check_clean_output_culprit.py`). This is
strong mechanistic evidence, not proof from a captured pre-strip log --
no debug logging captures the raw per-element JSON string before
`_clean_output()` runs on a successful parse (only on parse *failure*,
`llm_translate.py:483`), so the model's actual raw pre-strip output for
these specific historical lines can't be recovered after the fact; the
claim rests on `_clean_output()`'s behavior being exactly right to
produce this pattern, confirmed by direct simulation, combined with the
survey's own shape-based evidence (embedded dialogue's quotes sit
mid-string, never at position 0/-1, and are never vulnerable to this
strip -- consistent with its dramatically lower 21.4% vs 45.3% drop
rate) and length gradient (shorter whole-line translations are more
likely to be a single bare quoted clause with nothing else in the
string, i.e. exactly the shape `_clean_output()` can't tell apart from
its intended target).

**4. Translation-time vs rendering-time -- confirmed translation-time**:
traced the full path from cache to screen.
`_render_translated_content()` (`alphapolis_reader.py:1149-1184`, the
actual production renderer -- confirmed live by checking
`_render_translated_view()`'s dispatch logic, which falls through to
this function whenever `needs_review_flags` isn't present, the common
case for this novel's cache) inserts `ep["translated_lines"][line_idx]`
directly into the Tk text widget via `self.text.insert("end", line +
"\n", tag)` with **no string transformation of any kind** between the
cache read and the display insert -- confirmed by reading the function
body line by line, no regex, no `.replace()`, no stripping. Whatever is
in the on-disk `translated_lines` cache is exactly what renders,
character for character. The loss happens before caching, inside
`_translate_chunk_once()`/`_clean_output()`, not in the reader UI.

**Not done in this pass, deliberately**: no fix proposed or
implemented, per task scope. No change to `_clean_output()`,
`TRANSLATION_PROMPT`, or any call site. No investigation of the
2-case literal-Japanese-bracket-passthrough shape beyond noting it
exists -- sample too small to characterize a trigger condition. No
re-translation or live model call made to capture a genuine pre-
`_clean_output()` raw string (the mechanistic case rests on simulation
plus the survey's shape/length evidence, not a captured live example;
a future pass wanting stronger proof could temporarily log raw
`parsed` array elements before the `_clean_output()` call and
re-translate a small batch of known-dropped lines to observe directly).

**Status: confirmed real, root cause identified with strong
quantified/mechanistic evidence (not just correlation), distinct from
the collective-shout fix. Not fixed (open, investigation only).**

---

### 2026-08-04: 「」 dialogue-quote loss FIXED -- single-quote instruction added to TRANSLATION_PROMPT, live re-translation confirms recovery, `_clean_output()` untouched

Closes the `「」` half of the entry above (`（）` remains open, see the
continuation entry below -- unrelated mechanism, not touched by this
fix, per scope).

**Design decision, as scoped**: the investigation above confirmed
`_clean_output()`'s double-quote strip is structurally unable to
distinguish its intended target (the model wrapping a JSON array
element in a redundant extra quote layer) from a correctly
double-quoted whole-line dialogue translation -- both are, after
parsing, just "a string starting and ending with `"`." No smarter check
can resolve that after the fact; the two cases are the same string.
Rather than touch `_clean_output()`, `TRANSLATION_PROMPT`
(`llm_translate.py:86-101`) gained one new sentence: dialogue marked
with `「」` (whole-line or embedded in narration) should render wrapped
in single quotes (`'...'`), never double quotes -- moving dialogue off
the glyph `_clean_output()` keys on, rather than trying to make that
key smarter. `_clean_output()` itself was not modified at all -- still
valid for its original purpose (undoing the JSON-double-wrap artifact)
now that dialogue no longer collides with it.

**Live re-translation test, real production path**: called
`_translate_chunk_once()` directly (not a reimplementation) against
real lines pulled from the 2026-08-04 survey above.

- **Confirmed-dropped short lines, individually** (a 4-line batch first
  hit an unrelated pre-existing transient -- model returned a
  wrong-length array once, `_translate_chunk_once()`'s own existing
  length check correctly rejected it and returned `None`; re-run
  one-at-a-time to isolate, no connection to this fix):
  - `「うりうり！」` -> `'Uriuri!'` (single-quoted; before this fix,
    real cached output was `'Uririri!'`, no quote marking at all)
  - `「そうか」` -> `'I see'` (before: `'I see'`, bare, no quote)
  - `「え…」` -> `'Eh...'` (before: bare)
  - `「ヤバイ！」` -> `'Yabai!'` (before: bare)
  - All four confirmed single-quoted, and confirmed
    `_clean_output(tgt) == tgt` (no-op, quotes intact) for every one --
    the double-quote strip condition (`text[0] == '"'`) never fires on
    a string starting with `'`.
- **Embedded dialogue (previously already correctly quoted) --
  re-tested for regression, 3 repeats**: `それに医師が「時間を置いてまた
  来るように」とだけ告げ、ようやくオレが診察を受ける番となった。` ->
  consistently `"In addition, the doctor only told me, 'Please come
  back again later,' and finally it was my turn to be examined."` --
  still correctly quoted (now single-quoted for the embedded dialogue
  span specifically, double-quoting the outer sentence is fine since
  that's the model's own narrative-wrapping choice, not the `「」`
  content itself), no regression from the previously-working case.
- **One real, honestly-reported gap found**: a longer whole-line
  dialogue case, `「もぉ、ちゃんと聞いてる？それに熟れてるのは崩れやすい
  んだから、丁寧に扱うのよ」`, came back consistently (4/4 repeats,
  `temperature=0.1`) as `'"Are you really listening? Also, ripe fruit is
  fragile, so handle it with care."'` using **curly `“ ”` double
  quotes**, not the instructed single quotes -- the model does not
  follow the new instruction 100% of the time. Checked whether this
  reproduces the original bug: it does not -- `_clean_output()` only
  checks ASCII `"` (`text[0] == '"'`), so curly `“”` is untouched by it
  either way, confirmed directly (`_clean_output()` is a no-op on this
  string). So this line keeps its dialogue-quote marking (readers can
  still see it's dialogue), just not in the exact instructed glyph --
  a smaller, cosmetic gap, not a recurrence of content loss. Reported
  as found, not smoothed over: the instruction measurably fixes the
  `_clean_output()` collision (its actual purpose) but is not a 100%
  compliance guarantee from the model.

**Test suite**: `pytest tests/webnovels/ --ignore=tests/webnovels/ui_automation`
-- **345 passed** (344 baseline + 1 new), zero failures. `black`/
`isort`/`flake8` clean on both modified files.

**New regression test**: `TestCleanOutput.test_single_quoted_dialogue_not_stripped`
added to `tests/webnovels/test_llm_translate_core.py` -- pins
`_clean_output("'Uriuri!'") == "'Uriuri!'"`, with the "why" (the
ambiguity this sidesteps) documented directly in the test docstring so
a future reader doesn't need to cross-reference this DESIGN.md entry to
understand why the convention exists.

**Scope note**: only `TRANSLATION_PROMPT`'s text changed -- a prompt
instruction, not a cache-shape change, so no `CACHE_SCHEMA_VERSION`
bump, same precedent as the `<ruby>` fix earlier in this document.
Only affects future translations (new fetches/`Refresh`); already-cached
`translated_lines` with dropped quotes are not retroactively fixed.
`（）` handling was not touched in this pass -- remains open, see the
continuation entry below.

**Not done in this pass, deliberately**: no attempt to raise the
model's compliance rate on the single-quote instruction beyond what one
prompt sentence achieves (e.g. few-shot examples, stronger wording) --
the found gap is cosmetic (quote glyph choice) not functional (content
loss), so not pursued further per scope. No fix for `（）` (separate,
still-open investigation). No corpus-wide re-translation of the full
567-line survey set -- spot-checked representative cases (short
whole-line, longer whole-line, embedded) rather than exhaustively
re-running everything found in the original survey.

**Status: implemented. Live re-translation confirms the `_clean_output()`
collision is fixed for every case tested; one honest compliance gap
found (curly-quote instead of single-quote on one longer line) that
does not reproduce the original content-loss bug. 345/345 tests
passing. Closed.**

---

### 2026-08-04 (continued): （） inner-monologue parentheses -- a different, NOT-yet-explained failure shape; confirmed real and reproducible, confirmed NOT the same `_clean_output()` mechanism as the 「」 finding

Follow-up to the entry immediately above, expanding the dialogue-
punctuation investigation to `（）` (inner-monologue/thought parentheses,
distinct from `「」` spoken dialogue) per a second report. Still
findings-only, no fix.

**1. `（）` survey, same methodology as the `「」` survey**: 111
single-（）lines surveyed across the full cache
(`/tmp/claude-.../scratchpad/paren_survey*.py`, not committed). Overall
outcome mix: 63.1% both ASCII parens present and correctly rendered
(`(...)`), 14.4% parens fully dropped (silently, both sides gone,
same shape as the `「」` finding), 2.7% the full-width `（`/`）`
character itself surviving literally into English output (distinct
again from the `「」` investigation's 2-case literal-passthrough
finding -- same failure family, different bracket glyph), and **5.4%
(6 of 111) matching the reported shape** (open paren present, close
paren missing, often with a stray `"` also present).

Narrowing to the reported shape specifically (whole-line `（...）`
cases only, 84 of 111, and checking ASCII-paren balance directly rather
than the cruder first-pass categorization): **7 of 84 (8.3%) have an
unbalanced paren count in the translation** -- 6 cases of `open=1,
close=0`, 1 case of `open=2, close=1`. **Confirmed real and
reproducible, not a one-off or a transcription artifact of the pasted
example** -- concrete real cache examples (source / translated,
verbatim):

- `（うわっ！？）` -> `'(Whoa!?'` (no stray quote, just unclosed paren)
- `（まぁ昔とそう変わらないだろう。いつもの手だな…）` -> `"(Well, it
  probably hasn't changed much since then. It's the usual tactic..."`
  (no stray quote)
- `（…いったい、いったいどういうことだ！？）` -> `'("What the heck is
  going on?!"'` (the originally-reported case: open paren, a stray `"`,
  no closing paren)
- `（え～と、瑠羽は今、いったいなんて言った…？？）` -> `'("Umm, what
  exactly did Ruri just say...?"'` (same shape, same episode, 7803051)

**Refinement to the original report**: the "literal `(` + stray `"` +
missing `)`" description is only the exact shape in 2 of the 7 real
cases found (both from episode 7803051). The other 5 have the unclosed
`(` but **no** stray quote at all -- so the underlying failure is "the
model sometimes doesn't close the parenthetical it opened," and the
stray-quote detail is a separate, coincidental addition in some
instances, not a fixed combined signature.

**2. Spurious quoting of bracket-free narration -- confirmed real, not
a transcription artifact.** Directly investigated by finding episode
7803051's own line #1 (immediately after the originally-reported line #0)
in the raw cache: source `あ、なんだ、コレ。なんか視界が揺れて、
ぐわんぐわんする…。` (plain narration, zero brackets of any kind) ->
translated `'"Oh, what is this? My vision is swaying and blurring...".'`
-- fully wrapped in quote marks with no basis in the source at all,
confirmed present in the actual on-disk cache file, not something that
could have been introduced by pasting/transcription. A broader corpus
search (`/tmp/claude-.../scratchpad/spurious_quote_survey.py`) found 5
more real cases beyond this one (6 total), e.g. `いやそんなの現状じゃ
まったく機能してなくて...` -> `'"Well, it's completely non-functional
in its current state..."'`. Notable pattern: all 6 use **curly `“ ”`
quotes**, not straight `"`, and they cluster within the same
episode/local region (3 from episode 7800265, 3 from episode 7802066) --
consistent with the model occasionally losing track of the
dialogue/narration boundary partway through a chunk and treating
several consecutive lines as quotable material, rather than a per-line
independent misfire.

**3. `TRANSLATION_PROMPT` and `（）`**: confirmed no instruction for
`（）` either, same as `「」` -- `TRANSLATION_PROMPT` names no
punctuation-rendering convention for any bracket type. Nothing
`（）`-specific was found anywhere in `llm_translate.py` (no detection
function, no stripping, no special-casing analogous to
`_is_collective_shout()`/`_strip_collective_shout_brackets()`) --
`（）` lines are not treated any differently from ordinary prose by any
code in this module; whatever handling they get is entirely up to the
model's own judgment on each call, same root gap as `「」`.

**4. Root-cause check -- confirmed this is NOT the same `_clean_output()`
mechanism as the `「」` finding.** Tested directly: fed both real cached
values (`'("What the heck is going on?!"'` and `"(Well, it probably
hasn't changed much since then. It's the usual tactic..."`) through
`_clean_output()` (`/tmp/claude-.../scratchpad/check_paren_not_clean_output.py`).
Both came back **completely unchanged** -- `_clean_output()`'s strip
condition is `text[0] == '"' and text[-1] == '"'`; these strings start
with `(`, not `"`, so the condition never triggers, and the function is
a no-op on them. Also confirmed structurally that `_clean_output()`
could not produce this shape even in principle: it only ever removes a
matched leading+trailing `"` *pair*, never a lone trailing character,
and it never touches `(`/`)` at all -- there's no code path in this
function capable of turning a balanced `(...)"` into an unbalanced
`("...`. The `「」` finding's mechanism and this one are confirmed
distinct.

Also checked and ruled out a truncation hypothesis (chunk's token
budget cut the response off mid-string, landing exactly on one of
these lines): `parse_json_response()` uses `json.JSONDecoder().raw_decode()`
(`llm_translate.py:394`), which requires a syntactically complete,
well-formed JSON value -- an actually-truncated/unterminated JSON
string is a hard parse error there, not something that could yield a
clean array containing one oddly-punctuated-but-otherwise-valid string.
Since these values sit in the cache as ordinary successfully-parsed
array elements (not `None`/fallback placeholders, confirmed by their
presence in `translated_lines` at all), the JSON itself was
well-formed -- the unbalanced `(`/`"` is content the model wrote
inside a properly-closed JSON string, not a JSON-level truncation
artifact. **This means the true root cause of the missing-`）`/stray-`"`
shape is not yet identified** -- ruled out `_clean_output()` and JSON
truncation, but did not find what actually produces it. No chunk-
boundary reconstruction was attempted (the cache stores only final
`lines`/`translated_lines`, not per-chunk request/response boundaries,
so which lines shared a chunk with which can't be recovered after the
fact without re-running the pipeline).

**Not done in this pass, deliberately**: no fix proposed or
implemented. No re-translation/live model call to observe a raw
pre-cache response directly (same limitation noted in the entry
above -- would need temporary logging added and a live re-run,
out of scope here). No investigation of the 1 outlier `(open=2,
close=1)` case beyond noting its shape. No attempt to reconstruct
chunk boundaries for the 7 affected lines to check an end-of-chunk
position hypothesis -- flagged as a promising next step, not tested.

**Status: confirmed real (both the missing-close-paren shape and the
spurious-quoting-of-narration shape), reproducible across multiple
episodes, ruled out as the `「」` finding's `_clean_output()` mechanism
and as JSON-level truncation -- but the actual root cause remains
unidentified. Not fixed (open, investigation only, root cause is the
next open question).**

---

### 2026-08-05: （） missing-close-paren -- instrumented live re-translation, root cause NOT found, failure does not reproduce on demand; left open, no fix attempted (per checkpoint instruction)

Follow-up to the entry above, per the leading untested hypothesis
(chunk-boundary position) and the explicit instruction to instrument
raw pre-parse model output rather than guess. Stopped at the checkpoint
without proceeding to a fix, because the result was genuinely
ambiguous, not because of a time constraint.

**Method**: temporary, uncommitted instrumentation script
(`/tmp/claude-.../scratchpad/instrumented_retranslate_7803051.py`, not
added to the repo) that reproduces `translate_lines()`'s exact chunking
(`max_chunk_chars=400`) against the real 55-line source text of episode
7803051 (pulled from the real on-disk cache, not re-fetched -- source
text doesn't change), calls the real `/completion` endpoint with the
real production prompt-building logic (`TRANSLATION_PROMPT`, collective-
shout stripping, context-window building -- copied inline, not
reimplemented differently), and prints the raw model response string
**before** `parse_json_response()`/`_clean_output()` touch it, for the
specific chunk containing both known-affected lines from the original
report.

**Chunk-boundary hypothesis: ruled out.** Both known-affected lines
(source index 0: `（…いったい、いったいどういうことだ！？）`, and index
2: `（え～と、瑠羽は今、いったいなんて言った…？？）`) land in **chunk 0
of 7**, at positions 0 and 2 of an 11-line chunk -- one is the literal
first line of the first chunk, the other is in the middle, not at a
chunk's end. Since `n_predict` is sized per-chunk from the whole
chunk's character count (`llm_translate.py:482`) and both lines are
nowhere near the tail of their chunk (9 more lines follow both), a
token-budget cutoff landing exactly on either of these specific short
lines is not plausible as the mechanism -- if truncation were
happening, it would hit whichever line is generated last in the
response, not the first or an early-middle one.

**Raw pre-parse output: balanced, every time.** Across 4 live
re-translation runs of this exact chunk (current prompt, with the
2026-08-04 single-quote-for-「」 instruction active) and 3 more runs
using the **original, pre-single-quote-fix** `TRANSLATION_PROMPT`
restored from git history (`git show HEAD:...`, tested standalone to
isolate whether that fix's wording change was somehow responsible --
it is not, since the old prompt reproduces the same balanced result),
**the raw model output for both known-affected lines came back fully
balanced in all 7 runs**, e.g. `("Well, well, what on earth is going
on?!")`, `("…What on earth is going on?!")`,
`'"(…what on earth is going on?!)"'` -- varying in exact wording and
quote-style each run (expected, `temperature=0.1` is not zero) but
never reproducing the original cached shape (`'("What the heck is
going on?!"'`, unbalanced, missing the closing paren). `_clean_output()`
was confirmed a no-op on every one of these balanced raw values too
(none start with `"`, since they all start with `(`).

**Spurious-quoting-of-narration also inconsistent on the same line,
same runs**: the adjacent bracket-free narration line (index 1,
`あ、なんだ、コレ。なんか視界が揺れて、ぐわんぐわんする…。`, the exact
line originally reported as spuriously quoted) came back quoted in some
runs and correctly unquoted in others, for byte-identical input and
prompt, at the same low temperature -- consistent with plain
non-determinism, not a discoverable condition tied to chunk position,
prompt wording, or anything else varied across these runs.

**Conclusion: root cause not found, and the failure does not reproduce
on demand.** Both known-affected lines translate correctly (balanced,
readable) on every live re-run attempted, using both the current and
the original prompt. This means the original cached unbalanced/stray-
quote output was very likely a rare model-level sampling artifact --
not something introduced by any code path in this repository, not tied
to chunk-boundary position (confirmed neither line sits near a chunk
edge), and not reliably triggerable for direct study. Per the task's
explicit checkpoint instruction, **stopping here rather than
proceeding to a fix based on a guess** -- there is no confirmed,
specific mechanism to target, and implementing something anyway (e.g.
a defensive paren-balance repair pass) would be guessing at a shape
without evidence it addresses the actual cause, which for a
non-reproducing ~5-8% artifact is more likely to paper over a symptom
than fix anything.

**Not done in this pass, deliberately, per the checkpoint**: no fix
implemented. No change to `_clean_output()`, `TRANSLATION_PROMPT`, or
any other code. No broader re-run across the other 5 of 7 originally-
surveyed missing-close-paren cases (episodes other than 7803051) --
the two cases tested were the ones specifically named in the task
(the episode containing 2 of the 7 real confirmed cases, including the
originally-reported line); given both failed to reproduce after 7
combined attempts, broadening the sample further seemed unlikely to
change the conclusion, but was not exhaustively tried. No investigation
of whether a much larger number of repeated runs (dozens+) would
eventually reproduce the shape and reveal a low-probability but real
trigger condition -- 7 runs is enough to show "not reliably
reproducible," not enough to prove "can never happen under any
condition."

**Status: root cause NOT identified. Failure confirmed NOT reproducible
on demand across 7 live re-translation attempts (both current and
pre-2026-08-04 prompt versions), chunk-boundary-position hypothesis
ruled out directly. No fix attempted, per the checkpoint instruction to
stop rather than guess. Left open.**

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
