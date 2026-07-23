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
from typing import Callable, List, Optional

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
# Labeling the source text under "{source_lang}:" and starting the model's
# turn at "{target_lang}:" (rather than appending the source text after a
# free-floating instruction) reliably stops the model from echoing the
# source text or continuing the story past the given input -- confirmed via
# live testing against the target server. Without this framing the model
# would generate the source text again before translating it, followed by
# invented continuation content.
TRANSLATION_PROMPT = (
    "Translate the following {source_lang} text to {target_lang}. Output "
    "ONLY the {target_lang} translation and nothing else -- do not repeat "
    "or echo the {source_lang} source text, and do not continue the story "
    "beyond what is given. Preserve paragraph structure using blank lines "
    "between paragraphs. If you are unsure about a proper noun (character "
    "name, place name), transliterate it using standard romanization "
    "conventions.\n\n"
    "{source_lang}:\n{text}\n\n"
    "{target_lang}:"
)

# Sliding window context prompt prefix, inserted before the instruction line.
CONTEXT_PREFIX = "Here is the context from the previous paragraphs for consistency:\n{context}\n\n"

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


def _log_timing(data: dict) -> None:
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


def translate_chunk(
    text: str,
    target_lang: str = "en",
    source_lang: str = "ja",
    context: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    chunk_idx: int = 0,
    total_chunks: int = 1,
) -> str:
    """Translate a single text chunk using llama-server's /completion endpoint.

    Args:
        text: The source text to translate.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        context: Optional previous paragraphs for consistency.
        progress_cb: Optional callback(done, total) for progress updates.
        chunk_idx: Current chunk index (0-based).
        total_chunks: Total number of chunks being translated.

    Returns:
        The translated text string.

    Raises:
        requests.exceptions.ConnectionError: If llama-server is not reachable.
        RuntimeError: If the translation fails.
    """
    source_name = _language_name(source_lang)
    target_name = _language_name(target_lang)

    prompt = TRANSLATION_PROMPT.format(source_lang=source_name, target_lang=target_name, text=text)
    if context:
        prompt = CONTEXT_PREFIX.format(context=context) + prompt

    # Stop once the model starts a new "<language>:" label or drops into an
    # unrelated blank-line-separated block -- prevents echoing the source
    # text or continuing the story past the given input (see TRANSLATION_PROMPT).
    stop_sequences = [f"\n\n{source_name}:", f"\n\n{target_name}:", "\n\n\n"]

    # Scale the token budget with input size so large chunks (e.g. many
    # short paragraphs packed together) don't get truncated mid-translation,
    # which was observed to cause the model to drift/hallucinate rather than
    # stopping cleanly. ~4 chars/token is a safe margin for English output,
    # with a floor so short chunks still get enough room.
    n_predict = max(256, len(text) * 4)

    payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.1,
        "stop": stop_sequences,
    }

    url = f"{LLM_ENDPOINT}/completion"
    logger.debug(f"Translating chunk {chunk_idx + 1}/{total_chunks} with {LLM_MODEL}")

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to LLM server at {LLM_ENDPOINT}. Is llama-server running?")
        raise
    except requests.exceptions.Timeout:
        logger.error(f"Translation request timed out after {LLM_TIMEOUT}s")
        raise
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        raise RuntimeError(f"LLM translation failed: {e}") from e

    raw_output = data.get("content", "")
    translated = _clean_output(raw_output)

    _log_timing(data)

    if progress_cb:
        progress_cb(chunk_idx + 1, total_chunks)

    return translated


def translate_lines(
    lines: List[str],
    target_lang: str = "en",
    source_lang: str = "ja",
    max_chunk_chars: int = 400,
    context_window: int = 3,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translate a list of text lines using LLM with sliding context.

    Groups lines into chunks respecting the max character limit, then
    translates each chunk. Maintains a sliding window of previously
    translated paragraphs as context for consistency.

    Args:
        lines: List of source text lines/paragraphs to translate.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).
        max_chunk_chars: Maximum characters per translation chunk. Kept
            small (default 400, roughly 3-6 short paragraphs) because
            translategemma doesn't reliably keep blank-line boundaries
            between many packed paragraphs in one call -- larger chunks
            were observed to silently merge paragraphs together, which
            the fallback below then collapses into a single oversized
            "line" instead of preserving per-paragraph granularity.
        context_window: Number of previous paragraphs to use as context.
        progress_cb: Optional callback(done, total) for progress updates.

    Returns:
        List of translated text lines.
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

        joined = "\n\n".join(chunk)
        try:
            translated = translate_chunk(
                joined,
                target_lang=target_lang,
                source_lang=source_lang,
                context=context,
                progress_cb=progress_cb,
                chunk_idx=i,
                total_chunks=len(chunks),
            )
        except Exception as e:
            logger.error(f"Chunk {i + 1}/{len(chunks)} failed: {e}")
            translated = "\n\n".join(f"[translation failed: {e}]" for _ in chunk)

        # Split back into per-line translations
        parts = translated.split("\n\n")
        if len(parts) == len(chunk):
            translated_lines.extend(parts)
        else:
            # Fallback: treat entire chunk as one block
            translated_lines.append(translated)

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
        available = any(LLM_MODEL.startswith(m.split(":")[0]) for m in models)
        if not available:
            logger.warning(f"Model {LLM_MODEL} not found in LLM server. Available: {', '.join(models)}")
        return available
    except Exception:
        logger.debug(f"LLM server not reachable at {url}")
        return False
