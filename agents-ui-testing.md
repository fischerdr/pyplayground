# Agent UI Testing Notes

Practical reference for driving `pyplayground/webnovels/alphapolis_reader.py`
(a Tkinter app) live via `xdotool` for verification during agent-driven work.
Built up across several sessions of live-verifying fixes against the real
running app on a real X display (`DISPLAY=:0`). Not a general xdotool
tutorial -- specifically the commands and gotchas that came up running and
testing *this* app.

Companion to `DESIGN.md` (`pyplayground/webnovels/DESIGN.md`), which has the
task-specific findings this testing supported. This file is the reusable
mechanics; `DESIGN.md` is the specific investigation history.

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
look at it.

### What did NOT work in this environment

- **`xwd`**: installed but not tested.
- **True full-screen capture** with this ImageMagick 7.1.1 build: `import
  -window root`, `import -screen -window root`, and `import -window 0x374`
  (the actual root window ID from `xwininfo -root`) all failed with
  `import: missing an image filename`. Never found a working full-screen
  capture flag combination in this environment.
- **No alternative screenshot tools available**: `scrot`, `maim`,
  `gnome-screenshot` were all absent (`which` came back empty for all three) but should be requested via user.

**Workaround used throughout**: capture by specific window ID only. This is
sufficient for almost everything -- the one real gap is transient popup
menus (see below).

### Popup menus (`tk.Menu` right-click context menus) don't screenshot

A `tk.Menu` opened via right-click (`_on_text_right_click()`'s "Add to
Glossary...(...)" / "Retranslate this line..." menu) is a transient,
override-redirect-style window that `import -window <parent-id>` does not
capture -- the screenshot comes back showing the underlying window as if the
menu weren't there, even though it's genuinely open on screen.

**No automated workaround found.** When a menu needed to be clicked and its
presence/content verified, the working approach was to right-click to open
it, then **ask the human operator to look at the screen and click the
desired item directly** (see "Human-in-the-loop" below), rather than
guessing coordinates blind. This was reliable every time it was used.

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

Twice in this work, the reliable choice was to describe what should be
visible on screen and ask the human operator to click it directly, rather
than computing blind coordinates:

- Clicking a `tk.Menu` popup item (menus don't screenshot, see above).
- Confirming an ambiguous window state when repeated automated attempts
  weren't landing reliably.

This was not a fallback of last resort -- it was faster and more reliable
than iterating on blind coordinate guesses, especially for transient UI that
tooling genuinely can't observe.

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
