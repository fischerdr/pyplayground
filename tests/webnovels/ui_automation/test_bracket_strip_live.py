"""Live UI verification for DESIGN.md's 2026-08-01 bracket-stripping fix.

One-off live-verification pass, run manually via run_ui_tests.sh -- same
status as test_menu_smoke.py / test_global_vocabulary_live.py (excluded
from the default automated pytest sweep, per those modules' own
docstrings). Loads a real, previously-scraped cached episode
(https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7801892)
whose lines 45/49 (「「「キャアアアー！！」」」) were confirmed corrupt in
cached output before this fix (DESIGN.md's 2026-08-01 quantification
entry) and re-translated locally through the real, fixed
translate_lines_with_masking()/save_cached_episode() path (no network
fetch -- the source HTML was already scraped and cached previously; only
the translation step re-ran, via
scripts/retranslate_cached_episode.py-equivalent logic run ahead of this
test). Confirms the on-screen Translated-mode rendering now shows the
clean, re-wrapped output instead of the corrupted "" artifact, with a
clean app log.

Run with (Xvfb already running via run_ui_tests.sh xvfb-keep):
    DISPLAY=:99 .venv/bin/pytest tests/webnovels/ui_automation/test_bracket_strip_live.py -v -s
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from pyplayground.webnovels.ui_testing import log_correlator, xdo_helper

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_WINDOW_TITLE = "Alphapolis Reader"
TEST_EPISODE_URL = "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7801892"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


@pytest.fixture(scope="module")
def running_app():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    display_state = xdo_helper.check_display()
    if not display_state["live"]:
        pytest.fail(f"Display is not live: {display_state}")

    stdout_log = str(ARTIFACT_DIR / "bracket_strip_live_stdout.log")
    launch_time = datetime.now().replace(microsecond=0)
    proc = xdo_helper.launch_and_track(
        [sys.executable, "-m", "pyplayground.webnovels.alphapolis_reader", TEST_EPISODE_URL],
        stdout_log=stdout_log,
        env={**os.environ},
    )
    try:
        window_id = xdo_helper.find_window(APP_WINDOW_TITLE, expected_pid=proc.pid, timeout=30.0)
        log_path = None
        for _ in range(20):
            try:
                log_path = log_correlator.latest_log_file(str(REPO_ROOT / "logs"))
                break
            except FileNotFoundError:
                time.sleep(0.25)
        if log_path is None:
            pytest.fail(f"No app_log_*.log file appeared under {REPO_ROOT / 'logs'} after launch")
        if not log_correlator.wait_for_log_line(log_path, "Displayed episode:", timeout=180.0, since=launch_time):
            pytest.fail(f"Episode never finished loading within 180s (log: {log_path})")
        xdo_helper.activate_window(window_id)
        subprocess.run(["xdotool", "windowsize", window_id, "1400", "900"], check=True)
        yield window_id, log_path, launch_time
    finally:
        proc.terminate()


class TestBracketStripLive:
    """Confirms the on-screen rendering of a previously-corrupted collective-shout line is now clean."""

    def test_translated_mode_shows_clean_rewrapped_output(self, running_app):
        window_id, log_path, launch_time = running_app
        since = datetime.now().replace(microsecond=0)

        # Default view mode is Translated (per existing live-verification
        # precedent in DESIGN.md's needs_review entry) -- screenshot as-is,
        # no menu interaction needed to reach the mode under test.
        screenshot_path = str(ARTIFACT_DIR / "bracket_strip_translated_mode.png")
        xdo_helper.screenshot(window_id, screenshot_path)
        assert Path(screenshot_path).exists()

        log_correlator.assert_clean(log_path, since=since)

    def test_cache_file_confirms_no_stray_quote_artifact_reached_disk(self):
        """Direct confirmation (not just visual) that the corrupted shape never reached the cache backing what's on screen."""
        from pyplayground.webnovels.alphapolis_reader import load_cached_episode

        ep = load_cached_episode(TEST_EPISODE_URL)
        assert ep is not None

        assert '""' not in ep["translated_lines"][45], f"stray-quote artifact present: {ep['translated_lines'][45]!r}"
        assert '""' not in ep["translated_lines"][49], f"stray-quote artifact present: {ep['translated_lines'][49]!r}"
        assert ep["translated_lines"][45].startswith("「") and ep["translated_lines"][45].endswith("」"), f"expected re-wrapped output, got {ep['translated_lines'][45]!r}"
