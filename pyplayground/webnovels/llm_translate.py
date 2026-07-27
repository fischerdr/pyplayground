#!/usr/bin/env python3
"""llm_translate.py - Local LLM translation backend using llama-server.

Translates text to English (or other languages) using a llama-server
instance running the translategemma model. Designed as a drop-in
replacement for Google Translate in the Alphapolis reader pipeline.

Supported models (via llama-server):
    translategemma-12b-Q4_K_M  - Recommended default, best speed/quality balance
    translategemma-27b-Q6_K    - Best quality, slower

Note on translategemma's native chat template: the model card documents a
structured chat format (source_lang_code/target_lang_code fields, no system
prompt) intended to be applied via llama-server's --jinja flag. That path is
NOT used here: llama-server's Jinja parser fails to even start when given
translategemma's template ("Unable to generate parser for this template"),
so the server must run with --no-jinja. This module instead uses the plain
/completion endpoint with an inline instruction prompt naming the source and
target languages, which works under --no-jinja and supports translating from
any source language (not just Japanese) without restarting the server.

Environment variables:
    LLM_ENDPOINT       - llama-server API URL (default: http://flyyn:10001)
    LLM_MODEL          - Model name (default: mradermacher/translategemma-12b-it-GGUF:Q4_K_M)
    LLM_TIMEOUT        - Per-request timeout in seconds (default: 120)

Backend constants:
    BACKEND_GOOGLE, BACKEND_LLM, DEFAULT_BACKEND - shared translation backend
    identifiers used by the reader, CLI translator, and comparison script.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from pyplayground.utils.config_utils import get_env_var
from pyplayground.utils.logging_utils import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Backend identifiers (shared across reader, CLI translator, and comparison script)
# ---------------------------------------------------------------------------

BACKEND_GOOGLE = "google"
BACKEND_LLM = "llm"
DEFAULT_BACKEND = BACKEND_GOOGLE

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LLM_ENDPOINT = get_env_var("LLM_ENDPOINT", default="http://flyyn:10001")
"""llama-server API base URL."""

LLM_MODEL = get_env_var("LLM_MODEL", default="mradermacher/translategemma-12b-it-GGUF:Q4_K_M")
"""LLM model to use for translation."""

LLM_TIMEOUT = get_env_var("LLM_TIMEOUT", default="120", as_type=int)
"""Per-request timeout in seconds."""

# Prompt template for clean translation output (/completion endpoint).
#
# Uses a JSON-array request/response format rather than a plain-text
# "{target_lang}:" label. This was a deliberate fix for a real failure mode:
# with the label-based prompt, the model would sometimes hallucinate an
# entire fabricated scene (in {source_lang}, embedded mid-translation)
# instead of translating the given line -- confirmed to happen even with no
# glossary present, and made worse when a glossary's character names were
# in the prompt (the model apparently free-associates from names into
# invented dialogue). Rewording the instructions or delimiting the glossary
# more strongly did not fix it. Switching the expected output shape to a
# JSON array eliminated the hallucination across every case tested (see
# commit history for the specific failing line this was found on) --
# JSON doesn't read as "story so far" the way a labeled prose format does,
# so the model doesn't try to continue it as narrative.
#
# A side benefit: JSON arrays inherently preserve element count, so the
# translate_lines() alignment-retry logic that existed to recover from
# label-format merges is no longer the primary defense (though still kept
# as a fallback in case the model returns a wrong-length array).
TRANSLATION_PROMPT = (
    "You are a translation API. You output ONLY a JSON array of strings, "
    "nothing else -- no notes, no explanations, no markdown code fences.\n\n"
    "Translate each {source_lang} string in the array below to {target_lang}. "
    "Preserve order and array length exactly -- one output string per input "
    "string, even if a string is short or ambiguous. Do not merge, split, "
    "or add strings, and do not continue the story beyond what is given. "
    "If you are unsure about a proper noun (character name, place name), "
    "transliterate it using standard romanization conventions.\n\n"
    "{source_lang} array: {lines_json}\n\n"
    "JSON array:"
)

# Sliding window context prompt prefix, inserted before the instruction line.
# Worded forcefully (BACKGROUND ONLY / do NOT repeat) after a confirmed live
# failure: a softer "here is context for consistency" phrasing sometimes made
# the model treat the context as something to account for in its answer,
# causing it to emit the same translation twice in the output array (e.g. a
# 1-line request returning a 2-element array with the line duplicated).
CONTEXT_PREFIX = (
    "BACKGROUND ONLY -- for tone/terminology consistency. Do NOT translate "
    "this, do NOT include it in your output, and do NOT repeat your answer "
    "to account for it:\n{context}\n\n"
)

# Glossary prompt prefix, inserted before the sliding-window context (if any)
# and the instruction line. Distinct from CONTEXT_PREFIX: the glossary is
# "translate these specific terms consistently" (persistent, per-novel),
# while CONTEXT_PREFIX is "here's immediately preceding text" (transient,
# resets each translate_lines() call).
GLOSSARY_PREFIX = "Reference only, for terminology consistency -- not part of the text to translate:\n{glossary}\n\n"

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
}
"""Common source/target language code to display name mapping for prompts."""

# ---------------------------------------------------------------------------
# Sentinel masking (glossary review-queue splice: mask a term, translate
# around it, splice the original word back into the output untranslated)
# ---------------------------------------------------------------------------
#
# Format and survival rates validated against translategemma in
# test_sentinel_survival.py before this was wired in: an opaque placeholder
# (the model never sees the Japanese word, only ⟦TERM_n⟧) survived 15/15
# across single/multi-line, chunk-boundary, and 5-sentinel-dense chunks.
# Two alternative formats that left the word inline (bracket-wrapped,
# XML-tag) both scored 0/15 -- translategemma treats those as translatable
# content rather than structure to preserve. Do not switch formats without
# re-running that script; this is not a stylistic choice.

_SENTINEL_OPEN = "⟦"  # ⟦
_SENTINEL_CLOSE = "⟧"  # ⟧

# Bracket glyphs to tolerate on splice-back. Confirmed live: translategemma
# normalized ⟦...⟧ to plain ASCII [...] in at least one response even though
# the prompt only ever sends the fullwidth math brackets. Fullwidth square
# brackets are guarded defensively as the same normalization failure class,
# not yet confirmed to occur.
_OPEN_BRACKETS = r"⟦【［\["  # ⟦ 【 ［ [
_CLOSE_BRACKETS = r"⟧】］\]"  # ⟧ 】 ］ ]
_SENTINEL_DIGIT_NORMALIZE = str.maketrans("０１２３４５６７８９", "0123456789")


def _sentinel_pattern(n: int) -> "re.Pattern[str]":
    return re.compile(rf"[{_OPEN_BRACKETS}]\s*TERM_{n}\s*[{_CLOSE_BRACKETS}]")


@dataclass
class TranslatedLine:
    """One translated line, with whether it needs human review.

    Attributes:
        text: The translated (or spliced-back) line text.
        needs_review: True if this line had at least one masked term
            spliced back in -- whether the sentinel survived cleanly or
            had to be recovered by substitution -- since either path
            leaves the raw, untranslated source word in the output.
            Masking never asks the model to translate a masked term, so
            "spliced" and "translated" are never the same thing; callers
            should visually flag any line where this is True.
    """

    text: str
    needs_review: bool = False


def mask_terms(line: str, targets: List[Tuple[str, int]]) -> str:
    """Replace each (word, id) target in `line` with an opaque sentinel.

    Args:
        line: Source line to mask.
        targets: (word, id) pairs; word must appear verbatim in line. id is
            the sentinel number, unique within the request (not just this
            line), so callers must number targets across the whole chunk.

    Returns:
        `line` with each target word replaced by ⟦TERM_id⟧.

    Raises:
        ValueError: If a target word is not found in `line`.
    """
    for word, term_id in targets:
        if word not in line:
            raise ValueError(f"{word!r} not found in line {line!r} -- cannot mask")
        line = line.replace(word, f"{_SENTINEL_OPEN}TERM_{term_id}{_SENTINEL_CLOSE}", 1)
    return line


def splice_terms(translated_line: str, targets: List[Tuple[str, int]], fallbacks: Optional[Dict[str, str]] = None) -> TranslatedLine:
    """Replace each sentinel in a translated line with its original source word (or a better fallback, if one's available).

    Two distinct recovery paths, matched to what testing showed are two
    distinct failure classes (see test_sentinel_survival.py results):
      - Sentinel present (possibly with normalized brackets/digits): spliced
        back cleanly.
      - Sentinel missing from an otherwise-populated line: the substituted
        text is spliced in at the position where the sentinel should have
        been -- degrade gracefully rather than silently drop the term.

    needs_review=True whenever `targets` is non-empty, regardless of which
    path handled each individual term, and regardless of what gets
    substituted (raw source word or a fallbacks[] candidate) -- neither
    path translates the masked term, so the line is always genuinely
    review-worthy either way. See fallbacks' docstring note below; this is
    a display-quality change, not a trust change.

    `fallbacks`, if given, maps a masked word to a better display string
    than the bare raw word -- normally the term's best-ranked `suggested`
    candidate (see glossary.build_splice_fallbacks()), built by the caller
    since this module has no glossary.py import (a deliberate boundary --
    callers resolve/format glossary data themselves before calling in,
    same as glossary_text elsewhere in this module). A word with no entry
    in `fallbacks` (or when `fallbacks` is omitted entirely) falls back to
    the word itself, preserving the original behavior -- this is purely
    additive, not a required parameter, so every existing caller/test that
    doesn't pass it keeps working unchanged.

    Whole-line-empty (the other confirmed failure class, seen on dense
    multi-sentinel Qwen3 chunks) is NOT handled here -- callers should retry
    the request before calling this, since an empty line means the entire
    line's translation is gone, not just the marker.

    Args:
        translated_line: One line of model output, potentially containing
            ⟦TERM_n⟧ sentinels (or a normalized variant).
        targets: (word, id) pairs in the same numbering used for mask_terms().
        fallbacks: Optional dict mapping a masked word to the display text
            to substitute for it, in place of the bare word. See above.

    Returns:
        TranslatedLine with sentinels replaced by their source words (or
        fallbacks[] substitutes).
    """
    fallbacks = fallbacks or {}
    for word, term_id in targets:
        display_text = fallbacks.get(word, word)
        normalized = translated_line.translate(_SENTINEL_DIGIT_NORMALIZE)
        match = _sentinel_pattern(term_id).search(normalized)
        if not match:
            logger.warning(f"Sentinel TERM_{term_id} ({word!r}) missing from translated output; substituting {display_text!r} and flagging for review")
            translated_line = f"{translated_line} {display_text}".strip() if translated_line else display_text
            continue
        translated_line = translated_line[: match.start()] + display_text + translated_line[match.end() :]
    return TranslatedLine(text=translated_line, needs_review=bool(targets))


def _language_name(lang: str) -> str:
    """Resolve a language code to a display name for prompt interpolation.

    Args:
        lang: Language code (e.g. "ja") or already a display name.

    Returns:
        A human-readable language name suitable for the translation prompt.
    """
    return LANGUAGE_NAMES.get(lang.lower(), lang)


def _clean_output(text: str) -> str:
    """Clean up the model output by stripping quotes and whitespace.

    Args:
        text: Raw model output string.

    Returns:
        Cleaned translation string.
    """
    text = text.strip()
    # Strip surrounding quotes that some models add
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def _log_timing(data: Dict[str, Any]) -> None:
    """Log translation timing statistics from a llama-server /completion response.

    Args:
        data: Parsed JSON response from the /completion endpoint.
    """
    timings = data.get("timings", {})
    predicted_n = timings.get("predicted_n", 0)
    predicted_ms = timings.get("predicted_ms", 0)
    if predicted_n and predicted_ms:
        speed = predicted_n / (predicted_ms / 1000)
        logger.debug(f"Translation: {predicted_n} tokens in {predicted_ms / 1000:.1f}s ({speed:.1f} tok/s)")


def strip_code_fence(text: str) -> str:
    """Strip a markdown code fence the model may wrap JSON output in.

    Public (not module-private) since build_glossary.py's extraction call
    hits the same model behavior and reuses this rather than duplicating it.

    Args:
        text: Raw model output, possibly wrapped in ```json ... ``` or ``` ... ```.

    Returns:
        The text with any wrapping code fence removed.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_json_response(text: str) -> Any:
    """Parse the first complete JSON value from `text`, ignoring trailing content.

    Confirmed via a live failure: the model sometimes emits a complete, valid
    JSON array/object and then keeps generating past it (e.g. echoing part of
    the glossary text back after the closing bracket) instead of stopping.
    A plain json.loads() rejects the whole response in that case ("Extra
    data"), even though the JSON itself parsed fine up to that point. Using
    raw_decode() takes just the leading valid JSON value and discards
    whatever comes after, which is the actually-wanted behavior here.

    Public (not module-private) since build_glossary.py's extraction call
    hits the same model behavior and reuses this rather than duplicating it.

    Args:
        text: Model output, ideally starting with a JSON array or object
            (after code-fence stripping).

    Returns:
        The parsed JSON value (list or dict, typically).

    Raises:
        json.JSONDecodeError: If no valid JSON value starts at the beginning
            of `text`.
    """
    value, _end_index = json.JSONDecoder().raw_decode(text)
    return value


def _translate_chunk_once(
    lines: List[str],
    target_lang: str,
    source_lang: str,
    context: Optional[str],
    glossary_text: Optional[str],
    chunk_idx: int,
    total_chunks: int,
    log_context: str = "",
) -> Optional[List[str]]:
    """Make a single /completion request for `lines`, no retry.

    Args:
        lines: The source lines/paragraphs to translate, in order.
        target_lang: Target language code.
        source_lang: Source language code.
        context: Optional previous paragraphs for consistency.
        glossary_text: Optional pre-formatted glossary text.
        chunk_idx: Current chunk index (0-based), for log messages only.
        total_chunks: Total number of chunks, for log messages only.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error this call logs, so a failure in a shared
            log file can be traced back to which episode/request produced
            it without cross-referencing timestamps against a separate
            "Fetching and translating episode: ..." line. Empty by
            default (matches every existing call site/test unchanged).

    Returns:
        List of translated strings, same length and order as `lines`, or
        None if the response didn't parse as a JSON array of that length.

    Raises:
        requests.exceptions.ConnectionError: If llama-server is not reachable.
        requests.exceptions.Timeout: If the request times out.
    """
    log_prefix = f"[{log_context}] " if log_context else ""
    source_name = _language_name(source_lang)
    target_name = _language_name(target_lang)
    lines_json = json.dumps(lines, ensure_ascii=False)

    prompt = TRANSLATION_PROMPT.format(source_lang=source_name, target_lang=target_name, lines_json=lines_json)
    if context:
        prompt = CONTEXT_PREFIX.format(context=context) + prompt
    if glossary_text:
        prompt = GLOSSARY_PREFIX.format(glossary=glossary_text) + prompt

    # Scale the token budget with input size so large chunks don't get
    # truncated mid-response (which would also break JSON parsing).
    n_predict = max(256, sum(len(line) for line in lines) * 4)

    payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.1,
        "stop": ["\n\n\n"],
    }

    url = f"{LLM_ENDPOINT}/completion"
    logger.debug(f"{log_prefix}Translating chunk {chunk_idx + 1}/{total_chunks} ({len(lines)} lines) with {LLM_MODEL}")

    resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    raw_output = strip_code_fence(data.get("content", ""))
    _log_timing(data)

    try:
        parsed = parse_json_response(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: failed to parse JSON response ({e}): {raw_output[:200]!r}")
        return None

    if isinstance(parsed, list) and len(lines) == 1 and len(parsed) > 1:
        # Confirmed via live testing: injecting the sliding-context prefix
        # before a single-line request can make the model echo its answer
        # more than once instead of respecting the requested array length --
        # not a real split, the entries are (near-)identical. Collapse
        # rather than fail, since discarding a duplicated-but-correct
        # translation is worse than the small risk of collapsing a
        # legitimately different pair of entries.
        deduped = [_clean_output(str(item)) for item in parsed]
        if len(set(deduped)) == 1:
            logger.warning(
                f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: model duplicated its answer into {len(parsed)} identical entries for a single-line request; collapsing to one"
            )
            return [deduped[0]]

    if not isinstance(parsed, list) or len(parsed) != len(lines):
        got = f"{type(parsed).__name__} of length {len(parsed)}" if isinstance(parsed, list) else type(parsed).__name__
        logger.warning(f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: expected a JSON array of {len(lines)} string(s), got {got}")
        return None

    return [_clean_output(str(item)) for item in parsed]


def translate_chunk(
    lines: List[str],
    target_lang: str = "en",
    source_lang: str = "ja",
    context: Optional[str] = None,
    glossary_text: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    chunk_idx: int = 0,
    total_chunks: int = 1,
    log_context: str = "",
) -> List[str]:
    """Translate a chunk of source lines as a JSON array using llama-server.

    If the model returns an array of the wrong length (confirmed via live
    testing: it sometimes splits one multi-sentence source line into two
    translated entries), retries by translating each line in the chunk
    individually rather than discarding the whole chunk -- losing one
    oversized/ambiguous line's worth of translation is a much smaller
    problem than losing every line in the chunk.

    Args:
        lines: The source lines/paragraphs to translate, in order.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        context: Optional previous paragraphs for consistency.
        glossary_text: Optional pre-formatted glossary text (character names/
            terms) to prepend to the prompt, from
            pyplayground.webnovels.glossary.format_glossary_for_prompt().
        progress_cb: Optional callback(done, total) for progress updates.
        chunk_idx: Current chunk index (0-based).
        total_chunks: Total number of chunks being translated.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error this call (and its retries) logs -- see
            _translate_chunk_once()'s docstring for why.

    Returns:
        List of translated strings, same length and order as `lines`. Any
        line that still can't be translated after the per-line retry
        becomes a `[translation failed: ...]` placeholder, so callers can
        rely on the length invariant unconditionally.

    Raises:
        requests.exceptions.ConnectionError: If llama-server is not reachable.
        requests.exceptions.Timeout: If the request times out.
    """
    log_prefix = f"[{log_context}] " if log_context else ""
    translated = _translate_chunk_once(lines, target_lang, source_lang, context, glossary_text, chunk_idx, total_chunks, log_context)

    if translated is None and len(lines) > 1:
        logger.info(f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: retrying as {len(lines)} individual line(s) after length mismatch")
        translated = []
        for line in lines:
            single = _translate_chunk_once([line], target_lang, source_lang, context, glossary_text, chunk_idx, total_chunks, log_context)
            translated.append(single[0] if single else "[translation failed: unparseable response]")

    if translated is None:
        translated = ["[translation failed: unparseable response]" for _ in lines]

    if progress_cb:
        progress_cb(chunk_idx + 1, total_chunks)

    return translated


def translate_chunk_with_masking(
    lines: List[str],
    mask_targets: List[Tuple[int, str]],
    target_lang: str = "en",
    source_lang: str = "ja",
    context: Optional[str] = None,
    glossary_text: Optional[str] = None,
    chunk_idx: int = 0,
    total_chunks: int = 1,
    fallbacks: Optional[Dict[str, str]] = None,
    log_context: str = "",
) -> List[TranslatedLine]:
    """Translate a chunk while masking specific terms with opaque sentinels.

    For the glossary review-queue feature: masks each target word so the
    model translates around it rather than through it, then splices a
    fallback (see `fallbacks`) back into the model's output untranslated.
    Validated against translategemma via test_sentinel_survival.py (15/15
    survival across single/multi-line and 5-sentinel-dense chunks) before
    being wired in here -- see that script and the comment above
    _SENTINEL_OPEN for why this is an opaque placeholder rather than an
    inline-wrapped format.

    Two distinct failure classes, two distinct recoveries:
      - A sentinel goes missing from an otherwise-populated line (e.g. the
        model dropped it): a fallback is spliced in at that position and
        the line is flagged needs_review.
      - A whole line comes back empty (confirmed failure mode on dense
        multi-sentinel chunks against a model without a chat template):
        retried once as its own single-line request. If the retry is also
        empty, falls back to the unmasked raw source line rather than
        retrying indefinitely or leaving it blank. Distinct from
        `fallbacks` below -- this is a whole-line recovery (the entire
        line's translation is gone, not just one masked term's marker), so
        it always uses the original source line verbatim, never a
        per-term candidate substitution.

    Args:
        lines: The source lines/paragraphs to translate, in order.
        mask_targets: (line_idx, word) pairs; word must appear verbatim in
            lines[line_idx]. A line may have multiple targets. Sentinel ids
            are assigned in the order given, unique across the whole chunk.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        context: Optional previous paragraphs for consistency.
        glossary_text: Optional pre-formatted glossary text to prepend to
            the prompt.
        chunk_idx: Current chunk index (0-based).
        total_chunks: Total number of chunks being translated.
        fallbacks: Optional dict mapping a masked word to a better display
            fallback than the bare word (normally its best-ranked
            suggested candidate -- see glossary.build_splice_fallbacks()).
            Passed straight through to splice_terms(); see its docstring.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error this call logs -- see
            _translate_chunk_once()'s docstring for why.

    Returns:
        List of TranslatedLine, same length and order as `lines`.
    """
    log_prefix = f"[{log_context}] " if log_context else ""
    targets_by_line: Dict[int, List[Tuple[str, int]]] = {}
    for term_id, (line_idx, word) in enumerate(mask_targets, start=1):
        targets_by_line.setdefault(line_idx, []).append((word, term_id))

    masked_lines = list(lines)
    for line_idx, targets in targets_by_line.items():
        masked_lines[line_idx] = mask_terms(masked_lines[line_idx], targets)

    raw_translated = translate_chunk(masked_lines, target_lang, source_lang, context, glossary_text, chunk_idx=chunk_idx, total_chunks=total_chunks, log_context=log_context)

    result: List[TranslatedLine] = []
    for line_idx, raw_line in enumerate(raw_translated):
        line_targets = targets_by_line.get(line_idx)
        if not line_targets:
            result.append(TranslatedLine(text=raw_line))
            continue

        if not raw_line.strip():
            logger.warning(f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: masked line {line_idx} came back empty; retrying once")
            retry = translate_chunk(
                [masked_lines[line_idx]], target_lang, source_lang, context, glossary_text, chunk_idx=chunk_idx, total_chunks=total_chunks, log_context=log_context
            )
            raw_line = retry[0] if retry else ""

        if not raw_line.strip():
            logger.warning(f"{log_prefix}Chunk {chunk_idx + 1}/{total_chunks}: masked line {line_idx} still empty after retry; falling back to raw source line")
            result.append(TranslatedLine(text=lines[line_idx], needs_review=True))
            continue

        result.append(splice_terms(raw_line, line_targets, fallbacks))

    return result


# Prompt for the glossary popup's "meaning & alternatives" reference lookup
# (alphapolis_reader.py's open_word_glossary_popup) -- a different task shape
# than plain translation, so it gets its own prompt/parsing rather than
# reusing TRANSLATION_PROMPT. Confirmed via live testing against both a
# multi-character Chinese term (封禁) and a Japanese pronoun+particle
# (オレの) that the same translategemma model handles this reasonably well
# despite being translation-specialized -- it's still a general
# instruction-tuned model under the hood.
#
# "category" (character vs. term) and the surrounding-sentence CONTEXT_LINE
# are both load-bearing, not decorative: confirmed live that without any
# sentence context, the model misclassifies invented/ambiguous character
# names (e.g. 桂名, 仁菜, 音夢 -- not in any dictionary, the same root cause
# documented in build_glossary.py's extraction prompt) as generic "term"
# rather than "character", since in isolation they read like ordinary kanji
# compounds. Passing the sentence the word actually appeared in fixed
# classification on every case tested -- the model can use grammatical/
# narrative cues (honorifics, dialogue address, verb agreement) that the
# bare word alone doesn't carry.
#
# Does NOT ask the model to state a character's gender as a bare fact in
# "meaning" -- confirmed via live testing that it will confidently assert a
# wrong gender there (音夢 first called "female" despite being addressed
# with the masculine -kun honorific in its own source sentence). Instead,
# it's told to USE honorifics/context as evidence when picking alternative
# romanizations, and explicitly warned off picking one whose connotation
# fights the evidence (the same 音夢 case: "Otome" is phonetically close but
# carries 乙女/"maiden" baggage that contradicts a -kun-addressed character).
# This is a narrower, evidence-grounded ask than "guess the gender" -- it
# constrains word choice rather than asserting an unverified claim.
EXPLAIN_TERM_PROMPT = (
    "You are a translation reference tool for a {source_lang}-to-{target_lang} novel translator. "
    "For the given {source_lang} term, provide: "
    '(1) category: is it a person\'s name/character ("character") or a general term/place/object/'
    'concept ("term")? '
    "(2) meaning: a literal meaning/etymology, breaking down each character or component if the "
    "term has more than one. If it is a character's name, describe only what the name literally "
    "means -- do NOT state the character's gender, age, or other attributes as fact. "
    "(3) alternatives: 2-4 alternative {target_lang} translations with a short note on tone/"
    "register for each. For a character's name, use any context clues available (e.g. honorifics "
    "like -kun/-chan/-san, how other characters address them) to avoid alternatives whose "
    "connotation conflicts with that evidence -- e.g. do not suggest a stereotypically feminine "
    "name/spelling for a character addressed with a masculine honorific, or vice versa. "
    "Output ONLY valid JSON, no other text, no markdown fences, in this exact shape:\n"
    '{{"category": "character" or "term", "meaning": "...", '
    '"characters": [{{"char": "X", "meaning": "..."}}], '
    '"alternatives": [{{"word": "...", "note": "..."}}]}}\n\n'
    "{context_line}"
    "Term: {term}\n\n"
    "JSON:"
)

CONTEXT_LINE_PREFIX = "The term appears in this sentence for context: {context}\n\n"


def explain_term(term: str, source_lang: str = "ja", target_lang: str = "en", context: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Ask the LLM for a term's meaning/etymology and alternative translations.

    Used by the reader's click-to-add-glossary-term popup to show a deeper
    reference than the plain translate_chunk() guess -- category (character
    vs. general term), component character breakdown, and tone-noted
    alternatives, for building a real glossary entry rather than just
    accepting a first-guess translation.

    Args:
        term: The source-language word/phrase to explain.
        source_lang: Source language code (default: ja).
        target_lang: Target language code (default: en).
        context: Optional sentence the term appeared in. Strongly
            recommended when available -- confirmed via live testing that
            without it, ambiguous/invented character names are often
            misclassified as a generic "term" rather than "character".

    Returns:
        Dict with "category" ("character" or "term"), "meaning" (str),
        "characters" (list of {"char", "meaning"}), and "alternatives"
        (list of {"word", "note"}), or None if the request failed or the
        response didn't parse as the expected shape.
    """
    context_line = CONTEXT_LINE_PREFIX.format(context=context) if context else ""
    prompt = EXPLAIN_TERM_PROMPT.format(source_lang=_language_name(source_lang), target_lang=_language_name(target_lang), context_line=context_line, term=term)
    payload = {"prompt": prompt, "n_predict": 512, "temperature": 0.1}
    url = f"{LLM_ENDPOINT}/completion"

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        raw_output = strip_code_fence(data.get("content", ""))
        parsed = parse_json_response(raw_output)
    except requests.exceptions.RequestException as e:
        logger.debug(f"Term explanation request failed for {term!r}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.debug(f"Term explanation output failed to parse as JSON for {term!r}: {e}")
        return None

    if not isinstance(parsed, dict) or "meaning" not in parsed:
        logger.debug(f"Term explanation returned unexpected shape for {term!r}: {type(parsed).__name__}")
        return None

    category = parsed.get("category")
    if category not in ("character", "term"):
        category = "term"

    return {
        "category": category,
        "meaning": parsed.get("meaning", ""),
        "characters": parsed.get("characters", []),
        "alternatives": parsed.get("alternatives", []),
    }


# RETRANSLATION_DESIGN.md phase 2: single-line retranslation with a hint,
# for correcting a specific vocabulary/idiom mistranslation (not a proper
# noun/glossary-term issue -- that's the masking path in this same file;
# this is a different failure class, tracked in a separate doc on purpose,
# per that doc's own framing).
#
# Output format decided empirically, not assumed, per RETRANSLATION_DESIGN.md's
# explicit instruction -- tried plain-text-in/plain-text-out first (skips the
# JSON-array wrapper's entire class of escaping/malformation failures
# documented in DESIGN.md Sections 4/5 for this same model): 4 live calls
# against translategemma (3 repeats of one case, 1 different case) all
# returned clean plain text with no quotes/commentary/markdown fences, just
# incidental leading/trailing whitespace (stripped below). No fallback to a
# JSON-array wrapper was needed -- plain text held up across every real call
# tried. See RETRANSLATION_DESIGN.md's phase 2 status entry for the actual
# before/after examples this was validated against.
RETRANSLATE_LINE_PROMPT = (
    "You are a translation correction tool. Given a {source_lang} source line, its current "
    "{target_lang} translation, and a word/phrase to focus on, output ONLY the corrected "
    "{target_lang} translation of the full line -- no notes, no explanations, no quotes around "
    "the answer, no markdown.\n\n"
    "Pay particular attention to accurately translating this word/phrase: {hint}\n\n"
    "{source_lang} source line: {source_line}\n"
    "Current (possibly incorrect) translation: {current_translation}\n\n"
    "{glossary_prefix}"
    "Corrected translation:"
)


def retranslate_line_with_hint(
    source_line: str,
    current_translation: str,
    hint: str,
    source_lang: str = "ja",
    target_lang: str = "en",
    glossary_text: Optional[str] = None,
) -> Optional[str]:
    """Ask the LLM to retranslate one line, focusing on a specific word/phrase the user flagged.

    RETRANSLATION_DESIGN.md phase 2: the retranslation engine. Sees only
    the single line (source + its current translation), not surrounding
    context -- the documented v1 simplification, not an oversight (see
    that doc's "Explicitly deferred" section). This is a genuinely
    different call shape from translate_chunk_with_masking() (which masks
    proper nouns/glossary terms before translating a whole chunk) -- this
    corrects one already-translated line's ordinary-vocabulary/idiom
    mistranslation, hinted by a user-selected word/phrase. Does not call,
    and is not called by, any masking-path function.

    Takes glossary_text (pre-formatted), not a raw glossary dict, matching
    every other function in this module (translate_chunk(),
    translate_chunk_with_masking(), etc.) -- this module never imports
    glossary.py; callers format the glossary themselves via
    glossary.format_glossary_for_prompt() before passing it in.

    Args:
        source_line: The original-language line being corrected.
        current_translation: The existing (possibly wrong) translation of
            that line.
        hint: The word/phrase the user selected in the original line,
            passed to the model as "pay particular attention to this."
        source_lang: Source language code (default: ja).
        target_lang: Target language code (default: en).
        glossary_text: Optional pre-formatted glossary text (confirmed
            terms only -- see glossary.format_glossary_for_prompt()), for
            terminology consistency in the corrected line.

    Returns:
        The corrected translation string, or None if the request failed
        or the response was empty after stripping.
    """
    glossary_prefix = GLOSSARY_PREFIX.format(glossary=glossary_text) if glossary_text else ""
    prompt = RETRANSLATE_LINE_PROMPT.format(
        source_lang=_language_name(source_lang),
        target_lang=_language_name(target_lang),
        hint=hint,
        source_line=source_line,
        current_translation=current_translation,
        glossary_prefix=glossary_prefix,
    )
    payload = {"prompt": prompt, "n_predict": max(128, len(source_line) * 4), "temperature": 0.1}
    url = f"{LLM_ENDPOINT}/completion"

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logger.debug(f"Retranslation request failed for hint {hint!r}: {e}")
        return None

    corrected = strip_code_fence(data.get("content", "")).strip()
    # Plain-text output, not JSON -- strip_code_fence() is still reused in
    # case the model wraps the answer in a code fence despite being asked
    # not to (not observed in live testing, but a cheap, already-existing
    # safeguard). A stray pair of surrounding quotes is also common enough
    # in free-text LLM output generally (not observed for this specific
    # prompt in testing, but plausible) to strip defensively.
    if len(corrected) >= 2 and corrected[0] == '"' and corrected[-1] == '"':
        corrected = corrected[1:-1].strip()

    if not corrected:
        logger.debug(f"Retranslation returned empty output for hint {hint!r}")
        return None

    return corrected


def translate_lines(
    lines: List[str],
    target_lang: str = "en",
    source_lang: str = "ja",
    max_chunk_chars: int = 400,
    context_window: int = 3,
    glossary_text: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    log_context: str = "",
) -> List[str]:
    """Translate a list of text lines using LLM with sliding context.

    Groups lines into chunks respecting the max character limit, then
    translates each chunk as a JSON array (see TRANSLATION_PROMPT), which
    guarantees translate_chunk() returns exactly one output per input line
    in order -- there's no paragraph-merging/splitting to recover from like
    the old label-based prompt format had.

    Args:
        lines: List of source text lines/paragraphs to translate.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        max_chunk_chars: Maximum characters per translation chunk.
        context_window: Number of previous paragraphs to use as context.
        glossary_text: Optional pre-formatted glossary text (character names/
            terms), prepended to every chunk's prompt for consistency. See
            pyplayground.webnovels.glossary.
        progress_cb: Optional callback(done, total) for progress updates.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error logged for this call and its chunks --
            found necessary via a real live-test log where a chunk-level
            failure couldn't be traced back to which episode produced it
            without cross-referencing timestamps against a separate log
            line. Empty by default (matches every existing call site
            unchanged).

    Returns:
        List of translated text lines, same length as `lines`.
    """
    log_prefix = f"[{log_context}] " if log_context else ""
    # Pack lines into chunks respecting size limit
    chunks: List[List[str]] = []
    current_chunk: List[str] = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > max_chunk_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += len(line) + 2  # +2 for newline separator
    if current_chunk:
        chunks.append(current_chunk)

    logger.info(f"{log_prefix}Translating {len(lines)} lines in {len(chunks)} chunks using {LLM_MODEL}")

    translated_lines: List[str] = []
    # Keep last N translated paragraphs as context
    context_buffer: List[str] = []

    for i, chunk in enumerate(chunks):
        # Build context from previous translations
        context = ""
        if context_buffer:
            context = "\n\n".join(context_buffer[-context_window:])

        try:
            parts = translate_chunk(
                chunk,
                target_lang=target_lang,
                source_lang=source_lang,
                context=context,
                glossary_text=glossary_text,
                progress_cb=progress_cb,
                chunk_idx=i,
                total_chunks=len(chunks),
                log_context=log_context,
            )
        except Exception as e:
            logger.error(f"{log_prefix}Chunk {i + 1}/{len(chunks)} failed: {e}")
            parts = [f"[translation failed: {e}]" for _ in chunk]

        translated_lines.extend(parts)

        # Update context buffer
        for part in parts:
            context_buffer.append(part)
            # Keep buffer manageable
            if len(context_buffer) > context_window * 2:
                context_buffer = context_buffer[-context_window * 2 :]

        # Small delay between chunks to avoid overwhelming the model
        time.sleep(0.1)

    logger.info(f"{log_prefix}Translation complete: {len(translated_lines)} lines")
    return translated_lines


def translate_lines_with_masking(
    lines: List[str],
    mask_targets: List[Tuple[int, str]],
    target_lang: str = "en",
    source_lang: str = "ja",
    max_chunk_chars: int = 400,
    context_window: int = 3,
    glossary_text: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    fallbacks: Optional[Dict[str, str]] = None,
    log_context: str = "",
) -> List[TranslatedLine]:
    """Translate a list of text lines with sliding context, masking unconfirmed glossary terms.

    Sibling to translate_lines() (kept separate, not a parameter on it, to
    avoid a conditional-return-type function -- same pattern as
    translate_chunk_with_masking() being a sibling of translate_chunk()
    rather than a flag on it). Returns List[TranslatedLine] instead of
    List[str] -- callers that don't need masking should keep using
    translate_lines(), which is unchanged.

    Args:
        lines: List of source text lines/paragraphs to translate.
        mask_targets: (line_idx, word) pairs, indices relative to `lines`
            as a whole (e.g. from glossary.build_mask_targets(lines, glossary)) --
            NOT chunk-relative. This function re-indexes each target to be
            relative to whichever chunk it falls in before calling
            translate_chunk_with_masking(), since chunking is internal to
            this function and mask_targets is expressed against the full
            input.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        max_chunk_chars: Maximum characters per translation chunk.
        context_window: Number of previous paragraphs to use as context.
        glossary_text: Optional pre-formatted glossary text, prepended to
            every chunk's prompt for consistency.
        progress_cb: Optional callback(done, total) for progress updates.
        fallbacks: Optional dict mapping a masked word to a better display
            fallback than the bare word (see glossary.build_splice_fallbacks()).
            Passed straight through to every chunk's
            translate_chunk_with_masking() call; not re-indexed per chunk
            since it's keyed by word, not line index.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error logged for this call and its chunks -- see
            translate_lines()'s docstring for why.

    Returns:
        List of TranslatedLine, same length as `lines`.
    """
    log_prefix = f"[{log_context}] " if log_context else ""
    # Pack lines into chunks respecting size limit -- identical logic to
    # translate_lines(), but also tracking each chunk's starting offset
    # into `lines` so mask_targets (expressed against the full input) can
    # be re-indexed to be chunk-relative below.
    chunks: List[List[str]] = []
    chunk_offsets: List[int] = []
    current_chunk: List[str] = []
    current_len = 0
    offset = 0

    for i, line in enumerate(lines):
        if current_len + len(line) > max_chunk_chars and current_chunk:
            chunks.append(current_chunk)
            chunk_offsets.append(offset)
            current_chunk = []
            current_len = 0
            offset = i
        current_chunk.append(line)
        current_len += len(line) + 2
    if current_chunk:
        chunks.append(current_chunk)
        chunk_offsets.append(offset)

    logger.info(f"{log_prefix}Translating {len(lines)} lines in {len(chunks)} chunks (masking {len(mask_targets)} term occurrence(s)) using {LLM_MODEL}")

    translated_lines: List[TranslatedLine] = []
    context_buffer: List[str] = []

    for i, (chunk, chunk_offset) in enumerate(zip(chunks, chunk_offsets)):
        context = ""
        if context_buffer:
            context = "\n\n".join(context_buffer[-context_window:])

        chunk_end = chunk_offset + len(chunk)
        chunk_mask_targets = [(line_idx - chunk_offset, word) for line_idx, word in mask_targets if chunk_offset <= line_idx < chunk_end]

        try:
            parts = translate_chunk_with_masking(
                chunk,
                chunk_mask_targets,
                target_lang=target_lang,
                source_lang=source_lang,
                context=context,
                glossary_text=glossary_text,
                chunk_idx=i,
                total_chunks=len(chunks),
                fallbacks=fallbacks,
                log_context=log_context,
            )
        except Exception as e:
            logger.error(f"{log_prefix}Chunk {i + 1}/{len(chunks)} failed: {e}")
            parts = [TranslatedLine(text=f"[translation failed: {e}]") for _ in chunk]

        translated_lines.extend(parts)

        for part in parts:
            context_buffer.append(part.text)
            if len(context_buffer) > context_window * 2:
                context_buffer = context_buffer[-context_window * 2 :]

        if progress_cb:
            progress_cb(i + 1, len(chunks))

        time.sleep(0.1)

    logger.info(f"{log_prefix}Translation complete: {len(translated_lines)} lines")
    return translated_lines


def check_llm_available(endpoint: Optional[str] = None) -> bool:
    """Check if the LLM server is reachable and has the configured model.

    Args:
        endpoint: LLM API URL (default: LLM_ENDPOINT env var).

    Returns:
        True if the server is available and the model is loaded.
    """
    url = endpoint or LLM_ENDPOINT
    try:
        resp = requests.get(f"{url}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        # Check if the model (or a prefix match) is available
        model_name = str(LLM_MODEL)
        available = any(model_name.startswith(m.split(":")[0]) for m in models)
        if not available:
            logger.warning(f"Model {LLM_MODEL} not found in LLM server. Available: {', '.join(models)}")
        return available
    except Exception:
        logger.debug(f"LLM server not reachable at {url}")
        return False
