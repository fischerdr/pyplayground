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
from typing import Any, Dict, List

import requests

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.webnovels.glossary import load_glossary, merge_terms, save_glossary
from pyplayground.webnovels.llm_translate import LLM_ENDPOINT, LLM_TIMEOUT

logger = get_logger(__name__)

CACHE_DIR = Path.home() / ".cache" / "alphapolis_reader"

NOVEL_ID_RE = re.compile(r"/novel/(\d+)/")

EXTRACTION_PROMPT = (
    "You are analyzing a chapter of a web novel to build a translation glossary. "
    "Given the original text and its English translation below, list any character "
    "names or recurring terms (titles, places, magic systems, nicknames) that a "
    "translator should keep consistent across chapters.\n\n"
    "Output ONLY a JSON object with this exact shape, no other text:\n"
    '{{"terms": [{{"source": "...", "target": "...", "note": "..."}}], "context_note": "..."}}\n\n'
    '"terms" is a list of source-language name/term -> English translation pairs '
    '(note is optional, one short phrase). "context_note" is a single sentence '
    "describing the cast/tone so far, suitable for prepending to future chapters. "
    "If there is nothing new to add, return empty terms and an empty context_note.\n\n"
    "Original text:\n{source}\n\n"
    "English translation:\n{translated}\n\n"
    "JSON:"
)


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
        Dict with "terms" (list of {"source", "target", "note"}) and
        "context_note" (str), or empty values if extraction fails.
    """
    source_text = "\n\n".join(source_lines)
    translated_text = "\n\n".join(translated_lines)
    prompt = EXTRACTION_PROMPT.format(source=source_text, translated=translated_text)

    # Scale the token budget with input size, same rationale as
    # llm_translate.translate_chunk(): fixed budgets truncate long episodes
    # mid-response, which can leave the model emitting malformed/incomplete JSON.
    n_predict = max(512, len(prompt) // 2)

    payload = {"prompt": prompt, "n_predict": n_predict, "temperature": 0.1}
    url = f"{LLM_ENDPOINT}/completion"

    empty_result: Dict[str, Any] = {"terms": [], "context_note": ""}

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        raw_output = data.get("content", "").strip()
        # Model may wrap the JSON in a code fence despite instructions; strip it defensively.
        if raw_output.startswith("```"):
            raw_output = raw_output.strip("`").removeprefix("json").strip()
        parsed = json.loads(raw_output)
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM request failed during glossary extraction: {e}")
        return empty_result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM glossary extraction output as JSON: {e}")
        return empty_result

    if not isinstance(parsed, dict):
        logger.error(f"Glossary extraction returned unexpected JSON shape ({type(parsed).__name__}, expected object)")
        return empty_result

    return {"terms": parsed.get("terms", []), "context_note": parsed.get("context_note", "")}


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
    episodes = _load_cached_episodes_for_novel(novel_id)
    if not episodes:
        print(f"No cached episodes found for novel {novel_id}. Read some chapters first, then rerun this.")
        sys.exit(1)

    episodes = episodes[-args.max_episodes :] if args.max_episodes else episodes

    print(f"Found {len(episodes)} cached episode(s) for novel {novel_id}.")

    glossary = load_glossary(novel_id)
    if not glossary.get("title") and episodes:
        glossary["title"] = episodes[0].get("title", "")

    context_notes: List[str] = []
    for i, episode in enumerate(episodes, 1):
        source_lines = episode.get("lines", [])
        translated_lines = episode.get("translated_lines", [])
        if not source_lines or not translated_lines:
            print(f"[{i}/{len(episodes)}] Skipping episode with no translated text.")
            continue

        print(f"[{i}/{len(episodes)}] Extracting terms from: {episode.get('episode_title', 'unknown')}")
        result = extract_glossary_terms(source_lines, translated_lines)
        new_terms = result.get("terms", [])
        if new_terms:
            print(f"    Found {len(new_terms)} term(s): {', '.join(t.get('source', '?') for t in new_terms)}")
            glossary["terms"] = merge_terms(glossary.get("terms", []), new_terms)
        if result.get("context_note"):
            context_notes.append(result["context_note"])

    if context_notes:
        glossary["context_notes"] = " ".join(context_notes[-3:])

    glossary["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_glossary(novel_id, glossary)
    print(f"Glossary saved: {len(glossary.get('terms', []))} total term(s) for novel {novel_id}.")


if __name__ == "__main__":
    main()
