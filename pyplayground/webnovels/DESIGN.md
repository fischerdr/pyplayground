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
