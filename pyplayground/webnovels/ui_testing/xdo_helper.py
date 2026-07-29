"""xdotool wrapper for agent-driven UI testing of alphapolis_reader.py (Tkinter).

Works unmodified against a real X11/XWayland desktop session or an Xvfb
virtual display -- the only difference is which DISPLAY is set in the
environment before these functions are called. Xvfb is the recommended
default: see agents-ui-testing.md for the confirmed Wayland root-capture
limitation that makes Xvfb necessary for whole-screen/popup screenshots.

All functions raise RuntimeError with the raw xdotool/ImageMagick stderr on
failure rather than swallowing errors, since a silent failure here (e.g.
"window not found") is exactly the kind of bug that produces a false-pass
UI test.

Findings folded in from agents-ui-testing.md, all confirmed live against
this app, not carried over speculatively:

- On a real GNOME/Mutter desktop, `xdotool search --name` reliably returns
  two window ids for one logical window: the real Tk client window and a
  `mutter-x11-frames` decoration window. Disambiguate by PID first, window
  depth (Tk: 24, frame: 32) as a secondary signal -- see find_window() and
  get_window_depth(). Confirmed live under Xvfb+fluxbox that this does
  NOT hold there: there is exactly one matching window, and Tk's toplevel
  has no `_NET_WM_PID` property at all on that display (`getwindowpid`
  fails for it), so PID-based disambiguation is unavailable rather than
  merely redundant -- find_window() falls back to a plain unambiguous
  name match rather than waiting out its full timeout for a PID match
  that can never arrive on Xvfb.
- Root/whole-screen capture is broken under Wayland/XWayland regardless of
  tool (import, xwd, mss all fail identically); per-window capture by id is
  reliable. Xvfb has no such limitation for either. See screenshot().
- Never use `xdotool windowkill` on this app's windows -- it can crash the
  entire single-process Tk app, not just the targeted Toplevel. This
  module deliberately provides no windowkill wrapper; use close_window()
  (WM_DELETE_WINDOW via `xdotool windowclose`) or a process-level SIGTERM.
- Focus/click sequences are one chained xdotool invocation, not separate
  activate-then-move-then-click calls, so a shared/real display can't steal
  focus in the gap between calls.
- `tk.Menu` popups reuse the same internal window path (`!menu`, `!menu2`,
  ...) across opens/closes, so a name-based search can return a stale,
  already-unmapped window id from an earlier open. Filter by IsViewable
  before trusting a discovered popup id -- see find_popup_by_name() and
  is_viewable().
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

_APPROVAL_MARKER = Path("/tmp/ui_test_portal_approval_seen")


class PendingApprovalError(RuntimeError):
    """Raised when a command exceeds its timeout without completing.

    On a real desktop, this commonly means a GNOME permission dialog
    (screenshot or input access) is waiting for a human to click Allow/Deny
    -- not that the command itself is broken. See screenshot()'s
    approval-handling: wait, don't retry blind, and re-check focus
    afterward since the human's click to approve is itself an interaction
    with the shared display.
    """


def approval_marker_seen(max_age: float = 300.0) -> bool:
    """Whether a pending-approval dialog was seen recently enough to still trust it, within max_age seconds.

    The grant is not assumed to last indefinitely -- it has been observed
    to time out mid-session and require a fresh approval again. This only
    controls whether the first screenshot attempt starts with quick_timeout
    or approval_timeout; it never prevents a fresh approval-wait sequence
    from happening again if a call actually times out.
    """
    if not _APPROVAL_MARKER.exists():
        return False
    try:
        marked_at = float(_APPROVAL_MARKER.read_text().strip())
    except (ValueError, OSError):
        return False
    return (time.time() - marked_at) < max_age


def mark_approval_seen() -> None:
    """Record that a pending-approval dialog was just seen and resolved, timestamped for approval_marker_seen()."""
    _APPROVAL_MARKER.write_text(str(time.time()))


def clear_approval_marker() -> None:
    """Call at the start of a real-desktop test run so a stale marker isn't trusted blindly.

    A stale marker from a previous session should not be trusted blindly.
    """
    _APPROVAL_MARKER.unlink(missing_ok=True)


def _run(cmd: list[str], timeout: float | None = None) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PendingApprovalError(
            f"Command exceeded {timeout}s without completing: {' '.join(cmd)}. "
            "On a real desktop, this commonly means a GNOME permission dialog "
            "is waiting for a human to click Allow/Deny."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def check_tools_available() -> dict[str, bool]:
    """Verify xdotool and at least one screenshot backend are on PATH."""
    return {
        "xdotool": shutil.which("xdotool") is not None,
        "import": shutil.which("import") is not None,  # ImageMagick
        "xwd": shutil.which("xwd") is not None,
        "convert": shutil.which("convert") is not None or shutil.which("magick") is not None,
        "maim": shutil.which("maim") is not None,
        "xwininfo": shutil.which("xwininfo") is not None,
    }


def check_display() -> dict:
    """Confirm DISPLAY is not just set, but backed by a live, usable server.

    A dead or not-yet-started display (Xvfb still booting, or DISPLAY
    pointing at nothing) does not raise an error from most tools -- it just
    returns 1x1 or empty results forever. Call this once before
    find_window() rather than after a failure, since a failure caused by
    this is otherwise indistinguishable from "the app just hasn't drawn its
    window yet".
    """
    result = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, text=True)
    if result.returncode != 0:
        return {"live": False, "width": None, "height": None, "error": result.stderr.strip()}
    parts = result.stdout.strip().split()
    width, height = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (None, None)
    live = bool(width) and bool(height)
    return {"live": live, "width": width, "height": height, "error": None}


def _window_pid(window_id: str) -> int | None:
    result = subprocess.run(["xdotool", "getwindowpid", window_id], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def get_window_depth(window_id: str) -> int | None:
    """Return a window's color depth via xwininfo, as a secondary signal for disambiguating a real client window from a WM decoration frame.

    Useful when PID-based disambiguation isn't conclusive.

    Confirmed live for this app on GNOME/Mutter: the real Tk client window
    reliably reports Depth 24; the mutter-x11-frames decoration window
    reports Depth 32. Treat as a useful cross-check alongside expected_pid
    in find_window(), not a universal replacement for it.
    """
    result = subprocess.run(["xwininfo", "-id", window_id], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "Depth:" in line:
            try:
                return int(line.split(":", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                return None
    return None


def find_window(title_substring: str, expected_pid: int | None = None, timeout: float = 10.0) -> str:
    """Poll for a window whose name contains title_substring, return its window id.

    Polling matters because Tk startup is not instantaneous -- a single
    search right after subprocess.Popen() will frequently miss the window.

    A title match reliably returns more than one window id for this app
    on a real GNOME/Mutter desktop: the mutter-x11-frames decoration
    window alongside the real Tk client window. When expected_pid is
    provided (the PID of the process you launched), it is used to pick
    the matching window rather than blindly returning the first result.

    Confirmed live under Xvfb+fluxbox: Tk's own toplevel does not have
    `_NET_WM_PID` set at all there (`xdotool getwindowpid` returns nothing
    for it, unlike on Mutter where it resolves correctly), and fluxbox
    does not wrap it in a separate decoration window the way Mutter does
    -- there is exactly one matching window id, and PID-matching it is
    simply impossible on that display. Rather than poll to timeout
    waiting for a PID match that can never succeed, a plain name match is
    accepted once `expected_pid` fails to resolve for *every* candidate
    for `pid_grace` seconds -- if a PID pending resolution is genuinely a
    timing issue (candidate exists but its PID registration lags, as on
    Mutter), that still resolves within the grace window; if PID
    information is simply unavailable on this display (Xvfb), the
    fallback engages instead of hanging until `timeout`.
    """
    display_state = check_display()
    if not display_state["live"]:
        raise RuntimeError(f"Display is not live before search: {display_state}. " "Do not proceed with window queries until getdisplaygeometry returns real dimensions.")

    pid_grace_deadline = time.time() + min(3.0, timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(["xdotool", "search", "--name", title_substring], capture_output=True, text=True)
        ids = [line for line in result.stdout.strip().splitlines() if line]
        if ids:
            if expected_pid is not None:
                for candidate in ids:
                    if _window_pid(candidate) == expected_pid:
                        return candidate
                if time.time() >= pid_grace_deadline:
                    # No candidate's PID matched within the grace window --
                    # either PID info isn't available on this display at
                    # all (Xvfb), or genuine ambiguity. A single unambiguous
                    # name match is still trustworthy; more than one means
                    # a real frame-vs-client situation this fallback can't
                    # resolve on its own.
                    if len(ids) == 1:
                        return ids[0]
                    raise RuntimeError(
                        f"Multiple windows match '{title_substring}' ({ids}) and none resolved "
                        f"expected_pid={expected_pid} within {pid_grace_deadline - (deadline - timeout):.0f}s -- "
                        "cannot disambiguate without PID info. Check get_window_depth() manually."
                    )
                # Matched by name but not yet by PID (frame window drawn
                # before the client window registers) -- keep polling
                # rather than falsely returning a decoration window.
            else:
                for candidate in ids:
                    pid = _window_pid(candidate)
                    if pid is not None:
                        return candidate
                if len(ids) == 1:
                    return ids[0]
        time.sleep(0.25)
    raise RuntimeError(f"No matching window found for '{title_substring}' (expected_pid={expected_pid}) after {timeout}s")


def get_mouse_location() -> dict:
    """Return {'x', 'y', 'screen', 'window'} for the current pointer position.

    A stuck or unexpected value here is not necessarily a mousemove bug --
    on a shared display it can mean something else currently has
    pointer/focus control. Treat it as a diagnostic signal, not proof the
    tooling itself is broken -- see diagnose_state().
    """
    output = _run(["xdotool", "getmouselocation", "--shell"])
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {
        "x": int(values["X"]),
        "y": int(values["Y"]),
        "screen": values.get("SCREEN"),
        "window": values.get("WINDOW"),
    }


def get_active_window() -> str | None:
    """Return the currently focused window id, or None if none is focused.

    Cheap pre-flight check before any click sequence: if this does not
    match the window you are about to interact with, re-activate before
    proceeding rather than assuming your last activate call is still in
    effect -- on a shared/real display it may not be.
    """
    result = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True)
    return result.stdout.strip() or None


def diagnose_state(window_id: str) -> dict:
    """Snapshot focus/pointer state for use in a failure message.

    Call this when a verification step looks wrong (screenshot doesn't
    show the expected result, log correlation fails unexpectedly) BEFORE
    concluding the action itself failed or retrying it. On a shared or
    real display, focus and pointer control can be taken by something
    outside this test's control between one command and the next -- a
    mismatch here is evidence of contention, not proof the test logic or
    the application is broken.
    """
    active = get_active_window()
    mouse = get_mouse_location()
    return {
        "expected_window": window_id,
        "active_window": active,
        "focus_matches": active == window_id,
        "mouse": mouse,
        "mouse_in_expected_window": mouse.get("window") == window_id,
    }


def get_window_geometry(window_id: str) -> dict:
    """Return {'x', 'y', 'width', 'height'} in absolute screen coordinates."""
    output = _run(["xdotool", "getwindowgeometry", "--shell", window_id])
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {
        "x": int(values["X"]),
        "y": int(values["Y"]),
        "width": int(values["WIDTH"]),
        "height": int(values["HEIGHT"]),
    }


def activate_window(window_id: str, settle: float = 0.1) -> None:
    """Focus/raise the window with no other action.

    xdotool windowactivate fails with "Your windowmanager claims not to
    support _NET_ACTIVE_WINDOW" on a bare Xvfb display with no window
    manager running (fluxbox not started). That is a real setup problem to
    fix (start fluxbox), not something this function should silently
    swallow.
    """
    _run(["xdotool", "windowactivate", "--sync", window_id])
    time.sleep(settle)


def send_keys(window_id: str, keys: str, settle: float = 0.3) -> None:
    """Send a key combo, e.g. 'Return' or 'Escape' or 'Down Down Return'.

    settle: seconds to sleep after sending, giving Tk time to redraw before
    the next screenshot or action.

    windowactivate and key are chained into one xdotool call for the same
    reason click() chains activate+move+click: on a shared/real display,
    focus can be stolen in the gap between two separate subprocess calls.
    """
    _run(["xdotool", "windowactivate", "--sync", window_id, "key", "--window", window_id, keys])
    time.sleep(settle)


def type_text(window_id: str, text: str, settle: float = 0.2) -> None:
    """Type literal text into the focused widget.

    Uses `--` before text to terminate xdotool's own option parsing --
    without it, text starting with a dash (e.g. "-MERGEFIX") is parsed as
    an unrecognized xdotool flag and errors instead of being typed.
    Confirmed directly against this app.
    """
    _run(["xdotool", "windowactivate", "--sync", window_id, "type", "--window", window_id, "--", text])
    time.sleep(settle)


def click(window_id: str, x: int, y: int, button: int = 1, settle: float = 0.3) -> None:
    """Coordinate click, using window-relative coordinates.

    button: 1 = left, 2 = middle, 3 = right. Right-click (button=3) is what
    opens this app's context menu (tk.Menu, see the "Add to Glossary..."
    popup) -- see find_popup_by_name() and send_global_keys() for driving
    that popup once it's open.

    activate, move, and click are chained into a single xdotool invocation
    deliberately. Three separate calls leaves gaps where a shared/real
    display can steal focus back before the click lands, causing a click
    that silently lands on the wrong window with no error raised.
    """
    _run(
        [
            "xdotool",
            "windowactivate",
            "--sync",
            window_id,
            "mousemove",
            "--window",
            window_id,
            str(x),
            str(y),
            "click",
            str(button),
        ]
    )
    time.sleep(settle)


def send_global_keys(keys: str, settle: float = 0.3) -> None:
    """Send keys via XTEST to whatever currently holds keyboard focus/grab.

    Does not target a specific window id or call windowactivate first.

    Use this instead of send_keys() after opening a popup or context menu.
    A tk.Menu installs a keyboard grab the moment it opens. send_keys()
    calls windowactivate on a specific window id first, which can steal
    focus back from that grab rather than navigating it -- the popup
    closes or the keys go nowhere, with no error raised either way.

    A typical right-click-menu sequence:
        xdo_helper.click(window_id, x, y, button=3)  # open the popup
        xdo_helper.send_global_keys("Escape")  # close it
    """
    _run(["xdotool", "key", keys])
    time.sleep(settle)


def list_visible_windows() -> set[str]:
    """Return the set of all currently visible window ids on the display."""
    result = subprocess.run(["xdotool", "search", "--onlyvisible", ""], capture_output=True, text=True)
    return {line for line in result.stdout.strip().splitlines() if line}


def is_viewable(window_id: str) -> bool:
    """Whether a window is currently actually mapped/visible, via xwininfo's IsViewable state.

    Confirmed directly for this app: Tk reuses the same internal window
    path (!menu, !menu2, ...) across repeated open/close cycles of the
    right-click popup within one app session. A plain name search can
    return a stale, already-unmapped window id from an earlier open rather
    than the one currently on screen. Filtering by IsViewable before
    trusting a discovered window id avoids acting on a window that already
    closed.
    """
    result = subprocess.run(["xwininfo", "-id", window_id], capture_output=True, text=True)
    return result.returncode == 0 and "IsViewable" in result.stdout


def find_popup_by_name(name_pattern: str = "!menu", timeout: float = 2.0, poll_interval: float = 0.02) -> str | None:
    """Discover a tk.Menu popup by Tk's internal window-path naming convention, filtering out stale/closed candidates.

    This is the Tk-specific, confirmed-first technique from
    agents-ui-testing.md: Tk reuses the same internal window path (!menu,
    !menu2, ...) across opens/closes of a popup menu within one app
    session, so a plain name search can return a stale, already-unmapped
    window id from an earlier attempt. Poll in a tight loop immediately
    after the triggering click -- the window may not exist yet at the
    instant the click is sent, and can close again quickly -- and filter
    by is_viewable() before trusting a match.

    Try this before find_popup_by_ewmh_type(): it is the technique already
    confirmed to work for this app's tk.Menu popups, whereas the EWMH path
    is a toolkit-agnostic fallback not yet confirmed here.

    Returns the first currently-viewable matching window id, or None if
    none appeared within timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(["xdotool", "search", "--name", name_pattern], capture_output=True, text=True)
        for wid in result.stdout.split():
            if is_viewable(wid):
                return wid
        time.sleep(poll_interval)
    return None


def find_popup_by_ewmh_type(
    window_type_substrings: tuple[str, ...] = ("POPUP_MENU", "MENU", "DROPDOWN_MENU"),
) -> list[str]:
    """Discover popup/menu windows by EWMH _NET_WM_WINDOW_TYPE instead of by name/class guessing.

    Toolkit-agnostic fallback for when find_popup_by_name()'s Tk-specific
    !menu convention doesn't match (e.g. a popup this app doesn't currently
    have, or a future toolkit change). Not the primary path here since
    !menu is already confirmed to work for this app's tk.Menu popups.

    Returns currently-viewable candidate window ids (already filtered by
    is_viewable()), so a caller doesn't need to re-check.
    """
    result = subprocess.run(["xdotool", "search", "--class", ""], capture_output=True, text=True)
    candidates = []
    for wid in result.stdout.split():
        prop = subprocess.run(["xprop", "-id", wid, "_NET_WM_WINDOW_TYPE"], capture_output=True, text=True)
        if prop.returncode != 0:
            continue
        if any(sub in prop.stdout.upper() for sub in window_type_substrings) and is_viewable(wid):
            candidates.append(wid)
    return candidates


def move_window(window_id: str, x: int, y: int) -> None:
    """Reposition a window to absolute screen coordinates (x, y).

    Useful when two dialogs need to be open at once and one covers UI that
    needs to be clicked on the other -- move the obstruction out of the way
    rather than fighting window stacking/z-order.
    """
    _run(["xdotool", "windowmove", window_id, str(x), str(y)])


def drag_select(window_id: str, x1: int, y1: int, x2: int, y2: int, settle: float = 0.3) -> None:
    """Drag-select from (x1, y1) to (x2, y2), window-relative coordinates.

    Needed for selecting an exact substring in the Tk Text widget where a
    single click or double-click word-selection isn't sufficient (an exact
    range, or CJK source text with no space word boundaries).
    """
    _run(["xdotool", "mousemove", "--window", window_id, str(x1), str(y1)])
    _run(["xdotool", "mousedown", "1"])
    _run(["xdotool", "mousemove", "--window", window_id, str(x2), str(y1)])
    _run(["xdotool", "mouseup", "1"])
    time.sleep(settle)


def _screenshot_import(window_id: str, output_path: str, timeout: float | None = None) -> None:
    _run(["import", "-window", window_id, output_path], timeout=timeout)


def _screenshot_xwd(window_id: str, output_path: str, timeout: float | None = None) -> None:
    xwd_path = output_path + ".xwd"
    _run(["xwd", "-id", window_id, "-out", xwd_path], timeout=timeout)
    if shutil.which("convert"):
        _run(["convert", xwd_path, output_path])
    else:
        _run(["magick", xwd_path, output_path])
    subprocess.run(["rm", "-f", xwd_path])


def _screenshot_maim(window_id: str, output_path: str, timeout: float | None = None) -> None:
    _run(["maim", "--window", window_id, output_path], timeout=timeout)


_SCREENSHOT_BACKENDS = {
    "import": (_screenshot_import, "import"),
    "xwd": (_screenshot_xwd, "xwd"),
    "maim": (_screenshot_maim, "maim"),
}


def _looks_blank(image_path: str) -> bool:
    """Heuristic check for the documented GNOME-Wayland failure mode of a silently-blank capture.

    An X11-style window capture can silently succeed but return a solid
    black (or otherwise uniform) image instead of real content.

    Returns True if the image is suspiciously uniform. A False result is
    not a guarantee the capture is correct, only that it isn't trivially
    blank.
    """
    if not (shutil.which("identify") or shutil.which("magick")):
        return False  # can't check; don't block on a missing optional tool
    identify_bin = ["magick", "identify"] if shutil.which("magick") and not shutil.which("identify") else ["identify"]
    result = subprocess.run(identify_bin + ["-format", "%[fx:standard_deviation]", image_path], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        return float(result.stdout.strip()) < 0.001
    except ValueError:
        return False


def screenshot(
    window_id: str,
    output_path: str,
    tool: str = "auto",
    verify_not_blank: bool = True,
    quick_timeout: float = 5.0,
    approval_timeout: float = 120.0,
) -> str:
    """Capture the given window (not the whole screen) to output_path.

    tool: "auto" (try import, then xwd, then maim, use the first one that
    produces a real-looking image), or force a specific backend by name.

    verify_not_blank: on GNOME Wayland, X11-style window capture tools are
    documented to sometimes succeed with exit code 0 while returning a
    solid black or otherwise uniform image -- a Wayland design limitation
    (one client cannot freely read another's buffer contents), not a bug in
    any particular tool. When True (default), each attempt is checked with
    a cheap ImageMagick `identify` call and rejected if it looks blank,
    falling through to the next backend in "auto" mode. Under Xvfb this
    check should never trigger, since there is no Wayland compositor
    gating buffer access at all.

    quick_timeout / approval_timeout: each backend attempt first uses
    quick_timeout unless a recent approval was already seen this session
    (see approval_marker_seen()), in which case approval_timeout is used
    from the start. If an attempt exceeds its timeout, this is treated as
    a probable pending GNOME permission dialog rather than a hard failure:
    a message is printed asking a human to check for and approve the
    dialog, and the same attempt is retried once with approval_timeout.
    This retry always happens on a timeout, regardless of whether a marker
    was previously set -- approval has been observed to expire mid-session.

    After any attempt that had to wait out approval_timeout, this function
    re-activates window_id before returning, since the human's click to
    approve the dialog is itself an interaction with the shared display
    and can move focus.

    Callers should screenshot both before and after any interaction -- a
    missing expected result afterward is ambiguous on its own but a
    before/after pair makes it possible to tell "wrong coordinates" from
    "slow background thread" from "action genuinely failed".
    """
    if window_id == "root" and tool in ("xwd", "maim"):
        raise ValueError(
            f"Root-window capture via '{tool}' is not implemented here (xwd's root flag is `-root`, "
            "not `-id root`; maim's root-capture syntax hasn't been verified). Use tool='import' or "
            "tool='auto' for root captures."
        )

    if tool == "auto":
        if window_id == "root":
            # Root-window capture only has a confirmed-working path through
            # `import -window root`. Don't silently fall through to
            # backends whose root-capture behavior is unconfirmed.
            candidates = ["import"] if shutil.which("import") else []
        else:
            candidates = [name for name in ("import", "xwd", "maim") if shutil.which(name)]
    elif tool in _SCREENSHOT_BACKENDS:
        candidates = [tool]
    else:
        raise ValueError(f"Unknown screenshot tool '{tool}'; expected one of {list(_SCREENSHOT_BACKENDS)} or 'auto'")

    if not candidates:
        raise RuntimeError("No screenshot backend available (checked import, xwd, maim). " "Install ImageMagick (`import`), xorg-x11-server (`xwd`), or maim.")

    errors = []
    for name in candidates:
        capture_fn, _ = _SCREENSHOT_BACKENDS[name]
        marker_fresh = approval_marker_seen()
        first_timeout = approval_timeout if marker_fresh else quick_timeout
        had_to_wait_for_approval = False
        try:
            capture_fn(window_id, output_path, timeout=first_timeout)
        except PendingApprovalError:
            print(
                f"\n>>> ACTION REQUIRED: '{name}' screenshot has not completed within {first_timeout}s. "
                "This commonly means a GNOME permission dialog (screenshot access) is waiting for a "
                "human to click Allow/Deny -- this can happen again even if one was already approved "
                f"earlier this session, since the grant can time out. Check the desktop now -- waiting "
                f"up to {approval_timeout}s for a response before treating this as a real failure.\n"
            )
            try:
                capture_fn(window_id, output_path, timeout=approval_timeout)
            except PendingApprovalError as exc2:
                errors.append(f"{name}: still not responding after {approval_timeout}s: {exc2}")
                continue
            mark_approval_seen()
            had_to_wait_for_approval = True
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")
            continue

        if had_to_wait_for_approval:
            activate_window(window_id)

        if verify_not_blank and _looks_blank(output_path):
            errors.append(f"{name}: capture succeeded but image looks blank/uniform -- likely the GNOME-Wayland buffer-access limitation, not a tool bug")
            continue
        return output_path

    raise RuntimeError(
        "All screenshot backends failed or produced blank images:\n" + "\n".join(errors) + "\nIf this is real-desktop (XWayland) mode, this is a known GNOME Wayland limitation -- "
        "see agents-ui-testing.md, 'Screenshotting' section. Xvfb mode does not have this limitation."
    )


def close_window(window_id: str) -> None:
    """Send WM_DELETE_WINDOW to the given window (a real close request, not a connection-level kill).

    Deliberately no windowkill wrapper exists in this module -- see the
    module docstring and agents-ui-testing.md's "Closing the app" section
    for why `xdotool windowkill` is unsafe against this app.

    WARNING -- confirmed live, reproducibly, against this specific app
    under Xvfb: sending WM_DELETE_WINDOW via `xdotool windowclose` to a
    Toplevel dialog (Load Novel, tested directly) reliably crashes the
    entire process, distinct from and in addition to the already-known
    windowkill danger. The app's own Playwright/Chromium BrowserWorker
    (headless, started unconditionally at launch) is implicated: an
    isolated plain-Tk script with no Playwright involved survived an
    identical windowclose against the same Xvfb display without issue,
    while the real app crashed with a Node.js EPIPE following an X
    BadWindow error on X_UnmapWindow -- i.e. Playwright's own Node driver
    process appears to hold an X11 connection that reacts fatally to a
    WM_DELETE_WINDOW-driven unmap under Xvfb specifically. Clicking a
    dialog's own real Cancel/Close button (which calls Tk's `.destroy()`
    directly, bypassing the WM_DELETE_WINDOW protocol path entirely) was
    confirmed safe in the same session. NOT yet confirmed whether this
    also reproduces outside Xvfb (real XWayland desktop) -- that is a
    separate, unconfirmed question and this crash should be treated as a
    real application-level finding worth its own investigation (see
    DESIGN.md), not merely a testing-tooling quirk to route around
    silently. Prefer clicking the dialog's own Cancel/Close button over
    calling this function against alphapolis_reader.py until that
    investigation resolves it.
    """
    _run(["xdotool", "windowclose", window_id])


def launch_and_track(command: list[str], stdout_log: str | None = None, env: dict | None = None) -> subprocess.Popen:
    """Launch the app and return the Popen handle so its PID can be tracked and killed on teardown explicitly.

    Explicit tracking avoids leaving an orphaned process behind. Window-id
    reuse/ambiguity gets worse with every stray process left running, so
    cleanup is not optional cosmetic tidiness.

    stdout_log: if given, redirect the launched process's stdout/stderr to
    this file path. Confirmed useful directly: some errors only ever print
    to the console (e.g. print(..., file=sys.stderr)), not the app's own
    configured log file, so log_correlator.py's file-based checks alone can
    miss them.
    """
    if stdout_log:
        log_file = open(stdout_log, "w")
        return subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    return subprocess.Popen(command, env=env)
