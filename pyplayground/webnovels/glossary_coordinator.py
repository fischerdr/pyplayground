#!/usr/bin/env python3
"""glossary_coordinator.py - Per-novel glossary read/write coordinator.

REFACTOR_DESIGN.md Phase 3a: the shared write-path interface proposed in
Phase 1 section 4, built standalone in this step and NOT yet wired into
any dialog (that's 3b-3d). One GlossaryCoordinator instance is meant to be
owned per currently-open novel (today's app only ever has one novel open
at a time -- see Phase 1 section 4's "per-novel rebuild tracking" note --
so a single instance, re-created when the active novel changes, is
sufficient; no registry is needed).

Lifts two pieces of real, already-working logic verbatim rather than
redesigning them:

- save_snapshot()'s merge-on-divergence behavior is
  open_glossary_dialog()'s save_and_close() (alphapolis_reader.py,
  currently ~l.2210-2264), the fix for the cross-dialog stale-overwrite
  bug documented in DESIGN.md's 2026-07-27 entry: re-check updated_at
  against what was loaded at open time, and if it changed, merge by
  source rather than blindly overwriting, letting the caller's copy win
  only for sources it actually touched (edited_sources) with explicit
  deletes (deleted_sources) applied last so they survive the merge.
- reject()'s real-delete is open_term_review_dialog()'s reject_selected()
  (currently ~l.2481-2492): removes the term from the glossary entirely
  (not a status change), since a rejected term must not linger at any
  non-confirmed status -- build_mask_targets() masks anything that isn't
  STATUS_CONFIRMED, so leaving it in the glossary at any other status
  would keep it masked forever with no way to un-flag it. Phase 3c found
  and fixed a real mismatch here: reject()'s first version (built in 3a)
  matched by Python object identity, mirroring reject_selected()'s own
  `t is not term` filter exactly -- but that filter only works because
  reject_selected() mutates the *same* in-memory glossary dict it loaded
  once at dialog-open time, in the same local scope. A coordinator method
  that reloads fresh via load_glossary() internally (as every other
  write path here deliberately does, to avoid stale-snapshot bugs) can
  never produce a term object with the same identity as one from a
  caller's separate, earlier load_glossary() call -- confirmed directly,
  not assumed: two independent load_glossary() calls against the same
  on-disk file produce equal-content but not identical term dicts.
  reject() now matches by source (a stable, comparable key, same
  precedent as upsert_confirmed_term()'s own dedupe-by-source rule) --
  see reject()'s docstring for the full account.

upsert_confirmed() and start_rebuild()/is_rebuild_running() are thinner:
the former is a reload-then-write wrapper (no snapshot to reconcile,
since nothing calling it holds one), the latter has no existing
equivalent to lift -- open_glossary_dialog()'s rebuild_glossary() has its
own local, dialog-scoped rebuild_state dict today; this coordinator
generalizes that into shared, cross-dialog-visible state, which is what
Phase 3e's race fix depends on.
"""

import sys
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from pyplayground.utils.logging_utils import get_logger
from pyplayground.webnovels.build_glossary import build_glossary_for_novel
from pyplayground.webnovels.glossary import load_glossary, save_glossary, upsert_confirmed_term

logger = get_logger(__name__)


class GlossaryCoordinator:
    """Owns all glossary reads/writes for one novel, so no dialog has to do its own load/write pair.

    Not yet wired into any dialog as of Phase 3a -- see REFACTOR_DESIGN.md's
    Phase 3 sub-plan. Each dialog still does its own load_glossary()/
    save_glossary() calls until 3b-3d wire them through here one at a time.
    """

    def __init__(self, novel_id: str):
        """Initialize a coordinator scoped to one novel.

        Args:
            novel_id: The Alphapolis novel ID this coordinator owns
                glossary reads/writes for.
        """
        self.novel_id = novel_id
        self._rebuild_in_progress = False

    def load(self) -> Dict[str, Any]:
        """Load the current on-disk glossary for this coordinator's novel.

        Returns:
            The glossary dict, as returned by glossary.load_glossary().
        """
        return load_glossary(self.novel_id)

    def save_snapshot(
        self,
        opened_at: Optional[str],
        local_terms: List[Dict[str, Any]],
        edited_sources: Set[str],
        deleted_sources: Set[str],
        honorific_policy: str,
    ) -> Dict[str, Any]:
        """Write a long-lived in-memory snapshot back to disk, merging by source if another writer touched the file first.

        The only write path for a caller (open_glossary_dialog(), per
        Phase 1) that loaded a full glossary snapshot once at open time
        and edited it in memory over a whole dialog session, rather than
        writing immediately per action. Lifted verbatim from
        save_and_close()'s re-check-before-write logic: reloads the
        glossary fresh, right before writing, and compares updated_at
        against opened_at (what the caller's snapshot was loaded
        against). If they still match, local_terms is written as-is --
        no merge needed. If they diverged, merges by source instead of
        blindly overwriting: only sources in edited_sources let the
        caller's local copy win (sources the caller's snapshot contains
        but never actually touched must not overwrite whatever the
        concurrent writer changed on them -- confirmed live during the
        original fix that omitting this distinction reproduces the bug
        through the merge path itself), and deleted_sources are popped
        from the merge result last so an explicit delete survives even
        if the same source still exists, untouched, in the fresher
        on-disk copy.

        Args:
            opened_at: The glossary's updated_at value at the moment the
                caller's snapshot was loaded (None if the glossary was
                empty/new at that time).
            local_terms: The caller's full local copy of the term list
                (already filtered to entries with a non-empty source),
                as edited over the dialog session.
            edited_sources: Sources the caller actually visited/edited
                this session -- only these are allowed to overwrite the
                freshly-reloaded on-disk value on divergence.
            deleted_sources: Sources explicitly deleted this session --
                popped from the merge result last, so an explicit delete
                wins even over a concurrently-unrelated on-disk change to
                the same source.
            honorific_policy: The novel-wide honorific policy value to
                save alongside the terms (a dialog-owned UI setting, not
                something this coordinator can read on its own).

        Returns:
            The final glossary dict as written to disk.
        """
        current_glossary = self.load()
        if current_glossary.get("updated_at") != opened_at:
            logger.info(
                f"Glossary for novel {self.novel_id} changed on disk while a snapshot was held (updated_at {opened_at!r} -> {current_glossary.get('updated_at')!r}) -- merging by source instead of overwriting"
            )
            current_by_source = {t.get("source"): t for t in current_glossary.get("terms", []) if t.get("source")}
            local_by_source = {t.get("source"): t for t in local_terms}
            merged_by_source = dict(current_by_source)
            for source in edited_sources:
                if source in local_by_source:
                    merged_by_source[source] = local_by_source[source]
            for source in deleted_sources:
                merged_by_source.pop(source, None)
            final_terms = list(merged_by_source.values())
        else:
            final_terms = local_terms

        current_glossary["terms"] = final_terms
        current_glossary["honorific_policy"] = honorific_policy
        current_glossary["honorific_policy_user_set"] = True
        current_glossary["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_glossary(self.novel_id, current_glossary)
        return current_glossary

    def upsert_confirmed(self, new_term: Dict[str, Any]) -> Dict[str, Any]:
        """Reload the glossary fresh and write a single confirmed term into it immediately.

        Used by callers that write once per action and never hold a
        long-lived snapshot (open_term_review_dialog()'s Confirm,
        open_word_glossary_popup()'s Save, per Phase 1) -- no merge logic
        needed here, since there is no stale snapshot to reconcile
        against.

        Args:
            new_term: The term dict to upsert, as built by
                glossary.make_confirmed_term() (or with character-only
                fields added on top).

        Returns:
            The final glossary dict as written to disk.
        """
        current_glossary = self.load()
        current_glossary["terms"] = upsert_confirmed_term(current_glossary.get("terms", []), new_term)
        current_glossary["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_glossary(self.novel_id, current_glossary)
        return current_glossary

    def reject(self, source: str) -> Dict[str, Any]:
        """Reload the glossary fresh and delete one term from it entirely, matched by source.

        Real delete, not a status change -- lifted from
        open_term_review_dialog()'s reject_selected(). A rejected term
        must not linger at any non-confirmed status: build_mask_targets()
        masks anything that isn't STATUS_CONFIRMED, so leaving it at any
        other status would keep it masked forever with no way to un-flag
        it.

        Matches by source, not object identity. reject_selected()'s
        original code matched by identity (`t is not term`), which only
        works there because it mutates the same in-memory glossary dict
        it loaded once at dialog-open time, in the same local scope. This
        method reloads the glossary fresh via load() first (same
        re-check-before-write discipline every other write path here
        uses), so a term object from an earlier, separate load_glossary()
        call -- e.g. the caller's own dialog-open-time load -- can never
        be the same Python object as anything in the freshly-reloaded
        list, even with identical content. Matching by source instead
        sidesteps this entirely, and follows the same precedent
        upsert_confirmed_term() already established (dedupe-by-source,
        not by identity or (type, source)) for exactly this "a human
        acted on one specific term" trust level.

        Args:
            source: The source text of the term to remove.

        Returns:
            The final glossary dict as written to disk.
        """
        current_glossary = self.load()
        current_glossary["terms"] = [t for t in current_glossary.get("terms", []) if t.get("source") != source]
        current_glossary["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_glossary(self.novel_id, current_glossary)
        return current_glossary

    def is_rebuild_running(self) -> bool:
        """Whether a background glossary rebuild is currently in progress for this novel."""
        return self._rebuild_in_progress

    def start_rebuild(self, status_cb: Optional[Callable[[str], None]] = None) -> None:
        """Run build_glossary_for_novel() on a background thread, tracking is_rebuild_running() for the duration.

        Mirrors open_glossary_dialog()'s existing rebuild_glossary(),
        generalized into coordinator-owned state visible across every
        dialog and _do_fetch_and_translate() (Phase 3e's extraction-vs-
        dialog race fix depends on this being shared, not a
        dialog-local dict). No-op if a rebuild is already running for
        this novel -- callers should check is_rebuild_running() first if
        they want to show/avoid a duplicate-request message, same as
        rebuild_glossary()'s existing guard.

        Args:
            status_cb: Optional callback invoked with progress messages
                during extraction, forwarded to build_glossary_for_novel()
                as-is. Callers marshaling this onto a UI thread (e.g. via
                Tk's root.after()) are responsible for doing so themselves
                -- this coordinator has no widget/event-loop reference of
                its own.
        """
        if self._rebuild_in_progress:
            return

        self._rebuild_in_progress = True

        def worker():
            try:
                build_glossary_for_novel(self.novel_id, status_cb=status_cb)
            except Exception as e:
                logger.error(f"Glossary rebuild failed for novel {self.novel_id}: {e}", exc_info=True)
                print(traceback.format_exc(), file=sys.stderr)
            finally:
                self._rebuild_in_progress = False

        threading.Thread(target=worker, daemon=True).start()

    def notify_edited(self, edited: bool) -> None:
        """Placeholder for the forwarding hook Phase 1 describes -- not wired to anything in this step.

        Per Phase 1 section 4: this is meant to replace each dialog's
        direct self._maybe_refresh_after_glossary_edit() call, forwarding
        to a ReaderApp-supplied callback instead of the dialog needing
        its own reference to the app. The actual refresh-triggering logic
        (refresh_current_episode()/load_episode()) stays Group A's
        concern and does not move here. Registering and invoking that
        callback is 3b-3d's job, not this step's -- this method exists
        now so the interface is complete and testable, but it is
        intentionally a no-op until a callback is wired up.

        Args:
            edited: Whether the caller's dialog session actually wrote
                to disk (mirrors each dialog's own disk_write_happened/
                edited tracking today).
        """
        logger.debug(f"GlossaryCoordinator.notify_edited({edited!r}) for novel {self.novel_id} -- no-op, not wired to any callback yet (REFACTOR_DESIGN.md Phase 3b-3d)")
