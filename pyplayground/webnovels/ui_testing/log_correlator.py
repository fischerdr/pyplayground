"""Correlate a UI action's timestamp with alphapolis_reader.py's log output.

A screenshot only proves something was drawn. It does not prove the button
handler ran cleanly -- a caught-and-logged exception can leave the UI
looking completely normal. This module reads the log window immediately
following an action and flags anything at ERROR/CRITICAL level, so every UI
action gets a "looked right AND ran right" check (see agents-ui-testing.md
and the module's own example test for how the two checks are combined).

Matches this project's actual logging format, confirmed against a real
log file under logs/app_log_*.log rather than assumed from another
project's convention (pyplayground/utils/logging_utils.py's
log_format_file), which has no milliseconds and an extra bracketed
function-name field the generic "module - LEVEL - message" shape doesn't:
    2026-07-28 15:12:35 - pyplayground.webnovels.llm_translate - ERROR - [_translate_chunk_once] - message
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path

LOG_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - " r"(?P<module>\S+) - (?P<level>\w+) - \[(?P<func>[^\]]*)\] - (?P<message>.*)$")

FAILURE_LEVELS = {"ERROR", "CRITICAL"}


def lines_since(log_path: str, since: datetime) -> list[dict]:
    """Return parsed log entries with timestamp >= since.

    Reads the whole file each call rather than tailing/seeking, since a
    single UI test session's log is small; simplicity here beats premature
    optimization for a test helper.

    The project's log timestamps have only second resolution (no
    milliseconds, unlike a more granular logging config elsewhere), so two
    events within the same wall-clock second cannot be ordered relative to
    each other by timestamp alone. assert_clean()'s grace window exists
    precisely to avoid this being a false-positive source at a since
    boundary.
    """
    entries = []
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    for line in path.read_text(errors="replace").splitlines():
        match = LOG_LINE_RE.match(line)
        if not match:
            continue
        ts = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        if ts >= since:
            entries.append(match.groupdict() | {"ts": ts})
    return entries


def assert_clean(log_path: str, since: datetime, grace: float = 1.0) -> None:
    """Raise AssertionError if any ERROR/CRITICAL line appears after since.

    A small grace window is subtracted from since to avoid catching the
    previous action's tail, and to absorb the log's one-second timestamp
    resolution.
    """
    window_start = since - timedelta(seconds=grace)
    bad = [e for e in lines_since(log_path, window_start) if e["level"] in FAILURE_LEVELS]
    if bad:
        details = "\n".join(f"  {e['ts']} {e['module']} [{e['func']}]: {e['message']}" for e in bad)
        raise AssertionError(f"Log errors found following UI action:\n{details}")


def find_expected_marker(log_path: str, since: datetime, marker_substring: str) -> bool:
    """Check whether a specific expected log line appeared.

    This is positive confirmation, not just absence of errors -- e.g.
    confirming a button handler's entry log line actually fired at all.
    """
    return any(marker_substring in e["message"] for e in lines_since(log_path, since))


def wait_for_log_line(log_path: str, marker_substring: str, timeout: float = 60.0, poll_interval: float = 0.5, since: datetime | None = None) -> bool:
    """Block until a specific log line appears, or timeout elapses.

    Needed for reproducing a timing-sensitive race: some bugs only
    reproduce if an action (e.g. clicking "Next") happens at the exact
    moment a background operation reaches a specific point, not after
    waiting for everything to fully settle -- waiting fully means the race
    window has already closed by definition (see agents-ui-testing.md's
    "Reproducing a timing-sensitive race" section, which this generalizes).
    Poll for the log line that signals the race window opening, then act
    immediately:

        if log_correlator.wait_for_log_line(log_path, "Episode translated successfully"):
            xdo_helper.click(window_id, x, y)  # act immediately, not after a fixed sleep

    since: the timestamp to search from. Defaults to the moment this
    function is called, which is wrong whenever the triggering action
    (e.g. launching the app) happened before this call -- confirmed live:
    a fast background operation (a cache-hit episode load) can log its
    completion marker within 1-2 seconds of process launch, which can
    already be in the past by the time a caller gets around to calling
    this function (window discovery alone can take several seconds).
    Pass the actual pre-action timestamp explicitly in that case, or this
    will report a timeout even though the marker really did appear.

    Returns True if the marker was seen within timeout, False if it timed
    out first -- callers should check this rather than assuming the wait
    always succeeds.
    """
    deadline = time.time() + timeout
    start = since if since is not None else datetime.now()
    while time.time() < deadline:
        if find_expected_marker(log_path, start, marker_substring):
            return True
        time.sleep(poll_interval)
    return False


def latest_log_file(logs_dir: str = "logs") -> str:
    """Return the path to the most recently created app_log_*.log file.

    Convenience for test fixtures: the app names its log file with a
    launch-time timestamp (setup_logging() in logging_utils.py), so the
    exact filename isn't known until after the app is launched.
    """
    candidates = sorted(Path(logs_dir).glob("app_log_*.log"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No app_log_*.log files found under {logs_dir}/")
    return str(candidates[-1])
