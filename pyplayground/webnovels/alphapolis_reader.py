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
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from pyplayground.utils.config_utils import load_json_config, save_json_config
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.webnovels.build_glossary import build_glossary_for_novel
from pyplayground.webnovels.glossary import (
    DEFAULT_HONORIFIC_POLICY,
    HONORIFIC_POLICIES,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    build_mask_targets,
    format_glossary_for_prompt,
    load_glossary,
    make_confirmed_term,
    merge_terms,
    save_glossary,
    update_candidate_counts,
)
from pyplayground.webnovels.ja_tokenize import find_ja_word_at
from pyplayground.webnovels.llm_translate import BACKEND_GOOGLE, BACKEND_LLM, DEFAULT_BACKEND, TranslatedLine, check_llm_available, explain_term
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


def _extract_content(body) -> list:
    """Walk the novel body in document order, yielding text lines and images.

    Images are captured as they actually appear, so illustrations stay
    next to the paragraphs they belong to instead of being flattened
    away by get_text().

    Args:
        body: The BeautifulSoup body element to parse.

    Returns:
        List of dicts with type (text/image) and content fields.
    """
    content = []
    for node in body.descendants:
        if getattr(node, "name", None) == "img":
            src = node.get("src") or node.get("data-src")
            if src:
                content.append({"type": "image", "src": _resolve_image_url(src)})
        elif isinstance(node, str):
            parent_name = getattr(node.parent, "name", None)
            if parent_name in ("script", "style", "noscript", "iframe", "template"):
                continue
            text = node.strip()
            if text:
                content.append({"type": "text", "text": text})
    return content


def parse_episode(html: str) -> dict:
    """Parse an episode page HTML and extract title, author, content, and navigation.

    Args:
        html: The raw page HTML string.

    Returns:
        Dict with title, author, episode_title, lines, content, prev_url, next_url.

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

    title = title_tag.get_text(strip=True) if title_tag else ""
    author = author_tag.get_text(strip=True) if author_tag else ""
    episode_title = episode_title_tag.get_text(strip=True) if episode_title_tag else ""

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


def translate_lines(lines, target_lang="en", backend=BACKEND_GOOGLE, glossary_text=None, progress_cb=None) -> list:
    """Translate a list of text lines, chunking to respect API limits.

    Args:
        lines: List of text lines to translate.
        target_lang: Target language code (default: en).
        backend: Translation backend ('google' or 'llm').
        glossary_text: Optional pre-formatted glossary text (LLM backend only;
            ignored for Google, which has no mechanism to honor it).
        progress_cb: Optional callback(done, total) for progress updates.

    Returns:
        List of translated text lines.
    """
    if backend == BACKEND_LLM:
        return llm_translate_lines(lines, target_lang=target_lang, glossary_text=glossary_text, progress_cb=progress_cb)

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
        True. A line with mask_targets but needs_review=False (the term
        spliced back in cleanly) is intentionally excluded -- nothing to
        review there.
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


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
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
        self.cache = {}
        self._restore_scroll_pos = restore_scroll_pos
        # (start_index, end_index, tag, source_line) per rendered paragraph,
        # rebuilt on every render_text() call -- lets a right-click resolve
        # back to which source Japanese line a click/selection came from,
        # even when the rendered/tagged text is the English translation.
        self._rendered_spans = []
        # (start_index, end_index) -> ([masked source word(s)], source_line),
        # populated only by _render_translated_content_from_translated_lines()
        # for needs_review=True lines -- lets _on_needs_review_click() resolve
        # a click to the specific term (and its Japanese source sentence, for
        # explain_term() context) to pre-fill in the Add-to-Glossary dialog.
        # Rebuilt on every render_text() call, same lifecycle as
        # _rendered_spans.
        self._review_terms_by_span = {}
        # (word, context) -> (google_guess, llm_guess, explanation),
        # populated by open_word_glossary_popup()'s background lookup.
        # Session-only (not persisted) -- avoids repeating a network
        # round-trip if the user reopens the popup for the same word in
        # the same sentence (e.g. after Cancel). Keyed with context, not
        # just the word, since the same surface text can mean different
        # things (or be a name vs. not) depending on the sentence.
        self._word_guess_cache = {}

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
        self.view_mode = tk.StringVar(value=settings.get("view_mode", "translated"))
        self._prefetching = set()
        self._photo_images = {}
        # True while a load_episode() worker thread is running. Prevents
        # overlapping loads -- confirmed possible via rapid clicks on
        # Previous/Next or the <Left>/<Right> key bindings (keyboard repeat
        # fires go_prev()/go_next() directly, bypassing the toolbar buttons'
        # disabled state entirely). Concurrent loads meant multiple
        # simultaneous LLM translation requests hitting the same
        # llama-server slots, which is suspected to have contributed to
        # scrambled/misaligned translated output.
        self._loading = False

        available_fonts = self._available_fonts()
        self.font_family = saved_font_family if saved_font_family in available_fonts else self._pick_default_font()

        root.title("Alphapolis Reader")
        # Widened from 900 -> 990 (Refresh button) -> 1090 (Glossary... button)
        # to keep the toolbar from clipping Settings... off the right edge.
        root.geometry("1090x700")

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", padx=8, pady=6)

        self.prev_btn = ttk.Button(toolbar, text="< Previous", command=self.go_prev)
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(toolbar, text="Next >", command=self.go_next)
        self.next_btn.pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        for value, label in (("original", "Original"), ("translated", "Translated"), ("both", "Both"), ("interleaved", "Interleaved")):
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.view_mode, command=self._on_view_mode_change).pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="A-", width=3, command=self.decrease_font).pack(side="left")
        ttk.Button(toolbar, text="A+", width=3, command=self.increase_font).pack(side="left", padx=(2, 0))
        ttk.Button(toolbar, text="Dark", command=self.toggle_dark_mode).pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Img-", width=4, command=self.decrease_image_width).pack(side="left")
        ttk.Button(toolbar, text="Img+", width=4, command=self.increase_image_width).pack(side="left", padx=(2, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Load Novel...", command=self.open_load_url_dialog).pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=self.refresh_current_episode).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Glossary...", command=self.open_glossary_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Settings...", command=self.open_settings_dialog).pack(side="left", padx=(6, 0))

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
        self.text.tag_bind("needs_review", "<Button-1>", self._on_needs_review_click)
        self.apply_appearance()

        self.prev_btn.state(["disabled"])
        self.next_btn.state(["disabled"])

        root.bind("<Left>", lambda e: self.go_prev())
        root.bind("<Right>", lambda e: self.go_next())
        root.bind("<Prior>", lambda e: self.text.yview_scroll(-1, "pages"))
        root.bind("<Next>", lambda e: self.text.yview_scroll(1, "pages"))
        root.bind("<Control-equal>", lambda e: self.increase_font())
        root.bind("<Control-minus>", lambda e: self.decrease_font())

        self.load_episode(start_url)

    def _pick_default_font(self) -> str:
        available = self._available_fonts()
        for candidate in FONT_CANDIDATES:
            if candidate in available:
                return candidate
        return DEFAULT_FONT_FALLBACK

    def _available_fonts(self) -> set:
        import tkinter.font as tkfont

        return set(tkfont.families())

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
        """Persist current display settings (font, sizing, mode) to state."""
        try:
            update_reader_state(
                font_size=self.font_size,
                image_width=self.image_width,
                dark_mode=self.dark_mode,
                font_family=self.font_family,
                line_height=self.line_height,
                paragraph_spacing=self.paragraph_spacing,
                page_width_pct=self.page_width_pct,
                text_align=self.text_align,
                view_mode=self.view_mode.get(),
            )
        except Exception as e:
            logger.debug(f"Failed to save display settings: {e}")

    def apply_appearance(self):
        """Apply current appearance settings (colors, font, spacing) to the GUI."""
        palette = DARK_PALETTE if self.dark_mode else LIGHT_PALETTE
        # line_height is a multiplier on the font's natural line height, the
        # same convention as CSS line-height. 1.0 = tightest (no extra space
        # added); each +1.0 above that adds roughly one more font_size worth
        # of gap between lines.
        line_spacing = max(int(self.font_size * (self.line_height - 1.0)), 0)
        justify = "center" if self.text_align == "center" else "right" if self.text_align == "right" else "left"

        self.root.configure(bg=palette["bg"])
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
        self.root.update_idletasks()
        total_width = self.text.winfo_width() or 900
        margin = int(total_width * (1 - self.page_width_pct / 100) / 2)
        self.text.configure(padx=max(margin, 8))

    def increase_font(self):
        """Increase the font size by 1, up to a maximum of 32."""
        self.font_size = min(self.font_size + 1, 32)
        self.apply_appearance()
        self._save_settings()

    def decrease_font(self):
        """Decrease the font size by 1, down to a minimum of 8."""
        self.font_size = max(self.font_size - 1, 8)
        self.apply_appearance()
        self._save_settings()

    def increase_image_width(self):
        """Increase the image display width by 100 pixels, up to 1200px."""
        self.image_width = min(self.image_width + 100, 1200)
        self._photo_images.clear()
        self.render_text()
        self._save_settings()

    def decrease_image_width(self):
        """Decrease the image display width by 100 pixels, down to 100px."""
        self.image_width = max(self.image_width - 100, 100)
        self._photo_images.clear()
        self.render_text()
        self._save_settings()

    def toggle_dark_mode(self):
        """Toggle between light and dark color palettes."""
        self.dark_mode = not self.dark_mode
        self.apply_appearance()
        self._save_settings()

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
        font_var = tk.StringVar(value=self.font_family)
        font_choices = [f for f in FONT_CANDIDATES if f in self._available_fonts()]
        if self.font_family not in font_choices:
            font_choices.insert(0, self.font_family)
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

        line_height_var = tk.DoubleVar(value=self.line_height)
        make_slider("Line Height", line_height_var, 1.0, 2.5, resolution=0.1)

        paragraph_spacing_var = tk.IntVar(value=self.paragraph_spacing)
        make_slider("Paragraph Spacing (px)", paragraph_spacing_var, 0, 40)

        page_width_var = tk.IntVar(value=self.page_width_pct)
        make_slider("Page Width (%)", page_width_var, 40, 100)

        ttk.Label(win, text="Text Alignment").pack(anchor="w", **pad)
        align_var = tk.StringVar(value=self.text_align)
        align_row = ttk.Frame(win)
        align_row.pack(anchor="w", padx=10)
        for value, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            ttk.Radiobutton(align_row, text=label, value=value, variable=align_var).pack(side="left")

        def apply_and_close():
            self.font_family = font_var.get()
            self.line_height = line_height_var.get()
            self.paragraph_spacing = paragraph_spacing_var.get()
            self.page_width_pct = page_width_var.get()
            self.text_align = align_var.get()
            self.backend = backend_var.get()
            self._save_backend()
            self._save_settings()
            win.destroy()
            self.apply_appearance()
            self.render_text()

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
        """Fetch+translate an episode, checking memory and disk caches first."""
        if url in self.cache:
            return self.cache[url]
        cached = load_cached_episode(url)
        if cached is not None:
            self.cache[url] = cached
            return cached
        logger.info(f"Fetching and translating episode: {url} (backend={self.backend})")

        glossary_text = None
        glossary = None
        novel_id = None
        if self.backend == BACKEND_LLM:
            novel_id = _extract_novel_id(url)
            if novel_id:
                glossary = load_glossary(novel_id)
                glossary_text = format_glossary_for_prompt(glossary)

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
            translated = translate_lines_with_masking(ep["lines"], mask_targets, self.target_lang, glossary_text=glossary_text, progress_cb=progress_cb)
            ep["translated_lines"] = [t.text for t in translated]
            ep["needs_review_flags"] = [t.needs_review for t in translated]
        else:
            ep["translated_lines"] = translate_lines(ep["lines"], self.target_lang, backend=self.backend, glossary_text=glossary_text, progress_cb=progress_cb)
            ep["needs_review_flags"] = [False] * len(ep["translated_lines"])

        # Count-building loop (DESIGN.md Section 12): same guard as masking
        # above -- only when the LLM backend actually loaded a glossary.
        # Google Translate never produces a "candidate" to count against
        # (no glossary was even consulted for it), and there's nothing to
        # persist if novel_id never resolved.
        if glossary is not None and novel_id is not None:
            updated_glossary = update_candidate_counts(ep["lines"], ep["translated_lines"], glossary, needs_review_flags=ep["needs_review_flags"])
            save_glossary(novel_id, updated_glossary)

        title_lines = translate_lines([ep["title"], ep["episode_title"]], self.target_lang, backend=self.backend, glossary_text=glossary_text)
        ep["translated_title"], ep["translated_episode_title"] = title_lines
        for item in ep["content"]:
            if item["type"] == "image":
                try:
                    fetch_image_bytes(item["src"])
                except Exception:
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
            except Exception:
                full_trace = traceback.format_exc()
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
        # Work on a local copy of the term list; only written back to the
        # glossary dict (and disk) on Save, so Cancel discards cleanly.
        terms = [dict(t) for t in glossary.get("terms", [])]
        # Mutable container (not a plain bool) so nested handlers below can
        # flip it without needing `nonlocal` in every one of them. Tracks
        # unsaved edits so Rebuild Glossary can warn before discarding them
        # (rebuild always operates on the on-disk glossary, then reloads the
        # whole dialog from it -- see rebuild_glossary()).
        dirty = {"value": False}

        win = tk.Toplevel(self.root)
        win.title(f"Glossary - {glossary.get('title') or novel_id}")
        win.geometry("700x520")
        win.transient(self.root)

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
                tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(t.get("source", ""), t.get("confirmed_target") or "", t.get("type", TERM_TYPE_GENERAL), t.get("status", STATUS_SUGGESTED)),
                )
            if select_index is not None and 0 <= select_index < len(terms):
                tree.selection_set(str(select_index))
                tree.see(str(select_index))

        # --- Edit form, rebuilt each time the selected term's type changes ---
        form_vars = {}

        def clear_form():
            for widget in form.winfo_children():
                widget.destroy()
            form_vars.clear()

        def build_form(term, index):
            clear_form()
            pad = {"padx": 4, "pady": (6, 0)}
            term_type = term.get("type", TERM_TYPE_GENERAL)

            ttk.Label(form, text="Type").grid(row=0, column=0, sticky="w", **pad)
            form_vars["type"] = tk.StringVar(value=term_type)
            ttk.Combobox(form, textvariable=form_vars["type"], values=[TERM_TYPE_GENERAL, TERM_TYPE_CHARACTER], state="readonly", width=20).grid(row=0, column=1, **pad)

            ttk.Label(form, text="Source").grid(row=1, column=0, sticky="w", **pad)
            form_vars["source"] = tk.StringVar(value=term.get("source", ""))
            ttk.Entry(form, textvariable=form_vars["source"], width=22).grid(row=1, column=1, **pad)

            ttk.Label(form, text="Target").grid(row=2, column=0, sticky="w", **pad)
            form_vars["target"] = tk.StringVar(value=term.get("confirmed_target") or "")
            ttk.Entry(form, textvariable=form_vars["target"], width=22).grid(row=2, column=1, **pad)

            ttk.Label(form, text="Note").grid(row=3, column=0, sticky="w", **pad)
            form_vars["note"] = tk.StringVar(value=term.get("note") or "")
            ttk.Entry(form, textvariable=form_vars["note"], width=22).grid(row=3, column=1, **pad)

            next_row = 4
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
                t = terms[idx]
                t["type"] = form_vars["type"].get()
                t["source"] = form_vars["source"].get().strip()
                # Editing a term in this dialog is a deliberate human action,
                # same trust level as "Highlight -> Add Term" -- confirm it
                # immediately rather than leaving it in the suggested queue.
                target = form_vars["target"].get().strip()
                t["confirmed_target"] = target
                t["status"] = STATUS_CONFIRMED
                t["candidates"] = [{"target": target, "count": 1, "origin": "user"}]
                t["note"] = form_vars["note"].get().strip() or None
                if t["type"] == TERM_TYPE_CHARACTER:
                    t["gender"] = form_vars["gender"].get() or None
                    t["pronoun_style"] = form_vars["pronoun_style"].get().strip() or None
                    t["honorific_override"] = form_vars["honorific_override"].get() or None
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
            selection = tree.selection()
            if selection and "_save" in form_vars:
                form_vars["_save"](int(selection[0]))

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
            if rebuild_state["running"]:
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

            def worker():
                try:
                    build_glossary_for_novel(novel_id, status_cb=status_cb)
                except Exception as e:
                    full_trace = traceback.format_exc()
                    logger.error(f"Glossary rebuild failed for novel {novel_id}: {e}", exc_info=True)
                    print(full_trace, file=sys.stderr)
                    self.root.after(0, lambda: messagebox.showerror("Rebuild Glossary", f"Rebuild failed:\n{full_trace}", parent=win))
                finally:
                    rebuild_state["running"] = False

                    def reload_dialog():
                        win.destroy()
                        self.open_glossary_dialog()

                    self.root.after(0, reload_dialog)

            threading.Thread(target=worker, daemon=True).start()

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
            glossary["terms"] = []
            glossary["honorific_policy"] = DEFAULT_HONORIFIC_POLICY
            glossary["honorific_policy_user_set"] = False
            glossary["context_notes"] = ""
            glossary["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_glossary(novel_id, glossary)
            win.destroy()
            self.open_glossary_dialog()
            self.set_status("Glossary cleared")

        ttk.Button(btn_row, text="Clear Glossary", command=clear_glossary).pack(side="left", padx=(6, 0))

        def save_and_close():
            commit_selected_form()
            glossary["terms"] = [t for t in terms if t.get("source")]
            glossary["honorific_policy"] = honorific_var.get()
            glossary["honorific_policy_user_set"] = True
            save_glossary(novel_id, glossary)
            win.destroy()
            self.set_status("Glossary saved")

        bottom = ttk.Frame(win)
        bottom.pack(pady=(10, 10))
        ttk.Button(bottom, text="Save", command=save_and_close).pack(side="left", padx=4)
        ttk.Button(bottom, text="Cancel", command=win.destroy).pack(side="left", padx=4)

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
            except Exception:
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
        self.render_text(restore_scroll_pos=restore_scroll_pos)

        self.prev_btn.state(["!disabled"] if ep["prev_url"] else ["disabled"])
        self.next_btn.state(["!disabled"] if ep["next_url"] else ["disabled"])
        self.set_status(f"Chapter: {ep['episode_title']}")

        save_reader_state(url, self.target_lang)
        self.prefetch(ep.get("next_url"))

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
        except Exception:
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
        correspond. Reuses the existing "original"/"translated" tags
        (and, for the translated half, "needs_review" when that data is
        available) -- no new rendering path, no new tag.

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

            line_tag = "needs_review" if review_aware and needs_review_flags[line_idx] else translated_tag
            start = self.text.index("end-1c")
            self.text.insert("end", translated_line + "\n", line_tag)
            self._rendered_spans.append((start, self.text.index("end-1c"), line_tag, source_line))

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
            novel_id = _extract_novel_id(self.current_url) if getattr(self, "current_url", None) else None
            mask_targets = build_mask_targets(ep.get("lines", []), load_glossary(novel_id)) if novel_id else []
            self._render_translated_content_from_translated_lines(ep, tag, translated_lines, mask_targets)
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

    def _render_translated_content_from_translated_lines(self, ep, tag, translated_lines, mask_targets):
        """Render content using TranslatedLine output (needs_review-aware) instead of plain strings.

        Sibling to _render_translated_content(), which reads
        ep["translated_lines"] (plain List[str]) -- this instead takes the
        List[TranslatedLine] that translate_chunk_with_masking() produces
        directly, so a needs_review=True line gets a distinct "needs_review"
        tag (see apply_appearance()) instead of the plain "translated" tag,
        reusing the same Tk tag-over-character-range mechanism as every
        other span (DESIGN.md Section 7) rather than a separate rendering
        path.

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
            mask_targets: The (line_idx, word) list that produced
                translated_lines, for needs-review click pre-fill lookup
                (see build_review_term_map()).
        """
        review_terms = build_review_term_map(translated_lines, mask_targets)
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
                    line_tag = "needs_review" if translated.needs_review else tag
                else:
                    line_text = item["text"]
                    line_tag = tag
                # "end-1c", not "end" -- see _render_content()'s comment on
                # the same pattern for why.
                start = self.text.index("end-1c")
                self.text.insert("end", line_text + "\n", line_tag)
                end = self.text.index("end-1c")
                self._rendered_spans.append((start, end, line_tag, item["text"]))
                if line_idx in review_terms:
                    # item["text"] (the Japanese source), not line_text (the
                    # rendered/translated line) -- open_word_glossary_popup()'s
                    # context param needs the source sentence for
                    # explain_term()'s disambiguation, same as the existing
                    # right-click flow's source_line (see _span_at_index()).
                    self._review_terms_by_span[(start, end)] = (review_terms[line_idx], item["text"])
                line_idx += 1

    def _on_needs_review_click(self, event):
        """Click on a needs_review-tagged span: open Add-to-Glossary pre-filled with the flagged term.

        Reuses the existing open_word_glossary_popup() dialog (the same
        one used by the right-click flow) rather than a new one, per
        DESIGN.md Section 6. Pre-fills Source with the masked term that
        triggered needs_review on this line; Target is left blank -- the
        raw source word was spliced back into the line as a fallback (see
        llm_translate.splice_terms()), not offered as a translation guess,
        so prefilling Target with it would misrepresent an untranslated
        placeholder as a proposed English target.

        A needs-review line can have more than one flagged term (multiple
        masked words on the same line); this opens the dialog for the
        first one -- consistent with the existing right-click flow, which
        also resolves to a single word per click, not a batch action.

        Args:
            event: The Tk button-press event.
        """
        idx = self.text.index(f"@{event.x},{event.y}")
        for (start, end), (words, source_line) in self._review_terms_by_span.items():
            if self.text.compare(start, "<=", idx) and self.text.compare(idx, "<", end):
                self.open_word_glossary_popup(words[0], "", context=source_line)
                return

    def _on_view_mode_change(self):
        """Handle the Original/Translated/Both radio buttons: re-render and persist."""
        self.render_text()
        self._save_settings()

    def render_text(self, restore_scroll_pos=None):
        """Render the current episode content in the text widget.

        Args:
            restore_scroll_pos: Fraction (0.0-1.0) to scroll to after
                rendering, instead of scrolling to the top. Used only when
                resuming a previous session to the exact spot left off.
        """
        ep = self.episode
        if ep is None:
            return
        mode = self.view_mode.get()
        self.text.delete("1.0", "end")
        self._rendered_spans = []
        self._review_terms_by_span = {}

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
            span = self._span_at_index(sel_ranges[0])
            tag = span[2] if span else "original"
            source_line = span[3] if span else ""
            prefill = self._prefill_for_word(selected, tag)
        else:
            idx = self.text.index("insert")
            span = self._span_at_index(idx)
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
        menu.tk_popup(event.x_root, event.y_root)

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

        win = tk.Toplevel(self.root)
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

                glossary = load_glossary(novel_id)
                glossary["terms"] = merge_terms(glossary.get("terms", []), [new_term])
                glossary["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_glossary(novel_id, glossary)
                logger.info(f"Added glossary term via right-click for novel {novel_id}: {source!r} -> {target!r}")
                win.destroy()
                self.set_status("Term added to glossary")

            bottom = ttk.Frame(win)
            bottom.pack(pady=(10, 10))
            ttk.Button(bottom, text="Save", command=save_and_close).pack(side="left", padx=4)
            ttk.Button(bottom, text="Cancel", command=win.destroy).pack(side="left", padx=4)

        threading.Thread(target=fetch_guesses, daemon=True).start()

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
    except Exception:
        full_trace = traceback.format_exc()
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
