#!/usr/bin/env python3
"""publish_gist.py.

Publishes novelfire_library.py as a public GitHub Gist.

Usage:
  export GITHUB_TOKEN="ghp_yourtoken"
  python3 publish_gist.py

Optional — update an existing gist instead of creating a new one:
  export GIST_ID="abc123yourgistid"
  python3 publish_gist.py
"""

import os
import sys
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]

SCRIPT_PATH = Path(__file__).parent / "novelfire_library.py"
GIST_DESCRIPTION = (
    "NovelFire Library Scraper — backs up your bookmarked novels, " "current chapter, and reading progress to JSON + Markdown. " "See README in gist for setup instructions."
)
README = """\
# novelfire_library.py

Scrapes your [NovelFire](https://novelfire.net) library and saves every bookmarked novel with its current chapter and reading progress.

## Output

| File | Format | Use |
|---|---|---|
| `novelfire_library.json` | Machine-readable | Diffs, scripting, backups |
| `novelfire_library.md` | Human-readable | Quick reference, sharing |

## Setup

```bash
pip install requests beautifulsoup4
```

## Usage

```bash
export NOVELFIRE_EMAIL="you@example.com"
export NOVELFIRE_PASSWORD="yourpassword"
python3 novelfire_library.py
```

## Optional env vars

| Variable | Default | Description |
|---|---|---|
| `NOVELFIRE_MAX_PAGES` | `10` | Max library pages to scrape |
| `NOVELFIRE_OUTPUT_DIR` | `.` | Directory to write output files |
| `NOVELFIRE_DEBUG` | `0` | Set to `1` for verbose logs + HTML dumps |

## Debug mode

```bash
NOVELFIRE_DEBUG=1 python3 novelfire_library.py 2>&1 | tee run.log
```

Debug mode writes every fetched HTML page to `./novelfire_debug_dumps/` for inspection.

## Cron example

```bash
# Daily at 6am, keep 7-day rolling snapshots
0 6 * * * cd /path/to/scripts && \\
  python3 novelfire_library.py && \\
  cp novelfire_library.json "novelfire_library_$(date +\\%Y\\%m\\%d).json" && \\
  find . -name 'novelfire_library_*.json' -mtime +7 -delete
```

## Auth notes

NovelFire uses a jQuery AJAX login (`POST /loginAjax`) with a Laravel XSRF-TOKEN cookie.
There is no traditional login page — the script seeds the token from the homepage and
posts credentials directly to the AJAX endpoint, mirroring what the browser modal does.
"""


def create_gist(token: str, script: str) -> Any:
    """Create a new public GitHub Gist with the script and README."""
    resp = requests.post(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "description": GIST_DESCRIPTION,
            "public": True,
            "files": {
                "novelfire_library.py": {"content": script},
                "README.md": {"content": README},
            },
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def update_gist(token: str, gist_id: str, script: str) -> Any:
    """Update an existing GitHub Gist with the script and README."""
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "description": GIST_DESCRIPTION,
            "files": {
                "novelfire_library.py": {"content": script},
                "README.md": {"content": README},
            },
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    """Run the gist publishing script."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable is not set.")
        print("  Create one at: https://github.com/settings/tokens")
        print("  Required scope: gist")
        sys.exit(1)

    if not SCRIPT_PATH.exists():
        print(f"ERROR: Script not found at {SCRIPT_PATH}")
        sys.exit(1)

    script = SCRIPT_PATH.read_text(encoding="utf-8")
    gist_id = os.environ.get("GIST_ID", "").strip()

    try:
        if gist_id:
            print(f"Updating existing gist {gist_id} ...")
            data = update_gist(token, gist_id, script)
            print("Updated ✓")
        else:
            print("Creating new public gist ...")
            data = create_gist(token, script)
            print("Created ✓")

        url = data["html_url"]
        raw_url = data["files"]["novelfire_library.py"]["raw_url"]
        gist_id = data["id"]

        print(f"\n  Gist URL : {url}")
        print(f"  Gist ID  : {gist_id}  (set GIST_ID={gist_id} to update later)")
        print(f"  Raw py   : {raw_url}")
        print("\n  Install anywhere with:")
        print(f"  curl -fsSL {raw_url} -o novelfire_library.py")

    except requests.HTTPError as e:
        print(f"GitHub API error: {e.response.status_code} — {e.response.text[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
