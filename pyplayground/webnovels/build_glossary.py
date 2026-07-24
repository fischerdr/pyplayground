#!/usr/bin/env python3
"""build_glossary.py - Extract a per-novel glossary from cached episodes.

Scans the Alphapolis reader's on-disk episode cache
(~/.cache/alphapolis_reader/*.json) for episodes belonging to a given novel,
sends each episode's original + already-translated text to the LLM to
extract character names/terms and a short running context summary, then
merges the results into that novel's glossary file
(~/.config/alphapolis_reader/glossaries/{novel_id}.json).

Decoupled from the reader's live translation path on purpose: this can be
slow (one extra LLM call per episode) and isn't needed for every reading
session, so it's a separate manual step you run when you want the glossary
refreshed, not something wired into every episode load.

Usage:
    python build_glossary.py <novel_id>
    python build_glossary.py <episode_url>
    python build_glossary.py <novel_id> --max-episodes 10
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.webnovels.glossary import (
    HONORIFIC_POLICIES,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    load_glossary,
    merge_terms,
    save_glossary,
)
from pyplayground.webnovels.llm_translate import LLM_ENDPOINT, LLM_TIMEOUT, parse_json_response, strip_code_fence

logger = get_logger(__name__)

CACHE_DIR = Path.home() / ".cache" / "alphapolis_reader"

NOVEL_ID_RE = re.compile(r"/novel/(\d+)/")

# Asks for "character" entries to include gender/pronoun_style so the
# glossary can preserve voice/tone that a flat name mapping loses --
# Japanese frequently omits subject pronouns, and the ones used (俺/僕/私/
# あたし/わし etc.) encode gender, age, formality, and personality. "term"
# entries (places, magic systems, item names) don't need that detail.
# Also asks for one novel-wide honorific_policy suggestion (the user can
# override in the term editor); this is a single-word classification, not
# narrative text, so it doesn't carry the hallucination risk that a
# free-form context/scene summary would (see glossary.py's
# format_glossary_for_prompt() docstring for why context_notes was dropped
# from what gets sent to the translator).
#
# Uses a full worked example rather than a schema description -- confirmed
# via live testing that a schema-style prompt ("type": "character" or
# "term", ...) caused this model to ignore the glossary-extraction task
# entirely and instead just re-translate the input as a JSON array (the
# shape used elsewhere in this codebase for actual translation calls). A
# concrete example output fixed it completely.
_EXTRACTION_EXAMPLE = json.dumps(
    {
        "terms": [
            {
                "type": TERM_TYPE_CHARACTER,
                "source": "一郎",
                "target": "Ichiro",
                "note": "protagonist",
                "gender": "male",
                "pronoun_style": "casual, uses 'ore' -- brusque",
            },
            {"type": TERM_TYPE_GENERAL, "source": "魔法", "target": "magic", "note": None},
        ],
        "honorific_policy_suggestion": "drop",
        "context_note": "One sentence summary of cast/tone so far.",
    },
    ensure_ascii=False,
)

EXTRACTION_PROMPT_PREFIX = (
    "Extract a translation glossary from this web novel chapter sample. "
    "List character names and recurring terms (titles, places, magic systems, nicknames) "
    "that a translator should keep consistent across chapters. "
    "Output ONLY valid JSON, no other text, no markdown fences.\n\n"
    f"Example output format:\n{_EXTRACTION_EXAMPLE}\n\n"
    f'"type" is "{TERM_TYPE_CHARACTER}" for named people, "{TERM_TYPE_GENERAL}" for everything else. '
    '"gender" and "pronoun_style" only apply to characters (null otherwise). "pronoun_style" is a short '
    "phrase on a character's first-person pronoun/speech register, or null if not evident from this sample. "
    f'"honorific_policy_suggestion" is one of {HONORIFIC_POLICIES}, reflecting how honorifics '
    "(-san/-chan/-sama, or kinship address terms) are used in this text, or null if not evident. "
    "If there is nothing to add, return empty terms and an empty context_note.\n\n"
    "Now extract from this text:\n\n"
)
"""Prompt prefix built with f-strings (no {source}/{translated} placeholders
here) -- kept separate from the source/translated text so the JSON example's
literal braces never collide with str.format() placeholder syntax."""


def _build_extraction_prompt(source: str, translated: str) -> str:
    """Assemble the glossary extraction prompt for one episode's text.

    Args:
        source: Original-language paragraphs, joined.
        translated: Corresponding translated paragraphs, joined.

    Returns:
        The full prompt string.
    """
    return f"{EXTRACTION_PROMPT_PREFIX}Original (Japanese):\n{source}\n\nTranslation (English):\n{translated}\n\nJSON:"


def _extract_novel_id(novel_id_or_url: str) -> str:
    """Resolve a CLI argument to a novel ID, accepting either a bare ID or an episode URL.

    Args:
        novel_id_or_url: Either a novel ID (digits) or a full episode URL.

    Returns:
        The novel ID string.

    Raises:
        SystemExit: If the argument is a URL that doesn't match the expected pattern.
    """
    if novel_id_or_url.isdigit():
        return novel_id_or_url
    match = NOVEL_ID_RE.search(novel_id_or_url)
    if not match:
        print(f"Could not extract a novel ID from: {novel_id_or_url}", file=sys.stderr)
        sys.exit(2)
    return match.group(1)


def _load_cached_episodes_for_novel(novel_id: str) -> List[Dict[str, Any]]:
    """Load all cached episodes belonging to a given novel.

    Cache filenames are content-hashed, not sequential, and episode dicts
    don't carry a chapter number, so there's no reliable way to sort by
    actual reading order. Sorting by file modification time (oldest first)
    is used as a reasonable proxy, since episodes are typically cached in
    the order they were read.

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        List of cached episode dicts, ordered by cache file mtime (oldest first).
    """
    episodes: List[Dict[str, Any]] = []
    if not CACHE_DIR.exists():
        return episodes
    for path in CACHE_DIR.glob("*.json"):
        try:
            episode = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Skipping unreadable cache file {path}: {e}")
            continue
        if episode.get("novel_id") == novel_id:
            episode["_cache_mtime"] = path.stat().st_mtime
            episodes.append(episode)
    episodes.sort(key=lambda ep: ep["_cache_mtime"])
    return episodes


def extract_glossary_terms(source_lines: List[str], translated_lines: List[str]) -> Dict[str, Any]:
    """Ask the LLM to extract glossary terms from one episode's text.

    Args:
        source_lines: Original-language paragraphs.
        translated_lines: Corresponding translated paragraphs.

    Returns:
        Dict with "terms" (list of term dicts, see glossary.py for shape),
        "honorific_policy_suggestion" (str or None), and "context_note"
        (str), or empty/None values if extraction fails.
    """
    source_text = "\n\n".join(source_lines)
    translated_text = "\n\n".join(translated_lines)
    prompt = _build_extraction_prompt(source_text, translated_text)

    # Scale the token budget with input size, same rationale as
    # llm_translate.translate_chunk(): fixed budgets truncate long episodes
    # mid-response, which can leave the model emitting malformed/incomplete JSON.
    n_predict = max(512, len(prompt) // 2)

    payload = {"prompt": prompt, "n_predict": n_predict, "temperature": 0.1}
    url = f"{LLM_ENDPOINT}/completion"

    empty_result: Dict[str, Any] = {"terms": [], "honorific_policy_suggestion": None, "context_note": ""}

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        raw_output = strip_code_fence(data.get("content", ""))
        parsed = parse_json_response(raw_output)
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM request failed during glossary extraction: {e}")
        return empty_result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM glossary extraction output as JSON: {e}")
        return empty_result

    if isinstance(parsed, list):
        # Confirmed via live testing: on content-sparse chapters (e.g. a
        # dream sequence with few/no named characters or clear terms), the
        # model sometimes ignores the extraction task entirely and instead
        # falls back to its more heavily-trained "translate this text" JSON
        # array behavior (the same response shape llm_translate.py uses for
        # actual translation calls). That's a normal "nothing to extract
        # here" outcome for this episode, not a real error worth alarming
        # about in the logs -- log it quietly and move on.
        logger.debug(
            "Glossary extraction returned a translation-shaped JSON array instead of the extraction object -- likely a content-sparse chapter with nothing to extract; skipping."
        )
        return empty_result

    if not isinstance(parsed, dict):
        logger.error(f"Glossary extraction returned unexpected JSON shape ({type(parsed).__name__}, expected object)")
        return empty_result

    honorific_suggestion = parsed.get("honorific_policy_suggestion")
    if honorific_suggestion not in HONORIFIC_POLICIES:
        honorific_suggestion = None

    return {
        "terms": parsed.get("terms", []),
        "honorific_policy_suggestion": honorific_suggestion,
        "context_note": parsed.get("context_note", ""),
    }


def build_glossary_for_novel(novel_id: str, max_episodes: int = 20, status_cb: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
    """Extract and merge glossary terms from a novel's cached episodes.

    Core logic shared by the CLI (main(), below) and the reader's in-app
    "Rebuild Glossary" button (alphapolis_reader_v01.ReaderApp -- runs this
    on a background thread so the glossary dialog doesn't freeze while it
    makes one LLM call per episode).

    Args:
        novel_id: The Alphapolis novel ID.
        max_episodes: Maximum number of cached episodes to scan,
            most-recently-cached first.
        status_cb: Optional callback(message) invoked with a short status
            string before/after each episode is processed, for progress
            reporting. If None, no progress reporting happens (callers that
            want console output should pass status_cb=print, as main() does).

    Returns:
        The updated glossary dict (already saved to disk), or None if there
        were no cached episodes to process at all (distinct from processing
        episodes and finding zero terms, which still returns a saved dict).
    """

    def report(message: str) -> None:
        # Always goes to the log file (INFO) regardless of whether a
        # status_cb was given, so a rebuild triggered from the reader's
        # "Rebuild Glossary" button (whose status_cb only updates a small
        # in-dialog label, never the log) still leaves a durable record to
        # troubleshoot from -- status_cb is purely for live UI/console
        # feedback, logging is unconditional.
        logger.info(message)
        if status_cb:
            status_cb(message)

    logger.info(f"Starting glossary rebuild for novel {novel_id} (max_episodes={max_episodes})")

    episodes = _load_cached_episodes_for_novel(novel_id)
    if not episodes:
        report(f"No cached episodes found for novel {novel_id}. Read some chapters first, then rebuild.")
        return None

    total_cached = len(episodes)
    episodes = episodes[-max_episodes:] if max_episodes else episodes
    report(f"Found {total_cached} cached episode(s) for novel {novel_id}; processing {len(episodes)}.")

    glossary = load_glossary(novel_id)
    existing_term_count = len(glossary.get("terms", []))
    if not glossary.get("title") and episodes:
        glossary["title"] = episodes[0].get("title", "")

    context_notes: List[str] = []
    extraction_failures = 0
    for i, episode in enumerate(episodes, 1):
        source_lines = episode.get("lines", [])
        translated_lines = episode.get("translated_lines", [])
        if not source_lines or not translated_lines:
            report(f"[{i}/{len(episodes)}] Skipping episode with no translated text (url={episode.get('url', 'unknown')}).")
            continue

        report(f"[{i}/{len(episodes)}] Extracting terms from: {episode.get('episode_title', 'unknown')}")
        result = extract_glossary_terms(source_lines, translated_lines)
        new_terms = result.get("terms", [])
        if new_terms:
            before = len(glossary.get("terms", []))
            glossary["terms"] = merge_terms(glossary.get("terms", []), new_terms)
            added = len(glossary["terms"]) - before
            report(f"    Extracted {len(new_terms)} term(s), {added} new after merge: {', '.join(t.get('source', '?') for t in new_terms)}")
        else:
            extraction_failures += 1
            logger.debug(f"[{i}/{len(episodes)}] No terms extracted from {episode.get('episode_title', 'unknown')}")
        # Only apply an extracted suggestion if the user hasn't explicitly
        # set a policy themselves via the term editor -- don't clobber a
        # deliberate choice with an auto-detected guess from a later run.
        if result.get("honorific_policy_suggestion") and not glossary.get("honorific_policy_user_set"):
            logger.debug(f"[{i}/{len(episodes)}] Applying honorific_policy_suggestion: {result['honorific_policy_suggestion']}")
            glossary["honorific_policy"] = result["honorific_policy_suggestion"]
        if result.get("context_note"):
            context_notes.append(result["context_note"])

    if context_notes:
        glossary["context_notes"] = " ".join(context_notes[-3:])

    glossary["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_glossary(novel_id, glossary)
    final_term_count = len(glossary.get("terms", []))
    report(
        f"Glossary saved: {final_term_count} total term(s) for novel {novel_id} "
        f"({final_term_count - existing_term_count} new since this rebuild started, "
        f"{extraction_failures}/{len(episodes)} episode(s) yielded no terms)."
    )
    return glossary


def main() -> None:
    """Entry point for the glossary-builder CLI."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Build/update a per-novel translation glossary from cached episodes")
    parser.add_argument("novel", help="Novel ID or an episode URL for the target novel")
    parser.add_argument(
        "--max-episodes",
        type=int,
        default=20,
        help="Maximum number of cached episodes to scan, most-recently-cached first (default: 20)",
    )
    args = parser.parse_args()

    novel_id = _extract_novel_id(args.novel)
    glossary = build_glossary_for_novel(novel_id, max_episodes=args.max_episodes, status_cb=print)
    if glossary is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
