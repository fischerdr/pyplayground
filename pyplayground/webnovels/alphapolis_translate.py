#!/usr/bin/env python3
"""alphapolis_translate.py - Translate Alphapolis episodes to English.

Fetches an Alphapolis episode page, extracts the episode body text, and
translates it to English (or another target language) using Google's
free `gtx` translate endpoint or a local LLM backend.

Usage:
    pip install requests beautifulsoup4
    python alphapolis_translate.py "https://www.alphapolis.co.jp/novel/..."

Notes:
- Alphapolis' robots.txt disallows automated access. This script is meant
  for personal, one-off use (translating something you're already reading),
  not bulk/repeated scraping.
- If the response HTML looks like a bot-check / challenge page instead of
  the real episode, plain `requests` isn't enough -- you'd need a headless
  browser (e.g. `playwright`) to get past it.
- If the extracted Japanese text looks like garbage/mismatched characters,
  the site may be using font-ligature substitution or DOM text-scrambling
  as an anti-scrape measure; this script can't see through that.
"""

import argparse
import sys
import time

import requests
from bs4 import BeautifulSoup

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.webnovels.alphapolis_reader import _extract_novel_id
from pyplayground.webnovels.glossary import format_glossary_for_prompt, load_glossary
from pyplayground.webnovels.llm_translate import BACKEND_GOOGLE, BACKEND_LLM
from pyplayground.webnovels.llm_translate import translate_lines as llm_translate_lines

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 150  # keep encoded URLs well under length limits (see note below)


def fetch_html(url: str) -> str:
    """Fetch page HTML using requests with Alphapolis-like headers.

    Args:
        url: The episode URL to fetch.

    Returns:
        The page HTML string.

    Raises:
        requests.HTTPError: If the response status is not 2xx.
    """
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def find_content(soup: BeautifulSoup):
    """Heuristic: score every div/section/article by how much Japanese text.

    it directly contains, penalize link-heavy blocks (nav/menus), strip
    script/style noise before counting. Mirrors the logic used in the
    companion Greasemonkey userscript.
    """
    import re

    jp_re = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
    banned = {"script", "style", "nav", "header", "footer", "aside", "template", "noscript"}

    best, best_score = None, 0
    for el in soup.find_all(["div", "section", "article", "main"]):
        if el.name in banned:
            continue
        if el.find_parent(["nav", "header", "footer", "aside"]):
            continue

        clone_text = el.get_text(separator="\n", strip=False)
        for noise in el.find_all(["script", "style", "noscript", "iframe", "template"]):
            noise.extract()
        text = el.get_text(separator="\n", strip=False)

        jp_count = len(jp_re.findall(text))
        if jp_count < 200:
            continue

        link_len = sum(len(a.get_text()) for a in el.find_all("a"))
        if link_len / max(len(text), 1) > 0.4:
            continue

        if jp_count > best_score:
            best_score, best = jp_count, el

    return best


def chunk_text(paragraphs, max_chars=CHUNK_CHARS):
    """Split paragraphs into chunks respecting character limits.

    Args:
        paragraphs: List of text paragraphs.
        max_chars: Maximum characters per chunk.

    Returns:
        List of paragraph lists (chunks).
    """
    chunks, current, current_len = [], [], 0
    for p in paragraphs:
        if current_len + len(p) > max_chars and current:
            chunks.append(current)
            current, current_len = [], 0
        current.append(p)
        current_len += len(p) + 2
    if current:
        chunks.append(current)
    return chunks


def translate_chunk(text: str, target_lang: str = "en", source_lang: str = "ja") -> str:
    """Translate a single text chunk using Google Translate free endpoint.

    Args:
        text: The text to translate.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).

    Returns:
        The translated text string.
    """
    params = {
        "client": "gtx",
        "sl": source_lang,
        "tl": target_lang,
        "dt": "t",
        "q": text,
    }
    resp = requests.get(TRANSLATE_ENDPOINT, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return "".join(seg[0] for seg in data[0])


def translate_lines(lines, target_lang="en", backend=BACKEND_GOOGLE, glossary_text=None):
    """Translate a list of text lines using the selected backend.

    Args:
        lines: List of text lines to translate.
        target_lang: Target language code (default: en).
        backend: Translation backend ('google' or 'llm').
        glossary_text: Optional pre-formatted glossary text (LLM backend only).

    Returns:
        List of translated text lines.
    """
    if backend == BACKEND_LLM:
        return llm_translate_lines(lines, target_lang=target_lang, glossary_text=glossary_text)

    chunks = chunk_text(lines)
    translated_paragraphs = []
    for i, chunk in enumerate(chunks, 1):
        joined = "\n\n".join(chunk)
        try:
            translated = translate_chunk(joined, target_lang=target_lang)
        except Exception as e:
            logger.error(f"chunk {i}/{len(chunks)} failed: {e}")
            translated = "[translation failed for this section]"
        translated_paragraphs.append(translated)
        time.sleep(0.3)  # be polite to the free endpoint
    return translated_paragraphs


def main():
    """Entry point for the Alphapolis translation CLI tool."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Translate Alphapolis episode to English")
    parser.add_argument("url", help="Episode URL to translate")
    parser.add_argument("target_lang", nargs="?", default="en", help="Target language (default: en)")
    parser.add_argument(
        "--backend",
        choices=[BACKEND_GOOGLE, BACKEND_LLM],
        default=BACKEND_GOOGLE,
        help="Translation backend (default: google)",
    )
    args = parser.parse_args()

    url = args.url
    target_lang = args.target_lang
    backend = args.backend

    print(f"Fetching {url} ...")
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    content = find_content(soup)
    if content is None:
        logger.error("Could not locate episode text -- the page may be JS-rendered, " "behind a bot-check, or using an anti-scrape technique this " "script can't see through.")
        sys.exit(2)

    paragraphs = [p.get_text(strip=True) for p in content.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        # fall back to splitting on <br> boundaries
        raw = content.get_text(separator="\n", strip=True)
        paragraphs = [p for p in raw.split("\n") if p.strip()]

    print(f"Found {len(paragraphs)} paragraph(s). Translating with {backend} backend...")

    glossary_text = None
    if backend == BACKEND_LLM:
        novel_id = _extract_novel_id(url)
        if novel_id:
            glossary_text = format_glossary_for_prompt(load_glossary(novel_id))

    translated_paragraphs = translate_lines(paragraphs, target_lang=target_lang, backend=backend, glossary_text=glossary_text)

    print("\n\n".join(translated_paragraphs))


if __name__ == "__main__":
    main()
