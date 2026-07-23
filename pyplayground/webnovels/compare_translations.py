#!/usr/bin/env python3
"""compare_translations.py - Compare Google Translate vs LLM translations.

Fetches an Alphapolis episode, translates it with both Google Translate and
a local LLM (via llama-server), then outputs a side-by-side comparison with
per-chapter summary statistics.

Output modes:
    text  - Human-readable side-by-side with summary (default)
    json  - Structured JSON for programmatic analysis

Usage:
    python compare_translations.py "https://www.alphapolis.co.jp/novel/..."
    python compare_translations.py "<url>" --mode json --output comparison.json
    python compare_translations.py "<url>" --mode both
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.webnovels.alphapolis_reader_v01 import (
    BrowserWorker,
    _extract_novel_id,
    load_cached_episode,
    parse_episode,
)
from pyplayground.webnovels.glossary import format_glossary_for_prompt, load_glossary
from pyplayground.webnovels.llm_translate import translate_lines as llm_translate_lines

logger = get_logger(__name__)

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
MAX_CHUNK_CHARS = 150


def fetch_html(url: str, browser: BrowserWorker) -> str:
    """Fetch page HTML via Playwright browser worker.

    Args:
        url: The episode URL to fetch.
        browser: BrowserWorker instance.

    Returns:
        The page HTML string.
    """
    return browser.fetch(url)


def chunk_text(paragraphs: List[str], max_chars: int = MAX_CHUNK_CHARS) -> List[List[str]]:
    """Split paragraphs into chunks respecting character limits.

    Args:
        paragraphs: List of text paragraphs.
        max_chars: Maximum characters per chunk.

    Returns:
        List of paragraph lists (chunks).
    """
    chunks: List[List[str]] = []
    current: List[str] = []
    current_len = 0
    for p in paragraphs:
        if current_len + len(p) > max_chars and current:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(p)
        current_len += len(p) + 2
    if current:
        chunks.append(current)
    return chunks


def translate_google(lines: List[str], target_lang: str = "en") -> List[str]:
    """Translate lines using Google Translate.

    Args:
        lines: List of Japanese text lines.
        target_lang: Target language code.

    Returns:
        List of translated text lines.
    """
    chunks = chunk_text(lines)
    translated: List[str] = []
    for chunk in chunks:
        joined = "\n\n".join(chunk)
        params = {
            "client": "gtx",
            "sl": "ja",
            "tl": target_lang,
            "dt": "t",
            "q": joined,
        }
        resp = requests.get(TRANSLATE_ENDPOINT, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = "".join(seg[0] for seg in data[0])
        parts = result.split("\n\n")
        if len(parts) == len(chunk):
            translated.extend(parts)
        else:
            translated.append(result)
        time.sleep(0.2)
    return translated


def parse_episode_page(html: str) -> dict:
    """Parse episode HTML and extract content lines.

    Args:
        html: Raw page HTML.

    Returns:
        Dict with title, episode_title, lines, and other metadata.
    """
    return parse_episode(html)


def compare_translations(
    url: str,
    browser: BrowserWorker,
    target_lang: str = "en",
    output_format: str = "text",
    output_file: Optional[str] = None,
) -> dict:
    """Fetch and translate an episode with both backends, return comparison data.

    Args:
        url: Episode URL.
        browser: BrowserWorker instance.
        target_lang: Target language code.
        output_format: Output format ('text', 'json', or 'both').
        output_file: Optional file path to save JSON output.

    Returns:
        Comparison result dict with all translation data.
    """
    # Check cache first
    cached = load_cached_episode(url)
    if cached is not None:
        print("Using cached episode data")
        ep = cached
    else:
        print(f"Fetching episode: {url}")
        html = fetch_html(url, browser)
        ep = parse_episode_page(html)

    lines = ep.get("lines", [])
    if not lines:
        logger.error("No content lines found in episode")
        sys.exit(2)

    print(f"Translating {len(lines)} lines with Google Translate...")
    t0 = time.time()
    google_translated = translate_google(lines, target_lang=target_lang)
    google_time = time.time() - t0
    print(f"Google Translate completed in {google_time:.1f}s")

    glossary_text = None
    novel_id = _extract_novel_id(url)
    if novel_id:
        glossary_text = format_glossary_for_prompt(load_glossary(novel_id))

    print(f"Translating {len(lines)} lines with LLM...")
    t0 = time.time()
    llm_translated = llm_translate_lines(lines, target_lang=target_lang, glossary_text=glossary_text)
    llm_time = time.time() - t0
    print(f"LLM translation completed in {llm_time:.1f}s")

    # Build comparison data
    comparison = {
        "url": url,
        "title": ep.get("title", ""),
        "episode_title": ep.get("episode_title", ""),
        "author": ep.get("author", ""),
        "target_lang": target_lang,
        "total_lines": len(lines),
        "google": {
            "translated_lines": google_translated,
            "time_seconds": round(google_time, 2),
            "lines_count": len(google_translated),
            "avg_line_length": round(sum(len(line) for line in google_translated) / max(len(google_translated), 1), 1),
        },
        "llm": {
            "translated_lines": llm_translated,
            "time_seconds": round(llm_time, 2),
            "lines_count": len(llm_translated),
            "avg_line_length": round(sum(len(line) for line in llm_translated) / max(len(llm_translated), 1), 1),
        },
        "chapters": _build_chapter_summaries(lines, google_translated, llm_translated),
    }

    # Save JSON output
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False))
        print(f"JSON comparison saved to {output_path}")

    # Print output
    if output_format in ("text", "both"):
        _print_text_comparison(comparison)
    if output_format in ("json", "both"):
        print("\n" + "=" * 60)
        print("JSON OUTPUT")
        print("=" * 60)
        print(json.dumps(comparison, indent=2, ensure_ascii=False))

    return comparison


def _build_chapter_summaries(
    original: List[str],
    google: List[str],
    llm: List[str],
) -> List[dict]:
    """Build per-paragraph comparison summaries.

    Args:
        original: Original Japanese lines.
        google: Google-translated lines.
        llm: LLM-translated lines.

    Returns:
        List of chapter summary dicts.
    """
    summaries = []
    max_len = max(len(original), len(google), len(llm))

    for i in range(max_len):
        orig = original[i] if i < len(original) else ""
        g_trans = google[i] if i < len(google) else "[missing]"
        l_trans = llm[i] if i < len(llm) else "[missing]"

        # Simple quality heuristic: length ratio (both should be similar)
        orig_len = len(orig)
        g_len = len(g_trans)
        l_len = len(l_trans)

        g_ratio = g_len / max(orig_len, 1)
        l_ratio = l_len / max(orig_len, 1)

        summaries.append(
            {
                "index": i + 1,
                "original_length": orig_len,
                "google_length": g_len,
                "llm_length": l_len,
                "google_ratio": round(g_ratio, 2),
                "llm_ratio": round(l_ratio, 2),
                "google_preview": g_trans[:80] + ("..." if len(g_trans) > 80 else ""),
                "llm_preview": l_trans[:80] + ("..." if len(l_trans) > 80 else ""),
            }
        )

    return summaries


def _print_text_comparison(comparison: dict) -> None:
    """Print human-readable side-by-side comparison.

    Args:
        comparison: Comparison result dict from compare_translations().
    """
    print("\n" + "=" * 80)
    print(f"  {comparison['title']} - {comparison['episode_title']}")
    print(f"  Author: {comparison['author']}")
    print(f"  Language: {comparison['target_lang']}")
    print("=" * 80)

    # Timing summary
    google_time = comparison["google"]["time_seconds"]
    llm_time = comparison["llm"]["time_seconds"]
    ratio = google_time / max(llm_time, 0.01)
    print(f"\n  Timing: Google={google_time:.1f}s  |  LLM={llm_time:.1f}s  |  " f"LLM is {ratio:.1f}x {'faster' if llm_time < google_time else 'slower'}")
    print(f"  Lines: {comparison['total_lines']} original, " f"{comparison['google']['lines_count']} Google, " f"{comparison['llm']['lines_count']} LLM")

    # Per-chapter comparison
    print("\n" + "-" * 80)
    print("  PARAGRAPH-BY-PARAGRAPH COMPARISON")
    print("-" * 80)

    for chapter in comparison["chapters"]:
        print(f"\n  [{chapter['index']}] Original: {chapter['original_length']} chars")
        print(f"    Google ({chapter['google_length']} chars, ratio {chapter['google_ratio']}):")
        print(f"      {chapter['google_preview']}")
        print(f"    LLM    ({chapter['llm_length']} chars, ratio {chapter['llm_ratio']}):")
        print(f"      {chapter['llm_preview']}")

    # Summary statistics
    print("\n" + "-" * 80)
    print("  SUMMARY STATISTICS")
    print("-" * 80)

    google_ratios = [c["google_ratio"] for c in comparison["chapters"]]
    llm_ratios = [c["llm_ratio"] for c in comparison["chapters"]]

    print("\n  Google Translate:")
    avg_google = sum(google_ratios) / len(google_ratios)
    print(f"    Avg length ratio: {avg_google:.2f}")
    print(f"    Min ratio: {min(google_ratios):.2f}")
    print(f"    Max ratio: {max(google_ratios):.2f}")
    print(f"    Avg line length: {comparison['google']['avg_line_length']:.1f} chars")

    print("\n  LLM:")
    avg_llm = sum(llm_ratios) / len(llm_ratios)
    print(f"    Avg length ratio: {avg_llm:.2f}")
    print(f"    Min ratio: {min(llm_ratios):.2f}")
    print(f"    Max ratio: {max(llm_ratios):.2f}")
    print(f"    Avg line length: {comparison['llm']['avg_line_length']:.1f} chars")

    print("\n" + "=" * 80)


def main():
    """Entry point for the translation comparison tool."""
    parser = argparse.ArgumentParser(description="Compare Google Translate vs LLM translations for Alphapolis episodes")
    parser.add_argument("url", help="Episode URL to compare")
    parser.add_argument(
        "--target-lang",
        "-t",
        default="en",
        help="Target language code (default: en)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["text", "json", "both"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for JSON data",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    setup_logging(level="DEBUG" if args.verbose else "INFO")

    try:
        browser = BrowserWorker()
    except Exception as e:
        logger.error(f"Failed to start browser: {e}")
        sys.exit(1)

    try:
        comparison = compare_translations(
            url=args.url,
            browser=browser,
            target_lang=args.target_lang,
            output_format=args.mode,
            output_file=args.output,
        )
    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        sys.exit(1)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
