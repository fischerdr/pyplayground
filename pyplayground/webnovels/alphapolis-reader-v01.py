#!/usr/bin/env python3
"""alphapolis_reader.py.

Version 2.0, created 2026-07-22, author dfischer

Desktop reader for Alphapolis novels. Fetches episode pages with a real
headless browser (required -- plain HTTP requests get served an empty
202 "challenge" response by the site's AWS WAF bot-mitigation, confirmed
via direct testing), extracts the chapter text via the #novelBody
selector (confirmed from real page source), translates it with Google's
free translate endpoint, and displays it in a Tkinter window with
Previous/Next navigation driven by the episode list embedded in the
page's own `app-cover-data` JSON script tag.

Setup:
    pip install playwright beautifulsoup4 requests pillow
    playwright install chromium

Usage:
    python alphapolis_reader.py "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089"
    python alphapolis_reader.py "<url>" es      # translate to Spanish instead of English
"""

import sys
import json
import time
import queue
import signal
import hashlib
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import requests
from bs4 import BeautifulSoup

from pyplayground.utils.config_utils import load_json_config, save_json_config

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
MAX_CHUNK_CHARS = 150  # keep encoded URLs well under length limits
BASE_URL = "https://www.alphapolis.co.jp"

STATE_DIR = Path.home() / ".config" / "alphapolis_reader"
STATE_FILE = "state.json"
CACHE_DIR = Path.home() / ".cache" / "alphapolis_reader"

LIGHT_PALETTE = {"bg": "#ffffff", "fg": "#000000", "original": "#333333", "translated": "#1a56c4"}
DARK_PALETTE = {"bg": "#1e1e1e", "fg": "#e0e0e0", "original": "#c9c9c9", "translated": "#7aa2f7"}

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

CACHE_SCHEMA_VERSION = 2  # bump whenever the episode dict shape changes


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def load_cached_episode(url: str) -> dict:
    path = _cache_path(url)
    if not path.exists():
        return None
    episode = load_json_config(path.stem, config_dir=path.parent)
    if episode.get("_cache_schema_version") != CACHE_SCHEMA_VERSION:
        return None  # stale format from an older version of this script
    return episode


def save_cached_episode(url: str, episode: dict) -> None:
    episode = dict(episode, _cache_schema_version=CACHE_SCHEMA_VERSION)
    path = _cache_path(url)
    save_json_config(episode, path.stem, config_dir=path.parent)


def load_reader_state() -> dict:
    try:
        return load_json_config(STATE_FILE, config_dir=STATE_DIR)
    except FileNotFoundError:
        return {}


def save_reader_state(url: str, target_lang: str) -> None:
    save_json_config({"url": url, "target_lang": target_lang}, STATE_FILE, config_dir=STATE_DIR)


def _image_cache_path(image_url: str) -> Path:
    digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()
    ext = Path(image_url.split("?")[0]).suffix or ".img"
    return CACHE_DIR / "images" / f"{digest}{ext}"


def load_cached_image(image_url: str) -> bytes:
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
    def __init__(self):
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
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self.startup_error = RuntimeError(
                "Playwright isn't installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n\n"
                f"Original error: {e}"
            )
            self._ready.set()
            return

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                    ),
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
                self.startup_error = RuntimeError(
                    "Failed to launch Chromium via Playwright:\n" + traceback.format_exc()
                )
                self._ready.set()
            else:
                self._responses.put(("error", traceback.format_exc()))

    def fetch(self, url: str, timeout: float = 60.0) -> str:
        self._requests.put(url)
        status, payload = self._responses.get(timeout=timeout)
        if status == "error":
            raise RuntimeError("Browser fetch failed:\n" + payload)
        return payload

    def close(self):
        self._requests.put(None)
        self.join(timeout=10)


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------
def _resolve_image_url(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    return src


def _extract_content(body) -> list:
    """Walk the novel body in document order, yielding text lines and images
    as they actually appear, so illustrations stay next to the paragraphs
    they belong to instead of being flattened away by get_text()."""
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
    params = {"client": "gtx", "sl": source_lang, "tl": target_lang, "dt": "t", "q": text}
    resp = requests.get(TRANSLATE_ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return "".join(seg[0] for seg in data[0])


def translate_lines(lines, target_lang="en", progress_cb=None) -> list:
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


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class ReaderApp:
    def __init__(self, root, browser, start_url, target_lang="en"):
        self.root = root
        self.browser = browser
        self.target_lang = target_lang
        self.episode = None
        self.cache = {}
        self.font_size = 12
        self.image_width = 400
        self.dark_mode = False
        self.font_family = self._pick_default_font()
        self.line_height = 1.3  # multiplier on font_size, converted to pixel spacing
        self.paragraph_spacing = 12  # pixels between paragraphs
        self.page_width_pct = 100  # percent of the text widget's available width
        self.text_align = "left"  # left, center, right, justify(fallback to left)
        self.view_mode = tk.StringVar(value="both")
        self._prefetching = set()
        self._photo_images = {}

        root.title("Alphapolis Reader")
        root.geometry("900x700")

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", padx=8, pady=6)

        self.prev_btn = ttk.Button(toolbar, text="< Previous", command=self.go_prev)
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(toolbar, text="Next >", command=self.go_next)
        self.next_btn.pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        for value, label in (("original", "Original"), ("translated", "Translated"), ("both", "Both")):
            ttk.Radiobutton(
                toolbar, text=label, value=value, variable=self.view_mode, command=self.render_text
            ).pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="A-", width=3, command=self.decrease_font).pack(side="left")
        ttk.Button(toolbar, text="A+", width=3, command=self.increase_font).pack(side="left", padx=(2, 0))
        ttk.Button(toolbar, text="Dark", command=self.toggle_dark_mode).pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Img-", width=4, command=self.decrease_image_width).pack(side="left")
        ttk.Button(toolbar, text="Img+", width=4, command=self.increase_image_width).pack(side="left", padx=(2, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Load Novel...", command=self.open_load_url_dialog).pack(side="left")
        ttk.Button(toolbar, text="Settings...", command=self.open_settings_dialog).pack(side="left", padx=(6, 0))

        self.status_label = ttk.Label(toolbar, text="")
        self.status_label.pack(side="left", padx=12)

        url_bar = ttk.Frame(root)
        url_bar.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(url_bar, text="URL:").pack(side="left")
        self.url_var = tk.StringVar(value="")
        self.url_entry = ttk.Entry(url_bar, textvariable=self.url_var, state="readonly")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.text = tk.Text(root, wrap="word", padx=16, pady=12, borderwidth=0, highlightthickness=0)
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
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

    def apply_appearance(self):
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
        self.text.tag_configure(
            "heading", font=(self.font_family, self.font_size + 4, "bold"), spacing3=self.paragraph_spacing, foreground=palette["fg"]
        )
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
        self._apply_page_width()

    def _apply_page_width(self):
        self.root.update_idletasks()
        total_width = self.text.winfo_width() or 900
        margin = int(total_width * (1 - self.page_width_pct / 100) / 2)
        self.text.configure(padx=max(margin, 8))

    def increase_font(self):
        self.font_size = min(self.font_size + 1, 32)
        self.apply_appearance()

    def decrease_font(self):
        self.font_size = max(self.font_size - 1, 8)
        self.apply_appearance()

    def increase_image_width(self):
        self.image_width = min(self.image_width + 100, 1200)
        self._photo_images.clear()
        self.render_text()

    def decrease_image_width(self):
        self.image_width = max(self.image_width - 100, 100)
        self._photo_images.clear()
        self.render_text()

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.apply_appearance()

    def open_load_url_dialog(self):
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
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("360x360")
        win.transient(self.root)

        pad = {"padx": 10, "pady": (10, 2)}

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
            win.destroy()
            self.apply_appearance()
            self.render_text()

        btns = ttk.Frame(win)
        btns.pack(pady=(14, 10))
        ttk.Button(btns, text="Apply", command=apply_and_close).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=4)

    def set_status(self, msg):
        self.status_label.config(text=msg)
        self.root.update_idletasks()

    def show_error(self, full_trace: str):
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
        html = self.browser.fetch(url)
        ep = parse_episode(html)
        ep["translated_lines"] = translate_lines(ep["lines"], self.target_lang, progress_cb=progress_cb)
        title_lines = translate_lines([ep["title"], ep["episode_title"]], self.target_lang)
        ep["translated_title"], ep["translated_episode_title"] = title_lines
        for item in ep["content"]:
            if item["type"] == "image":
                try:
                    fetch_image_bytes(item["src"])
                except Exception:
                    print(traceback.format_exc(), file=sys.stderr)
        self.cache[url] = ep
        save_cached_episode(url, ep)
        return ep

    def load_episode(self, url):
        self.set_status("Loading...")
        self.prev_btn.state(["disabled"])
        self.next_btn.state(["disabled"])

        def progress_cb(done, total):
            self.root.after(0, lambda: self.set_status(f"Translating... {done}/{total}"))

        def worker():
            try:
                ep = self.fetch_and_translate(url, progress_cb=progress_cb)
                self.root.after(0, lambda: self.display_episode(url, ep))
            except Exception:
                full_trace = traceback.format_exc()
                print(full_trace, file=sys.stderr)  # always visible in the console too
                self.root.after(0, lambda: self.show_error(full_trace))
                self.root.after(0, lambda: self.set_status("Error"))

        threading.Thread(target=worker, daemon=True).start()

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
        self.episode = ep
        self.current_url = url
        self.url_var.set(url)
        self.render_text()

        self.prev_btn.state(["!disabled"] if ep["prev_url"] else ["disabled"])
        self.next_btn.state(["!disabled"] if ep["next_url"] else ["disabled"])
        self.set_status(f"Chapter: {ep['episode_title']}")

        save_reader_state(url, self.target_lang)
        self.prefetch(ep.get("next_url"))

    def _make_photo_image(self, src: str):
        """Load (from cache/network) and decode an episode image, scaled to
        fit the text widget's width. Returns None on any failure so a broken
        image never blocks the rest of the chapter from rendering."""
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
                self.text.insert("end", item["text"] + "\n", tag)

    def _render_translated_content(self, ep, tag):
        translated_lines = ep.get("translated_lines", [])
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
                self.text.insert("end", line + "\n", tag)
                line_idx += 1

    def render_text(self):
        ep = self.episode
        if ep is None:
            return
        mode = self.view_mode.get()
        self.text.delete("1.0", "end")

        if mode in ("original", "both"):
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
            self._render_translated_content(ep, "translated")
        self.text.see("1.0")

    def go_prev(self):
        if self.episode and self.episode["prev_url"]:
            self.load_episode(self.episode["prev_url"])

    def go_next(self):
        if self.episode and self.episode["next_url"]:
            self.load_episode(self.episode["next_url"])


def main():
    target_lang = sys.argv[2] if len(sys.argv) > 2 else "en"

    if len(sys.argv) < 2:
        state = load_reader_state()
        start_url = state.get("url")
        target_lang = state.get("target_lang", target_lang)
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
    app = ReaderApp(root, browser, start_url, target_lang)

    def on_close():
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
