#!/usr/bin/env python3
"""
alphapolis_translate.py
Version 1.0, created 2026-07-22, author dfischer

Fetches an Alphapolis episode page, extracts the episode body text, and
translates it to English (or another target language) using Google's
free `gtx` translate endpoint (same one browser extensions use, no API
key required).

Usage:
    pip install requests beautifulsoup4
    python alphapolis_translate.py "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800047"

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

import sys
import textwrap
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 150  # keep encoded URLs well under length limits (see note below)


def fetch_html(url: str) -> str:
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python alphapolis_translate.py <episode_url> [target_lang]")
        sys.exit(1)

    url = sys.argv[1]
    target_lang = sys.argv[2] if len(sys.argv) > 2 else "en"

    print(f"Fetching {url} ...", file=sys.stderr)
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    content = find_content(soup)
    if content is None:
        print(
            "Could not locate episode text -- the page may be JS-rendered, " "behind a bot-check, or using an anti-scrape technique this " "script can't see through.",
            file=sys.stderr,
        )
        sys.exit(2)

    paragraphs = [p.get_text(strip=True) for p in content.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        # fall back to splitting on <br> boundaries
        raw = content.get_text(separator="\n", strip=True)
        paragraphs = [p for p in raw.split("\n") if p.strip()]

    print(f"Found {len(paragraphs)} paragraph(s). Translating in chunks...", file=sys.stderr)

    chunks = chunk_text(paragraphs)
    translated_paragraphs = []
    for i, chunk in enumerate(chunks, 1):
        joined = "\n\n".join(chunk)
        try:
            translated = translate_chunk(joined, target_lang=target_lang)
        except Exception as e:
            print(f"  chunk {i}/{len(chunks)} failed: {e}", file=sys.stderr)
            translated = "[translation failed for this section]"
        translated_paragraphs.append(translated)
        time.sleep(0.3)  # be polite to the free endpoint

    print("\n\n".join(translated_paragraphs))


if __name__ == "__main__":
    main()
