#!/usr/bin/env python3
"""
novelfire_library.py
--------------------
Scrapes your NovelFire library (bookmarks) and saves:
  - novelfire_library.json   (machine-readable)
  - novelfire_library.md     (human-readable)

Credentials are read from environment variables:
  NOVELFIRE_EMAIL    - your login email
  NOVELFIRE_PASSWORD - your login password

Optional env vars:
  NOVELFIRE_MAX_PAGES      - max library pages to scrape (default: 10)
  NOVELFIRE_OUTPUT_DIR     - directory to write output files (default: current dir)
  NOVELFIRE_DEBUG          - set to "1" to enable verbose debug output + HTML dumps
  NOVELFIRE_FETCH_DETAILS  - set to "0" to skip per-novel detail fetching
  NOVELFIRE_DETAIL_DELAY   - seconds between detail page requests (default: 0.4)
  NOVELFIRE_HEADLESS       - set to "0" to show the browser window during login (default: 1)

Auth strategy:
  Playwright (Chromium) handles the Cloudflare JS challenge and login.
  It extracts the session + __cf_clearance cookies and hands them to a
  requests.Session for all subsequent scraping — faster and lighter than
  keeping the browser open.

Setup:
  pip install requests beautifulsoup4 playwright
  playwright install chromium

Usage:
  export NOVELFIRE_EMAIL="you@example.com"
  export NOVELFIRE_PASSWORD="yourpassword"
  python3 novelfire_library.py
"""

import json
import logging
import os
import sys
import textwrap
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import requests  # type: ignore[import-untyped]
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PWTimeoutError
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------

if not PLAYWRIGHT_AVAILABLE:
    # Warn early — user will get a cleaner message than an ImportError mid-run
    print(
        "WARNING: playwright not installed.\n" "  Run: pip install playwright && playwright install chromium\n",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# Logging — level controlled by NOVELFIRE_DEBUG env var
# ---------------------------------------------------------------------------
DEBUG_MODE = os.environ.get("NOVELFIRE_DEBUG", "0").strip() == "1"

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("novelfire")

# Silence noisy third-party libs unless in debug mode
if not DEBUG_MODE:
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
else:
    # Full HTTP wire-level info from urllib3 in debug mode
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://novelfire.net"
LOGIN_IFRAME_URL = f"{BASE_URL}/account/login"  # iframe that renders the login form (CSRF source)
LOGIN_AJAX_URL = f"{BASE_URL}/loginAjax"  # jQuery AJAX POST endpoint (confirmed from modal.min.js)
LIBRARY_URL = f"{BASE_URL}/account/library"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": BASE_URL,
}

RETRY_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds between retries
PAGE_DELAY = 1.5  # seconds between library page requests

# HTML dump directory (created only in debug mode)
DEBUG_DUMP_DIR = Path("./tmp/novelfire_debug_dumps")

# Show browser window during Playwright login? Default headless (no window).
# Set NOVELFIRE_HEADLESS=0 to watch the browser — useful for debugging CF challenges.
HEADLESS = os.environ.get("NOVELFIRE_HEADLESS", "1").strip() != "0"


# ---------------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------------


def _dump_html(label: str, html: str) -> None:
    """Write raw HTML to a file for offline inspection (debug mode only)."""
    if not DEBUG_MODE:
        return
    DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = label.replace("/", "_").replace("?", "_").replace("=", "_")
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    path = DEBUG_DUMP_DIR / f"{ts}_{safe_label}.html"
    path.write_text(html, encoding="utf-8")
    log.debug("[DUMP] HTML saved → %s (%d bytes)", path, len(html))


def _dump_cookies(session: requests.Session) -> None:
    """Log all session cookies (debug mode only)."""
    if not DEBUG_MODE:
        return
    cookies = dict(session.cookies)
    if cookies:
        log.debug(
            "[COOKIES] Session cookies:\n%s",
            json.dumps(
                {k: v[:40] + "…" if len(v) > 40 else v for k, v in cookies.items()},
                indent=2,
            ),
        )
    else:
        log.debug("[COOKIES] No session cookies found — login may have failed silently.")


def _dump_response_info(label: str, resp: requests.Response) -> None:
    """Log HTTP response metadata (debug mode only)."""
    if not DEBUG_MODE:
        return
    log.debug(
        "[HTTP] %s → status=%d  url=%s  content-type=%s  length=%d",
        label,
        resp.status_code,
        resp.url,
        resp.headers.get("Content-Type", "unknown"),
        len(resp.content),
    )
    if resp.history:
        log.debug(
            "[HTTP] Redirect chain: %s",
            " → ".join(f"{r.status_code} {r.url}" for r in resp.history),
        )


def _inspect_soup_structure(label: str, soup: BeautifulSoup) -> None:
    """
    Print a structural summary of the parsed HTML to help identify correct
    CSS selectors when the site layout is unknown (debug mode only).
    """
    if not DEBUG_MODE:
        return

    from collections import Counter

    log.debug("[SOUP] %s — tag inventory:", label)
    tag_counts = Counter(t.name for t in soup.find_all(True))
    log.debug("[SOUP]   tag counts: %s", dict(tag_counts.most_common(20)))

    log.debug("[SOUP]   unique class combos on div/li/article/section:")
    seen_classes: set[tuple[str, ...]] = set()
    for tag in soup.find_all(["div", "li", "article", "section"]):
        classes_val = tag.get("class", [])  # type: ignore[arg-type]
        classes = tuple(str(c) if classes_val else [] for c in classes_val) if classes_val else ()
        if classes and classes not in seen_classes:
            seen_classes.add(classes)  # type: ignore[arg-type]
            snippet = tag.get_text(separator=" ", strip=True)[:80]
            log.debug("[SOUP]     <%s class=%s>  →  %s", tag.name, list(classes), snippet)
        if len(seen_classes) >= 50:
            log.debug("[SOUP]     … (truncated at 50 unique class combos)")
            break

    book_links = soup.select("a[href*='/book/']")
    log.debug("[SOUP]   <a href*='/book/'> found: %d", len(book_links))
    for a in book_links[:8]:
        log.debug("[SOUP]     href=%-60s  text=%s", a.get("href"), a.get_text(strip=True)[:60])


def _log_card_parse(idx: int, card: Any, title: str, url: str, summary: str, chapter: str) -> None:
    """Log per-card parse results (debug mode only)."""
    if not DEBUG_MODE:
        return
    log.debug(
        "[CARD #%02d]  tag=<%s class=%s>\n" "             title  : %s\n" "             url    : %s\n" "             chapter: %s\n" "             summary: %s",
        idx,
        card.name,
        card.get("class", []),
        title,
        url,
        chapter,
        textwrap.shorten(summary, 100),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_env(key: str, required: bool = True) -> Optional[str]:
    val = os.environ.get(key, "").strip()
    if required and not val:
        log.error("Required environment variable '%s' is not set.", key)
        sys.exit(1)
    return val or None


def _fetch_with_retry(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """GET a URL with retry/backoff; exits on repeated failure."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            log.debug("[HTTP] GET %s (attempt %d/%d)", url, attempt, RETRY_ATTEMPTS)
            resp = session.get(url, headers=HEADERS, timeout=30, **kwargs)
            _dump_response_info(url, resp)
            resp.raise_for_status()
            return resp

        except requests.HTTPError as exc:
            log.warning(
                "HTTP %s on attempt %d/%d → %s",
                exc.response.status_code if exc.response else "?",
                attempt,
                RETRY_ATTEMPTS,
                url,
            )
            if exc.response is not None and DEBUG_MODE:
                log.debug("[HTTP] Error body (first 500 chars):\n%s", exc.response.text[:500])

        except requests.ConnectionError as exc:
            log.warning(
                "Connection error on attempt %d/%d for %s: %s",
                attempt,
                RETRY_ATTEMPTS,
                url,
                exc,
            )

        except requests.Timeout:
            log.warning("Timeout on attempt %d/%d for %s", attempt, RETRY_ATTEMPTS, url)

        except requests.RequestException as exc:
            log.warning(
                "Request error on attempt %d/%d for %s: %s",
                attempt,
                RETRY_ATTEMPTS,
                url,
                exc,
            )

        if attempt < RETRY_ATTEMPTS:
            log.info("  Retrying in %ds …", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    log.error("All %d attempts failed for %s — aborting.", RETRY_ATTEMPTS, url)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cloudflare + Auth  (Playwright → requests handoff)
# ---------------------------------------------------------------------------


def _playwright_login(email: str, password: str) -> dict[str, str]:
    """
    Use a real Chromium browser via Playwright to:
      1. Load the homepage — Cloudflare JS challenge runs transparently
      2. Trigger the login modal and submit credentials via the real UI
      3. Wait for /loginAjax to return {"status": 200}
      4. Extract ALL cookies (session + __cf_clearance + XSRF-TOKEN)
      5. Return them as a dict for injection into requests.Session

    The browser is closed immediately after — requests handles everything else.

    HEADLESS=True  → invisible (default, good for cron)
    HEADLESS=False → visible window, useful for debugging CF challenges
    """
    if not PLAYWRIGHT_AVAILABLE:
        log.error("Playwright is not installed.\n" "  Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    log.info("Launching Playwright Chromium (headless=%s) …", HEADLESS)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",  # hide webdriver flag
            ],
        )

        # Use a realistic viewport + locale to pass basic bot heuristics
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Chicago",
            user_agent=HEADERS["User-Agent"],
            java_script_enabled=True,
        )
        page = ctx.new_page()

        # ── Step 1: load homepage (triggers CF JS challenge if present) ───────
        log.info("[PW] Loading homepage …")
        page.goto(f"{BASE_URL}/home", wait_until="networkidle", timeout=30_000)
        log.debug("[PW] Homepage loaded: %s", page.url)

        if DEBUG_MODE:
            page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_01_home.png"))
            DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)

        # ── Step 2: open login modal (two-stage UI) ───────────────────────────
        # Stage 1: nav LOGIN → modal with "LOG IN WITH GOOGLE" + "LOG IN WITH EMAIL"
        # Stage 2: click "LOG IN WITH EMAIL" → email/password form expands
        log.info("[PW] Opening login modal …")
        try:
            page.click("a.login.button", timeout=8_000)
            page.wait_for_selector("text=LOG IN WITH EMAIL", timeout=8_000)
            log.debug("[PW] Modal opened — selecting email login method …")
        except PWTimeoutError:
            log.error("[PW] Login modal did not open after clicking LOGIN.\n" "  Try NOVELFIRE_HEADLESS=0 to watch what happens.")
            if DEBUG_MODE:
                page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_error_no_modal.png"))
            browser.close()
            sys.exit(1)

        if DEBUG_MODE:
            page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_02_modal_stage1.png"))

        # Stage 2: click "LOG IN WITH EMAIL" to reveal email/password form
        try:
            page.click("text=LOG IN WITH EMAIL", timeout=5_000)
            page.wait_for_selector(".user_login input[type=email]", timeout=8_000)
            log.debug("[PW] Email form visible.")
        except PWTimeoutError:
            log.error("[PW] Email form did not appear after clicking 'LOG IN WITH EMAIL'.\n" "  Try NOVELFIRE_HEADLESS=0 to watch what happens.")
            if DEBUG_MODE:
                page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_error_no_email_form.png"))
            browser.close()
            sys.exit(1)

        if DEBUG_MODE:
            page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_02_modal_stage2.png"))

        # ── Step 3: fill credentials ──────────────────────────────────────────
        log.info("[PW] Filling credentials …")
        page.fill(".user_login input[type=email]", email)
        page.fill(".user_login input[type=password]", password)
        time.sleep(0.5)  # brief pause so JS input handlers register before submit

        # ── Step 4: intercept /loginAjax response ────────────────────────────
        # The response listener races against the AJAX call — it may fire before
        # the response body is available, returning {}.
        # Strategy: register listener, click, then explicitly wait for the
        # /loginAjax response via page.expect_response() for a reliable capture.
        login_status = {}

        # The LOGIN element is an <a> tag with onclick="loginAjax()", NOT a <button>
        # Confirmed from pw_modal_dom.html:
        #   <a class="button btn-modal" onclick="loginAjax()">Login</a>
        log.debug("[PW] Clicking LOGIN and waiting for /loginAjax response …")
        with page.expect_response(lambda r: "/loginAjax" in r.url, timeout=15_000) as resp_info:
            page.click(".user_login a[onclick*='loginAjax']", timeout=10_000)

        # expect_response blocks until the response is fully received
        try:
            ajax_resp = resp_info.value
            login_status["body"] = ajax_resp.json()
            log.debug("[PW] /loginAjax response: %s", login_status["body"])
        except Exception as exc:
            log.warning("[PW] Could not parse /loginAjax response: %s", exc)

        # Wait for page to settle post-login
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PWTimeoutError:
            log.warning("[PW] networkidle timeout after login — proceeding.")

        if DEBUG_MODE:
            page.screenshot(path=str(DEBUG_DUMP_DIR / "pw_03_post_login.png"))

        # ── Step 5: verify login ──────────────────────────────────────────────
        # Primary check: /loginAjax JSON status
        # Fallback: if status is empty/ambiguous, the session cookie check in
        # login() will catch it — don't abort on empty response here.
        body = login_status.get("body", {})
        status_val = str(body.get("status", "")) if isinstance(body, dict) else ""
        log.debug("[PW] /loginAjax status_val=%r  full body=%s", status_val, body)

        if status_val and status_val not in ("200", "1", "true", "success", "ok"):
            # We got a response but it explicitly indicates failure
            msg = body.get("msg", body.get("message", body.get("error", str(body))))
            log.error(
                "[PW] Login rejected by server (status=%r): %s\n" "  → Check NOVELFIRE_EMAIL / NOVELFIRE_PASSWORD",
                status_val,
                msg,
            )
            browser.close()
            sys.exit(1)

        if status_val:
            log.info("[PW] Login confirmed via /loginAjax (status=%s)", status_val)
        else:
            log.info("[PW] /loginAjax status not captured — will verify via session cookie.")

        # ── Step 6: extract all cookies ───────────────────────────────────────
        raw_cookies = ctx.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}
        log.debug("[PW] Extracted %d cookies: %s", len(cookies), list(cookies.keys()))

        cf_cookie = cookies.get("__cf_clearance", "")
        if cf_cookie:
            log.info("[PW] __cf_clearance cookie acquired ✓")
        else:
            log.warning("[PW] __cf_clearance not found — Cloudflare may not have challenged.")

        browser.close()
        log.info("[PW] Browser closed. Handing off to requests session.")
        return cookies


def login(email: str, password: str) -> requests.Session:
    """
    Hybrid auth flow:
      1. Playwright Chromium handles Cloudflare challenge + modal login
      2. Cookies extracted and injected into a requests.Session
      3. All subsequent HTTP is done via requests (fast, lightweight)
    """
    # Get cookies from Playwright
    cookies = _playwright_login(email, password)

    # Build a requests session with those cookies
    session = requests.Session()
    session.headers.update(HEADERS)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="novelfire.net")

    log.debug("[SESSION] Injected cookies: %s", list(cookies.keys()))

    # ── Verify session via /account/library ───────────────────────────────────
    log.info("Verifying session via /account/library …")
    try:
        verify = session.get(
            LIBRARY_URL + "?page=1",
            headers={**HEADERS, "Accept-Encoding": "identity"},
            timeout=20,
            allow_redirects=True,
        )
        _dump_response_info("GET /account/library (verify)", verify)
        _dump_html("library_verify", verify.text)
    except requests.RequestException as exc:
        log.error("Session verification GET failed: %s", exc)
        sys.exit(1)

    final_url = verify.url.rstrip("/")
    if final_url in (f"{BASE_URL}/home", BASE_URL, f"{BASE_URL}/"):
        log.error(
            "Session invalid — /account/library redirected to %s\n"
            "  The Playwright login may have succeeded but the session cookie\n"
            "  wasn't transferred correctly. Try NOVELFIRE_HEADLESS=0 to inspect.",
            verify.url,
        )
        sys.exit(1)

    log.info("Session verified ✓  (landed on: %s)", verify.url)
    return session


# ---------------------------------------------------------------------------
# Library scraping
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# HTML structure (confirmed from live library page, v11.0.9):
#
#   <li class="trow">                          ← one novel per row
#     <div class="tcol cover-td">...</div>     ← cover image (ignored)
#     <div class="tcol sub">
#       <div class="tsubcol novel-title">
#         <a href="/book/SLUG">TITLE</a>
#       </div>
#       <div class="tsubcol">                  ← progress (no extra class)
#         <span class="chprog">3229 / 3539 (91.2%)</span>
#       </div>
#       <div class="tsubcol last-read">
#         <a class="text1row" href="/book/SLUG/chapter-N">CHAPTER NAME</a>
#       </div>
#     </div>
#   </li>
#
# Summary is NOT present on the library page (table view only).
# ---------------------------------------------------------------------------


def _parse_library_page(html: str, page_num: int) -> list[dict[str, str]]:
    """Parse one page of /account/library and return a list of novel dicts."""
    soup = BeautifulSoup(html, "html.parser")

    if DEBUG_MODE:
        _inspect_soup_structure(f"library_page_{page_num}", soup)

    cards = soup.select("li.trow")
    log.debug("[PARSE] Page %d: li.trow → %d cards", page_num, len(cards))

    if not cards:
        log.warning(
            "[PARSE] Page %d: zero li.trow cards found.\n"
            "  This usually means you have reached the last page (expected).\n"
            "  If this is page 1, the site layout may have changed.\n"
            "  → Run with NOVELFIRE_DEBUG=1 and inspect dump in %s/",
            page_num,
            DEBUG_DUMP_DIR,
        )
        _dump_html(f"library_page_{page_num}_ZERO_CARDS", html)
        return []

    items = []
    for idx, card in enumerate(cards, 1):
        # ── title + novel URL ─────────────────────────────────────────────────
        title_div = card.select_one("div.tsubcol.novel-title")
        title_a = title_div.select_one("a") if title_div else None
        title = title_a.get_text(strip=True) if title_a else "Unknown Title"
        href_val = title_a.get("href", "") if title_a else ""
        href = str(href_val) if href_val else ""
        novel_url = (BASE_URL + href) if href else ""

        # ── last-read chapter ─────────────────────────────────────────────────
        lread_div = card.select_one("div.tsubcol.last-read")
        chapter_a = lread_div.select_one("a.text1row") if lread_div else None
        current_chapter = chapter_a.get_text(strip=True) if chapter_a else ""

        # ── reading progress (e.g. "3229 / 3539 (91.2%)") ────────────────────
        prog_div = card.select_one("div.tsubcol:not(.novel-title):not(.last-read)")
        chprog = prog_div.select_one(".chprog") if prog_div else None
        progress = chprog.get_text(separator=" ", strip=True) if chprog else (prog_div.get_text(strip=True) if prog_div else "")
        # Strip leading "Progress:" label if present
        progress = progress.replace("Progress:", "").strip()

        # ── chapter URL (direct link to where you left off) ───────────────────
        chapter_href_val = chapter_a.get("href", "") if chapter_a else ""
        chapter_href = str(chapter_href_val) if chapter_href_val else ""
        chapter_url = (BASE_URL + chapter_href) if chapter_href else ""

        _log_card_parse(idx, card, title, novel_url, "", current_chapter)

        if title != "Unknown Title" or novel_url:
            items.append(
                {
                    "title": title,
                    "url": novel_url,
                    "current_chapter": current_chapter,
                    "chapter_url": chapter_url,
                    "progress": progress,
                    "summary": "",  # not available on library page
                }
            )
        else:
            log.debug("[CARD #%02d] Skipped — no title and no URL.", idx)

    log.debug("[PARSE] Page %d: %d/%d cards parsed", page_num, len(items), len(cards))
    return items


def scrape_library(session: requests.Session, max_pages: int = 10) -> list[dict[str, str]]:
    """Iterate through all library pages and return all novel entries."""
    all_novels: list[dict[str, str]] = []

    for page in range(1, max_pages + 1):
        url = f"{LIBRARY_URL}?page={page}"
        log.info("── Page %d/%d ── %s", page, max_pages, url)

        resp = _fetch_with_retry(session, url)
        _dump_html(f"library_page_{page}", resp.text)
        novels = _parse_library_page(resp.text, page)

        if not novels:
            log.info("No novels found on page %d — end of library.", page)
            break

        all_novels.extend(novels)
        log.info("  Running total: %d novels", len(all_novels))

        if page < max_pages:
            time.sleep(PAGE_DELAY)

    return all_novels


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Book detail fetcher  (one HTTP GET per novel)
# ---------------------------------------------------------------------------

# Optional: set NOVELFIRE_FETCH_DETAILS=0 to skip detail fetching entirely
FETCH_DETAILS = os.environ.get("NOVELFIRE_FETCH_DETAILS", "1").strip() != "0"

# Delay between book-page requests — 0.4s gives ~20s for 37 novels
DETAIL_DELAY = float(os.environ.get("NOVELFIRE_DETAIL_DELAY", "0.4"))


def _parse_book_detail(html: str, url: str) -> dict[str, Union[str, list[str]]]:
    """
    Parse a /book/<slug> page and return enrichment fields.

    Confirmed selectors (v11.0.9, from live HTML):
      author       div.author a[itemprop=author]   (multiple for CN novels)
      description  meta[itemprop=description]       (full synopsis)
      genres       div.categories ul li a
      tags         div.tags a.tag
      status       strong.ongoing / strong.completed
      rating       strong.nub
      rank         div.rank strong
      total_chaps  div.header-stats span:first strong
      views        div.header-stats span:nth strong
      bookmarked   div.header-stats span:nth strong
      cover_url    figure.cover img[src]
      keywords     meta[itemprop=keywords]
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── author ────────────────────────────────────────────────────────────────
    author_tags = soup.select("span[itemprop=author]")
    authors = [a.get_text(strip=True) for a in author_tags if a.get_text(strip=True)]
    # Filter out duplicates (CN novels list both EN transliteration + original)
    author = ", ".join(dict.fromkeys(authors))

    # ── description (full synopsis from itemprop, not the truncated meta tag) ─
    desc_meta = soup.find("meta", itemprop="description")
    content_val = desc_meta.get("content", "") if desc_meta else ""
    description = (str(content_val) if content_val else "").strip()

    # ── genres ────────────────────────────────────────────────────────────────
    genres = [a.get_text(strip=True) for a in soup.select("div.categories ul li a")]

    # ── tags ──────────────────────────────────────────────────────────────────
    tags = [a.get_text(strip=True) for a in soup.select("div.tags a.tag")]

    # ── status ────────────────────────────────────────────────────────────────
    status_tag = soup.select_one("strong.ongoing") or soup.select_one("strong.completed")
    status = status_tag.get_text(strip=True) if status_tag else ""

    # ── rating + rank ─────────────────────────────────────────────────────────
    rating_tag = soup.select_one("strong.nub")
    rating = rating_tag.get_text(strip=True) if rating_tag else ""

    rank_tag = soup.select_one("div.rank strong")
    rank = rank_tag.get_text(strip=True).replace("RANK", "").strip() if rank_tag else ""

    # ── header stats: total chapters / views / bookmarked ─────────────────────
    stat_spans = soup.select("div.header-stats span strong")
    total_chapters = stat_spans[0].get_text(strip=True) if len(stat_spans) > 0 else ""
    views = stat_spans[1].get_text(strip=True) if len(stat_spans) > 1 else ""
    bookmarked = stat_spans[2].get_text(strip=True) if len(stat_spans) > 2 else ""

    # ── cover image ───────────────────────────────────────────────────────────
    cover_tag = soup.select_one("figure.cover img")
    cover_url_val = cover_tag.get("src", "") if cover_tag else ""
    cover_url = str(cover_url_val) if cover_url_val else ""

    # ── keywords (comma-separated genre/type list from itemprop) ─────────────
    kw_meta = soup.find("meta", itemprop="keywords")
    content_val = kw_meta.get("content", "") if kw_meta else ""
    keywords = (str(content_val) if content_val else "").strip()

    detail: dict[str, Union[str, list[str]]] = {
        "author": author,
        "description": description,
        "genres": genres,
        "tags": tags,
        "status": status,
        "rating": rating,
        "rank": rank,
        "total_chapters": total_chapters,
        "views": views,
        "bookmarked": bookmarked,
        "cover_url": cover_url,
        "keywords": keywords,
    }

    log.debug(
        "[DETAIL] %s\n  author=%r  genres=%s  status=%r  rating=%r  tags=%d",
        url,
        author,
        genres,
        status,
        rating,
        len(tags),
    )
    return detail


def enrich_with_details(session: requests.Session, novels: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Fetch each novel's book detail page sequentially and merge enrichment fields.
    Skipped entirely if NOVELFIRE_FETCH_DETAILS=0.
    Delay between requests is NOVELFIRE_DETAIL_DELAY (default 0.4s, ~20s for 37 novels).
    """
    if not FETCH_DETAILS:
        log.info("Detail fetching disabled (NOVELFIRE_FETCH_DETAILS=0).")
        return novels

    total = len(novels)
    failed = 0
    log.info("Fetching detail pages for %d novels  [delay=%.1fs] …", total, DETAIL_DELAY)

    for i, novel in enumerate(novels, 1):
        url = novel.get("url", "")
        if not url:
            log.warning("[DETAIL %d/%d] No URL — skipping.", i, total)
            failed += 1
            continue

        log.info("  [%d/%d] %s", i, total, novel["title"])
        try:
            resp = _fetch_with_retry(session, url)
            _dump_html(f"book_detail_{i:03d}", resp.text)
            detail = _parse_book_detail(resp.text, url)
            novel.update(detail)  # type: ignore[arg-type]  # detail has list[str] values
        except Exception as exc:
            log.warning("[DETAIL %d/%d] Failed for %s: %s", i, total, url, exc)
            if DEBUG_MODE:
                traceback.print_exc()
            failed += 1

        if i < total:
            time.sleep(DETAIL_DELAY)

    if failed:
        log.warning("%d/%d detail fetches failed.", failed, total)
    log.info("Detail enrichment complete  (%d/%d succeeded).", total - failed, total)
    return novels


# Output writers
# ---------------------------------------------------------------------------


def write_json(novels: list[dict[str, str]], output_dir: Path) -> Path:
    path = output_dir / "novelfire_library.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
        "debug_mode": DEBUG_MODE,
        "total": len(novels),
        "novels": novels,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("JSON written → %s", path)
    return path


def write_markdown(novels: list[dict[str, str]], output_dir: Path) -> Path:
    path = output_dir / "novelfire_library.md"
    lines = [
        "# NovelFire Library",
        f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        f"_Total novels: {len(novels)}_",
        "",
    ]

    for i, n in enumerate(novels, 1):
        title = n["title"]
        url = n["url"]
        chapter = n["current_chapter"] or "_Not tracked_"
        chapter_url = n.get("chapter_url", "")
        progress = n.get("progress", "")
        author = n.get("author", "")
        description = n.get("description", "")
        genres: list[str] = n.get("genres", [])  # type: ignore[assignment]
        tags: list[str] = n.get("tags", [])  # type: ignore[assignment]
        status = n.get("status", "")
        rating = n.get("rating", "")
        rank = n.get("rank", "")
        total_chapters = n.get("total_chapters", "")
        views = n.get("views", "")

        title_line = f"## {i}. [{title}]({url})" if url else f"## {i}. {title}"
        chapter_line = f"**Currently reading:** [{chapter}]({chapter_url})" if chapter_url else f"**Currently reading:** {chapter}"

        entry = [title_line, ""]
        if author:
            entry += [f"**Author:** {author}"]
        meta_parts = []
        if status:
            meta_parts.append(f"Status: {status}")
        if rating:
            meta_parts.append(f"Rating: {rating}/5")
        if rank:
            meta_parts.append(f"Rank: #{rank}")
        if total_chapters:
            meta_parts.append(f"Chapters: {total_chapters}")
        if views:
            meta_parts.append(f"Views: {views}")
        if meta_parts:
            entry += [" · ".join(meta_parts)]
        if genres:
            entry += [f"**Genres:** {', '.join(genres)}"]
        if tags:
            entry += [f"**Tags:** {', '.join(tags)}"]
        if description:
            # Wrap long descriptions cleanly
            entry += [
                "",
                f"> {description[:500]}{'…' if len(description) > 500 else ''}",
            ]
        entry += ["", chapter_line]
        if progress:
            entry += [f"**Progress:** {progress}"]
        entry += ["", "---", ""]
        lines += entry

    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Markdown written → %s", path)
    return path


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------


def _print_config(email: str, max_pages: int, out_dir: Path) -> None:
    log.info("=" * 62)
    log.info("  NovelFire Library Scraper")
    log.info(
        "  debug mode  : %s",
        "ON  ← verbose logs + HTML dumps enabled" if DEBUG_MODE else "OFF",
    )
    log.info("  email       : %s", email)
    log.info("  max pages   : %d", max_pages)
    log.info("  output dir  : %s", out_dir.resolve())
    log.info(
        "  browser     : %s",
        "headless" if HEADLESS else "visible  (NOVELFIRE_HEADLESS=0)",
    )
    log.info(
        "  fetch detail: %s",
        f"YES  (delay={DETAIL_DELAY}s)" if FETCH_DETAILS else "NO  (NOVELFIRE_FETCH_DETAILS=0)",
    )
    if DEBUG_MODE:
        log.info("  dump dir    : %s", DEBUG_DUMP_DIR.resolve())
    log.info("=" * 62)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    email_str = _get_env("NOVELFIRE_EMAIL")
    password_str = _get_env("NOVELFIRE_PASSWORD")
    max_pages = int(_get_env("NOVELFIRE_MAX_PAGES", required=False) or 10)
    out_dir = Path(_get_env("NOVELFIRE_OUTPUT_DIR", required=False) or ".").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    assert email_str is not None
    assert password_str is not None
    _print_config(email_str, max_pages, out_dir)

    try:
        session = login(email_str, password_str)
        novels = scrape_library(session, max_pages=max_pages)
        novels = enrich_with_details(session, novels)
    except KeyboardInterrupt:
        log.warning("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        log.error("Unexpected error: %s", exc)
        if DEBUG_MODE:
            traceback.print_exc()
        else:
            log.error("Re-run with NOVELFIRE_DEBUG=1 for full traceback and HTML dumps.")
        sys.exit(1)

    if not novels:
        log.warning(
            "No novels were scraped.\n" "  → If you are logged in but getting 0 results, run with NOVELFIRE_DEBUG=1\n" "    and inspect HTML dumps in: %s/",
            DEBUG_DUMP_DIR,
        )
        sys.exit(0)

    log.info("Total novels scraped: %d", len(novels))
    write_json(novels, out_dir)
    write_markdown(novels, out_dir)
    log.info("Done ✓")


if __name__ == "__main__":
    main()
