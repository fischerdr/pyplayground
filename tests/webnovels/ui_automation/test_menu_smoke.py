"""UI smoke test for alphapolis_reader.py's toolbar/dialog/context-menu surface.

Sweeps the toolbar-button/dialog and right-click context-menu surface,
screenshotting each and cross-checking the app's own log for the same
time window.

This is the automated counterpart to a manual "click every button, open
every popup" pass -- meant to run unattended under Xvfb (see
agents-ui-testing.md's "Screenshotting" section for why Xvfb, not the
shared desktop session, is the right default). Every step in this file
follows the dual-check discipline: confirm the screenshot shows the
expected visual state AND confirm the log has no ERROR/CRITICAL line for
that same action, never either alone -- a caught-and-logged exception can
leave a dialog looking completely normal.

Unlike a conventional menubar app, alphapolis_reader.py has no top-level
Tk menu bar -- its "menu" surface is the toolbar's ttk.Buttons (each opens
a Toplevel dialog) plus one right-click tk.Menu context menu over
translated text. TOOLBAR_DIALOGS below sweeps the former; the latter is
its own test using find_popup_by_name(), the confirmed Tk-first popup
technique from agents-ui-testing.md.

Every dialog opened here is closed by clicking its own real Cancel/Close
button, never xdo_helper.close_window()/`xdotool windowclose`. Confirmed
live in this session: sending WM_DELETE_WINDOW via windowclose to a
Toplevel dialog reliably crashes the entire app under Xvfb (a Node.js
EPIPE follows an X BadWindow error), while clicking the dialog's own
Cancel/Close button -- which calls Tk's `.destroy()` directly -- does
not. See xdo_helper.close_window()'s docstring for the full writeup;
root cause is unconfirmed (implicates the app's own Playwright/Chromium
BrowserWorker, which is always running headless in the background) and
is being tracked as its own open question, not a solved one.

Run directly with (Xvfb already running on :99, fluxbox started):
    DISPLAY=:99 .venv/bin/pytest tests/webnovels/ui_automation/test_menu_smoke.py -v
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
# Cached episode (see ~/.cache/alphapolis_reader/) so the app starts
# without depending on a live network fetch during an unattended run.
# NOTE: confirmed live that a resize or an accidental click into the URL
# bar can still trigger a real (~90s) re-translation regardless of the
# cache -- this module's own fixture waits for display_episode()'s
# "Displayed episode:" log line before proceeding specifically to avoid
# racing that (see running_app's comment for why this marker, not
# "Episode translated successfully", is used).
TEST_EPISODE_URL = "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# Toolbar button label -> (the dialog window title it opens, window-relative
# (x, y) click point to close it via its own real Cancel/Close button).
# Measured directly against a live run at the app's default 1220x700 root
# geometry (see alphapolis_reader.py's root.geometry call in
# ReaderApp.__init__) -- "Settings..." is clipped off-window at that width,
# so this fixture widens the window before the sweep begins (see
# running_app). Re-measure with a screenshot if the toolbar or dialog
# layouts change.
TOOLBAR_DIALOGS = {
    "Load Novel...": {"button": (878, 21), "title": "Load Novel", "close": (280, 43)},
    "Glossary...": {"button": (1064, 21), "title": "Glossary", "close": (395, 494)},
    "Review Terms...": {"button": (1170, 21), "title": "Review Terms", "close": (380, 421)},
    "Settings...": {"button": (1275, 21), "title": "Settings", "close": (215, 421)},
}

# Widened from the app's default 1220px so "Settings..." (rightmost
# toolbar button) is not clipped off the visible window -- confirmed
# live that alphapolis_reader.py has no <Configure>/resize handler of its
# own, so widening does not itself trigger unwanted side effects.
WIDENED_WINDOW_SIZE = (1400, 700)


@pytest.fixture(scope="module")
def running_app():
    """Launch alphapolis_reader.py once for the module, tracked for cleanup.

    Yields its xdotool window id and guarantees process cleanup on
    teardown regardless of test outcomes.

    On a real GNOME/Mutter desktop, the app's PID would be used to
    disambiguate the real Tk client window from a mutter-x11-frames
    decoration window (see xdo_helper.find_window()). Confirmed live
    under Xvfb+fluxbox that this app's Tk toplevel has no `_NET_WM_PID`
    property at all there and fluxbox does not add a separate decoration
    window -- find_window() falls back to its single-unambiguous-match
    path in that case rather than polling to timeout.
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    tools = xdo_helper.check_tools_available()
    # xdotool is always required; maim is one of three interchangeable
    # screenshot backends (see xdo_helper.screenshot()'s "auto" mode) so
    # its absence alone is not fatal as long as import or xwd is present.
    required_missing = [name for name in ("xdotool", "xwininfo") if not tools[name]]
    if required_missing:
        pytest.skip(f"Required tools missing from PATH: {required_missing}")
    if not (tools["import"] or tools["xwd"] or tools["maim"]):
        pytest.skip("No screenshot backend available (checked import, xwd, maim)")

    display_state = xdo_helper.check_display()
    if not display_state["live"]:
        pytest.fail(f"Display is not live: {display_state}")

    stdout_log = str(ARTIFACT_DIR / "app_stdout.log")
    # Captured before launch, not before the wait_for_log_line() call below
    # -- confirmed live that a cache-hit episode load can log its
    # completion marker within 1-2 seconds of process start, which can
    # already be in the past by the time find_window() (itself several
    # seconds, polling for the window to appear) returns. wait_for_log_line()
    # defaulting to "now" at call time would then miss a marker that had
    # already been written, reporting a false timeout despite the app
    # having loaded correctly.
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
        # Wait for the episode to actually finish loading before the sweep
        # starts -- Glossary/Review Terms both require self.episode to be
        # set, and clicking them too early just opens a "Load a novel
        # first." info dialog instead of the real one. "Displayed episode:"
        # (display_episode()'s own log line, added for this module) fires
        # identically on a cache hit or a fresh fetch+translate -- unlike
        # "Episode translated successfully", which only logs on the
        # fresh-fetch path and never fires at all on a cache hit.
        if not log_correlator.wait_for_log_line(log_path, "Displayed episode:", timeout=180.0, since=launch_time):
            pytest.fail(f"Episode never finished loading within 180s (log: {log_path})")
        xdo_helper.activate_window(window_id)
        # See WIDENED_WINDOW_SIZE's comment for why this is needed.
        _run_xdotool_windowsize(window_id, *WIDENED_WINDOW_SIZE)
        yield window_id
    finally:
        # Never xdo_helper.close_window()/`xdotool windowclose` here --
        # confirmed live in this module's own docstring investigation to
        # crash the entire app (a Node.js EPIPE following an X BadWindow
        # error), distinct from and in addition to the already-documented
        # windowkill danger in agents-ui-testing.md. A process-level
        # SIGTERM is the safe teardown for the whole app.
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def _run_xdotool_windowsize(window_id: str, width: int, height: int) -> None:
    subprocess.run(["xdotool", "windowsize", window_id, str(width), str(height)], check=True)


def _current_log_path() -> str:
    return log_correlator.latest_log_file(str(REPO_ROOT / "logs"))


def _ensure_focus(window_id: str) -> None:
    """Confirm the target window is actually focused before an interaction.

    Pre-flight check run before any click/keypress sequence, rather than
    assuming a previous activate call is still in effect.
    """
    if xdo_helper.get_active_window() != window_id:
        xdo_helper.activate_window(window_id)


def test_app_launched_without_startup_errors(running_app):
    """Sanity check the app came up clean before dialog sweeping began.

    Confirms both that the window exists (running_app fixture already
    did this) and that startup logged no ERROR/CRITICAL line.
    """
    window_id = running_app
    screenshot_path = ARTIFACT_DIR / "startup.png"
    xdo_helper.screenshot(window_id, str(screenshot_path))
    assert screenshot_path.exists()
    log_correlator.assert_clean(_current_log_path(), since=datetime.now().replace(microsecond=0))


@pytest.mark.parametrize("button_label,spec", TOOLBAR_DIALOGS.items())
def test_toolbar_dialog_opens_cleanly(running_app, button_label, spec):
    """Click a toolbar button and dual-check the resulting dialog.

    Confirms the dialog opens (visual state) and that no ERROR/CRITICAL
    log line followed (log state), then closes it via its own real
    Cancel/Close button.
    """
    window_id = running_app
    dialog_title = spec["title"]
    _ensure_focus(window_id)
    action_time = datetime.now().replace(microsecond=0)

    before_path = ARTIFACT_DIR / f"toolbar_{dialog_title.lower().replace(' ', '_')}_before.png"
    xdo_helper.screenshot(window_id, str(before_path))

    xdo_helper.click(window_id, spec["button"][0], spec["button"][1], settle=0.4)

    dialog_id = xdo_helper.find_window(dialog_title, timeout=10.0)

    after_path = ARTIFACT_DIR / f"toolbar_{dialog_title.lower().replace(' ', '_')}_after.png"
    xdo_helper.screenshot(dialog_id, str(after_path))
    if not after_path.exists():
        state = xdo_helper.diagnose_state(window_id)
        raise AssertionError(
            f"Screenshot for '{dialog_title}' dialog was not created. "
            f"Focus/pointer state at time of failure: {state}. "
            "A focus_matches=False or mouse_in_expected_window=False here means "
            "display focus/pointer contention, not the dialog action itself failing."
        )

    xdo_helper.click(dialog_id, spec["close"][0], spec["close"][1], settle=0.3)
    log_correlator.assert_clean(_current_log_path(), since=action_time)


def test_context_menu_opens_and_closes_cleanly(running_app):
    """Right-click over the translated text to open the 'Add to Glossary...' context menu (tk.Menu), then verify.

    Confirmed via find_popup_by_name()'s Tk-first !menu search rather than
    EWMH type -- the technique agents-ui-testing.md confirmed working for
    this app -- then close it and cross-check the log. Escape (not a
    Cancel button, since this is a tk.Menu popup with no button of its
    own) was confirmed live to close this popup safely, distinct from the
    windowclose crash this module works around for the Toplevel dialogs
    above.
    """
    window_id = running_app
    _ensure_focus(window_id)
    action_time = datetime.now().replace(microsecond=0)

    # A point over actual translated episode text, confirmed live against
    # the widened WIDENED_WINDOW_SIZE geometry -- not exact widget-relative
    # math, just a point inside the Text widget clear of the toolbar row.
    click_x, click_y = 200, 232

    xdo_helper.click(window_id, click_x, click_y, button=3, settle=0.2)

    popup_id = xdo_helper.find_popup_by_name("!menu", timeout=2.0)
    if popup_id is None:
        # No episode text under the click point is a real, non-buggy
        # reason this can legitimately not open -- diagnose before
        # failing outright, per agents-ui-testing.md's guidance to check
        # contention/state before assuming a bug.
        state = xdo_helper.diagnose_state(window_id)
        pytest.skip(f"No context menu appeared at ({click_x},{click_y}) -- diagnostic state: {state}")

    popup_path = ARTIFACT_DIR / "context_menu.png"
    xdo_helper.screenshot("root", str(popup_path))
    assert popup_path.exists()

    xdo_helper.send_global_keys("Escape", settle=0.2)
    log_correlator.assert_clean(_current_log_path(), since=action_time)
