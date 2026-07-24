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
import time
from typing import Any, Callable, Dict, List, Optional

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

    Returns:
        List of translated strings, same length and order as `lines`, or
        None if the response didn't parse as a JSON array of that length.

    Raises:
        requests.exceptions.ConnectionError: If llama-server is not reachable.
        requests.exceptions.Timeout: If the request times out.
    """
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
    logger.debug(f"Translating chunk {chunk_idx + 1}/{total_chunks} ({len(lines)} lines) with {LLM_MODEL}")

    resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    raw_output = strip_code_fence(data.get("content", ""))
    _log_timing(data)

    try:
        parsed = parse_json_response(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"Chunk {chunk_idx + 1}/{total_chunks}: failed to parse JSON response ({e}): {raw_output[:200]!r}")
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
            logger.warning(f"Chunk {chunk_idx + 1}/{total_chunks}: model duplicated its answer into {len(parsed)} identical entries for a single-line request; collapsing to one")
            return [deduped[0]]

    if not isinstance(parsed, list) or len(parsed) != len(lines):
        got = f"{type(parsed).__name__} of length {len(parsed)}" if isinstance(parsed, list) else type(parsed).__name__
        logger.warning(f"Chunk {chunk_idx + 1}/{total_chunks}: expected a JSON array of {len(lines)} string(s), got {got}")
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

    Returns:
        List of translated strings, same length and order as `lines`. Any
        line that still can't be translated after the per-line retry
        becomes a `[translation failed: ...]` placeholder, so callers can
        rely on the length invariant unconditionally.

    Raises:
        requests.exceptions.ConnectionError: If llama-server is not reachable.
        requests.exceptions.Timeout: If the request times out.
    """
    translated = _translate_chunk_once(lines, target_lang, source_lang, context, glossary_text, chunk_idx, total_chunks)

    if translated is None and len(lines) > 1:
        logger.info(f"Chunk {chunk_idx + 1}/{total_chunks}: retrying as {len(lines)} individual line(s) after length mismatch")
        translated = []
        for line in lines:
            single = _translate_chunk_once([line], target_lang, source_lang, context, glossary_text, chunk_idx, total_chunks)
            translated.append(single[0] if single else "[translation failed: unparseable response]")

    if translated is None:
        translated = ["[translation failed: unparseable response]" for _ in lines]

    if progress_cb:
        progress_cb(chunk_idx + 1, total_chunks)

    return translated


def translate_lines(
    lines: List[str],
    target_lang: str = "en",
    source_lang: str = "ja",
    max_chunk_chars: int = 400,
    context_window: int = 3,
    glossary_text: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
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

    Returns:
        List of translated text lines, same length as `lines`.
    """
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

    logger.info(f"Translating {len(lines)} lines in {len(chunks)} chunks using {LLM_MODEL}")

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
            )
        except Exception as e:
            logger.error(f"Chunk {i + 1}/{len(chunks)} failed: {e}")
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

    logger.info(f"Translation complete: {len(translated_lines)} lines")
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
