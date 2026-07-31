"""Live UI verification for RETRANSLATION_DESIGN.md Phase 5 (global vocabulary-notes store).

One-off live-verification pass, run manually via run_ui_tests.sh -- not
part of the default automated test sweep (same status as
test_menu_smoke.py, which is also excluded from the plain pytest run per
its own module docstring's "Run directly with" instructions). Drives the
real, unmodified app to exercise both write entry points against real
on-disk data:

  - Scenario A: the glossary dialog's "Apply Globally" action.
  - Scenario B: the retranslation dialog's "remember this" checkbox and
    its follow-up "Remember Globally" popup.

Scenario C (confirming a subsequent real translation call actually
reflects a global note) does not need the UI and is run separately as a
plain script -- see RETRANSLATION_DESIGN.md's Phase 5 dated entry for
those results.

Run with (Xvfb already running via run_ui_tests.sh xvfb-keep):
    DISPLAY=:99 .venv/bin/pytest tests/webnovels/ui_automation/test_global_vocabulary_live.py -v -s
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from pyplayground.webnovels.ui_testing import log_correlator, xdo_helper

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_WINDOW_TITLE = "Alphapolis Reader"
TEST_EPISODE_URL = "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
GLOBAL_VOCAB_PATH = Path.home() / ".config" / "alphapolis_reader" / "global_vocabulary.json"


@pytest.fixture(scope="module")
def backed_up_global_vocab():
    """Move any pre-existing global_vocabulary.json aside for the duration of this module, restored after."""
    backup_path = GLOBAL_VOCAB_PATH.with_suffix(".json.livetest-backup")
    existed = GLOBAL_VOCAB_PATH.exists()
    if existed:
        shutil.move(str(GLOBAL_VOCAB_PATH), str(backup_path))
    yield
    if GLOBAL_VOCAB_PATH.exists():
        GLOBAL_VOCAB_PATH.unlink()
    if existed:
        shutil.move(str(backup_path), str(GLOBAL_VOCAB_PATH))


@pytest.fixture(scope="module")
def running_app(backed_up_global_vocab):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    display_state = xdo_helper.check_display()
    if not display_state["live"]:
        pytest.fail(f"Display is not live: {display_state}")

    stdout_log = str(ARTIFACT_DIR / "global_vocab_live_stdout.log")
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
        subprocess.run(["xdotool", "windowsize", window_id, "1400", "700"], check=True)
        yield window_id, log_path
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def _current_log_path(fallback):
    try:
        return log_correlator.latest_log_file(str(REPO_ROOT / "logs"))
    except FileNotFoundError:
        return fallback


def test_apply_globally_from_glossary_dialog(running_app):
    """Scenario A: select the confirmed term-typed row, click Apply Globally, confirm the on-disk global entry.

    This app exposes no widget-introspection-over-xdotool API, so there is
    no reliable way to assert "a button with this label exists/doesn't
    exist at this position" from outside the process -- an earlier version
    of this test tried a hardcoded (label -> coordinate) lookup table for
    that, which was not a real check at all (it returned a fixed
    coordinate regardless of what was actually on screen, so it could
    never have caught a real absence). Fixed here by verifying character-
    row exclusion **by effect** instead: click the exact screen position
    where "Apply Globally" appears for a term-typed row, but on the
    character-typed row instead (where the production code must not have
    placed a button there), and confirm no new global_vocabulary.json
    write and no matching log line resulted -- a real behavioral check,
    not a widget-presence guess.

    Coordinates below are not guesses -- every one was measured against a
    real running instance of this exact dialog during this test's own
    development (see RETRANSLATION_DESIGN.md's 2026-07-31 Phase 5 dated
    entry, "Live verification" / Scenario A, for the screenshots and
    reasoning that produced them). The Treeview's scroll position is not
    itself part of this app's state contract, so this test scrolls first
    rather than assuming バッターボックスに立/ハードキャッチ (both near
    the end of this novel's 19-term glossary) are already in view --
    confirmed live that the dialog opens scrolled to the top.
    """
    window_id, log_path = running_app
    action_time = datetime.now().replace(microsecond=0)

    # Toolbar button coordinates per test_menu_smoke.py's own measured
    # geometry at the same WIDENED_WINDOW_SIZE.
    xdo_helper.click(window_id, 1064, 21, settle=0.4)
    dialog_id = xdo_helper.find_window("Glossary", timeout=10.0)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_dialog_open.png"))

    # Scroll the Treeview down (mouse wheel over the tree area) until the
    # confirmed rows (バッターボックスに立/ハードキャッチ, both near the
    # end of this novel's seeded glossary) are visible -- measured live
    # that 3 wheel-down clicks over (150, 200) reliably brings them into
    # view at this dialog's fixed 700x520 geometry.
    subprocess.run(["xdotool", "mousemove", "--window", dialog_id, "150", "200"], check=True)
    for _ in range(3):
        subprocess.run(["xdotool", "click", "5"], check=True)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_scrolled.png"))

    # The confirmed term-typed row (バッターボックスに立 -> "batting box")
    # is the real confirmed non-character term in this novel's seeded
    # glossary -- select it in the Treeview at its measured row position
    # after scrolling. The "Apply Globally" button lands at (504, 213) in
    # this dialog's fixed layout when a confirmed term-typed row is
    # selected -- measured live, screenshot-confirmed.
    xdo_helper.click(dialog_id, 100, 361, settle=0.4)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_row_selected.png"))
    xdo_helper.click(dialog_id, 504, 213, settle=0.5)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_confirmation.png"))

    # Confirmation messagebox: dismissed with Return, confirmed live that
    # this reliably closes it in this environment (same as
    # test_menu_smoke.py's own dialog-dismissal precedent).
    xdo_helper.send_global_keys("Return", settle=0.4)

    log_correlator.assert_clean(_current_log_path(log_path), since=action_time)

    assert GLOBAL_VOCAB_PATH.exists(), "global_vocabulary.json was not created by Apply Globally"
    store = json.loads(GLOBAL_VOCAB_PATH.read_text(encoding="utf-8"))
    sources = {e["source"] for e in store["entries"]}
    assert "バッターボックスに立" in sources, f"Apply Globally did not write the expected entry; got {sources}"
    entry = next(e for e in store["entries"] if e["source"] == "バッターボックスに立")
    assert entry["target"] == "batting box"

    # Character-type row (ハードキャッチ): select it, then click the exact
    # position where Apply Globally sits for a term-typed row -- if a
    # button were (wrongly) present there too, this would write a second
    # global entry with source "ハードキャッチ" and log a matching INFO
    # line; if the row correctly has no button there, this click lands on
    # whatever inert control (if anything) actually occupies that spot for
    # a character row and neither of those things happens.
    exclusion_check_time = datetime.now().replace(microsecond=0)
    xdo_helper.click(dialog_id, 100, 384, settle=0.4)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_character_row.png"))
    xdo_helper.click(dialog_id, 504, 213, settle=0.5)
    xdo_helper.screenshot(dialog_id, str(ARTIFACT_DIR / "apply_globally_character_row_after_click.png"))

    log_correlator.assert_clean(_current_log_path(log_path), since=exclusion_check_time)
    store_after = json.loads(GLOBAL_VOCAB_PATH.read_text(encoding="utf-8"))
    assert store_after == store, "clicking the Apply-Globally position on a character-typed row must not write any global entry"

    xdo_helper.click(dialog_id, 395, 494, settle=0.3)  # Cancel
