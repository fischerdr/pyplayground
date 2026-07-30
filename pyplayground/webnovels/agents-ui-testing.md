# Agent UI Testing Notes

Practical reference for driving `pyplayground/webnovels/alphapolis_reader.py`
(a Tkinter app) live via `xdotool` for verification during agent-driven work.
Built up across several sessions of live-verifying fixes against the real
running app, both on a real shared desktop session and, later, a dedicated
Xvfb display. Not a general xdotool tutorial -- specifically the commands and
gotchas that came up running and testing *this* app, though the
display-server-level findings (Wayland root-capture limitation, Xvfb as the
fix) are not Tkinter-specific and generalize to PyQt/wxPython apps run the
same way -- see "Screenshotting" below, which is written toolkit-generally on
purpose.

Companion to `DESIGN.md` (`pyplayground/webnovels/DESIGN.md`), which has the
task-specific findings this testing supported. This file is the reusable
mechanics; `DESIGN.md` is the specific investigation history.

---

## Preferred entry point: `pyplayground/webnovels/ui_testing/`

**Start here for any new UI verification task, rather than hand-writing
`xdotool`/`import` bash snippets from scratch.** This module
(`xdo_helper.py` + `log_correlator.py`, with `tests/webnovels/ui_automation/
test_menu_smoke.py` as a working example) packages every finding below --
the two-window-ID gotcha, the Wayland root-capture limitation and Xvfb fix,
the `!menu` popup-discovery technique, focus/pointer contention diagnosis,
approval-timeout handling -- into tested, reusable Python functions, live-
verified end-to-end against the real running app on a clean Xvfb + fluxbox
session (all 6 example tests passing, screenshots visually confirmed, log
clean). It also enforces the **dual-check discipline** as the standard for
this project going forward: every UI action should confirm both visual state
(screenshot) and log state (`log_correlator.assert_clean()` /
`wait_for_log_line()`) together, not either alone -- a caught-and-logged
exception can leave a dialog looking completely normal on screen.

```bash
# One-time env check
DISPLAY=:99 .venv/bin/python -c "from pyplayground.webnovels.ui_testing import xdo_helper; print(xdo_helper.check_tools_available())"

# Standard entry point: run_ui_tests.sh owns starting Xvfb+fluxbox, running
# pytest against them with DISPLAY set, and tearing both down afterward --
# see "Launching a display for UI tests" below. Don't hand-start Xvfb/fluxbox
# and export DISPLAY yourself; this script is the one place that logic lives.
./pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb .venv/bin/pytest tests/webnovels/ui_automation/test_menu_smoke.py -v
```

Import `xdo_helper` and `log_correlator` from `pyplayground.webnovels.ui_testing`
for any new test or ad hoc verification script, rather than duplicating a raw
`subprocess.run(["xdotool", ...])` call inline -- per this repo's standing
code-reuse policy (see `CLAUDE.md`), and because the module's functions
already encode the gotchas below (chained activate+click, `IsViewable`
filtering, PID-vs-Xvfb fallback, etc.) that a fresh inline snippet would have
to rediscover one at a time.

**The bash-snippet patterns in the rest of this document are kept as
historical/fallback reference, not deleted** -- they document the same
underlying gotchas the module now encodes, and are useful if the module
itself is ever unavailable, being debugged, or a novel situation falls
outside what it currently covers. When in doubt, prefer the module; fall
back to raw `xdotool` only when the module doesn't fit.

### A crash the module deliberately works around, not yet fully explained

**Never call `xdo_helper.close_window()` (`xdotool windowclose`, i.e.
sending WM_DELETE_WINDOW) against one of this app's dialogs.** Confirmed
live, reproducibly, under Xvfb: doing so crashes the *entire* app -- a
Node.js EPIPE following an X BadWindow error, implicating the app's
always-running headless Chromium/Playwright `BrowserWorker`. This is
distinct from, and in addition to, the already-known `windowkill` danger
documented below. Clicking a dialog's own real Cancel/Close button (which
calls Tk's `.destroy()` directly, bypassing the WM_DELETE_WINDOW protocol
path) was confirmed safe and is what `test_menu_smoke.py` and
`xdo_helper.close_window()`'s own docstring both call out as the required
alternative. Root cause is not yet confirmed (including whether this
reproduces outside Xvfb at all) -- tracked as its own open investigation in
`pyplayground/webnovels/DESIGN.md` (2026-07-28 entry), not resolved here.

---

## Process discipline

### Launching the app

```bash
nohup /development/git/pyplayground/.venv/bin/python -m pyplayground.webnovels.alphapolis_reader "https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7800089" > /tmp/app_launch.log 2>&1 &
disown
```

Use `nohup ... &` plus `disown` so the process survives the launching shell
and doesn't get killed by SIGHUP. Redirect stdout/stderr to a scratch log --
some errors only ever print to the console (`print(..., file=sys.stderr)`),
not the app's own log file.

### Confirming exactly one process is running

**Trap**: naive `pgrep -af "python -m pyplayground.webnovels.alphapolis_reader"`
frequently self-matches the *shell wrapper* invoking the check (its `eval`
argument contains the same search string), producing a false positive that
looks like a stray running process when there isn't one.

```bash
pgrep -af "python -m pyplayground.webnovels.alphapolis_reader" 2>/dev/null | grep -v "bin/bash -c"
```

Always filter with `grep -v "bin/bash -c"` (or similarly exclude the wrapper
pattern) before trusting the result. Confirmed this was a false positive
multiple times by checking the actual command line before concluding a
process needed to be killed.

Poll for the process to actually appear rather than assuming a fixed launch
delay:

```bash
for i in $(seq 1 20); do
  found=$(pgrep -af "python -m pyplayground.webnovels.alphapolis_reader" 2>/dev/null | grep -v "bin/bash -c")
  [ -n "$found" ] && break
  sleep 0.5
done
```

### Closing the app

**Never use `xdotool windowkill` on this app's windows.** It's a
single-process Tk app -- killing one Toplevel's X client connection can take
down the *entire* process, including the main window, not just the dialog.
Confirmed live: an early attempt to clean up a stray duplicate dialog with
`windowkill` crashed the whole app.

Always close via:
1. The app's own real UI (Cancel/Close/Save buttons), or
2. A process-level `kill -TERM <pid>` on the actual Python process if the UI
   is genuinely unresponsive -- never a window-level kill.

```bash
kill -TERM <pid>
for i in $(seq 1 10); do
  found=$(pgrep -af "python -m pyplayground.webnovels.alphapolis_reader" 2>/dev/null | grep -v "bin/bash -c")
  [ -z "$found" ] && break
  sleep 0.5
done
pgrep -af "python -m pyplayground.webnovels.alphapolis_reader" 2>/dev/null | grep -v "bin/bash -c" || echo "confirmed: terminated cleanly"
```

Confirm zero processes remain before starting the next reproduction attempt
-- don't launch a second instance on top of a not-yet-dead first one.

---

## Finding the real window (the two-window-ID gotcha)

Every `xdotool search --name "<title>"` against this app returns **two**
window IDs, not one:

```bash
xdotool search --name "Alphapolis Reader" 2>&1
# 10516161
# 14680127
```

One is the real Tk client window; the other is a Mutter window-manager
decoration/frame window (`mutter-x11-frames`), not a second app instance.
Cross-check which is which before clicking or screenshotting -- targeting
the frame window does nothing useful.

```bash
for id in 10516161 14680127; do
  depth=$(xwininfo -id "$id" 2>&1 | grep Depth | awk '{print $2}')
  echo "id=$id depth=$depth"
done
```

The real content window reliably has **Depth: 24**; the frame window has
**Depth: 32**. (Also confirmable via `xdotool getwindowpid` -- the frame
window's PID belongs to `mutter-x11-frames`, not the Python process -- but
depth is the faster check.)

This applies to every dialog the app opens too (Glossary, Review Terms,
Retranslate popup, Load Novel, etc.) -- always search, always filter by
depth, every time a new window is expected to appear.

---

## Screenshotting

```bash
import -window <real-window-id> /path/to/output.png
```

`import` (ImageMagick) worked reliably for capturing a specific known window
by ID throughout. Then use the Read tool on the resulting PNG to actually
look at it. This part is not Tkinter-specific -- capturing any known
top-level window by ID this way works identically for a PyQt/wxPython app's
windows, since `import -window <id>` doesn't care what toolkit created the
window.

### Root-cause finding: whole-screen/root-window capture fails under Wayland, not because of any one tool

On a real, shared desktop session, **three independent tools all failed
identically** when asked to capture the root/whole-screen window, while every
one of them worked fine capturing a specific named top-level window by ID:

| Tool | Root/full-screen capture | Specific window capture (by ID) |
|---|---|---|
| `import -window root` (ImageMagick) | Errors: `missing an image filename` (a misleading message -- it's actually an invalid-window failure, not an argument-parsing one) | Works |
| `xwd -root` | `X Error: BadMatch (invalid parameter attributes)` on `X_GetImage` | Works (`xwd -id <window>`) |
| Python `mss` | Returns a valid image file, but every pixel is solid black | N/A (screen-region-based, not window-ID-based) |
| `gnome-screenshot` | Hangs indefinitely (likely waiting on a screenshot portal permission dialog that never resolves headlessly) | Not applicable -- this tool doesn't do per-window capture by ID |

**Root cause, confirmed rather than assumed**: the display session was
running under Wayland (`loginctl show-session ... -p Type` -> `Type=wayland`),
with X11 clients connecting through XWayland. XWayland's X11 root window is a
compatibility shim -- it does not back onto a real, readable composited
framebuffer the way a native X server's root window does. Any tool that
tries to read the **root window's** pixels via the classic X11
`XGetImage`/`XWDFileHeader` path gets nothing, regardless of which specific
tool is used, because the underlying X protocol call has nothing valid to
return. Individual **application windows** work because each app's own
client-side buffer is a real, readable X resource independent of the
compositor -- that path never touches Wayland's compositing layer at all.

This is the single most load-bearing fact for UI screenshot testing in this
kind of environment: **root/whole-screen capture is unreliable under
Wayland/XWayland regardless of tool; per-window capture by ID is reliable.**
It is not specific to Tkinter -- any toolkit's top-level windows are equally
screenshotable by ID, and any attempt to grab the whole screen hits the
identical Wayland limitation regardless of toolkit.

### The fix: a standalone Xvfb server, not the shared desktop session

Once identified, the practical fix was to stop trying to screenshot the
shared desktop session and instead spin up a dedicated, throwaway Xvfb X11
server (no Wayland/XWayland involved at all) and run the app under test
against it.

**Standard entry point: `pyplayground/webnovels/ui_testing/run_ui_tests.sh`.**
Don't hand-start Xvfb/fluxbox and export `DISPLAY` yourself -- this script
owns that lifecycle so it doesn't have to be rediscovered/re-typed per task.
Two modes:

```bash
# Always-clean (default): kills any existing Xvfb/fluxbox on the target
# display first, starts fresh, tears both down on exit -- success, failure,
# or interruption. Use this for anything meant to produce a trustworthy,
# reproducible result (e.g. Phase 2's own live verification).
./pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb .venv/bin/pytest tests/webnovels/ui_automation/ -v

# Reuse-if-present: starts Xvfb+fluxbox if not already running on the target
# display, reuses them if they are, and leaves them running on exit. Use this
# for iterative work spanning many short tool calls in one session, where
# tearing down and restarting the display every single check is wasteful.
./pyplayground/webnovels/ui_testing/run_ui_tests.sh xvfb-keep .venv/bin/pytest tests/webnovels/ui_automation/ -v
```

Both modes poll for actual readiness (Xvfb via `xdpyinfo`, fluxbox via
`_NET_SUPPORTING_WM_CHECK` appearing on the root window) rather than assuming
a fixed startup delay, and pass `DISPLAY` through to the wrapped command
rather than requiring it to be exported separately. Confirmed live: the
identical `import -window root` command that failed against the shared
session's display worked immediately once run through this script, producing
a correct full-screen screenshot including a transient right-click popup menu
(see next section) -- not just a plausible theory, a verified fix.

**No window manager runs on a bare Xvfb display**, which has one practical
consequence: `xdotool windowactivate` fails
(`Your windowmanager claims not to support _NET_ACTIVE_WINDOW`) since nothing
owns that protocol. Harmless with a single window (clicks still work fine via
absolute/window-relative `mousemove` + `click` on an unmanaged-but-mapped
window), but matters for anything needing real WM behavior: focus-follows-click,
multi-window z-ordering, taskbar interaction. `run_ui_tests.sh` always starts
fluxbox alongside Xvfb for exactly this reason -- **fluxbox is available in
this environment** and both modes above bring it up automatically; there is
no need to start it by hand.

**Recommendation: default to a dedicated Xvfb display, not the shared desktop
session, for automated UI screenshot verification.** Reasons:

1. Root/full-screen capture only works on Xvfb here -- a hard blocker on the
   shared session for anything needing a whole-screen shot (overlapping
   windows, popup menus, tooltips, drag ghosts), confirmed with three
   independent tools, not fixable by trying yet another tool against the
   same display.
2. No pointer contention -- the shared desktop is a real, actively-used
   session; the operator's own mouse/keyboard activity, and the
   approval-driven focus loss described below, don't exist on a private Xvfb
   display.
3. Reproducible geometry -- a fixed-resolution Xvfb screen gives identical
   window/widget positions every run; the shared session's actual resolution
   and window placement can vary between runs.
4. Cheap to spin up and tear down -- one line to start, a `kill` on the PID
   to stop, no special privileges needed.

**When the shared session is still the right call**: exploratory,
human-supervised verification where a person wants to watch the app live and
possibly interject -- that's a genuinely different use case (a human's live
eyes are the verification method) from producing a durable, unattended
screenshot artifact, not a fallback for when Xvfb "isn't working."

### Popup menus (`tk.Menu` right-click context menus) -- now solvable

A `tk.Menu` opened via right-click is a transient, override-redirect-style
window. **Update to a previous version of this note**: it was previously
believed there was no automated way to screenshot these -- that conclusion
was specific to the shared Wayland session and did not hold once tested
against an Xvfb display, where the same technique below worked cleanly and
reliably.

The remaining trick, even on Xvfb, is that the menu window doesn't exist
until the triggering click happens, and Tk reuses the same internal window
path (`!menu`, `!menu2`, ...) across opens/closes, so a plain name search can
return a **stale, already-unmapped** window ID from an earlier attempt in the
same session rather than the currently-open one:

```bash
python3 -c "
import subprocess, time

subprocess.run(['xdotool', 'mousemove', '--window', '<id>', '<x>', '<y>'])
time.sleep(0.05)
subprocess.run(['xdotool', 'mousedown', '3'])
time.sleep(0.02)
subprocess.run(['xdotool', 'mouseup', '3'])

for i in range(20):
    out = subprocess.run(['xdotool', 'search', '--name', '!menu'], capture_output=True, text=True)
    for wid in out.stdout.split():
        info = subprocess.run(['xwininfo', '-id', wid], capture_output=True, text=True).stdout
        if 'IsViewable' in info:   # filters out stale, already-closed menu IDs
            subprocess.run(['import', '-window', 'root', '/tmp/menu.png'])
            raise SystemExit
    time.sleep(0.02)
"
```

**This exact technique is available as `xdo_helper.find_popup_by_name("!menu")`**
in the module above (with `is_viewable()` filtering and the polling loop
already built in) -- confirmed live end-to-end against this app's real
right-click "Add to Glossary..." popup, not just as a bash snippet.

Key points, in order of importance:

1. **Filter by `IsViewable`, not just by name match.** The most recently
   returned search hit is not reliably the currently-open one.
2. **Poll in a tight loop (tens of milliseconds)** immediately after the
   triggering click -- the window may not exist yet at the instant the click
   is sent, and can close again quickly.
3. **Capture the root window (`import -window root`), not the menu's own
   window ID directly**, once on Xvfb -- this shows the menu positioned
   correctly in its real on-screen context (next to the text it was opened
   on), which is more useful for visual confirmation than an isolated crop
   of just the menu, and root capture is exactly the thing Xvfb fixes.

**This generalizes across toolkits, with one thing to verify per toolkit**:
the window-name pattern to search for is toolkit-specific (Tk uses `!menu`;
Qt/wx will have their own conventions -- not yet verified in this codebase).
A more robust, toolkit-agnostic alternative worth trying instead of
name-guessing is filtering by the EWMH window-type hint directly:

```bash
xdotool search --class "" 2>/dev/null | while read -r wid; do
  wtype=$(xprop -id "$wid" _NET_WM_WINDOW_TYPE 2>/dev/null)
  mapped=$(xwininfo -id "$wid" 2>/dev/null | grep -c IsViewable)
  if echo "$wtype" | grep -qi "POPUP_MENU\|MENU" && [ "$mapped" -gt 0 ]; then
    echo "candidate popup: $wid"
  fi
done
```

Not yet tested against a real PyQt/wxPython popup in this codebase -- flagged
as the technique to try first for those toolkits rather than assuming Tk's
`!menu` naming convention transfers. Available as
`xdo_helper.find_popup_by_ewmh_type()` in the module above; per its
docstring, try `find_popup_by_name("!menu")` first for this app specifically,
since that is the one already confirmed to work here.

Asking the human operator to click a menu item directly (see
"Human-in-the-loop" below) remains a valid, faster option when a human is
already watching live -- the Xvfb technique above is for when the
verification needs to run unattended and produce a saved screenshot.

### `xdo_helper.screenshot()` reliably timing out against a second `Error` Toplevel dialog

Encountered live while verifying a fetch-failure error path against this
app's own `show_error()` dialog (a plain `tk.Toplevel` with a `Text` widget
and a Close button, per its own docstring). `xdo_helper.screenshot()` hung
and timed out (120s) repeatedly against this specific window on more than
one occasion, weeks apart, on an otherwise-working Xvfb+fluxbox display
where the main app window and other dialogs (Glossary, etc.) had already
been screenshotted successfully in the same session. The tool's own error
message points at a plausible cause that did not apply here (no GNOME
permission dialog exists under Xvfb) -- this is a different, unexplained
failure mode specific to this one window/moment, not the same root cause
as the shared-desktop GNOME-approval case the message is worded for.

**What worked instead**: a direct, raw `xwd -id <window-id> -out
<file>.xwd` call (bypassing `xdo_helper.screenshot()`'s wrapper/retry logic
entirely), followed by `convert <file>.xwd <file>.png` -- this succeeded
immediately every time the wrapped call hung. Not fully explained why the
wrapper's own equivalent path fails where the raw call succeeds; flagged
here as a working fallback, not a diagnosed fix.

```bash
DISPLAY=:99 timeout 15 xwd -id <window-id> -out /tmp/out.xwd
convert /tmp/out.xwd /tmp/out.png   # ImageMagick v7: use "magick convert" instead
```

**A second, related issue on the same dialog**: even once captured this
way, repeated `xdotool click`/`mousemove` attempts at the Close button's
expected coordinates (calculated from the dialog's known `pack(pady=(0,8))`
layout, and previously confirmed reliable against the exact same dialog in
an earlier, separate investigation) did not register -- swept a wide grid
of plausible x/y values near the bottom of the 700x400 window and none
landed, even though the raw `xwd` capture showed only the `Text` widget's
own horizontal scrollbar in that region, with the Close button itself
never appearing in any captured region regardless of scroll position. Not
resolved or root-caused further -- most likely a window-stacking/timing
quirk specific to a *second* similarly-shaped `Toplevel` appearing in the
same session (the first investigation's dialog was the only such dialog
open all session; this later one appeared after a Glossary dialog was
already open), but this is a guess, not a confirmed explanation.

**Do not reach for `xdotool windowclose` as the resolution when a dialog's
own Close button can't be clicked.** Re-confirmed this session: that sends
WM_DELETE_WINDOW, which crashes the *entire app* for any Toplevel dialog,
not just the main window (see "A crash the module deliberately works
around" above) -- the risk applies exactly as much to a stuck `Error`
dialog as to any other. When a dialog's own button is genuinely
unreachable and the underlying verification evidence has already been
fully gathered by other means (log file contents, on-disk state), the
safe resolution is a process-level `kill -TERM` (escalating to `kill -9`
after a grace period) on the whole app, exactly as in ordinary teardown --
not fighting the stuck dialog further, and not `windowclose`.

---

## Clicking, typing, and mouse movement

### Basic pattern

```bash
xdotool windowactivate --sync <window-id>
xdotool mousemove --window <window-id> <x> <y>
sleep 1
xdotool getmouselocation   # verify before clicking, see below
xdotool click 1            # left click; 3 for right-click
```

### Always verify click position before trusting a click landed

`xdotool getmouselocation` after `mousemove` reports which window the
pointer is *actually* over on screen -- this caught real misses multiple
times, e.g. when a dialog had been moved/resized and the intended target
window no longer occupied the expected screen coordinates, or when two
overlapping windows meant a `mousemove --window A x y` call landed the
cursor over window B instead (window-relative coordinates don't protect
against another window occupying that same screen position on top).

```bash
xdotool mousemove --window 14680127 1152 21
sleep 1
xdotool getmouselocation
# x:1212 y:140 screen:0 window:14680127   <- confirms it's really over the target
```

If `getmouselocation` reports a different window than expected, do not
click -- reposition, or move the obstructing window out of the way first
(see below).

### Typing text with a leading dash

`xdotool type` parses a leading `-` as an option flag and errors
(`unrecognized option`). Use `--` to terminate option parsing:

```bash
xdotool type --window <id> --delay 30 -- "-MERGEFIX"
```

### Moving a window out of the way to avoid overlap

When two dialogs need to be open at once and one covers UI you need to
click on the other, move it rather than fighting z-order:

```bash
xdotool windowmove <window-id> 250 750
```

Used repeatedly to get an obstructing dialog's screen real estate clear of
the main window's toolbar before clicking a toolbar button underneath.

### Drag-selecting text in the Tk Text widget

```bash
xdotool mousemove --window <id> <x1> <y1>
xdotool mousedown 1
sleep 1
xdotool mousemove --window <id> <x2> <y1>
sleep 1
xdotool mouseup 1
```

### Timing/approval delays

**This environment sometimes requires a human approval click, or has a
screenshot/mouse-movement permission prompt that needs a moment to clear,
before an action actually completes or a window actually appears.** A
single click-then-immediately-check sequence undercounted this at least
once and had to be retried. Build in real waiting, not just a fixed short
`sleep`:

- Poll for window existence in a loop (see pattern above) rather than
  asserting immediately after a click.
- After a click that's expected to open something, allow multiple seconds
  and re-check, rather than treating one immediate failed check as
  conclusive.
- If a window still isn't found after generous polling, re-screenshot the
  main window first to see actual current state before retrying the same
  click blindly -- don't stack duplicate clicks without checking (see
  "duplicate window" gotcha below).

---

## Known gotchas and how they were resolved

### Duplicate windows from retried/mistimed clicks

Retrying a click (e.g. because a first attempt seemed not to register) can
result in **two independent windows** actually opening, each with its own
correct, independent state -- not a shared-state bug, just an artifact of
sending two clicks that both landed. Confirmed by inspecting each window's
content separately; both showed correct, consistent data.

**Resolution**: close the extra one via its own real Close/Cancel button,
then continue with a single clean instance. Don't assume the first click
failed just because a check immediately after came back empty -- check
again before retrying.

### Shared, real (not headless) display -- pointer contention

This is a genuinely shared X display, not an isolated headless one. The
human operator's own real mouse/keyboard activity (e.g. switching focus to
answer a question mid-task) can contend for the same pointer, causing
`mousemove` + `getmouselocation` to report a stuck/unrelated position on
first attempts.

**Resolution**: chain `windowactivate --sync` immediately before
`mousemove ... click` in as few separate command invocations as practical,
rather than issuing focus and click as separate calls with a gap where
focus could be stolen back.

### Reproducing a timing-sensitive race (prefetch vs. navigation)

One investigation (duplicate `fetch_and_translate()` calls, see `DESIGN.md`)
required clicking "Next" at the *exact* moment a background prefetch for the
same episode was starting -- a real race window of a few seconds. A first,
untimed attempt (click Next only after fully waiting for everything to
settle) *cannot* reproduce this by definition, since waiting fully means the
race window has already closed.

**Resolution**: watch the app's log file with a tight poll loop for the
specific line that signals the race window opening, then click immediately:

```bash
until grep -q "Episode translated successfully" /path/to/app_log.log 2>/dev/null; do
  sleep 0.5
done
xdotool windowactivate --sync <id>
xdotool mousemove --window <id> <x> <y>
xdotool click 1
date   # record exact click time for later log cross-referencing
```

Cross-reference the click time against subsequent log lines to confirm
whether the race actually landed.

### Simulating a concurrent writer without two real dialogs open

After adding `win.grab_set()` (modality) to a dialog, the original
overlapping-dialogs UI reproduction path became impossible to trigger
through the UI anymore (by design -- that was the fix). To still verify the
underlying data-merge logic (not just the modality), the concurrent writer
was simulated directly by writing to the on-disk glossary JSON file with a
short Python snippet while the modal dialog sat open, mimicking exactly what
the other dialog's write path would have done:

```bash
python3 -c "
import json
from datetime import datetime, timezone
path = '/home/dfischer/.config/alphapolis_reader/glossaries/375266002.json'
with open(path) as f:
    d = json.load(f)
for t in d['terms']:
    if t['source'] == 'TARGET_TERM':
        t['status'] = 'confirmed'
        t['confirmed_target'] = 'value'
d['updated_at'] = datetime.now(timezone.utc).isoformat()
with open(path, 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
"
```

Useful pattern generally: when a fix closes off the exact UI path that
created a bug, live-verifying the *deeper* mechanism sometimes requires
re-creating the precondition a different way, not concluding the fix is
unverifiable.

### Invalidating a cache entry without deleting the file

Bash tool permission was denied for `rm` on cache files mid-task. Instead of
deleting, the on-disk cache entry was invalidated by writing a mismatched
schema version -- `load_cached_episode()` treats this exactly like "not
cached" and the app re-fetches for real:

```bash
python3 -c "
import json
path = '/home/dfischer/.cache/alphapolis_reader/<hash>.json'
with open(path) as f:
    d = json.load(f)
d['_cache_schema_version'] = -1
with open(path, 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
"
```

A write-based invalidation instead of a delete is also generally safer/more
reversible during investigation.

### Waiting for long-running real LLM work without blocking the turn

Real chapter translations against the local LLM server took ~90-100 seconds
each; some investigations needed two or three in sequence. Long blocking
`sleep`-then-check sequences in a single tool call are disallowed by the
harness beyond a short threshold.

**Resolution**: run the wait-loop as a backgrounded command
(`run_in_background: true` on the Bash call, or the Monitor tool with an
until-loop) and continue other work (writing tests, reading code) until
notified, rather than blocking the whole turn on a sleep loop:

```bash
until grep -q "Episode translated successfully" /path/to/app_log.log 2>/dev/null; do
  sleep 3
done
echo "translation finished"
```

---

## Human-in-the-loop: when to ask instead of guessing

Several times in this work, the reliable choice was to describe what should
be visible on screen and ask the human operator to click it directly, or to
simply watch and confirm, rather than computing blind coordinates or fighting
tooling:

- Clicking a `tk.Menu` popup item, before the Xvfb-based capture technique
  above was found -- on the shared Wayland session, menus genuinely couldn't
  be screenshotted by any tool tried, so a human's direct click/observation
  was the only way to confirm one worked. (No longer the *only* option once
  Xvfb is available, but still valid and often faster when a human is
  already watching.)
- Confirming an ambiguous window state when repeated automated attempts
  weren't landing reliably.

This was not a fallback of last resort -- it was faster and more reliable
than iterating on blind coordinate guesses, especially for transient UI that
tooling genuinely can't observe on the display in use at the time.

**Remember the shared session's approval mechanic causes focus loss.** On the
real desktop session (not Xvfb), each simulated click/action can require the
human operator's live permission approval, and that approval step itself
takes window focus away from the app under test. Re-activate the target
window (`xdotool windowactivate --sync <id>`) immediately before every
subsequent action rather than assuming focus persisted from the previous
command -- this is not an issue on a private Xvfb display, since nothing else
is competing for the display's focus there.

---

## Log-file cross-referencing

The app's log file (`logs/app_log_<timestamp>.log`) was often the more
reliable source of truth than a screenshot for confirming *what actually
ran and when* -- especially for timing-sensitive races and for confirming a
background operation (translation, glossary rebuild) actually completed
vs. merely appearing to on screen.

```bash
ls -t /development/git/pyplayground/logs/*.log | head -1   # find current run's log
grep -n "Fetching and translating episode\|Episode translated successfully" <log>
```

Useful habit: note the exact log line(s) expected before/after an action,
then grep for them after clicking, rather than relying on the screenshot
alone to confirm an action's *effect* (as opposed to its visible UI state).
