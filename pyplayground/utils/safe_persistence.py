#!/usr/bin/env python3
"""safe_persistence.py - General-purpose atomic-write and verify-before-write helpers.

Implements the design recorded in this module's prior design-only revision
(see git history for the original proposal) and migrated onto by every
direct file-write call site in pyplayground/webnovels/ -- config_utils.py's
save_json_config() (and, transitively, alphapolis_reader.py's
save_cached_episode()), glossary.py's save_glossary(),
global_vocabulary.py's save_global_vocabulary(), GlossaryCoordinator's
save_snapshot(), and open_retranslate_popup()'s stale-popup guard in
alphapolis_reader.py.

WHY THIS EXISTS

Two independently-built fixes for the same underlying problem --
"don't silently lose data by writing a stale in-memory snapshot over a
file someone else changed" -- existed in pyplayground/webnovels/, built at
different times for different features, with no shared abstraction between
them: GlossaryCoordinator.save_snapshot()'s merge-by-source logic and
open_retranslate_popup()'s skip-and-warn stale-popup guard. Both are
"capture state at session start, re-verify immediately before writing, do
something safe on mismatch" -- but one merges and one skips, because the
data shapes differ. Separately, every direct file-write call site in this
codebase wrote straight to its target path with no temp file and no
os.replace()/os.rename() anywhere, so a crash, kill, or power loss
mid-write could leave a truncated/corrupt file.

This module holds the mechanical parts of both patterns, generalized so a
future, unrelated call site can reuse them without importing or assuming
anything about Alphapolis, webnovels, glossaries, or episodes.

PART 1: ATOMIC WRITE HELPER

atomic_write() is a drop-in replacement for `open(path, "w") +
json.dump(...)` / `path.write_text(...)` call sites: it writes to a temp
file in the same directory as the target (so the final os.replace() stays
on one filesystem and is atomic), flushes and os.fsync()s the temp file,
then calls os.replace(tmp_path, target_path). On any exception before the
replace completes, the temp file is cleaned up before re-raising.

The helper's signature carries no domain assumptions -- it takes a target
path and either raw bytes or an already-serialized string, never a domain
dict. Serialization (e.g. json.dumps()) stays the caller's responsibility,
exactly as it was before; this helper only makes the write-to-disk step
atomic.

Two accepted-residue notes, deliberately stated here rather than left as
implicit gaps:

- An abnormal termination (SIGKILL, power loss) between the temp-file
  write and os.replace() may leave a stray temp file behind. This is
  harmless -- the original target file is untouched until os.replace()
  succeeds -- and is not automatically cleaned up on next run. Accepted
  as-is for a personal, single-user tool; not a data-loss risk, just disk
  residue.
- The temp filename is unique per write (PID plus a random suffix
  appended to the target name), not a fixed `path + ".tmp"` --
  otherwise two concurrent writers targeting the same path could stomp
  each other's temp file before either reaches os.replace(). Not a real
  risk under this codebase's current single-threaded-per-write usage, but
  cheap to get right rather than retrofit once more subsystems adopt this
  helper.

PART 2: GENERALIZED VERIFY-BEFORE-WRITE HELPER

verify_before_write() abstracts exactly the shape shared by
GlossaryCoordinator.save_snapshot() and the retranslate popup's
capture-at-open/verify-at-click guard, and no more:

  1. Capture an opaque "version marker" for some piece of state at the
     start of an editing session (the caller does this itself, before
     ever calling verify_before_write() -- capture is not this helper's
     job).
  2. Immediately before writing -- not earlier -- reload/re-derive the
     current version marker fresh, via a caller-supplied `reload_current`
     callback.
  3. Compare the captured marker against the freshly-reloaded one, via a
     caller-supplied `markers_match` callback (defaults to `==`).
  4. If unchanged: return the caller's data as-is, ready to hand to
     atomic_write() (or any other write path).
     If changed: invoke a caller-supplied `on_divergence` callback with
     both the freshly-reloaded state and the caller's original data, and
     return its result instead of blindly overwriting.

This helper's own responsibility is only capture / reload / compare /
dispatch -- it holds no domain vocabulary, and the "what happens on
divergence" decision (merge by a stable key, skip and warn, or anything
else) always belongs to the caller's `on_divergence` callback, never to
this module.

Example, using a neutral placeholder domain (an inventory count, not any
real call site in this codebase):

    def reload_current():
        return load_inventory().get("version")

    def on_divergence(current_state, local_data):
        # Caller decides what "merge" or "skip" means for its own data.
        return merge_by_key(current_state, local_data)

    result = verify_before_write(
        captured_marker=opened_version,
        reload_current=reload_current,
        on_divergence=on_divergence,
        local_data=local_inventory_snapshot,
    )
    save_inventory(result)
"""

import logging
import os
from typing import Any, Callable, Optional, Union

logger = logging.getLogger(__name__)


def atomic_write(target_path: Union[str, "os.PathLike[str]"], data: Union[str, bytes], encoding: str = "utf-8") -> None:
    """Write `data` to `target_path` atomically via a same-directory temp file and os.replace().

    Writes to a uniquely-named temp file in the same directory as
    `target_path` (so the final os.replace() is guaranteed to stay on one
    filesystem and be atomic), flushes and fsyncs it, then replaces the
    target in one atomic step. On any exception before the replace
    completes, the temp file is removed before re-raising, so a failed
    write never leaves partial content next to (let alone over) the
    original target.

    Args:
        target_path: Path of the file to write. Its parent directory must
            already exist.
        data: Pre-serialized content to write -- either `str` (written
            with `encoding`) or `bytes` (written as-is). Callers are
            responsible for serialization (e.g. `json.dumps()`); this
            helper only makes the write-to-disk step atomic.
        encoding: Text encoding used when `data` is a `str`. Ignored when
            `data` is `bytes`.

    Raises:
        OSError: If the temp file cannot be created/written, or if
            os.replace() fails. The temp file is cleaned up before this
            propagates.
    """
    target_path = os.fspath(target_path)
    directory = os.path.dirname(target_path) or "."
    tmp_path = os.path.join(directory, f".{os.path.basename(target_path)}.{os.getpid()}.{os.urandom(8).hex()}.tmp")

    logger.debug(f"Writing atomically to {target_path} via temp file {tmp_path}")
    try:
        if isinstance(data, bytes):
            with open(tmp_path, "wb") as fb:
                fb.write(data)
                fb.flush()
                os.fsync(fb.fileno())
        else:
            with open(tmp_path, "w", encoding=encoding) as ft:
                ft.write(data)
                ft.flush()
                os.fsync(ft.fileno())
        os.replace(tmp_path, target_path)
        logger.debug(f"Atomic write completed: {target_path}")
    except Exception as e:
        logger.error(f"Atomic write to {target_path} failed, cleaning up temp file: {e}", exc_info=True)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def verify_before_write(
    captured_marker: Any,
    reload_current: Callable[[], Any],
    on_divergence: Callable[[Any, Any], Any],
    local_data: Any,
    markers_match: Optional[Callable[[Any, Any], bool]] = None,
) -> Any:
    """Reload current state fresh, compare against a previously-captured marker, and dispatch on divergence.

    Generalizes the capture/reload/compare/dispatch shape shared by every
    "don't blindly overwrite a file someone else changed since I loaded
    it" call site in this codebase. This helper does not capture the
    initial marker itself -- the caller does that at the start of its own
    editing session, before ever calling this function -- and it does not
    write anything to disk; it only decides what data the caller should
    write.

    Args:
        captured_marker: The version marker captured by the caller at the
            start of its editing session (e.g. when a dialog was opened).
            Opaque to this helper -- any type the caller's
            `markers_match` can compare.
        reload_current: Zero-argument callback that re-derives the
            current version marker fresh, called immediately before the
            comparison -- never earlier, so the comparison is always
            against genuinely current state.
        on_divergence: Callback invoked as `on_divergence(current_marker,
            local_data)` when `captured_marker` and the freshly-reloaded
            marker no longer match. Its return value is returned as-is
            from this function. This is where all caller-specific
            divergence handling lives (merge by a stable key, skip and
            warn, or anything else) -- this helper never decides that
            itself.
        local_data: The caller's data to return unchanged when the
            markers still match.
        markers_match: Optional callback `(captured, current) -> bool`
            for comparing markers. Defaults to `==`, which covers both
            string equality (an `updated_at` marker) and tuple/identity
            comparisons that already support `==`.

    Returns:
        `local_data` unchanged if the markers still match; otherwise
        whatever `on_divergence` returns.
    """
    current_marker = reload_current()
    matches = markers_match(captured_marker, current_marker) if markers_match else captured_marker == current_marker

    if matches:
        return local_data

    logger.debug(f"verify_before_write: marker diverged ({captured_marker!r} -> {current_marker!r}), dispatching to divergence callback")
    return on_divergence(current_marker, local_data)
