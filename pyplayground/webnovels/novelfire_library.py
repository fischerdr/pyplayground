#!/usr/bin/env python3
"""Scrape NovelFire library and save to JSON/Markdown files.

novelfire_library.py

Scrapes your NovelFire library (bookmarks) and saves:
  - novelfire_library.json   (machine-readable)
  - novelfire_library.md     (human-readable)

Credentials are read from environment variables:
  NOVELFIRE_EMAIL    - your login email
  NOVELFIRE_PASSWORD - your login password

Optional env vars:
  NOVELFIRE_MAX_PAGES  - max library pages to scrape (default: 10)
  NOVELFIRE_OUTPUT_DIR - directory to write output files (default: current dir)
  NOVELFIRE_DEBUG      - set to "1" to enable verbose debug output + HTML dumps.

Usage:
  export NOVELFIRE_EMAIL="you@example.com"
  export NOVELFIRE_PASSWORD="yourpassword"
  export NOVELFIRE_DEBUG=1          # optional — enables full debug mode
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
from typing import Optional

import requests
from bs4 import BeautifulSoup

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
DEBUG_DUMP_DIR = Path("./novelfire_debug_dumps")


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
    """Print a structural summary of the parsed HTML to help identify correct CSS selectors when the site layout is unknown (debug mode only).

    Print a structural summary of the parsed HTML to help identify correct
    CSS selectors when the site layout is unknown.
    """
    if not DEBUG_MODE:
        return

    from collections import Counter

    log.debug("[SOUP] %s — tag inventory:", label)
    tag_counts = Counter(t.name for t in soup.find_all(True))
    log.debug("[SOUP]   tag counts: %s", dict(tag_counts.most_common(20)))

    log.debug("[SOUP]   unique class combos on div/li/article/section:")
    seen_classes: set = set()
    for tag in soup.find_all(["div", "li", "article", "section"]):
        classes = tuple(tag.get("class", []))
        if classes and classes not in seen_classes:
            seen_classes.add(classes)
            snippet = tag.get_text(separator=" ", strip=True)[:80]
            log.debug("[SOUP]     <%s class=%s>  →  %s", tag.name, list(classes), snippet)
        if len(seen_classes) >= 50:
            log.debug("[SOUP]     … (truncated at 50 unique class combos)")
            break

    book_links = soup.select("a[href*='/book/']")
    log.debug("[SOUP]   <a href*='/book/'> found: %d", len(book_links))
    for a in book_links[:8]:
        log.debug("[SOUP]     href=%-60s  text=%s", a.get("href"), a.get_text(strip=True)[:60])


def _log_card_parse(idx: int, card, title: str, url: str, summary: str, chapter: str) -> None:
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


def _fetch_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
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


def login(email: str, password: str) -> requests.Session:
    """Log in to NovelFire and return an authenticated session.

    Auth flow (confirmed from modal.min.js v11.0.9 + HTML inspection):
      - Login is a pure JS modal (href="#modal class="login") — no dedicated page
      - /account/login is a 404; XSRF-TOKEN is set on any page load (/home)
      - POST /loginAjax with email + password form data + X-XSRF-TOKEN header
      - Returns JSON {"status": 1, ...} on success
      - Verify by GETting /account/library — redirects to /home if not authed
    """
    from urllib.parse import unquote

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Step 1: GET /home to seed XSRF-TOKEN cookie ───────────────────────────
    seed_url = f"{BASE_URL}/home"
    log.info("Loading homepage to acquire XSRF-TOKEN cookie …")
    try:
        resp = session.get(
            seed_url,
            headers={**HEADERS, "Accept-Encoding": "identity"},
            timeout=30,
            allow_redirects=True,
        )
        _dump_response_info("GET /home (XSRF seed)", resp)
        _dump_html("home_seed", resp.text)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to load homepage: %s", exc)
        if DEBUG_MODE:
            traceback.print_exc()
        sys.exit(1)

    if DEBUG_MODE:
        _inspect_soup_structure("/home seed page", BeautifulSoup(resp.text, "html.parser"))

    # ── Step 2: extract XSRF-TOKEN from cookie jar ────────────────────────────
    xsrf_raw = session.cookies.get("XSRF-TOKEN", "")
    if not xsrf_raw:
        # Fallback: meta csrf-token in the page head
        soup_home = BeautifulSoup(resp.text, "html.parser")
        meta_csrf = soup_home.find("meta", {"name": "csrf-token"})
        meta_val = (meta_csrf.get("content", "") or "").strip() if meta_csrf else ""
        if meta_val:
            log.debug("[LOGIN] XSRF-TOKEN cookie absent — using meta csrf-token tag.")
            xsrf_raw = meta_val
        else:
            log.warning("[LOGIN] No XSRF-TOKEN cookie or meta csrf-token found. " "POST may receive 419.")
    else:
        log.debug("[LOGIN] XSRF-TOKEN cookie: %s… (%d chars)", xsrf_raw[:24], len(xsrf_raw))

    xsrf_token = unquote(xsrf_raw)  # Laravel URL-encodes the token in the cookie

    # ── Step 3: POST credentials to /loginAjax ───────────────────────────────
    post_headers = {
        **HEADERS,
        "Referer": seed_url,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "identity",
    }
    if xsrf_token:
        post_headers["X-XSRF-TOKEN"] = xsrf_token

    payload = {"email": email, "password": password, "remember": "1"}
    log.debug("[LOGIN] POST %s  payload keys=%s", LOGIN_AJAX_URL, list(payload.keys()))
    log.info("Posting credentials to /loginAjax …")

    try:
        ajax_resp = session.post(
            LOGIN_AJAX_URL,
            data=payload,
            headers=post_headers,
            timeout=30,
            allow_redirects=False,
        )
        _dump_response_info("POST /loginAjax", ajax_resp)
        _dump_html("loginAjax_response", ajax_resp.text)
        _dump_cookies(session)
    except requests.RequestException as exc:
        log.error("Login AJAX POST failed: %s", exc)
        if DEBUG_MODE:
            traceback.print_exc()
        sys.exit(1)

    log.debug(
        "[LOGIN] /loginAjax HTTP %d  body: %s",
        ajax_resp.status_code,
        ajax_resp.text[:500],
    )

    # ── Step 4: parse JSON response ───────────────────────────────────────────
    if ajax_resp.status_code == 419:
        log.error("HTTP 419 — XSRF token was rejected. " "Check that the XSRF-TOKEN cookie is being set on /home.")
        sys.exit(1)

    try:
        rdata = ajax_resp.json()
        status = str(rdata.get("status", rdata.get("success", rdata.get("code", ""))))
        log.debug("[LOGIN] JSON: status=%r  full=%s", status, rdata)

        if status not in ("1", "true", "success", "ok", "200"):
            msg = rdata.get("msg", rdata.get("message", rdata.get("error", str(rdata))))
            log.error(
                "Login rejected by /loginAjax (status=%r).\n" "  Server message: %s\n" "  → Check NOVELFIRE_EMAIL / NOVELFIRE_PASSWORD",
                status,
                msg,
            )
            sys.exit(1)

        log.debug("[LOGIN] Credentials accepted (status=%r)", status)

    except ValueError:
        log.warning(
            "[LOGIN] /loginAjax returned non-JSON (HTTP %d). " "Verifying via library page.",
            ajax_resp.status_code,
        )
        if ajax_resp.status_code not in (200, 302):
            log.error("Unexpected HTTP %d from /loginAjax.", ajax_resp.status_code)
            sys.exit(1)

    # ── Step 5: verify session by loading /account/library ───────────────────
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
            "Login FAILED — /account/library redirected to %s\n"
            "  Likely causes:\n"
            "    1. Wrong credentials\n"
            "    2. XSRF token was rejected — check loginAjax dump\n"
            "    3. Response format changed\n"
            "  → loginAjax body: %s\n"
            "  → Dumps in: %s/",
            verify.url,
            ajax_resp.text[:300],
            DEBUG_DUMP_DIR,
        )
        sys.exit(1)

    log.info("Login verified ✓  (landed on: %s)", verify.url)
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


def _parse_library_page(html: str, page_num: int) -> list[dict]:
    """Parse one page of /account/library and return a list of novel dicts.

    Parse one page of /account/library and return a list of novel dicts.
    """
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
        href = title_a.get("href", "") if title_a else ""
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
        chapter_href = chapter_a.get("href", "") if chapter_a else ""
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


def scrape_library(session: requests.Session, max_pages: int = 10) -> list[dict]:
    """Iterate through all library pages and return all novel entries."""
    all_novels: list[dict] = []

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

DETAIL_DELAY = 1.0  # seconds between book-page requests (be polite)

# Optional: set NOVELFIRE_FETCH_DETAILS=0 to skip detail fetching
FETCH_DETAILS = os.environ.get("NOVELFIRE_FETCH_DETAILS", "1").strip() != "0"


def _parse_book_detail(html: str, url: str) -> dict:
    """Parse a /book/<slug> page and return enrichment fields.

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
    description = (desc_meta.get("content", "") if desc_meta else "").strip()

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
    cover_url = cover_tag.get("src", "") if cover_tag else ""

    # ── keywords (comma-separated genre/type list from itemprop) ─────────────
    kw_meta = soup.find("meta", itemprop="keywords")
    keywords = (kw_meta.get("content", "") if kw_meta else "").strip()

    detail = {
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


def enrich_with_details(session: requests.Session, novels: list[dict]) -> list[dict]:
    """Fetch each novel's book page and merge enrichment fields in-place.

    Fetch each novel's book page and merge enrichment fields in-place.
    Skipped entirely if NOVELFIRE_FETCH_DETAILS=0.
    """
    if not FETCH_DETAILS:
        log.info("Detail fetching disabled (NOVELFIRE_FETCH_DETAILS=0). Skipping.")
        return novels

    total = len(novels)
    log.info("Fetching book detail pages for %d novels …", total)

    for i, novel in enumerate(novels, 1):
        url = novel.get("url", "")
        if not url:
            log.warning("[DETAIL %d/%d] No URL — skipping.", i, total)
            continue

        log.info("  [%d/%d] %s", i, total, novel["title"])
        try:
            resp = _fetch_with_retry(session, url)
            _dump_html(f"book_detail_{i:03d}", resp.text)
            detail = _parse_book_detail(resp.text, url)
            novel.update(detail)
        except Exception as exc:
            log.warning("[DETAIL %d/%d] Failed for %s: %s", i, total, url, exc)
            if DEBUG_MODE:
                traceback.print_exc()

        if i < total:
            time.sleep(DETAIL_DELAY)

    log.info("Detail enrichment complete.")
    return novels


# Output writers
# ---------------------------------------------------------------------------


def write_json(novels: list[dict], output_dir: Path) -> Path:
    """Write novels list to JSON file with metadata.

    Write novels list to JSON file with metadata.
    """
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


def write_markdown(novels: list[dict], output_dir: Path) -> Path:
    """Write novels list to Markdown file with metadata.

    Write novels list to Markdown file with metadata.
    """
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
        genres = n.get("genres", [])
        tags = n.get("tags", [])
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
        "  fetch detail: %s",
        "YES" if FETCH_DETAILS else "NO (set NOVELFIRE_FETCH_DETAILS=1 to enable)",
    )
    if DEBUG_MODE:
        log.info("  dump dir    : %s", DEBUG_DUMP_DIR.resolve())
    log.info("=" * 62)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    """Main entry point for NovelFire library scraper.

    Main entry point for NovelFire library scraper.
    """
    email = _get_env("NOVELFIRE_EMAIL")
    password = _get_env("NOVELFIRE_PASSWORD")
    max_pages = int(_get_env("NOVELFIRE_MAX_PAGES", required=False) or 10)
    out_dir = Path(_get_env("NOVELFIRE_OUTPUT_DIR", required=False) or ".").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    _print_config(email, max_pages, out_dir)

    try:
        session = login(email, password)
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
