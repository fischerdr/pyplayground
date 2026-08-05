#!/usr/bin/env python3
"""alphapolis_reader.py.

Desktop reader for Alphapolis novels. Fetches episode pages with a real
headless browser (required -- plain HTTP requests get served an empty
202 "challenge" response by the site's AWS WAF bot-mitigation, confirmed
via direct testing), extracts the chapter text via the #novelBody
selector (confirmed from real page source), and displays it in a Tkinter
window with Previous/Next navigation driven by the episode list embedded
in the page's own `app-cover-data` JSON script tag.

Translation runs through either Google's free `gtx` translate endpoint
or a local LLM backend (see llm_translate.py), selectable in Settings.
A per-novel glossary (glossary.py, auto-extracted via build_glossary.py
or hand-edited through the in-app Glossary dialog) is injected into
every translation call so character names and recurring terms stay
consistent across chapters; the glossary dialog also supports rebuilding
from cached episodes and clearing a novel's terms from scratch.

Setup:
    pip install playwright beautifulsoup4 requests pillow
    playwright install chromium

Usage:
    python alphapolis_reader.py "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089"
    python alphapolis_reader.py "<url>" es      # translate to Spanish instead of English
"""

import difflib
import hashlib
import json
import queue
import re
import signal
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from pyplayground.utils.config_utils import load_json_config, save_json_config
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.safe_persistence import verify_before_write
from pyplayground.webnovels.global_vocabulary import format_global_vocabulary_for_prompt, get_global_entry, load_global_vocabulary, upsert_global_entry
from pyplayground.webnovels.glossary import (
    HONORIFIC_POLICIES,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    best_candidate_for_term,
    build_mask_targets,
    build_splice_fallbacks,
    find_glossary_term_spans,
    format_glossary_for_prompt,
    load_glossary,
    make_confirmed_term,
    save_glossary,
    update_candidate_counts,
)
from pyplayground.webnovels.glossary_coordinator import GlossaryCoordinator
from pyplayground.webnovels.ja_tokenize import find_ja_word_at
from pyplayground.webnovels.llm_translate import BACKEND_GOOGLE, BACKEND_LLM, DEFAULT_BACKEND, TranslatedLine, check_llm_available, explain_term, retranslate_line_with_hint
from pyplayground.webnovels.llm_translate import translate_chunk as llm_translate_chunk
from pyplayground.webnovels.llm_translate import translate_lines as llm_translate_lines
from pyplayground.webnovels.llm_translate import translate_lines_with_masking

logger = get_logger(__name__)

"""Constants for the Alphapolis reader application."""

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
"""Google Translate API endpoint URL."""

MAX_CHUNK_CHARS = 150  # keep encoded URLs well under length limits
BASE_URL = "https://www.alphapolis.co.jp"
"""Base URL for Alphapolis website."""

STATE_DIR = Path.home() / ".config" / "alphapolis_reader"
"""Directory for storing reader state (e.g., last-read URL)."""

STATE_FILE = "state.json"
"""Filename for the reader state file."""

CACHE_DIR = Path.home() / ".cache" / "alphapolis_reader"
"""Directory for caching episode data and images."""

LIGHT_PALETTE = {"bg": "#ffffff", "fg": "#000000", "original": "#333333", "translated": "#1a56c4", "needs_review": "#b45309"}
DARK_PALETTE = {"bg": "#1e1e1e", "fg": "#e0e0e0", "original": "#c9c9c9", "translated": "#7aa2f7", "needs_review": "#f0a742"}
"""needs_review is an amber/orange, deliberately distinct in hue (not just
shade) from "translated"'s blue -- a shade difference alone risks reading
as "same category, slightly different" rather than "different category,"
which matters here since confirmed vs. needs-review must not be
confusable at a glance."""

# Candidate reading fonts, in preference order. Not all are installed on
# every system, so the actual choice is filtered against tkinter's available
# font families at runtime (see ReaderApp._available_fonts).
FONT_CANDIDATES = [
    "Georgia",
    "Lora",
    "Noto Serif",
    "Liberation Serif",
    "Roboto",
    "Noto Sans",
    "Liberation Sans",
    "Cantarell",
    "Liberation Mono",
]
DEFAULT_FONT_FALLBACK = "TkDefaultFont"

CACHE_SCHEMA_VERSION = 4  # bump whenever the episode dict shape changes
"""v4 (2026-07-25, DESIGN.md Section 11): added needs_review_flags -- a
parallel List[bool], same length/order as translated_lines. Bumping this
invalidates old-shape cache files (load_cached_episode() returns None for
a version mismatch, so the episode gets refetched/retranslated) rather
than migrating them in place -- no real cached data worth preserving,
same no-backward-compat precedent as Sections 9/10."""

_STALE_POPUP_SENTINEL = object()
"""Sentinel returned by open_retranslate_popup()'s accept_and_close() divergence
callback so the caller can distinguish "the popup went stale, skip the write"
from any real local_data value verify_before_write() might otherwise return."""

NOVEL_ID_RE = re.compile(r"/novel/(\d+)/")


def _extract_novel_id(url: str) -> Optional[str]:
    """Extract the Alphapolis novel ID from an episode URL.

    Args:
        url: An episode URL, e.g. https://www.alphapolis.co.jp/novel/{novel_id}/{volume_id}/episode/{episode_id}.

    Returns:
        The novel ID string, or None if the URL doesn't match the expected pattern.
    """
    match = NOVEL_ID_RE.search(url)
    return match.group(1) if match else None


def _cache_path(url: str) -> Path:
    """Return the cache file path for a given episode URL.

    Args:
        url: The episode URL to cache.

    Returns:
        Path object pointing to the cache JSON file.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def load_cached_episode(url: str) -> dict:
    """Load a cached episode from disk, returning None if not found or stale.

    Args:
        url: The episode URL to look up.

    Returns:
        Episode dict if cached and schema matches, else None.
    """
    path = _cache_path(url)
    if not path.exists():
        return None
    episode = load_json_config(path.stem, config_dir=path.parent)
    if episode.get("_cache_schema_version") != CACHE_SCHEMA_VERSION:
        return None  # stale format from an older version of this script
    return episode


def save_cached_episode(url: str, episode: dict) -> None:
    """Save an episode dict to the on-disk cache with schema version.

    Args:
        url: The episode URL used as cache key.
        episode: The episode data to cache.
    """
    episode = dict(episode, _cache_schema_version=CACHE_SCHEMA_VERSION, url=url, novel_id=_extract_novel_id(url))
    path = _cache_path(url)
    save_json_config(episode, path.stem, config_dir=path.parent)


def load_reader_state() -> dict:
    """Load the reader state from the state file.

    Returns:
        Dict containing saved state (e.g., last URL, target language).
    """
    try:
        return load_json_config(STATE_FILE, config_dir=STATE_DIR)
    except FileNotFoundError:
        return {}


def save_reader_state(url: str, target_lang: str, scroll_pos: Optional[float] = None) -> None:
    """Save the current URL, target language, and scroll position to the state file.

    Merges into the existing state rather than overwriting it, so other
    persisted settings (backend, appearance) written elsewhere aren't lost.

    Args:
        url: The current episode URL.
        target_lang: The target translation language code.
        scroll_pos: Fraction (0.0-1.0) of the way scrolled through the text
            widget, from Text.yview()[0]. None leaves the field unset.
    """
    state = load_reader_state()
    state["url"] = url
    state["target_lang"] = target_lang
    if scroll_pos is not None:
        state["scroll_pos"] = scroll_pos
    save_json_config(state, STATE_FILE, config_dir=STATE_DIR)


def update_reader_state(**kwargs: Any) -> None:
    """Merge arbitrary key/value pairs into the persisted reader state.

    Used for display settings (font size, image width, dark mode, view
    mode, etc.) that don't fit save_reader_state()'s url/target_lang/
    scroll_pos-specific signature.

    Args:
        **kwargs: Key/value pairs to merge into state.json.
    """
    state = load_reader_state()
    state.update(kwargs)
    save_json_config(state, STATE_FILE, config_dir=STATE_DIR)


def _image_cache_path(image_url: str) -> Path:
    """Return the cache file path for a given image URL.

    Args:
        image_url: The image URL to cache.

    Returns:
        Path object pointing to the cached image file.
    """
    digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()
    ext = Path(image_url.split("?")[0]).suffix or ".img"
    return CACHE_DIR / "images" / f"{digest}{ext}"


def load_cached_image(image_url: str) -> bytes:
    """Load cached image bytes from disk, returning None if not found.

    Args:
        image_url: The image URL to look up.

    Returns:
        Image bytes if cached, else None.
    """
    path = _image_cache_path(image_url)
    if not path.exists():
        return None
    return path.read_bytes()


def fetch_image_bytes(image_url: str) -> bytes:
    """Fetch image bytes, using the on-disk cache when available."""
    cached = load_cached_image(image_url)
    if cached is not None:
        return cached
    resp = requests.get(image_url, timeout=15)
    resp.raise_for_status()
    path = _image_cache_path(image_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


# ---------------------------------------------------------------------------
# Browser (runs in one dedicated, persistent thread)
# ---------------------------------------------------------------------------
# Playwright's SYNC api is bound to the thread that created it -- calling
# page.goto() from a different thread than the one that ran
# sync_playwright().start() raises things like:
#   greenlet.error: cannot switch to a different thread (which happens to
#   have exited)
# and/or a confusing net::ERR_ABORTED. So all Playwright calls live in ONE
# thread for the whole app's lifetime; everything else talks to it through
# a request/response queue pair.
class BrowserWorker(threading.Thread):
    """Playwright browser worker running in a dedicated daemon thread.

    All Playwright calls live in this thread for the app's lifetime;
    everything else talks to it through a request/response queue pair.
    """

    def __init__(self):
        """Initialize and start the browser worker thread."""
        super().__init__(daemon=True)
        self._requests = queue.Queue()
        self._responses = queue.Queue()
        self._ready = threading.Event()
        self.startup_error = None
        self.start()
        self._ready.wait(timeout=60)
        if self.startup_error:
            raise self.startup_error

    def run(self):
        """Run the Playwright browser loop in this thread.

        Launches Chromium, then processes fetch requests from the queue
        until a None shutdown signal is received.
        """
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self.startup_error = RuntimeError("Playwright isn't installed. Run:\n" "  pip install playwright\n" "  playwright install chromium\n\n" f"Original error: {e}")
            self._ready.set()
            return

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
                    locale="ja-JP",
                )
                page = context.new_page()
                self._ready.set()

                while True:
                    item = self._requests.get()
                    if item is None:  # shutdown signal
                        break
                    url = item
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_selector("#novelBody, .p-novel-episode__text", timeout=15000)
                        html = page.content()
                        self._responses.put(("ok", html))
                    except Exception:
                        self._responses.put(("error", traceback.format_exc()))

                browser.close()
        except Exception:
            # Startup failed inside the `with` block (e.g. couldn't launch
            # chromium at all) -- if _ready was never set, surface it there;
            # otherwise there's nowhere else for it to go but a response.
            if not self._ready.is_set():
                self.startup_error = RuntimeError("Failed to launch Chromium via Playwright:\n" + traceback.format_exc())
                self._ready.set()
            else:
                self._responses.put(("error", traceback.format_exc()))

    def fetch(self, url: str, timeout: float = 60.0) -> str:
        """Fetch a page HTML by sending a request to the browser worker thread.

        Args:
            url: The URL to fetch.
            timeout: Max seconds to wait for a response.

        Returns:
            The page HTML string.

        Raises:
            RuntimeError: If the browser fetch fails.
        """
        self._requests.put(url)
        status, payload = self._responses.get(timeout=timeout)
        if status == "error":
            raise RuntimeError("Browser fetch failed:\n" + payload)
        return payload

    def close(self):
        """Signal the browser worker to shut down and join the thread."""
        self._requests.put(None)
        self.join(timeout=10)


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------
def _resolve_image_url(src: str) -> str:
    """Resolve a relative or protocol-relative image URL to an absolute URL.

    Args:
        src: The image src attribute value.

    Returns:
        The resolved absolute URL.
    """
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    return src


_RUBY_FILLER_RT = "・"


def _is_ruby_filler_dot(ruby_tag) -> bool:
    """Check whether a <ruby> tag matches the confirmed emphasis-dot filler signature.

    The signature (confirmed against two real status-window/skill-name
    cases) is a <ruby> whose <rt> child's stripped text is exactly a
    single "・" character -- a typographic emphasis marker, not a real
    furigana reading. Any other <rt> shape (multi-character katakana
    readings, etc.) is left untouched, since that pattern has only been
    confirmed to carry real content (e.g. technique-name pronunciations).

    Args:
        ruby_tag: The BeautifulSoup <ruby> tag element.

    Returns:
        True if this <ruby> tag's <rt> is the single-dot filler pattern.
    """
    rt = ruby_tag.find("rt")
    if rt is None:
        return False
    return rt.get_text().strip() == _RUBY_FILLER_RT


def _extract_content(body) -> list:
    """Walk the novel body in document order, yielding text lines and images.

    Images are captured as they actually appear, so illustrations stay
    next to the paragraphs they belong to instead of being flattened
    away by get_text().

    A narrow special case handles <ruby> tags used purely for
    typographic emphasis (single "・" dot as the <rt> reading, e.g.
    <ruby>塩<rt>・</rt></ruby>) -- confirmed on real chapters to fragment
    a single skill/status term into one isolated character per <ruby>.
    That base text is folded into the surrounding line and its filler
    <rt> is dropped; any other <ruby> shape (real furigana readings) is
    left completely untouched, since that case is confirmed to carry
    real content and must not be silently dropped.

    Args:
        body: The BeautifulSoup body element to parse.

    Returns:
        List of dicts with type (text/image) and content fields.
    """
    content = []
    skip_ids = set()
    # True when the most recently appended text item is eligible to have
    # more filler-dot <ruby> base text glued onto it -- i.e. it was itself
    # filler-dot <ruby> base text, or it's plain text immediately followed
    # by a filler-dot <ruby> in the same parent (checked via lookahead so
    # the merge also catches the text run *before* the first <ruby> in a
    # cluster, not just runs *between* consecutive <ruby> tags).
    merge_eligible = False
    for node in body.descendants:
        if getattr(node, "name", None) == "img":
            merge_eligible = False
            src = node.get("src") or node.get("data-src")
            if src:
                content.append({"type": "image", "src": _resolve_image_url(src)})
        elif isinstance(node, str):
            if id(node) in skip_ids:
                continue
            parent = node.parent
            parent_name = getattr(parent, "name", None)
            if parent_name in ("script", "style", "noscript", "iframe", "template"):
                continue
            is_filler_ruby_base = parent_name == "ruby" and _is_ruby_filler_dot(parent)
            if is_filler_ruby_base:
                rt = parent.find("rt")
                if rt is not None and rt.string is not None:
                    skip_ids.add(id(rt.string))
                text = str(node).strip()
                if text:
                    if merge_eligible and content and content[-1]["type"] == "text":
                        content[-1]["text"] += text
                    else:
                        content.append({"type": "text", "text": text})
                    merge_eligible = True
                continue
            text = node.strip()
            if not text:
                continue
            next_sib = node.next_sibling
            next_is_filler_ruby = getattr(next_sib, "name", None) == "ruby" and _is_ruby_filler_dot(next_sib)
            if merge_eligible and content and content[-1]["type"] == "text":
                content[-1]["text"] += text
            else:
                content.append({"type": "text", "text": text})
            merge_eligible = next_is_filler_ruby
    return content


def _parse_page_count(text: str) -> Optional[Tuple[int, int]]:
    """Parse a ".p-novel-episode__page-count" text value into (current, total).

    Args:
        text: The element's stripped text, expected shape "445 / 689".

    Returns:
        (current, total) as ints, or None if the text doesn't match the
        expected "N / M" shape (STATUS_BAR_DESIGN.md Phase 1: confirmed
        live against real pages, but markup/format changes on Alphapolis'
        end are always possible -- fail soft, not with a raised exception,
        same discipline as every other single-value scrape in this
        function).
    """
    match = re.match(r"^(\d+)\s*/\s*(\d+)$", text.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def parse_episode(html: str) -> dict:
    """Parse an episode page HTML and extract title, author, content, and navigation.

    Args:
        html: The raw page HTML string.

    Returns:
        Dict with title, author, episode_title, lines, content, prev_url,
        next_url, page_count.

    Raises:
        RuntimeError: If #novelBody is not found in the page markup.
    """
    soup = BeautifulSoup(html, "html.parser")

    body = soup.select_one("#novelBody, .p-novel-episode__text")
    if body is None:
        raise RuntimeError("Could not find #novelBody in page HTML -- markup may have changed.")

    for noise in body.find_all(["script", "style", "noscript", "iframe", "template"]):
        noise.extract()

    content = _extract_content(body)
    lines = [item["text"] for item in content if item["type"] == "text"]

    title_tag = soup.select_one(".p-novel-episode__title")
    author_tag = soup.select_one(".p-novel-episode__author")
    episode_title_tag = soup.select_one(".p-novel-episode__episode-title")
    # STATUS_BAR_DESIGN.md Phase 1/2: chapter position within the novel's
    # total serialization (confirmed live against two real, directly-
    # adjacent episode pages -- not per-episode pagination). Same
    # single-value-scrape idiom as title_tag/author_tag/episode_title_tag
    # above.
    page_count_tag = soup.select_one(".p-novel-episode__page-count")

    title = title_tag.get_text(strip=True) if title_tag else ""
    author = author_tag.get_text(strip=True) if author_tag else ""
    episode_title = episode_title_tag.get_text(strip=True) if episode_title_tag else ""
    page_count = _parse_page_count(page_count_tag.get_text()) if page_count_tag else None

    prev_url, next_url = None, None
    cover_tag = soup.select_one("#app-cover-data")
    if cover_tag and cover_tag.string:
        try:
            data = json.loads(cover_tag.string)
            episodes = []
            for chapter in data.get("chapterEpisodes", []):
                episodes.extend(chapter.get("episodes", []))
            current_no = data.get("currentEpisode", {}).get("episodeNo")
            idx = next((i for i, e in enumerate(episodes) if e.get("episodeNo") == current_no), None)
            if idx is not None:
                if idx > 0:
                    prev_url = BASE_URL + episodes[idx - 1]["url"]
                if idx < len(episodes) - 1:
                    next_url = BASE_URL + episodes[idx + 1]["url"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return {
        "title": title,
        "author": author,
        "episode_title": episode_title,
        "lines": lines,
        "content": content,
        "prev_url": prev_url,
        "next_url": next_url,
        "page_count": page_count,
    }


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------
def pack_into_chunks(strings, max_chars):
    """Split a list of strings into chunks that fit within max_chars total length.

    Args:
        strings: List of strings to chunk.
        max_chars: Maximum total character count per chunk.

    Returns:
        List of string lists, each fitting within the size limit.
    """
    chunks, current, current_len = [], [], 0
    for s in strings:
        if current_len + len(s) > max_chars and current:
            chunks.append(current)
            current, current_len = [], 0
        current.append(s)
        current_len += len(s) + 2
    if current:
        chunks.append(current)
    return chunks


def translate_chunk(text: str, target_lang="en", source_lang="ja") -> str:
    """Translate a single text chunk using Google Translate free endpoint.

    Args:
        text: The text to translate.
        target_lang: Target language code (default: en).
        source_lang: Source language code (default: ja).

    Returns:
        The translated text string.
    """
    params = {"client": "gtx", "sl": source_lang, "tl": target_lang, "dt": "t", "q": text}
    resp = requests.get(TRANSLATE_ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return "".join(seg[0] for seg in data[0])


def translate_lines(lines, target_lang="en", backend=BACKEND_GOOGLE, glossary_text=None, progress_cb=None, log_context="") -> list:
    """Translate a list of text lines, chunking to respect API limits.

    Args:
        lines: List of text lines to translate.
        target_lang: Target language code (default: en).
        backend: Translation backend ('google' or 'llm').
        glossary_text: Optional pre-formatted glossary text (LLM backend only;
            ignored for Google, which has no mechanism to honor it).
        progress_cb: Optional callback(done, total) for progress updates.
        log_context: Optional label (e.g. the episode URL) prefixed to
            every warning/error llm_translate.py logs for this call --
            LLM backend only, ignored for Google (which doesn't log
            chunk-level failures the same way). Found necessary via a
            real live-test log where a chunk failure couldn't be traced
            back to which episode produced it.

    Returns:
        List of translated text lines.
    """
    if backend == BACKEND_LLM:
        return llm_translate_lines(lines, target_lang=target_lang, glossary_text=glossary_text, progress_cb=progress_cb, log_context=log_context)

    chunks = pack_into_chunks(lines, MAX_CHUNK_CHARS)
    translated_lines = []
    for i, chunk in enumerate(chunks):
        joined = "\n\n".join(chunk)
        try:
            translated = translate_chunk(joined, target_lang=target_lang)
        except Exception as e:
            translated = f"[translation failed: {e}]"
        parts = translated.split("\n\n")
        if len(parts) == len(chunk):
            translated_lines.extend(parts)
        else:
            translated_lines.append(translated)
        if progress_cb:
            progress_cb(i + 1, len(chunks))
        time.sleep(0.2)  # be polite to the free endpoint
    return translated_lines


def build_review_term_map(translated_lines: List[TranslatedLine], mask_targets: List[Tuple[int, str]]) -> Dict[int, List[str]]:
    """Map each needs_review line index to the source word(s) masked for it.

    TranslatedLine itself carries no positional/source-word information --
    just text and a whole-line needs_review bool (see llm_translate.py's
    TranslatedLine/splice_terms() docstrings) -- so a click handler on a
    needs-review line can't recover which glossary term triggered the flag
    from the TranslatedLine alone. This reconstructs that association from
    `mask_targets`, the same (line_idx, word) list passed to
    translate_chunk_with_masking() to produce `translated_lines` in the
    first place -- both must come from the same call for this to be
    meaningful.

    Args:
        translated_lines: Output of translate_chunk_with_masking().
        mask_targets: The (line_idx, word) list passed to that same call.

    Returns:
        Dict of line_idx -> list of source words masked on that line, but
        only for indices where translated_lines[line_idx].needs_review is
        True. In practice this is every masked line -- splice_terms() sets
        needs_review whenever a line has any mask targets at all, since
        splicing never translates a term either way (see its docstring) --
        but the filter is kept rather than trusting mask_targets alone, so
        a future needs_review producer with narrower semantics doesn't
        silently over-include here.
    """
    words_by_line: Dict[int, List[str]] = {}
    for line_idx, word in mask_targets:
        words_by_line.setdefault(line_idx, []).append(word)

    return {line_idx: words for line_idx, words in words_by_line.items() if line_idx < len(translated_lines) and translated_lines[line_idx].needs_review}


def build_interleaved_pairs(source_lines: List[str], translated_lines: List[str]) -> Optional[List[Tuple[str, str]]]:
    """Pair each source line with its corresponding translated line, for the interleaved view.

    RETRANSLATION_DESIGN.md's phase 1: the interleaved display needs no new
    data or alignment computation, since source_lines[i] and
    translated_lines[i] already correspond 1:1 by construction --
    grep-confirmed against parse_episode(): ep["lines"] is built as
    `[item["text"] for item in content if item["type"] == "text"]`, and
    translate_lines()/translate_chunk() (see llm_translate.py) preserve
    input order/length by contract, so translated_lines[i] is the
    translation of ep["lines"][i] for the same i, not something this
    function needs to verify per-call -- it only needs to detect when that
    contract has been violated (a stale/corrupted cache entry) and refuse
    to pair mismatched data rather than silently misattributing a
    translation to the wrong source line.

    Args:
        source_lines: ep["lines"] -- text-only, images already excluded.
        translated_lines: ep["translated_lines"] -- same shape.

    Returns:
        List of (source_line, translated_line) tuples, same length/order
        as the inputs, or None if the lengths don't match -- callers
        should fall back to the existing non-interleaved translated view
        in that case rather than pairing lines that don't actually
        correspond (e.g. a cache entry from before translate_lines()
        guaranteed alignment; see _render_translated_content()'s same
        length check for the non-interleaved path).
    """
    if len(source_lines) != len(translated_lines):
        return None
    return list(zip(source_lines, translated_lines))


def _diff_single_substring(before: str, after: str) -> Optional[str]:
    """Return the single contiguous replacement substring that turns `before` into `after`, or None if ambiguous.

    RETRANSLATION_DESIGN.md phase 5: used to pre-fill the "remember
    globally" popup's Target field from a whole-line retranslation
    (candidate) versus its pre-correction baseline (current_translation).
    A whole-line correction isn't itself a clean term pair, so this is a
    best-effort pre-fill, not an authoritative extraction -- the popup
    always leaves the field editable and the user must confirm it before
    anything is written to the global store.

    Only handles the single-contiguous-replacement case (one "replace"
    opcode from a word-level difflib.SequenceMatcher, with the rest of
    the line unchanged) -- a correction touching multiple non-contiguous
    spots in the line has no single unambiguous "the corrected term" to
    extract, so this returns None rather than guessing. Diffing is done
    word-level, not character-level: a character-level diff of e.g.
    "dark"->"tanned" (which share the letter "a") splits into an
    insert+delete pair rather than one clean replace op, since the
    matcher greedily aligns the shared character -- word-level diffing
    treats each whole word as one atomic unit, avoiding that false split.

    Args:
        before: The original (possibly incorrect) translation.
        after: The corrected translation.

    Returns:
        The replacement substring from `after`, or None if the diff
        isn't a single contiguous replacement.
    """
    before_words = before.split()
    after_words = after.split()
    matcher = difflib.SequenceMatcher(a=before_words, b=after_words)
    replace_ops = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if len(replace_ops) != 1 or replace_ops[0][0] != "replace":
        return None
    _, _, _, b_start, b_end = replace_ops[0]
    substring = " ".join(after_words[b_start:b_end]).strip()
    return substring or None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class ReaderRenderer:
    """Owns view-mode rendering, span tracking, and appearance/theming for a ReaderApp.

    REFACTOR_DESIGN.md Phase 2: extracted from ReaderApp per the Phase 1
    investigation's Group B (rendering). Composition, not a mixin (see
    Phase 1's section 3 for why) -- holds an explicit back-reference to
    the owning ReaderApp (`self.app`) for state it needs to read but
    doesn't own (`current_url`, `episode`, `backend` for settings
    persistence purposes -- see _save_settings() on ReaderApp) rather
    than assuming a shared flat namespace. The `tk.Text` widget itself
    (`self.app.text`) stays owned/constructed by ReaderApp, since it's
    read by Group A (`load_episode()`'s "Loading..." placeholder),
    Group C, and Group D call sites not yet extracted -- only this
    renderer's own view-mode/span-tracking/appearance state moved here.

    Two known, deliberate cross-group entanglements preserved exactly,
    not cleaned up as part of this extraction (per Phase 1's explicit
    finding that these are load-bearing, not incidental coupling):

    - _render_translated_content_from_translated_lines() and
      _render_interleaved_content() call glossary.load_glossary()
      directly and pass the *unfiltered* glossary dict to
      find_glossary_term_spans() -- not build_mask_targets()'s
      confirmed-only filter. This is a read-only lookup, not the
      load/write-pair pattern this refactor exists to close, so
      ReaderRenderer importing glossary.py directly is fine (Phase 1
      section 2's recommendation (a)).
    - _on_needs_review_click() calls self.app.open_word_glossary_popup()
      (Group C, still on ReaderApp) via the back-reference, rather than
      moving or duplicating that dialog method here.
    """

    def __init__(self, app: "ReaderApp"):
        """Initialize renderer state from the owning ReaderApp's persisted settings.

        Args:
            app: The owning ReaderApp instance -- read for current_url,
                episode, and the text widget; never written to directly
                by this class except via the app's own public methods.
        """
        self.app = app
        settings = load_reader_state()
        self.font_size = settings.get("font_size", 12)
        self.image_width = settings.get("image_width", 400)
        self.dark_mode = settings.get("dark_mode", False)
        saved_font_family = settings.get("font_family")
        self.line_height = settings.get("line_height", 1.3)  # multiplier on font_size, converted to pixel spacing
        self.paragraph_spacing = settings.get("paragraph_spacing", 12)  # pixels between paragraphs
        self.page_width_pct = settings.get("page_width_pct", 100)  # percent of the text widget's available width
        self.text_align = settings.get("text_align", "left")  # left, center, right, justify(fallback to left)
        # Default changed to "translated" (was "both") per
        # RETRANSLATION_DESIGN.md's phase 1 design decision -- confirmed
        # the prior default before changing it, not assumed.
        #
        # WINDOW_REDESIGN.md Phase 2: Original/Both were removed as
        # selectable modes (only Translated/Interleaved remain). A plain
        # .get(..., "translated") default only covers a *missing* key --
        # a state file saved before this change can still hold a literal
        # "original" or "both" string, which render_text() would keep
        # rendering even though no menu/toolbar control can select it
        # anymore (WINDOW_REDESIGN.md Phase 1 finding). Remap those two
        # stale values to the current default explicitly, once, at load
        # time; the next _on_view_mode_change() naturally overwrites the
        # stale on-disk value with a current one, so no persisted
        # migration or schema-version bump is needed.
        saved_view_mode = settings.get("view_mode", "translated")
        if saved_view_mode in ("original", "both"):
            saved_view_mode = "translated"
        self.view_mode = tk.StringVar(value=saved_view_mode)
        self._photo_images = {}
        available_fonts = self._available_fonts()
        self.font_family = saved_font_family if saved_font_family in available_fonts else self._pick_default_font()
        # (start_index, end_index, tag, source_line) per rendered paragraph,
        # rebuilt on every render_text() call -- lets a right-click resolve
        # back to which source Japanese line a click/selection came from,
        # even when the rendered/tagged text is the English translation.
        self._rendered_spans = []
        # (start_index, end_index) -> (word, source_line), one entry per
        # individual masked-term span within a needs_review=True line (not
        # one entry per line) -- populated by both
        # _render_translated_content_from_translated_lines() and
        # _render_interleaved_content() via find_glossary_term_spans().
        # Lets _on_needs_review_click() resolve a click to the *specific*
        # term at that click position (and its Japanese source sentence,
        # for explain_term() context) to pre-fill in the Add-to-Glossary
        # dialog, rather than always the line's first flagged term.
        # Deliberately kept separate from _rendered_spans (a purpose-built
        # dict for its own narrower case, same as before) -- RETRANSLATION_
        # DESIGN.md's _translated_span_after() depends on _rendered_spans'
        # exact one-pair-per-line (original, translated) shape, which this
        # must not disturb. Rebuilt on every render_text() call, same
        # lifecycle as _rendered_spans.
        self._review_terms_by_span = {}
        # (start_index, end_index) -> index into ep["translated_lines"],
        # one entry per translated-half span rendered by
        # _render_interleaved_content() -- lets open_retranslate_popup()'s
        # Accept write the correction into the shared episode dict itself
        # (not just the live widget/_rendered_spans), so the fix survives a
        # view-mode switch within the same session. Same "separate,
        # purpose-built side table" pattern as _review_terms_by_span, kept
        # apart from _rendered_spans for the same reason given there.
        # Rebuilt on every render_text() call, same lifecycle as the above.
        self._translated_line_index_by_span = {}

    @property
    def text(self):
        """The shared tk.Text widget -- owned/constructed by ReaderApp, read here via the back-reference."""
        return self.app.text

    def _pick_default_font(self) -> str:
        available = self._available_fonts()
        for candidate in FONT_CANDIDATES:
            if candidate in available:
                return candidate
        return DEFAULT_FONT_FALLBACK

    def _available_fonts(self) -> set:
        import tkinter.font as tkfont

        return set(tkfont.families())

    def apply_appearance(self):
        """Apply current appearance settings (colors, font, spacing) to the GUI."""
        palette = DARK_PALETTE if self.dark_mode else LIGHT_PALETTE
        # line_height is a multiplier on the font's natural line height, the
        # same convention as CSS line-height. 1.0 = tightest (no extra space
        # added); each +1.0 above that adds roughly one more font_size worth
        # of gap between lines.
        line_spacing = max(int(self.font_size * (self.line_height - 1.0)), 0)
        justify = "center" if self.text_align == "center" else "right" if self.text_align == "right" else "left"

        self.app.root.configure(bg=palette["bg"])
        self.text.configure(
            font=(self.font_family, self.font_size),
            bg=palette["bg"],
            fg=palette["fg"],
            insertbackground=palette["fg"],
        )
        self.text.tag_configure("heading", font=(self.font_family, self.font_size + 4, "bold"), spacing3=self.paragraph_spacing, foreground=palette["fg"])
        self.text.tag_configure(
            "original",
            foreground=palette["original"],
            spacing1=line_spacing,
            spacing2=line_spacing,
            spacing3=self.paragraph_spacing,
            justify=justify,
        )
        self.text.tag_configure(
            "translated",
            foreground=palette["translated"],
            spacing1=line_spacing,
            spacing2=line_spacing,
            spacing3=self.paragraph_spacing,
            justify=justify,
        )
        # needs_review lines (DESIGN.md Section 6): distinct in both color
        # AND underline from "translated" -- color alone is a weaker signal
        # (unreliable for colorblind users, easy to miss at a glance) and
        # confirmed-vs-needs-review must not be confusable. Reuses the same
        # Tk tag-over-character-range mechanism as "original"/"translated"
        # rather than a separate rendering path, per DESIGN.md Section 7.
        self.text.tag_configure(
            "needs_review",
            foreground=palette["needs_review"],
            underline=True,
            spacing1=line_spacing,
            spacing2=line_spacing,
            spacing3=self.paragraph_spacing,
            justify=justify,
        )
        self._apply_page_width()

    def _apply_page_width(self):
        self.app.root.update_idletasks()
        total_width = self.text.winfo_width() or 900
        margin = int(total_width * (1 - self.page_width_pct / 100) / 2)
        self.text.configure(padx=max(margin, 8))

    def increase_font(self):
        """Increase the font size by 1, up to a maximum of 32."""
        self.font_size = min(self.font_size + 1, 32)
        self.apply_appearance()
        self.app._save_settings()

    def decrease_font(self):
        """Decrease the font size by 1, down to a minimum of 8."""
        self.font_size = max(self.font_size - 1, 8)
        self.apply_appearance()
        self.app._save_settings()

    def increase_image_width(self):
        """Increase the image display width by 100 pixels, up to 1200px."""
        self.image_width = min(self.image_width + 100, 1200)
        self._photo_images.clear()
        self.render_text()
        self.app._save_settings()

    def decrease_image_width(self):
        """Decrease the image display width by 100 pixels, down to 100px."""
        self.image_width = max(self.image_width - 100, 100)
        self._photo_images.clear()
        self.render_text()
        self.app._save_settings()

    def toggle_dark_mode(self):
        """Toggle between light and dark color palettes."""
        self.dark_mode = not self.dark_mode
        self.apply_appearance()
        self.app._save_settings()

    def _make_photo_image(self, src: str):
        """Load an episode image from cache or network and scale it.

        Returns None on any failure so a broken image never blocks the
        rest of the chapter from rendering.

        Args:
            src: The image source URL.

        Returns:
            A PhotoImage instance, or None on failure.
        """
        if src in self._photo_images:
            return self._photo_images[src]
        try:
            from io import BytesIO

            from PIL import Image, ImageTk

            data = fetch_image_bytes(src)
            img = Image.open(BytesIO(data))
            img.load()
            max_width = self.image_width
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception as e:
            logger.error(f"Failed to load episode image {src}: {e}", exc_info=True)
            print(traceback.format_exc(), file=sys.stderr)
            return None
        self._photo_images[src] = photo
        return photo

    def _render_content(self, ep, tag):
        for item in ep["content"]:
            if item["type"] == "image":
                photo = self._make_photo_image(item["src"])
                if photo is not None:
                    self.text.insert("end", "\n")
                    self.text.image_create("end", image=photo)
                    self.text.insert("end", "\n")
            else:
                # "end" (not "end-1c") always refers to the position AFTER
                # Tk's mandatory trailing newline, one line past where
                # .insert("end", ...) actually places new text -- confirmed
                # live: on a widget with nothing yet on the line being
                # written, text.index("end") reports one line further than
                # where the text lands, which silently broke
                # _span_at_index() for the first paragraph of every episode
                # (right-click-to-add-glossary-term did nothing there).
                # "end-1c" is the real insertion point.
                start = self.text.index("end-1c")
                self.text.insert("end", item["text"] + "\n", tag)
                self._rendered_spans.append((start, self.text.index("end-1c"), tag, item["text"]))

    def _render_interleaved_content(self, ep, original_tag, translated_tag):
        """Render each source line immediately followed by its translated line, repeating (RETRANSLATION_DESIGN.md phase 1).

        Walks ep["content"] the same way _render_content()/
        _render_translated_content() do (a mixed text/image list, with a
        separate line_idx counter that only advances on text items) rather
        than zipping ep["lines"] against ep["content"] directly, since
        ep["content"] also contains image items that ep["lines"] excludes
        -- naive zipping would misalign every line after the first image.

        Falls back to the plain (translated-only) rendering path -- via
        _render_translated_view(), so needs_review-aware rendering still
        applies there -- when build_interleaved_pairs() detects a length
        mismatch, rather than pairing lines that don't actually
        correspond. Reuses the existing "original"/"translated" tags; the
        translated half of a needs_review=True pair gets "needs_review"
        applied span-level (only the exact masked-term text, via
        _apply_needs_review_spans()), not over the whole line -- no new
        rendering path, no new tag.

        Args:
            ep: Episode dict.
            original_tag: Tag for the source-language half of each pair
                (normally "original").
            translated_tag: Tag for the translated half of each pair
                (normally "translated").
        """
        pairs = build_interleaved_pairs(ep.get("lines", []), ep.get("translated_lines", []))
        if pairs is None:
            logger.warning(
                f"Interleaved view: source_lines ({len(ep.get('lines', []))}) and translated_lines ({len(ep.get('translated_lines', []))}) length mismatch for {ep.get('episode_title', 'unknown')} -- falling back to translated-only view; refresh this chapter to retranslate"
            )
            self._render_translated_view(ep, translated_tag)
            return

        needs_review_flags = ep.get("needs_review_flags")
        review_aware = bool(needs_review_flags) and len(needs_review_flags) == len(pairs)
        novel_id = _extract_novel_id(self.app.current_url) if getattr(self.app, "current_url", None) else None
        # Full glossary, not build_mask_targets()'s unconfirmed-only
        # filter -- see find_glossary_term_spans()'s docstring for why
        # status must not gate span lookup here.
        glossary = load_glossary(novel_id) if (review_aware and novel_id) else {"terms": []}

        line_idx = 0
        for item in ep["content"]:
            if item["type"] == "image":
                photo = self._make_photo_image(item["src"])
                if photo is not None:
                    self.text.insert("end", "\n")
                    self.text.image_create("end", image=photo)
                    self.text.insert("end", "\n")
                continue

            source_line, translated_line = pairs[line_idx]

            start = self.text.index("end-1c")
            self.text.insert("end", source_line + "\n", original_tag)
            self._rendered_spans.append((start, self.text.index("end-1c"), original_tag, source_line))

            start = self.text.index("end-1c")
            self.text.insert("end", translated_line + "\n", translated_tag)
            end = self.text.index("end-1c")
            self._rendered_spans.append((start, end, translated_tag, source_line))
            self._translated_line_index_by_span[(start, end)] = line_idx
            if review_aware and needs_review_flags[line_idx]:
                self._apply_needs_review_spans(start, translated_line, source_line, glossary)

            line_idx += 1

    def _render_translated_view(self, ep, tag):
        """Dispatch to the needs_review-aware renderer when the cached episode has that data, else the plain one.

        The on-disk cache (DESIGN.md Section 11) stores translated_lines as
        plain List[str] plus a parallel needs_review_flags: List[bool] --
        not TranslatedLine objects directly, since build_glossary.py's
        extraction and other readers of ep["translated_lines"] need plain
        joinable strings (see Section 11 for the full reasoning). This
        reconstructs TranslatedLine objects from that pair, and recomputes
        mask_targets fresh from the current glossary (via
        build_mask_targets()) for the needs-review click-to-add pre-fill --
        safe to recompute since mask_targets is only used here to resolve
        "which word" for the dialog, not as a record of what happened at
        translation time (that fact is needs_review_flags, which IS
        persisted as-is, not recomputed).
        """
        needs_review_flags = ep.get("needs_review_flags")
        translated_strs = ep.get("translated_lines", [])
        if needs_review_flags and len(needs_review_flags) == len(translated_strs):
            translated_lines = [TranslatedLine(text=t, needs_review=r) for t, r in zip(translated_strs, needs_review_flags)]
            novel_id = _extract_novel_id(self.app.current_url) if getattr(self.app, "current_url", None) else None
            # The full glossary, not build_mask_targets()'s filtered
            # unconfirmed-only list -- find_glossary_term_spans() (span-
            # level highlighting/click resolution) deliberately searches
            # every term regardless of current status, since needs_review
            # is a historical fact about translation time, not current
            # glossary state. See find_glossary_term_spans()'s docstring.
            glossary = load_glossary(novel_id) if novel_id else {"terms": []}
            self._render_translated_content_from_translated_lines(ep, tag, translated_lines, glossary)
        else:
            self._render_translated_content(ep, tag)

    def _render_translated_content(self, ep, tag):
        translated_lines = ep.get("translated_lines", [])
        expected = sum(1 for item in ep["content"] if item["type"] == "text")
        if len(translated_lines) != expected:
            # translated_lines is walked in lockstep with the text items in
            # ep["content"] below -- if the counts don't match (e.g. a stale
            # cache entry from before translate_lines() guaranteed alignment),
            # every paragraph after the point of drift renders against the
            # wrong translated line instead of its own. Surfacing this in the
            # log is the only way to tell "wrong text showing" apart from a
            # fresh translation bug, since the render itself has no way to
            # detect misalignment from the text alone.
            logger.warning(
                f"translated_lines length ({len(translated_lines)}) != expected text item count ({expected}) for {ep.get('episode_title', 'unknown')} -- display will drift; refresh this chapter to retranslate"
            )
        line_idx = 0
        for item in ep["content"]:
            if item["type"] == "image":
                photo = self._make_photo_image(item["src"])
                if photo is not None:
                    self.text.insert("end", "\n")
                    self.text.image_create("end", image=photo)
                    self.text.insert("end", "\n")
            else:
                line = translated_lines[line_idx] if line_idx < len(translated_lines) else item["text"]
                # "end-1c", not "end" -- see _render_content()'s comment on
                # the same pattern for why.
                start = self.text.index("end-1c")
                self.text.insert("end", line + "\n", tag)
                # source_line is always the original Japanese text for this
                # paragraph (item["text"]), even though the rendered/tagged
                # text here is the translation -- needed so a right-click on
                # translated text can still surface the Japanese source, e.g.
                # for the glossary popup's reference context.
                self._rendered_spans.append((start, self.text.index("end-1c"), tag, item["text"]))
                line_idx += 1

    def _render_translated_content_from_translated_lines(self, ep, tag, translated_lines, glossary):
        """Render content using TranslatedLine output, span-level needs_review-aware.

        Sibling to _render_translated_content(), which reads
        ep["translated_lines"] (plain List[str]) -- this instead takes the
        List[TranslatedLine] that translate_chunk_with_masking() produces
        directly.

        Span-level highlighting (not line-level): a needs_review=True
        line's base text is inserted with the ordinary `tag` (normally
        "translated"), then find_glossary_term_spans() locates the exact
        masked-term substring(s) actually present in that line, and only
        those spans get the "needs_review" tag added on top via
        tag_add() -- the rest of the line keeps its normal styling. See
        _apply_needs_review_spans() for the shared per-line span-tagging
        logic (also used by _render_interleaved_content()).

        Not currently called from render_text() -- there is no production
        code path that produces List[TranslatedLine] yet
        (translate_chunk_with_masking() has no live callers; see DESIGN.md
        Section 10). This exists so the rendering logic is ready and
        testable once that wiring (a separate, later task) lands, and so
        it can be exercised directly against synthetic TranslatedLine data
        in the meantime.

        Args:
            ep: Episode dict, for ep["content"] (paragraph/image structure)
                and the source Japanese text of each paragraph.
            tag: Base tag for non-flagged lines (normally "translated").
            translated_lines: List[TranslatedLine], same length/order as
                the text items in ep["content"].
            glossary: Glossary dict as returned by load_glossary() --
                the full glossary, not filtered by status. See
                find_glossary_term_spans()'s docstring for why status
                must not gate this search.
        """
        line_idx = 0
        for item in ep["content"]:
            if item["type"] == "image":
                photo = self._make_photo_image(item["src"])
                if photo is not None:
                    self.text.insert("end", "\n")
                    self.text.image_create("end", image=photo)
                    self.text.insert("end", "\n")
            else:
                if line_idx < len(translated_lines):
                    translated = translated_lines[line_idx]
                    line_text = translated.text
                    needs_review = translated.needs_review
                else:
                    line_text = item["text"]
                    needs_review = False
                # "end-1c", not "end" -- see _render_content()'s comment on
                # the same pattern for why.
                start = self.text.index("end-1c")
                self.text.insert("end", line_text + "\n", tag)
                end = self.text.index("end-1c")
                self._rendered_spans.append((start, end, tag, item["text"]))
                if needs_review:
                    self._apply_needs_review_spans(start, line_text, item["text"], glossary)
                line_idx += 1

    def _apply_needs_review_spans(self, line_start, line_text, source_line, glossary):
        """Tag the exact masked-term span(s) within an already-inserted needs_review line, and track them for click resolution.

        Shared by _render_translated_content_from_translated_lines() and
        _render_interleaved_content() -- both insert a needs_review=True
        line's text with the ordinary translated tag first, then call this
        to layer "needs_review" on top of only the term span(s)
        find_glossary_term_spans() actually locates, via tag_add() rather
        than re-inserting the text. Tk gives the later-added tag priority
        for conflicting display attributes (confirmed directly: a tag
        added via tag_add() after insert()'s tag wins), so "needs_review"'s
        amber/underline styling correctly overrides "translated"'s blue
        over just that span, leaving the rest of the line unaffected.

        If find_glossary_term_spans() finds nothing (e.g. the exact raw
        word isn't a literal substring of the rendered line for some
        reason not yet seen in practice), nothing is tagged/tracked here --
        needs_review=True still applies to _rendered_spans' base "tag" as
        normal, so the line doesn't silently lose its needs_review fact,
        it just has no clickable highlighted sub-span. Not expected to
        happen in practice (splice_terms() always inserts the literal
        source word), but not treated as an error if it does.

        Args:
            line_start: The Tk text index where line_text's insertion began.
            line_text: The rendered (translated/spliced) line text.
            source_line: The Japanese source text for this line, passed
                through to open_word_glossary_popup() as explain_term()
                context, same as every other span-click path.
            glossary: Glossary dict as returned by load_glossary().
        """
        for span_start, span_end, word in find_glossary_term_spans(line_text, glossary):
            tk_start = self.text.index(f"{line_start}+{span_start}c")
            tk_end = self.text.index(f"{line_start}+{span_end}c")
            self.text.tag_add("needs_review", tk_start, tk_end)
            self._review_terms_by_span[(tk_start, tk_end)] = (word, source_line)

    def _on_needs_review_click(self, event):
        """Click on a needs_review-tagged span: open Add-to-Glossary pre-filled with the specific term clicked.

        Reuses the existing open_word_glossary_popup() dialog (the same
        one used by the right-click flow) rather than a new one, per
        DESIGN.md Section 6. Pre-fills Source with the masked term whose
        exact span was clicked (span-level, not line-level -- a line with
        more than one flagged term now resolves to whichever one was
        actually clicked, via _review_terms_by_span's per-span entries;
        see _apply_needs_review_spans()). Target is left blank -- the raw
        source word was spliced back into the line as a fallback (see
        llm_translate.splice_terms()), not offered as a translation guess,
        so prefilling Target with it would misrepresent an untranslated
        placeholder as a proposed English target.

        Args:
            event: The Tk button-press event.
        """
        idx = self.text.index(f"@{event.x},{event.y}")
        for (start, end), (word, source_line) in self._review_terms_by_span.items():
            if self.text.compare(start, "<=", idx) and self.text.compare(idx, "<", end):
                # Group C dialog, not yet extracted (Phase 3) -- reached via
                # the back-reference rather than moved/duplicated here.
                self.app.open_word_glossary_popup(word, "", context=source_line)
                return

    def _on_view_mode_change(self):
        """Handle the Original/Translated/Both radio buttons: re-render and persist."""
        self.render_text()
        self.app._save_settings()

    def render_text(self, restore_scroll_pos=None):
        """Render the current episode content in the text widget.

        Args:
            restore_scroll_pos: Fraction (0.0-1.0) to scroll to after
                rendering, instead of scrolling to the top. Used only when
                resuming a previous session to the exact spot left off.
        """
        ep = self.app.episode
        if ep is None:
            return
        mode = self.view_mode.get()
        self.text.delete("1.0", "end")
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self._translated_line_index_by_span = {}

        if mode in ("original", "both", "interleaved"):
            self.text.insert("end", f"{ep['title']} — {ep['episode_title']}\n", "heading")
        if mode in ("translated", "both"):
            title = ep.get("translated_title", ep["title"])
            episode_title = ep.get("translated_episode_title", ep["episode_title"])
            self.text.insert("end", f"{title} — {episode_title}\n", "heading")

        self.text.insert("end", f"by {ep['author']}\n\n", "original")
        if mode in ("original", "both"):
            self._render_content(ep, "original")
        if mode == "both":
            self.text.insert("end", "\n---- Translation ----\n\n", "heading")
        if mode in ("translated", "both"):
            self._render_translated_view(ep, "translated")
        if mode == "interleaved":
            self._render_interleaved_content(ep, "original", "translated")
        if restore_scroll_pos is not None:
            self.text.yview_moveto(restore_scroll_pos)
        else:
            self.text.see("1.0")

    def _span_at_index(self, idx):
        """Find the rendered paragraph span containing a text-widget index.

        Args:
            idx: A Tk text index (e.g. "12.34").

        Returns:
            The (start, end, tag, source_line) tuple from self._rendered_spans
            whose range contains idx, or None if idx falls outside any
            tracked paragraph (e.g. a heading, the byline, or an image).
        """
        for start, end, tag, source_line in self._rendered_spans:
            if self.text.compare(start, "<=", idx) and self.text.compare(idx, "<", end):
                return (start, end, tag, source_line)
        return None

    def _translated_span_after(self, original_span):
        """Find the translated-line span immediately following an original-line span in _rendered_spans.

        RETRANSLATION_DESIGN.md phase 3: _render_interleaved_content()
        appends spans in strict (original, translated) pairs, one pair per
        source line -- see its implementation. That ordering, not a tag
        lookup, is what lets this resolve "the current translation of this
        line" from an original-tagged span without a second tracking
        structure (mirroring how _review_terms_by_span is a *separate*
        dict built only in the needs_review-aware translated path, not
        reused here since Interleaved mode doesn't populate it).

        Args:
            original_span: A (start, end, tag, source_line) tuple from
                self._rendered_spans, expected to have tag == "original".

        Returns:
            The (start, end, tag, source_line) tuple for the very next
            entry in self._rendered_spans, or None if original_span isn't
            found or has no following entry (e.g. malformed input).
        """
        try:
            idx = self._rendered_spans.index(original_span)
        except ValueError:
            return None
        if idx + 1 >= len(self._rendered_spans):
            return None
        return self._rendered_spans[idx + 1]


class ReaderApp:
    """Tkinter-based desktop reader for Alphapolis novels.

    Provides navigation, translation display, font controls, and dark mode.
    """

    def __init__(self, root, browser, start_url, target_lang="en", restore_scroll_pos=None):
        """Initialize the reader application GUI.

        Args:
            root: The Tkinter root window.
            browser: A BrowserWorker instance for fetching pages.
            start_url: The initial episode URL to load.
            target_lang: Target translation language code (default: en).
            restore_scroll_pos: Fraction (0.0-1.0) to scroll to once start_url
                finishes loading, if resuming a previous session. None means
                scroll to the top as usual (a fresh/explicit URL was given).
        """
        self.root = root
        self.browser = browser
        self.target_lang = target_lang
        self.backend = self._load_backend()
        self.episode = None
        # Never re-set by any code path other than display_episode() --
        # explicitly initialized here (rather than left absent until the
        # first episode loads) so no reader needs a hasattr(self,
        # "current_url") guard; every such guard elsewhere in this file
        # predates this initialization and is left as defensive but
        # no longer strictly necessary.
        self.current_url = None
        self.cache = {}
        # url -> threading.Event, one entry per fetch_and_translate() call
        # currently in flight (real network fetch + real LLM translation
        # running, cache not yet populated). Guards against the duplicate-
        # fetch race documented in DESIGN.md: prefetch() (fired from
        # display_episode() right after an episode finishes loading, to
        # warm the next chapter in the background) and a navigation-
        # triggered load_episode() (e.g. the user clicking Next) can both
        # call fetch_and_translate() for the same URL before either has
        # written to self.cache/disk -- self._prefetching only guards
        # prefetch() against re-entering itself, and self._loading only
        # guards load_episode() against overlapping *unrelated* loads,
        # neither prevents this specific same-URL race between the two
        # different call paths. A second concurrent call for a URL already
        # in this dict waits on its Event instead of duplicating the real
        # network fetch and real LLM translation pass -- see
        # fetch_and_translate() for the wait/signal logic.
        self._fetch_in_progress: Dict[str, threading.Event] = {}
        self._restore_scroll_pos = restore_scroll_pos
        # Tracks the currently-open Add-to-Glossary / Retranslate popup (at
        # most one of each kind at a time), so a second click while one is
        # already open raises/focuses it instead of opening a duplicate --
        # found live: repeated clicks (e.g. during xdotool verification, or
        # an impatient double-click) could otherwise stack multiple
        # independent Toplevel windows, each with its own background
        # lookup thread, confusing rather than just redundant. None when no
        # popup of that kind is open; cleared via a <Destroy> binding on
        # the Toplevel itself so it's reset regardless of how the window
        # closed (Save, Cancel, Accept/Discard, or the window manager's
        # close button).
        self._glossary_popup = None
        self._retranslate_popup = None
        # (word, context) -> (google_guess, llm_guess, explanation),
        # populated by open_word_glossary_popup()'s background lookup.
        # Session-only (not persisted) -- avoids repeating a network
        # round-trip if the user reopens the popup for the same word in
        # the same sentence (e.g. after Cancel). Keyed with context, not
        # just the word, since the same surface text can mean different
        # things (or be a name vs. not) depending on the sentence.
        self._word_guess_cache = {}

        self._prefetching = set()
        # True while a load_episode() worker thread is running. Prevents
        # overlapping loads -- confirmed possible via rapid clicks on
        # Previous/Next or the <Left>/<Right> key bindings (keyboard repeat
        # fires go_prev()/go_next() directly, bypassing the toolbar buttons'
        # disabled state entirely). Concurrent loads meant multiple
        # simultaneous LLM translation requests hitting the same
        # llama-server slots, which is suspected to have contributed to
        # scrambled/misaligned translated output.
        self._loading = False

        root.title("Alphapolis Reader")
        # Widened from 900 -> 990 (Refresh button) -> 1090 (Glossary... button)
        # -> 1220 (Review Terms... button) to keep the toolbar from clipping
        # Settings... off the right edge. WINDOW_REDESIGN.md Phase 2 removed
        # five toolbar widgets (Load Novel..., Settings..., A-/A+/Dark/
        # Img-/Img+, two of the four view-mode radios) but this geometry is
        # left as-is -- narrowing it is a cosmetic follow-up, not required
        # for every remaining control to stay reachable.
        root.geometry("1220x700")

        # ReaderRenderer (REFACTOR_DESIGN.md Phase 2) owns view_mode and
        # every appearance/font/image-size control below -- constructed
        # before the menu bar and toolbar, since both wire directly into
        # the renderer's StringVar/commands.
        self.renderer = ReaderRenderer(self)

        # Menu bar (WINDOW_REDESIGN.md Phase 2): holds all five dialog
        # launchers plus the display controls that used to live only on
        # the toolbar. File/Refresh/Settings share one menu since all
        # three act on "the app/loaded novel" rather than editing glossary
        # state, per WINDOW_REDESIGN.md Phase 1's proposal.
        menubar = tk.Menu(root)
        root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load Novel...", command=self.open_load_url_dialog)
        file_menu.add_command(label="Refresh", command=self.refresh_current_episode)
        file_menu.add_separator()
        file_menu.add_command(label="Settings...", command=self.open_settings_dialog)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        for value, label in (("translated", "Translated"), ("interleaved", "Interleaved")):
            view_menu.add_radiobutton(label=label, value=value, variable=self.renderer.view_mode, command=self.renderer._on_view_mode_change)
        view_menu.add_separator()
        view_menu.add_command(label="Increase Font Size", command=self.renderer.increase_font)
        view_menu.add_command(label="Decrease Font Size", command=self.renderer.decrease_font)
        view_menu.add_command(label="Toggle Dark Mode", command=self.renderer.toggle_dark_mode)
        view_menu.add_command(label="Increase Image Width", command=self.renderer.increase_image_width)
        view_menu.add_command(label="Decrease Image Width", command=self.renderer.decrease_image_width)
        menubar.add_cascade(label="View", menu=view_menu)

        glossary_menu = tk.Menu(menubar, tearoff=0)
        glossary_menu.add_command(label="Glossary...", command=self.open_glossary_dialog)
        glossary_menu.add_command(label="Review Terms...", command=self.open_term_review_dialog)
        menubar.add_cascade(label="Glossary", menu=glossary_menu)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", padx=8, pady=6)

        self.prev_btn = ttk.Button(toolbar, text="< Previous", command=self.go_prev)
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(toolbar, text="Next >", command=self.go_next)
        self.next_btn.pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        for value, label in (("translated", "Translated"), ("interleaved", "Interleaved")):
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.renderer.view_mode, command=self.renderer._on_view_mode_change).pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Refresh", command=self.refresh_current_episode).pack(side="left")
        ttk.Button(toolbar, text="Glossary...", command=self.open_glossary_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Review Terms...", command=self.open_term_review_dialog).pack(side="left", padx=(6, 0))

        # Toolbar right-click context menu (WINDOW_REDESIGN.md Phase 3):
        # quick access to the now menu-only dialog launchers (Load
        # Novel..., Settings...) without a full menu-bar navigation, plus
        # the three actions that already have visible toolbar buttons.
        toolbar.bind("<Button-3>", self._on_toolbar_right_click)

        url_bar = ttk.Frame(root)
        url_bar.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(url_bar, text="URL:").pack(side="left")
        self.url_var = tk.StringVar(value="")
        self.url_entry = ttk.Entry(url_bar, textvariable=self.url_var, state="readonly")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # Status bar docked at the bottom -- packed before the text widget so
        # it claims its space first; the text widget then fills what remains.
        status_bar = ttk.Frame(root)
        status_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 6))
        self.status_label = ttk.Label(status_bar, text="")
        self.status_label.pack(side="left")

        # STATUS_BAR_DESIGN.md Phase 2: two new permanent labels alongside
        # (not replacing) status_label's existing transient-message use.
        # Packed from the right so they stay visually distinct from
        # set_status()'s left-packed messages rather than competing for
        # the same run of text -- "where am I" (page_count_label) and
        # "how much is here" (content_count_label) are deliberately two
        # separate labels, not one combined string, per this doc's own
        # navigation-fact-vs-content-fact framing. Both start empty and
        # are populated by _update_status_bar_counts(), called from
        # display_episode() -- the one call site that fires on every
        # navigation (Prev/Next/Load) and after Refresh (refresh_current_episode()
        # -> load_episode() -> ... -> display_episode() once the re-fetch
        # completes), so a single hook covers both triggers this doc's
        # own "Update triggers" section calls for.
        self.content_count_label = ttk.Label(status_bar, text="")
        self.content_count_label.pack(side="right", padx=(12, 0))
        self.page_count_label = ttk.Label(status_bar, text="")
        self.page_count_label.pack(side="right")

        text_frame = ttk.Frame(root)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        text_scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        text_scrollbar.pack(side="right", fill="y")

        self.text = tk.Text(text_frame, wrap="word", padx=16, pady=12, borderwidth=0, highlightthickness=0, yscrollcommand=text_scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        text_scrollbar.config(command=self.text.yview)
        self.text.bind("<Button-3>", self._on_text_right_click)
        # Left-click specifically on a needs_review span (tag_bind, not the
        # widget-wide right-click handler) opens Add-to-Glossary pre-filled
        # with the flagged term -- a lower-friction path than "right-click,
        # then pick Add to Glossary from a menu" for the specific case of a
        # term the pipeline already flagged as needing attention.
        self.text.tag_bind("needs_review", "<Button-1>", self.renderer._on_needs_review_click)
        self.renderer.apply_appearance()

        self.prev_btn.state(["disabled"])
        self.next_btn.state(["disabled"])

        root.bind("<Left>", lambda e: self.go_prev())
        root.bind("<Right>", lambda e: self.go_next())
        root.bind("<Prior>", lambda e: self.text.yview_scroll(-1, "pages"))
        root.bind("<Next>", lambda e: self.text.yview_scroll(1, "pages"))
        root.bind("<Control-equal>", lambda e: self.renderer.increase_font())
        root.bind("<Control-minus>", lambda e: self.renderer.decrease_font())

        self.load_episode(start_url)

    def _load_backend(self) -> str:
        """Load the saved translation backend setting."""
        try:
            state = load_reader_state()
            return state.get("backend", DEFAULT_BACKEND)
        except Exception:
            return DEFAULT_BACKEND

    def _save_backend(self) -> None:
        """Save the current backend setting to state."""
        try:
            update_reader_state(backend=self.backend)
        except Exception as e:
            logger.debug(f"Failed to save backend setting: {e}")

    def _save_settings(self) -> None:
        """Persist current display settings (font, sizing, mode) to state.

        Reads from self.renderer (REFACTOR_DESIGN.md Phase 2) -- these are
        all ReaderRenderer-owned attributes now, read here via the explicit
        back-reference rather than this method moving to the renderer
        itself, since persistence-to-disk is a core-app-shell concern
        (this method also isn't renderer-specific in spirit -- it's the
        same "settings" bucket _save_backend() writes into).
        """
        try:
            update_reader_state(
                font_size=self.renderer.font_size,
                image_width=self.renderer.image_width,
                dark_mode=self.renderer.dark_mode,
                font_family=self.renderer.font_family,
                line_height=self.renderer.line_height,
                paragraph_spacing=self.renderer.paragraph_spacing,
                page_width_pct=self.renderer.page_width_pct,
                text_align=self.renderer.text_align,
                view_mode=self.renderer.view_mode.get(),
            )
        except Exception as e:
            logger.debug(f"Failed to save display settings: {e}")

    def open_load_url_dialog(self):
        """Open a dialog window for loading a new episode by URL."""
        win = tk.Toplevel(self.root)
        win.title("Load Novel")
        win.geometry("500x110")
        win.transient(self.root)

        ttk.Label(win, text="Episode URL:").pack(anchor="w", padx=10, pady=(10, 0))
        url_var = tk.StringVar(value=self.url_var.get())
        entry = ttk.Entry(win, textvariable=url_var, width=60)
        entry.pack(fill="x", padx=10, pady=6)
        entry.focus_set()
        entry.select_range(0, "end")

        def submit():
            url = url_var.get().strip()
            win.destroy()
            if url:
                self.load_episode(url)

        entry.bind("<Return>", lambda e: submit())
        btns = ttk.Frame(win)
        btns.pack(pady=(0, 10))
        ttk.Button(btns, text="Load", command=submit).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=4)

    def open_settings_dialog(self):
        """Open the settings dialog for font, spacing, and alignment controls."""
        win = tk.Toplevel(self.root)
        win.title("Settings")
        # Heightened from 360 to fit the Clear Cache section added below
        # the existing controls without clipping the Apply/Cancel buttons.
        win.geometry("360x440")
        win.transient(self.root)

        pad = {"padx": 10, "pady": (10, 2)}

        ttk.Label(win, text="Translation Backend").pack(anchor="w", **pad)
        backend_var = tk.StringVar(value=self.backend)
        backend_row = ttk.Frame(win)
        backend_row.pack(anchor="w", padx=10)
        llm_available = check_llm_available()
        for value, label in ((BACKEND_GOOGLE, "Google Translate"), (BACKEND_LLM, f"Local LLM ({'available' if llm_available else 'not found'})")):
            state = "normal" if value != BACKEND_LLM or llm_available else "disabled"
            ttk.Radiobutton(backend_row, text=label, value=value, variable=backend_var, state=state).pack(side="left")
        if not llm_available:
            ttk.Label(backend_row, text="(llama-server not running)", fg="#888").pack(side="left", padx=(4, 0))

        ttk.Label(win, text="Font").pack(anchor="w", **pad)
        font_var = tk.StringVar(value=self.renderer.font_family)
        font_choices = [f for f in FONT_CANDIDATES if f in self.renderer._available_fonts()]
        if self.renderer.font_family not in font_choices:
            font_choices.insert(0, self.renderer.font_family)
        font_combo = ttk.Combobox(win, textvariable=font_var, values=font_choices, state="readonly")
        font_combo.pack(fill="x", padx=10)

        def make_slider(label, var, frm, to, resolution=1):
            ttk.Label(win, text=label).pack(anchor="w", **pad)
            row = ttk.Frame(win)
            row.pack(fill="x", padx=10)
            value_lbl = ttk.Label(row, width=5)
            value_lbl.pack(side="right")

            def on_move(v):
                value_lbl.config(text=f"{float(v):.1f}" if resolution < 1 else f"{int(float(v))}")

            scale = ttk.Scale(row, from_=frm, to=to, orient="horizontal", variable=var, command=on_move)
            scale.pack(side="left", fill="x", expand=True)
            on_move(var.get())
            return scale

        line_height_var = tk.DoubleVar(value=self.renderer.line_height)
        make_slider("Line Height", line_height_var, 1.0, 2.5, resolution=0.1)

        paragraph_spacing_var = tk.IntVar(value=self.renderer.paragraph_spacing)
        make_slider("Paragraph Spacing (px)", paragraph_spacing_var, 0, 40)

        page_width_var = tk.IntVar(value=self.renderer.page_width_pct)
        make_slider("Page Width (%)", page_width_var, 40, 100)

        ttk.Label(win, text="Text Alignment").pack(anchor="w", **pad)
        align_var = tk.StringVar(value=self.renderer.text_align)
        align_row = ttk.Frame(win)
        align_row.pack(anchor="w", padx=10)
        for value, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            ttk.Radiobutton(align_row, text=label, value=value, variable=align_var).pack(side="left")

        def apply_and_close():
            self.renderer.font_family = font_var.get()
            self.renderer.line_height = line_height_var.get()
            self.renderer.paragraph_spacing = paragraph_spacing_var.get()
            self.renderer.page_width_pct = page_width_var.get()
            self.renderer.text_align = align_var.get()
            self.backend = backend_var.get()
            self._save_backend()
            self._save_settings()
            win.destroy()
            self.renderer.apply_appearance()
            self.renderer.render_text()

        ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(win, text="Clear Cache...", command=lambda: self._confirm_clear_cache(win)).pack(anchor="w", padx=10, pady=(8, 0))

        btns = ttk.Frame(win)
        btns.pack(pady=(14, 10))
        ttk.Button(btns, text="Apply", command=apply_and_close).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=4)

    def set_status(self, msg):
        """Update the status bar text and force a GUI refresh.

        Args:
            msg: The status message to display.
        """
        self.status_label.config(text=msg)
        self.root.update_idletasks()

    def _update_status_bar_counts(self, ep):
        """Update the page-count and word/paragraph-count status bar labels from a parsed episode dict.

        STATUS_BAR_DESIGN.md Phase 2. Two independent labels, per that
        doc's own decision to keep "where am I" (page_count) and "how
        much is here" (content counts) visually distinct rather than
        bundled into one string.

        page_count_label: from ep["page_count"] (a (current, total) tuple
        from parse_episode(), or None for an episode cached before this
        field existed -- CACHE_SCHEMA_VERSION was deliberately not
        bumped for this addition, since forcing a full refetch/
        re-translate of every already-cached episode just to backfill a
        display-only field would be a real, disproportionate cost; the
        label is simply blank until that episode is next fetched fresh
        or Refreshed, same no-migration-needed precedent this project
        already established for honorific_policy-shaped fields).

        content_count_label: paragraph count from len(ep["lines"])
        (confirmed 1:1 with len(ep["translated_lines"]) per
        STATUS_BAR_DESIGN.md Phase 1, so one number covers both sides,
        no separate original/translated paragraph counts needed),
        original-language character count from
        sum(len(t) for t in ep["lines"]), translated-language word count
        from a plain str.split() over ep["translated_lines"] -- per this
        doc's now-locked-in decision, these two counts are not meant to
        be compared against each other, each is just meaningful for its
        own side. translated_lines may be absent (an episode dict that
        hasn't been translated yet, if this is ever called before that
        stage) -- guarded the same way page_count is.

        Args:
            ep: The current episode dict (self.episode).
        """
        page_count = ep.get("page_count")
        if page_count:
            current, total = page_count
            self.page_count_label.config(text=f"Chapter {current} / {total}")
        else:
            self.page_count_label.config(text="")

        lines = ep.get("lines") or []
        translated_lines = ep.get("translated_lines") or []
        paragraph_count = len(lines)
        original_char_count = sum(len(t) for t in lines)
        translated_word_count = sum(len(t.split()) for t in translated_lines)
        self.content_count_label.config(text=f"{paragraph_count} paragraphs | {original_char_count} chars (orig) | {translated_word_count} words (translated)")

    def show_error(self, full_trace: str):
        """Display an error dialog with the full traceback.

        Args:
            full_trace: The exception traceback string to display.
        """
        win = tk.Toplevel(self.root)
        win.title("Error")
        win.geometry("700x400")
        text = tk.Text(win, wrap="word", font=("Courier", 10), fg="#a00000")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        text.insert("end", full_trace)
        text.config(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 8))

    def fetch_and_translate(self, url, progress_cb=None):
        """Fetch+translate an episode, checking memory and disk caches first.

        Guards against duplicate concurrent work for the same URL (found
        live: prefetch() warming the next chapter in the background races
        a navigation-triggered load_episode() call for that same URL,
        producing two independent real network fetches and two independent
        real LLM translation passes -- see DESIGN.md for the live
        reproduction). A second caller for a URL already in flight waits
        for the first to finish and reuses its result instead of
        duplicating the work.
        """
        if url in self.cache:
            return self.cache[url]
        cached = load_cached_episode(url)
        if cached is not None:
            self.cache[url] = cached
            return cached

        existing = self._fetch_in_progress.get(url)
        if existing is not None:
            logger.info(f"fetch_and_translate({url}) already in progress on another call -- waiting for it instead of duplicating the fetch/translate")
            existing.wait()
            # The winning caller populates self.cache before signaling
            # (see the finally block below) -- if it failed instead
            # (exception path), self.cache won't have url and this
            # falls through to attempting the fetch itself, same as if
            # no in-flight call had ever existed.
            if url in self.cache:
                return self.cache[url]

        done_event = threading.Event()
        self._fetch_in_progress[url] = done_event
        try:
            return self._do_fetch_and_translate(url, progress_cb=progress_cb)
        finally:
            del self._fetch_in_progress[url]
            done_event.set()

    def _do_fetch_and_translate(self, url, progress_cb=None):
        """The actual fetch+translate work, called only once per URL at a time -- see fetch_and_translate()'s in-flight guard."""
        logger.info(f"Fetching and translating episode: {url} (backend={self.backend})")

        glossary_text = None
        glossary = None
        novel_id = None
        if self.backend == BACKEND_LLM:
            novel_id = _extract_novel_id(url)
            if novel_id:
                glossary = load_glossary(novel_id)
                glossary_text = format_glossary_for_prompt(glossary)
                global_text = format_global_vocabulary_for_prompt(load_global_vocabulary(), glossary)
                if global_text:
                    glossary_text = f"{glossary_text}\n\n{global_text}" if glossary_text else global_text

        html = self.browser.fetch(url)
        logger.debug(f"Fetched {len(html)} bytes of HTML for {url}")
        ep = parse_episode(html)
        logger.info(f"Parsed {len(ep['lines'])} paragraph(s), {len(ep['content'])} content item(s) from {url}")
        if len(ep["lines"]) < 5:
            # A normal chapter runs from a few dozen to over a hundred
            # paragraphs (confirmed across multiple real episodes); a
            # handful or fewer usually means the page was a bot-check/
            # challenge response or genuinely truncated rather than a full
            # chapter, so flag it instead of silently translating almost nothing.
            logger.warning(
                f"Only {len(ep['lines'])} paragraph(s) parsed from {url} -- page may not have fully loaded or loaded a bot-check page instead of the chapter; verify before trusting this translation"
            )

        # Masking (DESIGN.md Section 4/10/11) only applies to the LLM
        # backend -- Google Translate has no sentinel-survival mechanism at
        # all, masking would just corrupt its output. mask_targets only
        # covers ep["lines"] (the chapter body); title/episode_title are a
        # separate, unmasked translate_lines() call below -- glossary terms
        # in a title are rare enough, and the review-queue UX doesn't have
        # a natural place to flag a title, that masking titles wasn't worth
        # the added complexity here.
        mask_targets = build_mask_targets(ep["lines"], glossary) if glossary is not None else []
        if mask_targets:
            # Best-available-candidate fallback (DESIGN.md's dated entry):
            # splice_terms() substitutes a masked term's best suggested
            # candidate instead of the bare raw word when one exists --
            # display-quality only, does not affect what's injected into
            # the translation prompt (glossary_text below stays
            # confirmed-only, per Section 9). Built from the same
            # `glossary` snapshot mask_targets was just computed against,
            # so a word here can never belong to an already-confirmed term
            # (see build_splice_fallbacks()'s docstring).
            fallbacks = build_splice_fallbacks(mask_targets, glossary)
            translated = translate_lines_with_masking(
                ep["lines"], mask_targets, self.target_lang, glossary_text=glossary_text, progress_cb=progress_cb, fallbacks=fallbacks, log_context=url
            )
            ep["translated_lines"] = [t.text for t in translated]
            ep["needs_review_flags"] = [t.needs_review for t in translated]
        else:
            ep["translated_lines"] = translate_lines(ep["lines"], self.target_lang, backend=self.backend, glossary_text=glossary_text, progress_cb=progress_cb, log_context=url)
            ep["needs_review_flags"] = [False] * len(ep["translated_lines"])

        # Count-building loop (DESIGN.md Section 12): same guard as masking
        # above -- only when the LLM backend actually loaded a glossary.
        # Google Translate never produces a "candidate" to count against
        # (no glossary was even consulted for it), and there's nothing to
        # persist if novel_id never resolved.
        if glossary is not None and novel_id is not None:
            updated_glossary = update_candidate_counts(ep["lines"], ep["translated_lines"], glossary, needs_review_flags=ep["needs_review_flags"])
            save_glossary(novel_id, updated_glossary)

        title_lines = translate_lines([ep["title"], ep["episode_title"]], self.target_lang, backend=self.backend, glossary_text=glossary_text, log_context=url)
        ep["translated_title"], ep["translated_episode_title"] = title_lines
        for item in ep["content"]:
            if item["type"] == "image":
                try:
                    fetch_image_bytes(item["src"])
                except Exception as e:
                    logger.error(f"Failed to prefetch episode image {item['src']}: {e}", exc_info=True)
                    print(traceback.format_exc(), file=sys.stderr)
        self.cache[url] = ep
        save_cached_episode(url, ep)
        logger.info(f"Episode translated successfully: {ep.get('episode_title', 'unknown')}")
        return ep

    def load_episode(self, url):
        """Load and display an episode by URL in a background thread.

        No-ops if a load is already in progress -- guards against
        overlapping loads from rapid Previous/Next clicks or held-down
        arrow keys (the <Left>/<Right> bindings call go_prev()/go_next()
        directly and aren't gated by the toolbar buttons' disabled state).
        Without this, multiple concurrent LLM translation requests could
        hit the server at once, which is suspected to have contributed to
        scrambled/misaligned translated output.

        Args:
            url: The episode URL to load.
        """
        if self._loading:
            logger.debug(f"Ignoring load_episode({url}) -- a load is already in progress")
            return
        self._loading = True

        self.set_status("Loading...")
        self.prev_btn.state(["disabled"])
        self.next_btn.state(["disabled"])
        # Clear the text area immediately rather than leaving the previous
        # chapter's text sitting there unchanged -- the status bar alone is
        # easy to miss, so without this a slow LLM translation could look
        # like nothing is happening rather than a load in progress.
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "Loading...", "heading")

        start_time = time.time()

        def progress_cb(done, total):
            elapsed = time.time() - start_time
            if done > 0:
                eta = elapsed / done * (total - done)
                text = f"Translating... {done}/{total} ({elapsed:.0f}s elapsed, ~{eta:.0f}s left)"
            else:
                text = f"Translating... {done}/{total} ({elapsed:.0f}s elapsed)"
            self.root.after(0, lambda: self.set_status(text))

        def worker():
            try:
                ep = self.fetch_and_translate(url, progress_cb=progress_cb)
                self.root.after(0, lambda: self.display_episode(url, ep))
            except Exception as e:
                full_trace = traceback.format_exc()
                logger.error(f"Failed to load episode {url}: {e}", exc_info=True)
                print(full_trace, file=sys.stderr)  # always visible in the console too
                self.root.after(0, lambda: self.show_error(full_trace))
                self.root.after(0, lambda: self.set_status("Error"))
            finally:
                self._loading = False

        threading.Thread(target=worker, daemon=True).start()

    def refresh_current_episode(self):
        """Discard cached data for the current episode and re-fetch/re-translate it."""
        if not hasattr(self, "current_url") or not self.current_url:
            return
        url = self.current_url
        self.cache.pop(url, None)
        _cache_path(url).unlink(missing_ok=True)
        self.set_status("Refreshing chapter...")
        self.load_episode(url)

    def _maybe_refresh_after_glossary_edit(self, dialog_novel_id, edited):
        """Auto-refresh the currently displayed episode after a glossary dialog closes, if warranted.

        Called once, on dialog close (WM_DELETE_WINDOW plus every button
        that ends up calling win.destroy()), not once per Confirm/Reject/
        Save action -- refresh_current_episode() is a full re-scrape +
        re-translate (real network fetch, real LLM calls), confirmed by
        reading its implementation before this method was written, not
        assumed from its name. Firing it after every individual edit in a
        multi-term Review Terms session (e.g. confirming 5 terms in a row)
        would mean 5 expensive passes instead of one -- wasteful, and
        needs_review flags/span highlighting are computed and cached at
        translation time, not re-derived live from current glossary state
        on render, so "auto-refresh" can only mean "re-run the
        translation," never a cheap in-place re-render.

        Deliberately narrow triggering conditions, both required:
        - `edited` must be true -- opening and closing a dialog with no
          Confirm/Reject/Save actions must not trigger anything.
        - `dialog_novel_id` must match the novel of the *currently
          displayed* episode, checked at call time (dialog close), not
          the novel that was current when the dialog was opened -- the
          displayed episode can change while the dialog is open (the
          main window's novel switch is independent of either dialog,
          confirmed in the stale-overwrite/novel-switch investigation),
          so re-checking at close time is what actually matters here.

        Args:
            dialog_novel_id: The novel_id the glossary dialog was opened
                for (pinned at dialog-open time, same as both dialogs
                already do for their own save/confirm/reject calls).
            edited: Whether at least one Confirm/Reject/Save action
                actually happened during this dialog session.
        """
        if not edited:
            return
        if not hasattr(self, "current_url") or not self.current_url:
            return
        current_novel_id = _extract_novel_id(self.current_url)
        if current_novel_id != dialog_novel_id:
            logger.debug(f"Glossary dialog for novel {dialog_novel_id} closed with edits, but displayed episode belongs to novel {current_novel_id!r} -- not auto-refreshing")
            return
        logger.info(f"Auto-refreshing displayed episode after glossary edit for novel {dialog_novel_id}")
        self.refresh_current_episode()

    def _confirm_clear_cache(self, settings_win):
        """Ask for confirmation, then clear the entire on-disk episode cache.

        Args:
            settings_win: The Settings dialog window, closed on confirm.
        """
        if not messagebox.askyesno(
            "Clear Cache",
            "This will delete all cached episode translations and images. " "You'll need to re-translate anything you read again. Continue?",
            parent=settings_win,
        ):
            return
        self.clear_cache()
        settings_win.destroy()

    def clear_cache(self):
        """Clear the in-memory and on-disk episode cache (not reader state)."""
        self.cache.clear()
        if CACHE_DIR.exists():
            for path in CACHE_DIR.rglob("*"):
                if path.is_file():
                    path.unlink()
        self.set_status("Cache cleared")

    def open_glossary_dialog(self):
        """Open the glossary term editor for the current novel.

        Lets the user view, add, edit, and delete glossary terms/characters
        and the novel-wide honorific policy. Edits take effect on the next
        chapter load or Refresh (fetch_and_translate() loads the glossary
        fresh each time, no separate reload needed here).
        """
        if not hasattr(self, "current_url") or not self.current_url:
            messagebox.showinfo("Glossary", "Load a novel first.")
            return
        novel_id = _extract_novel_id(self.current_url)
        if not novel_id:
            messagebox.showinfo("Glossary", "Could not determine the novel for this URL.")
            return

        glossary = load_glossary(novel_id)
        # Captured once at open time -- compared against the on-disk
        # value at Save time to detect whether another writer (e.g.
        # open_term_review_dialog(), which writes immediately per
        # Confirm/Reject rather than batching like this dialog) touched
        # the file while this dialog was open. See save_and_close()'s
        # merge-on-divergence logic below -- this is the actual fix for
        # the cross-dialog stale-overwrite bug documented in DESIGN.md.
        opened_updated_at = glossary.get("updated_at")
        # Work on a local copy of the term list; only written back to the
        # glossary dict (and disk) on Save, so Cancel discards cleanly.
        terms = [dict(t) for t in glossary.get("terms", [])]
        # Sources deleted via the Delete button this session -- tracked
        # separately from `terms` (which simply no longer contains them)
        # so a merge-on-divergence at Save time can still honor an
        # explicit delete even for a term that also exists, untouched, in
        # a newer on-disk snapshot -- otherwise the merge below would
        # treat "not in `terms`" as "never existed" and silently resurrect
        # it from disk instead of respecting the deletion.
        deleted_sources = set()
        # Sources actually touched this session (row visited/edited via
        # save_form_to_term(), or a newly added term) -- the merge-on-
        # divergence logic in save_and_close() only lets THIS dialog's
        # local copy win, per source, for entries in this set. Without
        # this distinction, merging `local_terms` wholesale would let
        # every term in this dialog's stale in-memory snapshot overwrite
        # the fresh on-disk copy, including terms the user never touched
        # -- silently reverting exactly the kind of concurrent write
        # (e.g. a Review Terms Confirm) this fix exists to protect,
        # just via the merge path instead of a blind save. Confirmed
        # this distinction is necessary by first shipping the merge
        # without it and reproducing the original bug through the merge
        # path itself -- not a hypothetical concern.
        edited_sources = set()
        # Mutable container (not a plain bool) so nested handlers below can
        # flip it without needing `nonlocal` in every one of them. Tracks
        # unsaved edits so Rebuild Glossary can warn before discarding them
        # (rebuild always operates on the on-disk glossary, then reloads the
        # whole dialog from it -- see rebuild_glossary()).
        dirty = {"value": False}
        # Separate from `dirty` above on purpose: `dirty` tracks in-memory
        # edits that Cancel can still discard with no disk write at all,
        # but auto-refresh (_maybe_refresh_after_glossary_edit()) must only
        # fire when something was actually written to disk -- Cancel with
        # a `dirty` session must not trigger a refresh of already-correct
        # displayed content. Set only at the three points that actually
        # call save_glossary(): save_and_close(), clear_glossary(), and a
        # successful rebuild_glossary().
        disk_write_happened = {"value": False}

        win = tk.Toplevel(self.root)
        win.title(f"Glossary - {glossary.get('title') or novel_id}")
        win.geometry("700x520")
        win.transient(self.root)
        # Modal: prevents a user from ever having open_term_review_dialog()
        # (or anything else) open and interactive at the same time as this
        # dialog, closing off the specific overlapping-dialogs reproduction
        # of the cross-dialog stale-overwrite bug (DESIGN.md) entirely, on
        # top of (not instead of) the merge-on-divergence fix in
        # save_and_close() below -- modality alone would not fix a
        # sequential case (open this dialog, something else writes to the
        # same file some other way while it's open, Save anyway), only the
        # interactive-overlap case. Not applied to open_term_review_dialog()
        # itself: that dialog already writes immediately per action, so it
        # isn't the one holding a stale snapshot, and making it modal too
        # would block the legitimate case of opening it to check current
        # state while this dialog is up, which isn't the bug.
        win.grab_set()

        def close_dialog():
            # Single close path -- called from every button that ends this
            # dialog (Save, Cancel, and indirectly Clear Glossary/Rebuild
            # Glossary's destroy-then-reopen) and from the window manager's
            # own close button (bound via WM_DELETE_WINDOW below) -- so the
            # auto-refresh check (_maybe_refresh_after_glossary_edit())
            # fires exactly once regardless of *how* the dialog closed, not
            # just for one specific button. A plain win.destroy() bound
            # directly to a button would bypass this entirely, since
            # WM_DELETE_WINDOW only fires for the OS-level close, not a
            # programmatic destroy() call from within the app.
            self._maybe_refresh_after_glossary_edit(novel_id, disk_write_happened["value"])
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close_dialog)

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Honorific handling (default):").pack(side="left")
        honorific_var = tk.StringVar(value=glossary.get("honorific_policy", HONORIFIC_POLICIES[0]))
        ttk.Combobox(top, textvariable=honorific_var, values=HONORIFIC_POLICIES, state="readonly", width=12).pack(side="left", padx=(6, 0))

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=10, pady=4)

        columns = ("source", "target", "type", "status")
        tree = ttk.Treeview(body, columns=columns, show="headings", height=12)
        for col, label, width in (("source", "Source", 130), ("target", "Target", 130), ("type", "Type", 70), ("status", "Status", 80)):
            tree.heading(col, text=label)
            tree.column(col, width=width)
        tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree_scroll.pack(side="left", fill="y")
        tree.config(yscrollcommand=tree_scroll.set)

        form = ttk.Frame(body)
        form.pack(side="left", fill="y", padx=(10, 0))

        def refresh_tree(select_index=None):
            tree.delete(*tree.get_children())
            for i, t in enumerate(terms):
                target_display = t.get("confirmed_target") or best_candidate_for_term(t) or ""
                tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(t.get("source", ""), target_display, t.get("type", TERM_TYPE_GENERAL), t.get("status", STATUS_SUGGESTED)),
                )
            if select_index is not None and 0 <= select_index < len(terms):
                tree.selection_set(str(select_index))
                tree.see(str(select_index))

        # --- Edit form, rebuilt each time the selected term's type changes ---
        form_vars = {}
        # Index of the term the form currently on screen was built for.
        # Mutable container (see `dirty` above) so `<<TreeviewSelect>>`'s
        # handler can read the *previous* selection before committing it --
        # by the time that event fires, tree.selection() already reflects
        # the *new* row, so committing against a freshly re-read
        # tree.selection() would silently save the still-displayed old
        # form values into the newly selected row's term dict instead of
        # the row the form was actually showing. See on_select_with_commit.
        displayed_index: Dict[str, Optional[int]] = {"value": None}

        # Snapshot of each field's value as build_form() initialized it for
        # the currently displayed row (post-fallback for target, since a
        # suggested term's field is pre-filled from best_candidate_for_term()
        # rather than left blank) -- save_form_to_term() diffs the live form
        # against this to tell "user actually typed something" apart from
        # "user merely selected this row and moved on." Without this check,
        # every row a user ever clicks through gets unconditionally
        # confirmed on Save (STATUS_CONFIRMED, candidates overwritten with
        # origin="user") purely from being displayed once -- confirmed live
        # against novel 375266002's real glossary before this fix landed:
        # selecting three suggested rows in sequence with zero typing, then
        # Save, flipped all three to confirmed and (pre-fallback) blanked
        # their confirmed_target and clobbered their LLM-origin candidate
        # with an empty user-origin one, permanently destroying the
        # suggestion. Keyed by field name, mirroring form_vars.
        initial_values: Dict[str, str] = {}

        def clear_form():
            for widget in form.winfo_children():
                widget.destroy()
            form_vars.clear()
            initial_values.clear()
            displayed_index["value"] = None

        def build_form(term, index):
            clear_form()
            displayed_index["value"] = index
            pad = {"padx": 4, "pady": (6, 0)}
            term_type = term.get("type", TERM_TYPE_GENERAL)
            # Same fallback as refresh_tree()'s target_display -- a
            # suggested term's field is pre-filled from its best candidate,
            # not left blank, so that pre-filled value (not "") is what
            # counts as "unchanged" for this row.
            initial_values["type"] = term_type
            initial_values["source"] = term.get("source", "")
            initial_values["target"] = term.get("confirmed_target") or best_candidate_for_term(term) or ""
            initial_values["note"] = term.get("note") or ""
            initial_values["gender"] = term.get("gender") or ""
            initial_values["pronoun_style"] = term.get("pronoun_style") or ""
            initial_values["honorific_override"] = term.get("honorific_override") or ""

            ttk.Label(form, text="Type").grid(row=0, column=0, sticky="w", **pad)
            form_vars["type"] = tk.StringVar(value=term_type)
            ttk.Combobox(form, textvariable=form_vars["type"], values=[TERM_TYPE_GENERAL, TERM_TYPE_CHARACTER], state="readonly", width=20).grid(row=0, column=1, **pad)

            ttk.Label(form, text="Source").grid(row=1, column=0, sticky="w", **pad)
            form_vars["source"] = tk.StringVar(value=term.get("source", ""))
            ttk.Entry(form, textvariable=form_vars["source"], width=22).grid(row=1, column=1, **pad)

            ttk.Label(form, text="Target").grid(row=2, column=0, sticky="w", **pad)
            form_vars["target"] = tk.StringVar(value=initial_values["target"])
            ttk.Entry(form, textvariable=form_vars["target"], width=22).grid(row=2, column=1, **pad)

            ttk.Label(form, text="Note").grid(row=3, column=0, sticky="w", **pad)
            form_vars["note"] = tk.StringVar(value=term.get("note") or "")
            ttk.Entry(form, textvariable=form_vars["note"], width=22).grid(row=3, column=1, **pad)

            next_row = 4
            # Global vocabulary reference/promotion (RETRANSLATION_DESIGN.md
            # phase 5) -- term-typed rows only, per that doc's scope
            # decision that a character name is only correct for one
            # specific story and is never globally eligible.
            if term_type == TERM_TYPE_GENERAL:
                existing_global = get_global_entry(term.get("source", ""))
                if existing_global:
                    # Same click-to-use idiom as open_word_glossary_popup()'s
                    # Google/LLM reference buttons -- a pre-fill offer, not
                    # a silent auto-fill.
                    global_target = existing_global.get("target", "")
                    ttk.Button(form, text=f"Global: {global_target}", command=lambda t=global_target: form_vars["target"].set(t)).grid(
                        row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0)
                    )
                else:
                    ttk.Label(form, text="Global: (none)", foreground="#888").grid(row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))
                next_row += 1

                if term.get("status") == STATUS_CONFIRMED:

                    def apply_globally():
                        source = form_vars["source"].get().strip()
                        target = form_vars["target"].get().strip()
                        if not source or not target:
                            messagebox.showinfo("Apply Globally", "Source and Target are both required.", parent=win)
                            return
                        upsert_global_entry(source, target, form_vars["note"].get().strip() or None)
                        messagebox.showinfo("Apply Globally", f"Saved {source!r} -> {target!r} to the global vocabulary store.", parent=win)

                    ttk.Button(form, text="Apply Globally", command=apply_globally).grid(row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))
                    next_row += 1

            if term_type == TERM_TYPE_CHARACTER:
                ttk.Label(form, text="Gender").grid(row=next_row, column=0, sticky="w", **pad)
                form_vars["gender"] = tk.StringVar(value=term.get("gender") or "")
                ttk.Combobox(form, textvariable=form_vars["gender"], values=["", "male", "female"], state="readonly", width=20).grid(row=next_row, column=1, **pad)
                next_row += 1

                ttk.Label(form, text="Pronoun / voice note").grid(row=next_row, column=0, sticky="w", **pad)
                form_vars["pronoun_style"] = tk.StringVar(value=term.get("pronoun_style") or "")
                ttk.Entry(form, textvariable=form_vars["pronoun_style"], width=22).grid(row=next_row, column=1, **pad)
                next_row += 1

                ttk.Label(form, text="Honorific override").grid(row=next_row, column=0, sticky="w", **pad)
                form_vars["honorific_override"] = tk.StringVar(value=term.get("honorific_override") or "")
                ttk.Combobox(form, textvariable=form_vars["honorific_override"], values=[""] + HONORIFIC_POLICIES, state="readonly", width=20).grid(row=next_row, column=1, **pad)
                next_row += 1

            def apply_type_change(_event=None):
                # Rebuild the form when Type changes so character-only
                # fields appear/disappear immediately, without losing the
                # source/target/note the user already typed.
                if form_vars["type"].get() != term_type:
                    save_form_to_term(index)
                    build_form(terms[index], index)

            form.grid_slaves(row=0, column=1)[0].bind("<<ComboboxSelected>>", apply_type_change)

            def save_form_to_term(idx):
                # Only treat this row as edited if some field's live value
                # actually differs from what build_form() initialized it to
                # -- merely selecting a row and moving to the next one (the
                # <<TreeviewSelect>> path, via commit_selected_form()) must
                # not silently confirm a suggested term the user never
                # touched. Confirmed live as a real bug, not hypothetical:
                # before this check existed, clicking through unconfirmed
                # rows with zero typing and then Save flipped every visited
                # row to STATUS_CONFIRMED and overwrote its LLM-origin
                # candidate with an empty user-origin one, permanently
                # losing the suggestion. Compared against initial_values
                # (not the term dict directly) since the Target field is
                # pre-filled from best_candidate_for_term() for a suggested
                # term, not blank -- the unedited state is that pre-filled
                # text, not "".
                current = {
                    "type": form_vars["type"].get(),
                    "source": form_vars["source"].get().strip(),
                    "target": form_vars["target"].get().strip(),
                    "note": form_vars["note"].get().strip(),
                }
                if current["type"] == TERM_TYPE_CHARACTER:
                    current["gender"] = form_vars["gender"].get()
                    current["pronoun_style"] = form_vars["pronoun_style"].get().strip()
                    current["honorific_override"] = form_vars["honorific_override"].get()
                if all(current[k] == initial_values.get(k, "") for k in current):
                    return

                t = terms[idx]
                # Track both the source this term had when the dialog
                # loaded it and whatever it's being renamed to (if
                # different) as "edited" -- the merge-on-divergence logic
                # in save_and_close() needs to let this dialog's copy win
                # under the *new* key, and must not treat the *old* key as
                # still protected (it no longer describes this term).
                edited_sources.add(t.get("source", ""))
                t["type"] = current["type"]
                t["source"] = current["source"]
                edited_sources.add(t["source"])
                # Editing a term in this dialog is a deliberate human action,
                # same trust level as "Highlight -> Add Term" -- confirm it
                # immediately rather than leaving it in the suggested queue.
                target = current["target"]
                t["confirmed_target"] = target
                t["status"] = STATUS_CONFIRMED
                t["candidates"] = [{"target": target, "count": 1, "origin": "user"}]
                t["note"] = current["note"] or None
                if t["type"] == TERM_TYPE_CHARACTER:
                    t["gender"] = current.get("gender") or None
                    t["pronoun_style"] = current.get("pronoun_style") or None
                    t["honorific_override"] = current.get("honorific_override") or None
                else:
                    t.pop("gender", None)
                    t.pop("pronoun_style", None)
                    t.pop("honorific_override", None)
                dirty["value"] = True

            form_vars["_save"] = save_form_to_term

        def on_select(_event=None):
            selection = tree.selection()
            if not selection:
                clear_form()
                return
            index = int(selection[0])
            build_form(terms[index], index)

        def commit_selected_form():
            # Write whatever's currently in the form back into `terms`
            # before switching selection, adding, deleting, or saving --
            # otherwise in-progress edits on the selected row are lost.
            #
            # Deliberately commits against `displayed_index` (the row
            # build_form() actually populated the form from), NOT a fresh
            # tree.selection() read. When this runs from the
            # <<TreeviewSelect>> handler (on_select_with_commit), Tk has
            # already updated tree.selection() to the *newly* clicked row
            # by the time the event fires -- re-reading it here would save
            # the still-on-screen previous term's field values into the
            # newly selected row's term dict, corrupting it before
            # build_form() even runs. displayed_index always identifies the
            # row the on-screen values actually belong to, regardless of
            # what the Treeview's selection has already moved to.
            index = displayed_index["value"]
            if index is not None and "_save" in form_vars:
                form_vars["_save"](index)

        def on_select_with_commit(event=None):
            commit_selected_form()
            on_select(event)

        tree.bind("<<TreeviewSelect>>", on_select_with_commit)

        def add_term(term_type):
            commit_selected_form()
            new_term = make_confirmed_term(term_type=term_type, source="", target="")
            if term_type == TERM_TYPE_CHARACTER:
                new_term.update(gender=None, pronoun_style=None, honorific_override=None)
            terms.append(new_term)
            dirty["value"] = True
            refresh_tree(select_index=len(terms) - 1)
            build_form(terms[-1], len(terms) - 1)

        def delete_selected():
            selection = tree.selection()
            if not selection:
                return
            index = int(selection[0])
            deleted_source = terms[index].get("source")
            if deleted_source:
                deleted_sources.add(deleted_source)
            del terms[index]
            dirty["value"] = True
            clear_form()
            refresh_tree()

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=10, pady=(4, 0))
        ttk.Button(btn_row, text="Add Term", command=lambda: add_term(TERM_TYPE_GENERAL)).pack(side="left")
        ttk.Button(btn_row, text="Add Character", command=lambda: add_term(TERM_TYPE_CHARACTER)).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="Delete", command=delete_selected).pack(side="left", padx=(6, 0))

        rebuild_status = ttk.Label(win, text="", foreground="#888")
        rebuild_status.pack(fill="x", padx=10, pady=(6, 0))

        rebuild_state = {"running": False}

        def set_dialog_controls_enabled(enabled):
            state = "normal" if enabled else "disabled"
            for widget in list(btn_row.winfo_children()) + list(bottom.winfo_children()) + [rebuild_btn]:
                widget.config(state=state)
            tree.config(selectmode="extended" if enabled else "none")

        def rebuild_glossary():
            # Rebuild always operates on the on-disk glossary (not this
            # dialog's in-memory `terms`), then reloads the whole dialog
            # from the updated file once done -- see the module-level
            # comment on `dirty` above for why. Warn first if there are
            # unsaved edits so a rebuild doesn't silently discard them.
            #
            # Routed through GlossaryCoordinator.start_rebuild()/
            # is_rebuild_running() (REFACTOR_DESIGN.md Phase 3e) instead
            # of calling build_glossary_for_novel() directly -- this is
            # the shared, coordinator-owned tracking state the
            # extraction-vs-dialog race fix depends on (a per-dialog
            # local dict, as this used to be, is invisible to
            # upsert_confirmed()/reject()/save_snapshot()/clear() calls
            # from the other two dialogs, or a second open instance of
            # this same dialog). rebuild_state["running"] below is kept
            # as a dialog-local mirror purely for this dialog's own UI
            # (disabling buttons, showing "Rebuilding..." status) --
            # GlossaryCoordinator has no widget/event-loop reference of
            # its own to drive that.
            coordinator = GlossaryCoordinator(novel_id)
            if rebuild_state["running"] or coordinator.is_rebuild_running():
                return
            if dirty["value"]:
                if not messagebox.askyesno(
                    "Rebuild Glossary",
                    "You have unsaved changes in this dialog. Rebuilding will discard them and reload from the saved glossary. Continue?",
                    parent=win,
                ):
                    return

            rebuild_state["running"] = True
            set_dialog_controls_enabled(False)
            rebuild_status.config(text="Rebuilding...")
            logger.info(f"User triggered glossary rebuild for novel {novel_id}")

            def status_cb(message):
                self.root.after(0, lambda: rebuild_status.config(text=message))

            def on_complete(error):
                rebuild_state["running"] = False

                def finish_on_ui_thread():
                    if error is not None:
                        full_trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                        messagebox.showerror("Rebuild Glossary", f"Rebuild failed:\n{full_trace}", parent=win)
                    disk_write_happened["value"] = True
                    close_dialog()
                    self.open_glossary_dialog()

                self.root.after(0, finish_on_ui_thread)

            coordinator.start_rebuild(status_cb=status_cb, on_complete=on_complete)

        rebuild_btn = ttk.Button(btn_row, text="Rebuild Glossary", command=rebuild_glossary)
        rebuild_btn.pack(side="left", padx=(12, 0))

        def clear_glossary():
            if rebuild_state["running"]:
                return
            if not messagebox.askyesno(
                "Clear Glossary",
                "This will delete all terms and reset honorific handling for this novel. This cannot be undone. Continue?",
                parent=win,
            ):
                return
            logger.info(f"User cleared glossary for novel {novel_id}")
            # Routed through GlossaryCoordinator.clear() (REFACTOR_DESIGN.md
            # Phase 3d) -- a dedicated method, not save_snapshot(), since a
            # Clear is an unconditional reset the user explicitly asked
            # for, not an edited snapshot to merge against a concurrent
            # writer. See GlossaryCoordinator.clear()'s docstring.
            GlossaryCoordinator(novel_id).clear()
            disk_write_happened["value"] = True
            close_dialog()
            self.open_glossary_dialog()
            self.set_status("Glossary cleared")

        ttk.Button(btn_row, text="Clear Glossary", command=clear_glossary).pack(side="left", padx=(6, 0))

        def save_and_close():
            commit_selected_form()
            local_terms = [t for t in terms if t.get("source")]

            # Routed through GlossaryCoordinator.save_snapshot()
            # (REFACTOR_DESIGN.md Phase 3d) instead of this dialog's own
            # reload/merge/write block -- save_snapshot() is the
            # re-check-before-write, merge-on-divergence logic originally
            # written here (the fix for the cross-dialog stale-overwrite
            # bug documented in DESIGN.md), lifted into the coordinator
            # verbatim back in Phase 3a. edited_sources/deleted_sources
            # are still tracked locally by this dialog's own
            # save_form_to_term()/delete_selected() (both still directly
            # above), since only this dialog's UI knows what the user
            # actually touched this session -- the coordinator has no way
            # to know that on its own.
            GlossaryCoordinator(novel_id).save_snapshot(
                opened_at=opened_updated_at,
                local_terms=local_terms,
                edited_sources=edited_sources,
                deleted_sources=deleted_sources,
                honorific_policy=honorific_var.get(),
            )
            disk_write_happened["value"] = True
            close_dialog()
            self.set_status("Glossary saved")

        bottom = ttk.Frame(win)
        bottom.pack(pady=(10, 10))
        ttk.Button(bottom, text="Save", command=save_and_close).pack(side="left", padx=4)
        ttk.Button(bottom, text="Cancel", command=close_dialog).pack(side="left", padx=4)

        refresh_tree()

    def open_term_review_dialog(self):
        """Open the bulk term-review screen: confirm or reject the current novel's suggested glossary terms in one sitting.

        A separate, standalone dialog from open_glossary_dialog() (the
        general term editor, which lists every term of every status and
        always confirms-on-save), not an extension of it -- deliberately.
        This dialog is scoped to exactly one purpose: review the backlog
        of unreviewed suggested terms faster than the existing one-at-a-
        time right-click flow, without conflating that with general
        term editing. Reasoning for building new rather than extending:
        open_glossary_dialog()'s Treeview shows all terms/all statuses and
        its Save button always writes STATUS_CONFIRMED on any edit -- a
        "review only the suggested backlog, with a real Reject (delete),
        candidate picker, and per-term Confirm/Reject actions" purpose
        needs a different filter, different actions, and a different
        default trust posture (nothing here is confirmed until explicitly
        confirmed) than that dialog's "edit anything, save commits
        everything" model. Building this as a second dialog keeps that
        distinction visible in the UI rather than overloading one screen
        with two different mental models.

        Deliberately one-at-a-time review, no "confirm all" bulk action --
        see this task's DESIGN.md entry for why: a bulk-confirm button
        would reintroduce exactly the "trust unreviewed model output"
        failure Section 1 of this doc documented as the original reason
        this whole redesign started (Lanchester's Law hallucination,
        mundane compounds entering the glossary unreviewed). Faster
        iteration through the list is the goal, not batch trust.

        Confirm writes through upsert_confirmed_term() (the same path the
        manual "Add to Glossary" dialog uses, from the dedup-bug fix) --
        not a third way of writing a confirmed term into the glossary.
        Reject is a real delete (removes the term from the glossary
        entirely), not a status change -- a rejected term shouldn't keep
        occupying a mask-target slot (build_mask_targets() masks anything
        that isn't STATUS_CONFIRMED, so leaving a rejected term in the
        glossary at any other status would keep it masked forever with no
        way to un-flag it). No rejection-blocklist mechanism -- a term
        rejected here can be re-suggested by a future build_glossary.py
        extraction run and reviewed again; that's an acceptable v1
        tradeoff, not an oversight (see DESIGN.md for the reasoning).
        """
        if not hasattr(self, "current_url") or not self.current_url:
            messagebox.showinfo("Review Terms", "Load a novel first.")
            return
        novel_id = _extract_novel_id(self.current_url)
        if not novel_id:
            messagebox.showinfo("Review Terms", "Could not determine the novel for this URL.")
            return

        glossary = load_glossary(novel_id)

        win = tk.Toplevel(self.root)
        win.title(f"Review Terms - {glossary.get('title') or novel_id}")
        win.geometry("760x480")
        win.transient(self.root)

        # Tracks whether at least one Confirm/Reject actually happened
        # this dialog session -- both write to disk immediately (see this
        # dialog's own docstring), unlike open_glossary_dialog()'s
        # batch-on-Save model, so unlike that dialog there is no separate
        # "in-memory dirty vs. actually written" distinction to make here:
        # any Confirm/Reject IS a disk write, so this flag alone is the
        # correct auto-refresh trigger signal.
        edited = {"value": False}

        def close_dialog():
            # Single close path -- this dialog has exactly one button
            # ("Close") plus the window manager's own close button, both
            # routed through here so the auto-refresh check
            # (_maybe_refresh_after_glossary_edit()) fires exactly once
            # per dialog session regardless of which one was used. See
            # open_glossary_dialog()'s close_dialog() for the fuller
            # rationale (same pattern, applied here for consistency).
            self._maybe_refresh_after_glossary_edit(novel_id, edited["value"])
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close_dialog)

        # reviewable_indices maps each Treeview row back to its real index
        # in glossary["terms"] -- the tree shows every not-yet-confirmed
        # term (status != STATUS_CONFIRMED, same broad rule
        # build_mask_targets() uses -- see the filter below for why),
        # since already-confirmed terms have nothing to review here. The
        # underlying list is the full, unfiltered glossary, and
        # Confirm/Reject need to mutate the right entry in it.
        reviewable_indices: List[int] = []

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("source", "type", "best_candidate", "count")
        tree = ttk.Treeview(body, columns=columns, show="headings", height=14)
        for col, label, width in (("source", "Source", 140), ("type", "Type", 70), ("best_candidate", "Best candidate", 160), ("count", "Candidates", 80)):
            tree.heading(col, text=label)
            tree.column(col, width=width)
        tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree_scroll.pack(side="left", fill="y")
        tree.config(yscrollcommand=tree_scroll.set)

        form = ttk.Frame(body)
        form.pack(side="left", fill="y", padx=(10, 0))

        empty_label = ttk.Label(win, text="No unconfirmed terms to review for this novel.", foreground="#888")

        def refresh_tree(select_index=None):
            tree.delete(*tree.get_children())
            reviewable_indices.clear()
            for i, t in enumerate(glossary.get("terms", [])):
                # Anything not confirmed, not just status == STATUS_SUGGESTED
                # -- matches build_mask_targets()'s own broader rule
                # (status != STATUS_CONFIRMED), which also catches old-shape
                # terms with no status field at all (status is None). A
                # narrower "== STATUS_SUGGESTED" check would silently hide
                # exactly the pre-Section-9-shape terms most in need of
                # review from this dialog -- confirmed live against
                # novel 375266002's real glossary, which has 9 old-shape
                # unconfirmed terms and only 1 properly-suggested one.
                if t.get("status") == STATUS_CONFIRMED:
                    continue
                reviewable_indices.append(i)
                row_id = str(len(reviewable_indices) - 1)
                best = best_candidate_for_term(t) or ""
                count = len(t.get("candidates") or [])
                tree.insert("", "end", iid=row_id, values=(t.get("source", ""), t.get("type", TERM_TYPE_GENERAL), best, count))
            if reviewable_indices:
                empty_label.pack_forget()
            else:
                empty_label.pack(fill="x", padx=10, pady=(0, 10))
            if select_index is not None and 0 <= select_index < len(reviewable_indices):
                tree.selection_set(str(select_index))
                tree.see(str(select_index))

        form_vars: Dict[str, Any] = {}

        def clear_form():
            for widget in form.winfo_children():
                widget.destroy()
            form_vars.clear()

        def build_form(row_index):
            clear_form()
            term_idx = reviewable_indices[row_index]
            term = glossary["terms"][term_idx]
            pad = {"padx": 4, "pady": (6, 0)}

            ttk.Label(form, text="Source:", foreground="#888").grid(row=0, column=0, sticky="w", **pad)
            ttk.Label(form, text=term.get("source", ""), wraplength=220, justify="left").grid(row=0, column=1, sticky="w", **pad)

            ttk.Label(form, text="Type").grid(row=1, column=0, sticky="w", **pad)
            form_vars["type"] = tk.StringVar(value=term.get("type", TERM_TYPE_GENERAL))
            # Type is editable here on purpose -- this is exactly the
            # character-vs-term misclassification problem Section 1/8
            # documents (build_glossary.py's extraction guesses a type
            # that isn't always right). Correcting it here, at review
            # time, needs no special handling beyond what Confirm already
            # does: the corrected type_var value flows straight into
            # make_confirmed_term()'s term_type argument below, same as
            # every other manual-confirm path in this file.
            ttk.Combobox(form, textvariable=form_vars["type"], values=[TERM_TYPE_GENERAL, TERM_TYPE_CHARACTER], state="readonly", width=18).grid(row=1, column=1, sticky="w", **pad)

            best = best_candidate_for_term(term) or ""
            ttk.Label(form, text="Target").grid(row=2, column=0, sticky="w", **pad)
            form_vars["target"] = tk.StringVar(value=best)
            ttk.Entry(form, textvariable=form_vars["target"], width=24).grid(row=2, column=1, sticky="w", **pad)

            candidates = term.get("candidates") or []
            next_row = 3
            if candidates:
                # Same "click to use as Target" reference pattern as
                # open_word_glossary_popup()'s Reference/Alternatives
                # section -- reused, not a new UI idiom -- ranked by count
                # (best_candidate_for_term()'s own rule) so the top pick is
                # listed first.
                ranked = sorted(candidates, key=lambda c: -c.get("count", 0))
                ttk.Label(form, text="Candidates (click to use as Target):", foreground="#888").grid(row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(10, 0))
                next_row += 1
                for c in ranked:
                    label = f"{c.get('target', '')} (x{c.get('count', 0)}, {c.get('origin', '')})"
                    ttk.Button(form, text=label, command=lambda t=c.get("target", ""): form_vars["target"].set(t)).grid(
                        row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 0)
                    )
                    next_row += 1

            def confirm_selected():
                target = form_vars["target"].get().strip()
                if not target:
                    messagebox.showinfo("Review Terms", "Target is required to confirm.", parent=win)
                    return
                new_term = make_confirmed_term(term_type=form_vars["type"].get(), source=term.get("source", ""), target=target, note=term.get("note"))
                if form_vars["type"].get() == TERM_TYPE_CHARACTER:
                    new_term.update(
                        gender=term.get("gender"),
                        pronoun_style=term.get("pronoun_style"),
                        honorific_override=term.get("honorific_override"),
                    )
                # Routed through GlossaryCoordinator (REFACTOR_DESIGN.md
                # Phase 3c) instead of calling load_glossary()/
                # upsert_confirmed_term()/save_glossary() directly -- same
                # write path the manual "Add to Glossary" dialog uses
                # (dedup-bug fix), not a third way of confirming a term.
                # The coordinator does its own independent reload/save
                # (avoiding a stale-snapshot write), so this dialog's own
                # in-memory `glossary["terms"]` is updated separately,
                # from the coordinator's returned result, purely so
                # refresh_tree() (which reads `glossary`, not disk) keeps
                # reflecting the current state without a full dialog
                # reload after every single action.
                updated_glossary = GlossaryCoordinator(novel_id).upsert_confirmed(new_term)
                glossary["terms"] = updated_glossary["terms"]
                glossary["updated_at"] = updated_glossary["updated_at"]
                edited["value"] = True
                logger.info(f"Confirmed term via review dialog for novel {novel_id}: {term.get('source')!r} -> {target!r}")
                clear_form()
                refresh_tree()
                self.set_status(f"Confirmed: {term.get('source')} -> {target}")

            def reject_selected():
                # Real delete, not a status change -- see this method's
                # docstring for why a rejected term must not linger at any
                # non-confirmed status (it would stay masked forever).
                if not messagebox.askyesno("Review Terms", f"Reject {term.get('source')!r}? This removes it from the glossary entirely.", parent=win):
                    return
                source = term.get("source", "")
                # Routed through GlossaryCoordinator.reject() (Phase 3c),
                # matched by source rather than object identity -- see
                # GlossaryCoordinator.reject()'s docstring for why identity
                # matching (this dialog's own original `t is not term`
                # filter) cannot work against a coordinator method that
                # reloads the glossary fresh internally. Same
                # in-memory-mirroring reasoning as confirm_selected() above
                # for why `glossary["terms"]` is still updated here, not
                # just left to a full dialog reload.
                updated_glossary = GlossaryCoordinator(novel_id).reject(source)
                glossary["terms"] = updated_glossary["terms"]
                glossary["updated_at"] = updated_glossary["updated_at"]
                edited["value"] = True
                logger.info(f"Rejected term via review dialog for novel {novel_id}: {source!r}")
                clear_form()
                refresh_tree()
                self.set_status(f"Rejected: {source}")

            action_row = ttk.Frame(form)
            action_row.grid(row=next_row, column=0, columnspan=2, sticky="w", padx=4, pady=(12, 0))
            ttk.Button(action_row, text="Confirm", command=confirm_selected).pack(side="left")
            ttk.Button(action_row, text="Reject", command=reject_selected).pack(side="left", padx=(6, 0))

        def on_select(_event=None):
            selection = tree.selection()
            if not selection:
                clear_form()
                return
            build_form(int(selection[0]))

        tree.bind("<<TreeviewSelect>>", on_select)

        bottom = ttk.Frame(win)
        bottom.pack(pady=(0, 10))
        ttk.Button(bottom, text="Close", command=close_dialog).pack(side="left", padx=4)

        refresh_tree()

    def prefetch(self, url):
        """Fetch+translate an episode in the background so navigating to it is instant."""
        if not url or url in self.cache or url in self._prefetching:
            return
        if load_cached_episode(url) is not None:
            return
        self._prefetching.add(url)

        def worker():
            try:
                self.fetch_and_translate(url)
            except Exception as e:
                logger.error(f"Failed to prefetch episode {url}: {e}", exc_info=True)
                print(traceback.format_exc(), file=sys.stderr)
            finally:
                self._prefetching.discard(url)

        threading.Thread(target=worker, daemon=True).start()

    def display_episode(self, url, ep):
        """Display a parsed episode and update navigation buttons.

        Args:
            url: The episode URL that was loaded.
            ep: The parsed episode dict.
        """
        self.episode = ep
        self.current_url = url
        self.url_var.set(url)
        # Only ever applies once, on the very first episode load at startup
        # when resuming a previous session -- consume it here so any later
        # navigation (Next/Prev, loading a different URL) scrolls to top as normal.
        restore_scroll_pos = self._restore_scroll_pos
        self._restore_scroll_pos = None
        self.renderer.render_text(restore_scroll_pos=restore_scroll_pos)

        self.prev_btn.state(["!disabled"] if ep["prev_url"] else ["disabled"])
        self.next_btn.state(["!disabled"] if ep["next_url"] else ["disabled"])
        self.set_status(f"Chapter: {ep['episode_title']}")
        self._update_status_bar_counts(ep)
        logger.info(f"Displayed episode: {ep['episode_title']}")

        save_reader_state(url, self.target_lang)
        self.prefetch(ep.get("next_url"))

    def _on_toolbar_right_click(self, event):
        """Right-click on the toolbar: offer the same five dialog launchers as the File/Glossary menus.

        WINDOW_REDESIGN.md Phase 3. A static menu -- no span/selection
        resolution needed, unlike _on_text_right_click(), since the
        toolbar's context doesn't vary by click position. Reuses the
        exact same bound commands the menu bar and toolbar buttons
        already use, not new wrapper functions.

        Args:
            event: The Tk button-press event.
        """
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Load Novel...", command=self.open_load_url_dialog)
        menu.add_command(label="Refresh", command=self.refresh_current_episode)
        menu.add_command(label="Glossary...", command=self.open_glossary_dialog)
        menu.add_command(label="Review Terms...", command=self.open_term_review_dialog)
        menu.add_command(label="Settings...", command=self.open_settings_dialog)
        menu.tk_popup(event.x_root, event.y_root)

    def _on_text_right_click(self, event):
        """Right-click on chapter text: offer to add the word/selection to the glossary.

        Uses the current text selection verbatim if one is active (e.g. the
        user drag-selected a multi-character name that a single click's
        word-boundary guess can't resolve on its own -- fugashi's bundled
        dictionary doesn't recognize invented character names as single
        tokens, so this is the escape hatch for that case). Otherwise falls
        back to a single-word guess at the click point: find_ja_word_at()
        for Japanese text, Tk's wordstart/wordend for English text.

        Args:
            event: The Tk button-press event.
        """
        self.text.mark_set("insert", f"@{event.x},{event.y}")

        sel_ranges = self.text.tag_ranges("sel")
        if sel_ranges:
            selected = self.text.get(sel_ranges[0], sel_ranges[1])
            span = self.renderer._span_at_index(sel_ranges[0])
            tag = span[2] if span else "original"
            source_line = span[3] if span else ""
            prefill = self._prefill_for_word(selected, tag)
        else:
            idx = self.text.index("insert")
            span = self.renderer._span_at_index(idx)
            if span is None:
                return
            _, _, tag, source_line = span
            if tag == "translated":
                word = self.text.get(f"{idx} wordstart", f"{idx} wordend").strip()
                if not word:
                    return
                prefill = self._prefill_for_word(word, tag)
            else:
                line_start = self.text.index(f"{idx} linestart")
                char_offset = len(self.text.get(line_start, idx))
                found = find_ja_word_at(source_line, char_offset)
                if found is None:
                    return
                word = source_line[found[0] : found[1]]
                prefill = self._prefill_for_word(word, tag)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Add to Glossary...", command=lambda: self.open_word_glossary_popup(*prefill, context=source_line))

        # Change Type: only offered when the resolved word is itself an
        # existing glossary term's exact source string (WINDOW_REDESIGN.md
        # Phase 4). Reuses prefill (already resolved above by the same
        # selection/word-boundary logic every other branch of this method
        # uses) rather than re-deriving the word a second time -- prefill
        # is (source_prefill, target_prefill), exactly one of which is the
        # resolved word depending on which side (original/translated) was
        # clicked, per _prefill_for_word().
        resolved_word = prefill[0] or prefill[1]
        existing_term = self._find_glossary_term_by_source(resolved_word) if resolved_word else None
        if existing_term is not None:
            type_submenu = tk.Menu(menu, tearoff=0)
            type_submenu.add_command(label="Term", command=lambda: self._change_term_type(resolved_word, TERM_TYPE_GENERAL))
            # Character (General -> Character specifically) opens a further
            # Gender submenu rather than calling _change_term_type()
            # directly -- tk.Menu.tk_popup() is non-blocking (confirmed
            # live: it posts the menu and returns immediately, the actual
            # selection is delivered later via the command= callback on
            # the app's normal event loop), so there is no synchronous
            # "ask and get an answer back" shape available here. Each
            # gender leaf command carries its own answer baked in, same
            # pattern as every other tk.Menu item in this file.
            gender_submenu = tk.Menu(type_submenu, tearoff=0)
            gender_submenu.add_command(label="Unspecified", command=lambda: self._change_term_type(resolved_word, TERM_TYPE_CHARACTER, gender=None))
            gender_submenu.add_command(label="Male", command=lambda: self._change_term_type(resolved_word, TERM_TYPE_CHARACTER, gender="male"))
            gender_submenu.add_command(label="Female", command=lambda: self._change_term_type(resolved_word, TERM_TYPE_CHARACTER, gender="female"))
            type_submenu.add_cascade(label="Character", menu=gender_submenu)
            menu.add_cascade(label="Change Type", menu=type_submenu)

        # Retranslate: only offered on original-language text, and only in
        # Interleaved mode (RETRANSLATION_DESIGN.md phase 3) -- Interleaved
        # is the only mode where _rendered_spans holds an original span
        # immediately followed by its paired translated span (see
        # _render_interleaved_content()), which _translated_span_after()
        # relies on to resolve "the current translation of this line"
        # without adding a second span-tracking structure. "Original" and
        # "Both" modes both render original text but never pair it with a
        # translated span at a resolvable position, so retranslate isn't
        # offered there for now -- a possible future extension, not
        # something this phase needs to solve.
        #
        # self.renderer.view_mode/_rendered_spans (REFACTOR_DESIGN.md
        # Phase 2): this method is a genuine hybrid per Phase 1's finding
        # (reads renderer state, but also references Group C/D dialogs) --
        # left on ReaderApp rather than forced into ReaderRenderer, since
        # its full three-way dependency can't be resolved properly until
        # Groups C/D are real components too (Phase 1 section 2).
        if tag == "original" and self.renderer.view_mode.get() == "interleaved" and span is not None:
            hint_word = (selected.strip() if sel_ranges else prefill[0]) or ""
            translated_span = self.renderer._translated_span_after(span)
            if translated_span is not None and hint_word:
                menu.add_command(
                    label="Retranslate this line...",
                    command=lambda: self.open_retranslate_popup(source_line, translated_span, hint_word),
                )

        menu.tk_popup(event.x_root, event.y_root)

    def _find_glossary_term_by_source(self, word):
        """Look up whether `word` is the exact source string of an existing glossary term for the current novel.

        WINDOW_REDESIGN.md Phase 4: shared by _on_text_right_click() (to
        decide whether to offer "Change Type...") and _change_term_type()
        (to read the term's current shape immediately before writing).
        Reuses find_glossary_term_spans() (WINDOW_REDESIGN.md Phase 1 §6
        confirmed this is the right tool -- searches every term regardless
        of status, unlike build_mask_targets()) against `word` treated as
        a one-word line, then only returns a match if some found span
        covers the word's *entire* length -- a word that merely contains a
        shorter existing term as a substring (e.g. "音夢くん" containing
        "音夢") should not be treated as itself being that shorter term.

        Args:
            word: The exact clicked/selected text to look up.

        Returns:
            The matching term dict (fresh from disk), or None if no novel
            is loaded or no term's source matches `word` exactly.
        """
        if not hasattr(self, "current_url") or not self.current_url:
            return None
        novel_id = _extract_novel_id(self.current_url)
        if not novel_id:
            return None
        glossary = load_glossary(novel_id)
        for start, end, matched_word in find_glossary_term_spans(word, glossary):
            if start == 0 and end == len(word) and matched_word == word:
                for term in glossary.get("terms", []):
                    if term.get("source") == word:
                        return term
        return None

    def _change_term_type(self, source, new_type, gender=None):
        """Change an existing glossary term's type, preserving every other field.

        WINDOW_REDESIGN.md Phase 4. Reloads the term fresh (via
        _find_glossary_term_by_source()) rather than trusting a snapshot
        captured when the right-click menu was built, matching this
        codebase's established reload-fresh-immediately-before-write
        discipline -- the glossary could have changed in the time between
        opening the context menu and clicking a submenu item.

        General -> Character: `gender` is supplied by the caller, already
        chosen via the Change Type > Character > <gender> submenu chain in
        _on_text_right_click() (a tk.Menu posts asynchronously -- see that
        method's comment on why the gender pick has to be baked into each
        leaf command rather than asked for synchronously here). Asking for
        gender at all, rather than silently leaving it unset, matters
        because gender/pronoun_style/honorific_override are confirmed
        genuinely read by format_glossary_for_prompt() and injected into
        the live translation prompt, not cosmetic. pronoun_style and
        honorific_override are still left unset regardless of `gender`:
        pronoun_style has no natural quick-pick shape (free text), and
        honorific_override already falls back to the novel-wide
        honorific_policy until someone sets it explicitly via the full
        Glossary dialog -- per WINDOW_REDESIGN.md's Phase 4 investigation,
        no honorific-suffix auto-detection exists or is attempted here.

        Character -> Term: the three character-only fields simply drop
        off by omission (upsert_confirmed_term()'s replace-the-whole-entry
        semantics) -- no prompt needed, this direction has no data-loss
        concern equivalent to the other direction. `gender` is ignored in
        this direction (always None from this method's own General-only
        call site, but this method doesn't rely on that -- it's dropped
        unconditionally whenever new_type isn't TERM_TYPE_CHARACTER).

        Args:
            source: The term's source string (dedup key for
                upsert_confirmed_term()).
            new_type: TERM_TYPE_GENERAL or TERM_TYPE_CHARACTER.
            gender: "male", "female", or None -- only applied when
                new_type is TERM_TYPE_CHARACTER.
        """
        term = self._find_glossary_term_by_source(source)
        if term is None:
            messagebox.showinfo("Change Type", "This term no longer exists in the glossary (it may have been edited or removed).")
            return
        novel_id = _extract_novel_id(self.current_url)

        new_term = dict(term)
        new_term["type"] = new_type

        if new_type == TERM_TYPE_CHARACTER:
            new_term["gender"] = gender
            new_term["pronoun_style"] = None
            new_term["honorific_override"] = None
        else:
            new_term.pop("gender", None)
            new_term.pop("pronoun_style", None)
            new_term.pop("honorific_override", None)

        GlossaryCoordinator(novel_id).upsert_confirmed(new_term)
        logger.info(f"Changed glossary term type via right-click for novel {novel_id}: {source!r} -> {new_type!r}")
        self.set_status(f"{source!r} changed to {new_type}")

    def _prefill_for_word(self, word, tag):
        """Build (source_prefill, target_prefill) for the glossary popup.

        Args:
            word: The clicked/selected text.
            tag: The text tag it came from ("original" or "translated").

        Returns:
            A (source_prefill, target_prefill) tuple -- the Japanese side
            is prefilled when the click/selection was on original text,
            the English side when it was on translated text, matching how
            the full glossary editor's Add Term already leaves the other
            side blank for the user to fill in.
        """
        if tag == "translated":
            return ("", word)
        return (word, "")

    def open_word_glossary_popup(self, source_prefill, target_prefill, context=None):
        """Open a small popup to add a glossary term/character from selected text.

        Shows reference translation guesses (Google Translate and, if
        available, the local LLM) alongside editable Source/Target/Note
        fields, and saves directly to the current novel's glossary file --
        independent of whether the full Glossary dialog is open. Takes
        effect on the next chapter load/Refresh, same as any other
        glossary edit.

        Args:
            source_prefill: Initial value for the Source field (Japanese).
            target_prefill: Initial value for the Target field (English).
            context: The source sentence the word was clicked/selected in,
                if available. Passed to explain_term() so the LLM can tell
                an ambiguous/invented character name apart from an ordinary
                word -- confirmed via live testing that without it, names
                like 桂名 get misclassified as a generic term rather than
                a character, since they carry no dictionary meaning on
                their own.
        """
        if not hasattr(self, "current_url") or not self.current_url:
            messagebox.showinfo("Add to Glossary", "Load a novel first.")
            return
        novel_id = _extract_novel_id(self.current_url)
        if not novel_id:
            messagebox.showinfo("Add to Glossary", "Could not determine the novel for this URL.")
            return

        if self._glossary_popup is not None and self._glossary_popup.winfo_exists():
            # Already open -- raise/focus it rather than stacking a second,
            # independent popup (each with its own background lookup
            # thread) on top.
            self._glossary_popup.lift()
            self._glossary_popup.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._glossary_popup = win
        win.bind("<Destroy>", lambda e: setattr(self, "_glossary_popup", None) if e.widget is win else None)
        win.title("Add to Glossary")
        win.transient(self.root)
        win.resizable(False, False)

        lookup_word = source_prefill or target_prefill

        # Fetch both reference guesses (blocking network calls) before
        # building the real form -- building/populating widgets from a
        # background thread while this window is only a bare shell led to
        # a Tkinter rendering issue where labels never painted even though
        # they were present in the widget tree. Fetching first and only
        # building the form once, fully populated, sidesteps that
        # entirely and is simpler than mutating a live window. Cached
        # per session (_word_guess_cache) so re-opening the popup for a
        # word already looked up -- e.g. the user cancelled and tried
        # again -- doesn't repeat the network round-trip.
        status_label = ttk.Label(win, text="Looking up translations..." if lookup_word else "Building form...")
        status_label.pack(padx=20, pady=20)

        # Keyed on (word, context) rather than just word -- the same surface
        # text can appear in different sentences with a different intended
        # meaning/category (e.g. a common word vs. a character's name that
        # happens to share the same kanji), so caching on word alone could
        # serve a stale classification for a different occurrence.
        cache_key = (lookup_word, context)

        def fetch_guesses():
            if cache_key in self._word_guess_cache:
                google_guess, llm_guess, explanation = self._word_guess_cache[cache_key]
                self.root.after(0, lambda: build_form(google_guess, llm_guess, explanation))
                return

            google_guess = "(nothing selected)"
            llm_guess = "(nothing selected)"
            explanation = None
            if lookup_word:
                try:
                    google_guess = translate_chunk(lookup_word, target_lang="en", source_lang="ja")
                except Exception as e:
                    logger.debug(f"Google guess lookup failed for {lookup_word!r}: {e}")
                    google_guess = "(unavailable)"

                if not check_llm_available():
                    llm_guess = "(not available)"
                else:
                    try:
                        result = llm_translate_chunk([lookup_word])
                        llm_guess = result[0] if result else "(no result)"
                    except Exception as e:
                        logger.debug(f"LLM guess lookup failed for {lookup_word!r}: {e}")
                        llm_guess = "(unavailable)"
                    explanation = explain_term(lookup_word, source_lang="ja", target_lang="en", context=context)
                self._word_guess_cache[cache_key] = (google_guess, llm_guess, explanation)
            self.root.after(0, lambda: build_form(google_guess, llm_guess, explanation))

        def build_form(google_guess, llm_guess, explanation):
            status_label.destroy()

            pad = {"padx": 10, "pady": (6, 0)}

            # Pre-select Type from the LLM's category classification when
            # available (explain_term() with sentence context reliably
            # tells an invented/ambiguous character name apart from an
            # ordinary word, confirmed via live testing) -- user can still
            # override with the radio buttons below.
            initial_type = TERM_TYPE_CHARACTER if explanation and explanation.get("category") == "character" else TERM_TYPE_GENERAL
            type_var = tk.StringVar(value=initial_type)
            type_row = ttk.Frame(win)
            type_row.pack(fill="x", **pad)
            ttk.Label(type_row, text="Type:").pack(side="left")
            ttk.Radiobutton(type_row, text="Term", variable=type_var, value=TERM_TYPE_GENERAL).pack(side="left", padx=(6, 0))
            ttk.Radiobutton(type_row, text="Character", variable=type_var, value=TERM_TYPE_CHARACTER).pack(side="left", padx=(6, 0))

            source_var = tk.StringVar(value=source_prefill)
            ttk.Label(win, text="Source (original):").pack(anchor="w", **pad)
            ttk.Entry(win, textvariable=source_var).pack(fill="x", padx=10)

            target_var = tk.StringVar(value=target_prefill)
            ttk.Label(win, text="Target (translation):").pack(anchor="w", **pad)
            ttk.Entry(win, textvariable=target_var).pack(fill="x", padx=10)

            note_var = tk.StringVar(value="")
            ttk.Label(win, text="Note:").pack(anchor="w", **pad)
            note_entry = ttk.Entry(win, textvariable=note_var)
            note_entry.pack(fill="x", padx=10)

            # Character-only fields, matching the full glossary editor's
            # Add Character fields exactly (gender/pronoun_style/
            # honorific_override) -- deliberately NOT auto-filled from the
            # LLM explanation (see EXPLAIN_TERM_PROMPT's comment on why
            # gender is left for the user to set here rather than guessed).
            char_fields = ttk.Frame(win)
            gender_var = tk.StringVar(value="")
            ttk.Label(char_fields, text="Gender:").pack(anchor="w", padx=10, pady=(6, 0))
            ttk.Combobox(char_fields, textvariable=gender_var, values=["", "male", "female"], state="readonly", width=20).pack(anchor="w", padx=10)
            pronoun_var = tk.StringVar(value="")
            ttk.Label(char_fields, text="Pronoun / voice note:").pack(anchor="w", padx=10, pady=(6, 0))
            ttk.Entry(char_fields, textvariable=pronoun_var).pack(fill="x", padx=10)
            honorific_var = tk.StringVar(value="")
            ttk.Label(char_fields, text="Honorific override:").pack(anchor="w", padx=10, pady=(6, 0))
            ttk.Combobox(char_fields, textvariable=honorific_var, values=[""] + HONORIFIC_POLICIES, state="readonly", width=20).pack(anchor="w", padx=10)

            def update_char_fields_visibility(*_args):
                if type_var.get() == TERM_TYPE_CHARACTER:
                    char_fields.pack(fill="x", after=note_entry, pady=(0, 0))
                else:
                    char_fields.pack_forget()

            type_var.trace_add("write", update_char_fields_visibility)
            update_char_fields_visibility()

            ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=(10, 4))
            ttk.Label(win, text="Reference (click to use as Target):", foreground="#888").pack(anchor="w", padx=10)
            # Real ttk.Buttons (not labels) so a guess can be applied to
            # Target with one click instead of the user retyping what's
            # already shown -- only shown when there's an actual guess to
            # offer, not for the "(unavailable)"/"(nothing selected)" cases.
            if google_guess not in ("(unavailable)", "(nothing selected)"):
                ttk.Button(win, text=f"Google: {google_guess}", command=lambda: target_var.set(google_guess)).pack(anchor="w", padx=10, pady=(2, 0))
            else:
                ttk.Label(win, text=f"Google: {google_guess}", foreground="#888").pack(anchor="w", padx=10, pady=(2, 0))
            if llm_guess not in ("(unavailable)", "(not available)", "(nothing selected)", "(no result)"):
                ttk.Button(win, text=f"LLM: {llm_guess}", command=lambda: target_var.set(llm_guess)).pack(anchor="w", padx=10, pady=(2, 0))
            else:
                ttk.Label(win, text=f"LLM: {llm_guess}", foreground="#888").pack(anchor="w", padx=10, pady=(2, 0))

            if explanation and explanation.get("meaning"):
                ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=(10, 4))
                ttk.Label(win, text="Meaning:", foreground="#888").pack(anchor="w", padx=10)
                ttk.Label(win, text=explanation["meaning"], wraplength=380, justify="left").pack(anchor="w", padx=10)

                characters = explanation.get("characters") or []
                if len(characters) > 1:
                    # Only worth showing a per-character breakdown for
                    # multi-character terms -- a single-character term's
                    # breakdown would just repeat the overall meaning.
                    ttk.Label(win, text="Characters:", foreground="#888").pack(anchor="w", padx=10, pady=(6, 0))
                    for c in characters:
                        char, char_meaning = c.get("char", ""), c.get("meaning", "")
                        if char:
                            ttk.Label(win, text=f"  {char} -- {char_meaning}", wraplength=380, justify="left").pack(anchor="w", padx=10)

                alternatives = explanation.get("alternatives") or []
                if alternatives:
                    ttk.Label(win, text="Alternatives (click to use as Target):", foreground="#888").pack(anchor="w", padx=10, pady=(6, 0))
                    for alt in alternatives:
                        word, note = alt.get("word", ""), alt.get("note", "")
                        if not word:
                            continue
                        alt_row = ttk.Frame(win)
                        alt_row.pack(fill="x", padx=10, pady=(1, 0))
                        ttk.Button(alt_row, text=word, command=lambda w=word: target_var.set(w)).pack(side="left")
                        if note:
                            ttk.Label(alt_row, text=note, foreground="#888", wraplength=280, justify="left").pack(side="left", padx=(6, 0))

            ttk.Label(
                win,
                text="Note: existing cached/translated chapters won't\nreflect this until you Refresh or reload them.",
                foreground="#888",
                justify="left",
            ).pack(anchor="w", padx=10, pady=(8, 0))

            def save_and_close():
                source = source_var.get().strip()
                target = target_var.get().strip()
                if not source:
                    messagebox.showinfo("Add to Glossary", "Source is required.", parent=win)
                    return
                new_term = make_confirmed_term(term_type=type_var.get(), source=source, target=target, note=note_var.get().strip() or None)
                if type_var.get() == TERM_TYPE_CHARACTER:
                    new_term.update(
                        gender=gender_var.get() or None,
                        pronoun_style=pronoun_var.get().strip() or None,
                        honorific_override=honorific_var.get() or None,
                    )

                # Routed through GlossaryCoordinator (REFACTOR_DESIGN.md
                # Phase 3b) instead of calling load_glossary()/
                # upsert_confirmed_term()/save_glossary() directly --
                # upsert, not merge_terms(), a human confirming this
                # source word via this dialog should replace any existing
                # entry for it (regardless of that entry's type), not
                # coexist alongside it. See upsert_confirmed_term()'s
                # docstring for the bug this fixes. A fresh coordinator is
                # constructed here rather than cached on self, matching
                # how novel_id itself is already re-derived fresh on every
                # open of this dialog rather than cached.
                GlossaryCoordinator(novel_id).upsert_confirmed(new_term)
                logger.info(f"Added glossary term via right-click for novel {novel_id}: {source!r} -> {target!r}")
                win.destroy()
                self.set_status("Term added to glossary")

            bottom = ttk.Frame(win)
            bottom.pack(pady=(10, 10))
            ttk.Button(bottom, text="Save", command=save_and_close).pack(side="left", padx=4)
            ttk.Button(bottom, text="Cancel", command=win.destroy).pack(side="left", padx=4)

        threading.Thread(target=fetch_guesses, daemon=True).start()

    def _open_remember_globally_popup(self, parent_win, hint_word, current_translation, candidate):
        """Small follow-up popup: confirm the source->target term pair to write to the global vocabulary store.

        RETRANSLATION_DESIGN.md phase 5. Triggered by "Also remember this
        for next time" on the retranslation popup's Accept -- a whole-line
        correction (candidate) is not itself a clean term mapping, so this
        asks the user to confirm/edit the actual term pair rather than
        silently deriving or misusing the whole sentence as a "target".
        Source pre-fills from hint_word (the word/phrase the user already
        flagged); Target pre-fills via _diff_single_substring() when
        unambiguous, else is left blank for the user to fill in -- a
        pre-fill, not an auto-decision, same idiom as every other
        click-to-use reference field in this file.

        Fire-and-forget from the caller's perspective: this popup's
        Save/Skip outcome never blocks or gates the outer Accept's
        existing line-apply-and-persist behavior (RETRANSLATION_DESIGN.md
        phase 4), which proceeds immediately regardless.

        Args:
            parent_win: The retranslation popup's Toplevel. NOT used as
                this popup's actual Tk parent -- accept_and_close() calls
                this method and then immediately destroys parent_win as
                part of its own existing session-apply flow, which would
                also destroy any child Toplevel of parent_win before the
                user gets to interact with it. self.root is used as the
                real parent instead, so this popup survives its caller's
                teardown; parent_win is accepted as a parameter only for
                signature clarity/future use, not actually parented to.
            hint_word: The word/phrase the user selected as the
                retranslation hint -- pre-fills Source.
            current_translation: The pre-correction translation of the
                line -- used only for the Target diff heuristic.
            candidate: The accepted, corrected whole-line translation --
                used only for the Target diff heuristic.
        """
        win = tk.Toplevel(self.root)
        win.title("Remember Globally")
        win.resizable(False, False)

        target_guess = _diff_single_substring(current_translation, candidate)

        pad = {"padx": 10, "pady": (6, 0)}
        ttk.Label(win, text="Source (original word/phrase):").pack(anchor="w", **pad)
        source_var = tk.StringVar(value=hint_word)
        ttk.Entry(win, textvariable=source_var).pack(fill="x", padx=10)

        ttk.Label(win, text="Target (corrected rendering):").pack(anchor="w", **pad)
        target_var = tk.StringVar(value=target_guess or "")
        ttk.Entry(win, textvariable=target_var).pack(fill="x", padx=10)
        if not target_guess:
            ttk.Label(win, text="(could not auto-detect -- please fill in)", foreground="#888").pack(anchor="w", padx=10)

        ttk.Label(win, text="Note (optional):").pack(anchor="w", **pad)
        note_var = tk.StringVar(value="")
        ttk.Entry(win, textvariable=note_var).pack(fill="x", padx=10)

        def save_and_close():
            source = source_var.get().strip()
            target = target_var.get().strip()
            if not source or not target:
                messagebox.showinfo("Remember Globally", "Source and Target are both required.", parent=win)
                return
            upsert_global_entry(source, target, note_var.get().strip() or None)
            win.destroy()

        bottom = ttk.Frame(win)
        bottom.pack(pady=(10, 10))
        ttk.Button(bottom, text="Save Globally", command=save_and_close).pack(side="left", padx=4)
        ttk.Button(bottom, text="Skip", command=win.destroy).pack(side="left", padx=4)

    def open_retranslate_popup(self, source_line, translated_span, hint_word):
        """Open a popup offering a hint-guided retranslation candidate for one line (RETRANSLATION_DESIGN.md phase 3).

        Same dialog pattern as open_word_glossary_popup() (a bare
        tk.Toplevel, blocking network/LLM call done in a background
        thread, form built only once the result is in) -- per the design
        doc's own locked-in decision to reuse that pattern rather than
        invent a new one. Calls the phase-2 engine,
        retranslate_line_with_hint(), which is used as-is: this task wires
        it, it doesn't change it.

        Accept **persists to the on-disk cache** (RETRANSLATION_DESIGN.md
        phase 4): it overwrites the translated_span's rendered text in the
        live tk.Text widget, updates self.renderer._rendered_spans and
        self.episode["translated_lines"][line_idx] (phase 3's fix, so the
        correction survives a same-session view-mode switch), and then
        calls save_cached_episode() so it also survives a reload/restart.
        Reuses translated_lines directly rather than a separate
        line_overrides field -- see that doc's phase 4 dated entry for why
        a second field was judged unnecessary once phase 3's actual
        mechanism was reconsidered.

        Stale-popup guard: this popup is non-modal and load_episode()/
        go_prev()/go_next() do not close it, so a user can open it, then
        navigate to a different episode, then click Accept -- at which
        point self.current_url/self.episode refer to the new episode, not
        the one this popup's correction belongs to. popup_opened_for_url/
        popup_opened_for_episode below are captured once, at open time, so
        accept_and_close() can detect this and refuse to write (neither in
        memory nor to disk) rather than writing a correction under the
        wrong cache key. See RETRANSLATION_DESIGN.md's dated finding on
        this race for the full account.

        Args:
            source_line: The Japanese source line being retranslated.
            translated_span: The (start, end, tag, source_line) tuple from
                self.renderer._rendered_spans for this line's current
                translated text -- see _translated_span_after().
            hint_word: The word/phrase the user selected in the original
                line, passed to the engine as the retranslation hint.
        """
        if self._retranslate_popup is not None and self._retranslate_popup.winfo_exists():
            # Already open -- raise/focus it rather than stacking a second,
            # independent popup (each with its own background LLM call) on
            # top. Same guard as open_word_glossary_popup(), tracked
            # separately since the two are different dialog kinds.
            self._retranslate_popup.lift()
            self._retranslate_popup.focus_force()
            return

        _, _, translated_tag, _ = translated_span
        current_translation = self.text.get(translated_span[0], translated_span[1]).rstrip("\n")

        # Captured once, at open time -- see the stale-popup guard note
        # above. Compared against self.current_url/self.episode fresh at
        # Accept time, not re-derived, since navigation may have already
        # replaced both by then.
        popup_opened_for_url = getattr(self, "current_url", None)
        popup_opened_for_episode = getattr(self, "episode", None)

        win = tk.Toplevel(self.root)
        self._retranslate_popup = win
        win.bind("<Destroy>", lambda e: setattr(self, "_retranslate_popup", None) if e.widget is win else None)
        win.title("Retranslate Line")
        win.transient(self.root)
        win.resizable(False, False)

        status_label = ttk.Label(win, text=f"Retranslating with hint {hint_word!r}...")
        status_label.pack(padx=20, pady=20)

        novel_id = _extract_novel_id(self.current_url) if getattr(self, "current_url", None) else None

        def fetch_candidate():
            glossary_text = None
            if novel_id:
                novel_glossary = load_glossary(novel_id)
                glossary_text = format_glossary_for_prompt(novel_glossary)
                global_text = format_global_vocabulary_for_prompt(load_global_vocabulary(), novel_glossary)
                if global_text:
                    glossary_text = f"{glossary_text}\n\n{global_text}" if glossary_text else global_text
            try:
                candidate = retranslate_line_with_hint(
                    source_line,
                    current_translation,
                    hint_word,
                    source_lang="ja",
                    target_lang=self.target_lang,
                    glossary_text=glossary_text,
                )
            except Exception as e:
                logger.error(f"Retranslation request errored for hint {hint_word!r}: {e}", exc_info=True)
                candidate = None
            self.root.after(0, lambda: build_form(candidate))

        def build_form(candidate):
            status_label.destroy()

            pad = {"padx": 10, "pady": (6, 0)}

            ttk.Label(win, text="Source:", foreground="#888").pack(anchor="w", **pad)
            ttk.Label(win, text=source_line, wraplength=420, justify="left").pack(anchor="w", padx=10)

            ttk.Label(win, text="Current translation:", foreground="#888").pack(anchor="w", **pad)
            ttk.Label(win, text=current_translation, wraplength=420, justify="left").pack(anchor="w", padx=10)

            ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=(10, 4))

            if candidate is None:
                # retranslate_line_with_hint() returning None is a real,
                # documented outcome (empty/whitespace model output, or a
                # request failure) -- shown as an explicit inline error,
                # not silently left blank and not a crash, so the user
                # knows to retry rather than wondering if anything happened.
                ttk.Label(
                    win,
                    text="Retranslation failed -- no candidate was returned. Try again.",
                    foreground="#a00000",
                    wraplength=420,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 4))
                bottom = ttk.Frame(win)
                bottom.pack(pady=(10, 10))
                ttk.Button(bottom, text="Retry", command=lambda: retry()).pack(side="left", padx=4)
                ttk.Button(bottom, text="Close", command=win.destroy).pack(side="left", padx=4)

                def retry():
                    for child in list(win.winfo_children()):
                        child.destroy()
                    retry_status = ttk.Label(win, text=f"Retranslating with hint {hint_word!r}...")
                    retry_status.pack(padx=20, pady=20)
                    nonlocal status_label
                    status_label = retry_status
                    threading.Thread(target=fetch_candidate, daemon=True).start()

                return

            ttk.Label(win, text=f"Candidate (hint: {hint_word}):", foreground="#888").pack(anchor="w", **pad)
            ttk.Label(win, text=candidate, wraplength=420, justify="left", foreground="#1a7a1a").pack(anchor="w", padx=10)

            remember_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(win, text="Also remember this for next time", variable=remember_var).pack(anchor="w", padx=10, pady=(10, 0))

            # Best-effort UI hint, not a guarantee -- reflects staleness as
            # of this render only, does not re-poll while the popup sits
            # open and idle (e.g. the user navigates away and back without
            # this form ever re-rendering). accept_and_close()'s own check,
            # run fresh at click time, is the actual authoritative gate;
            # this is only a courtesy so Accept doesn't look clickable when
            # it's already known (as of render time) to be inert.
            is_stale = self.current_url != popup_opened_for_url or self.episode is not popup_opened_for_episode
            if is_stale:
                ttk.Label(
                    win,
                    text="This correction is for a different chapter and can't be saved.",
                    foreground="#a00000",
                    wraplength=420,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(8, 0))
            else:
                ttk.Label(
                    win,
                    text="Note: Accept saves this correction to the episode cache.",
                    foreground="#888",
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(8, 0))

            def accept_and_close():
                # Authoritative check, re-evaluated fresh at click time --
                # not reused from is_stale above, since that was only
                # correct as of this form's render and the popup may have
                # sat open for a while since then. See this method's
                # docstring for the full account of why this race matters
                # now that Accept writes to disk. Routed through
                # verify_before_write() (safe_persistence.py): the
                # captured marker is the (url, episode) pair below,
                # reload_current() re-reads both fresh, markers_match()
                # reproduces the exact != / is not comparison this guard
                # always used, and on_divergence() is this skip-and-warn
                # logic, verbatim, returning the _STALE sentinel so the
                # caller below can tell "diverged" apart from "proceed".
                def reload_current() -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
                    return (self.current_url, self.episode)

                def markers_match(captured: Tuple[Optional[str], Optional[Dict[str, Any]]], current: Tuple[Optional[str], Optional[Dict[str, Any]]]) -> bool:
                    captured_url, captured_episode = captured
                    current_url, current_episode = current
                    return current_url == captured_url and current_episode is captured_episode

                def on_divergence(current_marker: Tuple[Optional[str], Optional[Dict[str, Any]]], local_data: None) -> object:
                    current_url, _ = current_marker
                    logger.warning(
                        f"Retranslation accepted but the displayed episode changed since this popup was opened "
                        f"(opened for {popup_opened_for_url!r}, now on {current_url!r}) -- "
                        f"skipping both the in-memory and on-disk write to avoid saving under the wrong cache key"
                    )
                    return _STALE_POPUP_SENTINEL

                outcome = verify_before_write(
                    captured_marker=(popup_opened_for_url, popup_opened_for_episode),
                    reload_current=reload_current,
                    on_divergence=on_divergence,
                    local_data=None,
                    markers_match=markers_match,
                )
                if outcome is _STALE_POPUP_SENTINEL:
                    win.destroy()
                    self.set_status("Retranslation not saved -- you navigated to a different chapter")
                    return

                if remember_var.get():
                    self._open_remember_globally_popup(win, hint_word, current_translation, candidate)

                start, end, _, _ = translated_span
                self.text.config(state="normal")
                self.text.delete(start, end)
                self.text.insert(start, candidate + "\n", translated_tag)
                new_end = self.text.index(f"{start}+{len(candidate) + 1}c")
                # self.renderer._rendered_spans/_translated_line_index_by_span
                # (REFACTOR_DESIGN.md Phase 2): these tracking structures are
                # ReaderRenderer-owned now -- written here via the explicit
                # back-reference rather than left pointing at a stale/
                # orphaned attribute on ReaderApp that no longer exists.
                idx = self.renderer._rendered_spans.index(translated_span)
                self.renderer._rendered_spans[idx] = (start, new_end, translated_tag, source_line)

                # Write through to the shared episode dict (not just the
                # live widget/_rendered_spans above) so the correction
                # survives a view-mode switch within the same session --
                # render_text() always rebuilds from self.episode fresh on
                # every mode change, so anything not written here is
                # silently lost the moment the user switches modes.
                line_idx = self.renderer._translated_line_index_by_span.pop((start, end), None)
                persisted = False
                if line_idx is not None and self.episode is not None:
                    translated_lines = self.episode.get("translated_lines")
                    if translated_lines is not None and 0 <= line_idx < len(translated_lines):
                        translated_lines[line_idx] = candidate
                        self.renderer._translated_line_index_by_span[(start, new_end)] = line_idx
                        # Phase 4: persist to the on-disk cache immediately
                        # (same "instant reload-then-save" trigger already
                        # established for GlossaryCoordinator/
                        # global_vocabulary.py) -- reuses translated_lines
                        # directly, the same field a normal translation
                        # populates, rather than a new line_overrides field.
                        # self.current_url is re-read here (not
                        # popup_opened_for_url) since the guard above
                        # already confirmed they're equal at this point.
                        save_cached_episode(self.current_url, self.episode)
                        persisted = True
                    else:
                        logger.warning(
                            f"Retranslation accepted but translated_lines index {line_idx} out of range ({len(translated_lines) if translated_lines is not None else 'n/a'}) -- in-memory episode not updated, correction not saved"
                        )
                else:
                    logger.warning("Retranslation accepted but no translated_lines index found for this span -- in-memory episode not updated, correction not saved")

                if persisted:
                    logger.info(f"Retranslation accepted and saved for line: {source_line!r} -> {candidate!r}")
                    self.set_status("Retranslation saved")
                else:
                    logger.info(f"Retranslation accepted (not saved -- see prior warning) for line: {source_line!r} -> {candidate!r}")
                    self.set_status("Retranslation applied for this session (not saved)")
                win.destroy()

            bottom = ttk.Frame(win)
            bottom.pack(pady=(10, 10))
            accept_btn = ttk.Button(bottom, text="Accept", command=accept_and_close)
            accept_btn.pack(side="left", padx=4)
            if is_stale:
                accept_btn.state(["disabled"])
            ttk.Button(bottom, text="Discard", command=win.destroy).pack(side="left", padx=4)

        threading.Thread(target=fetch_candidate, daemon=True).start()

    def go_prev(self):
        """Navigate to the previous episode if available."""
        if self.episode and self.episode["prev_url"]:
            self.load_episode(self.episode["prev_url"])

    def go_next(self):
        """Navigate to the next episode if available."""
        if self.episode and self.episode["next_url"]:
            self.load_episode(self.episode["next_url"])


def main():
    """Entry point for the Alphapolis reader application."""
    setup_logging()
    target_lang = sys.argv[2] if len(sys.argv) > 2 else "en"

    restore_scroll_pos = None
    if len(sys.argv) < 2:
        state = load_reader_state()
        start_url = state.get("url")
        target_lang = state.get("target_lang", target_lang)
        restore_scroll_pos = state.get("scroll_pos")
        if not start_url:
            print("Usage: python alphapolis_reader.py <episode_url> [target_lang]")
            sys.exit(1)
        print(f"No URL given -- resuming last-read episode: {start_url}")
    else:
        start_url = sys.argv[1]

    try:
        browser = BrowserWorker()
    except Exception as e:
        full_trace = traceback.format_exc()
        logger.error(f"Failed to start browser worker: {e}", exc_info=True)
        print(full_trace, file=sys.stderr)
        # Show it in a window too, in case this was launched without a
        # visible console (e.g. double-clicked rather than run from a shell).
        err_root = tk.Tk()
        err_root.title("Startup Error")
        err_root.geometry("700x400")
        text = tk.Text(err_root, wrap="word", font=("Courier", 10), fg="#a00000")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        text.insert("end", full_trace)
        text.config(state="disabled")
        ttk.Button(err_root, text="Close", command=err_root.destroy).pack(pady=(0, 8))
        err_root.mainloop()
        sys.exit(1)

    root = tk.Tk()
    app = ReaderApp(root, browser, start_url, target_lang, restore_scroll_pos=restore_scroll_pos)

    def on_close():
        if hasattr(app, "current_url"):
            scroll_pos = app.text.yview()[0]
            save_reader_state(app.current_url, app.target_lang, scroll_pos=scroll_pos)
        browser.close()
        root.destroy()

    def on_sigint(signum, frame):
        # Ctrl-C: Tk's mainloop doesn't handle SIGINT on its own, so without
        # this the KeyboardInterrupt just propagates out of mainloop() as an
        # unhandled traceback and browser.close() (killing the Chromium
        # subprocess) never runs.
        root.after(0, on_close)

    signal.signal(signal.SIGINT, on_sigint)

    def keep_alive():
        # Tk's mainloop only returns control to the Python interpreter (where
        # queued signals actually get delivered) when an event wakes it up.
        # If the window is unfocused and idle, that can not happen for a long
        # time, so Ctrl-C appears to do nothing until the window is clicked.
        # A no-op timer firing regularly forces that wakeup unconditionally.
        root.after(200, keep_alive)

    keep_alive()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
