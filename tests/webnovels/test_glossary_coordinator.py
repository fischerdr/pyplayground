#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for glossary_coordinator.py (REFACTOR_DESIGN.md Phase 3a/3b/3c).

Phase 3a: standalone unit tests against GlossaryCoordinator directly -- no
Tk, no dialog harness, since that step deliberately did not wire the
coordinator into any dialog yet. save_snapshot()'s merge-on-divergence
scenarios mirror tests/webnovels/test_alphapolis_reader.py's
TestGlossaryDialogMergeOnDivergence exactly (same fixtures, same three
scenarios), confirming the logic lifted into the coordinator behaves
identically to the original open_glossary_dialog().save_and_close() it
was copied from.

Phase 3b: TestOpenWordGlossaryPopupRoutesThroughCoordinator drives the
real, unmodified open_word_glossary_popup() (via the reader_app_shell
fixture) end-to-end through its actual Save button, confirming the
dialog's on-disk write now happens via GlossaryCoordinator.upsert_confirmed()
rather than direct load_glossary()/upsert_confirmed_term()/save_glossary()
calls -- a test that would fail if the dialog reverted to calling those
glossary.py functions directly instead of going through the coordinator.

Phase 3c: TestOpenTermReviewDialogRoutesThroughCoordinator drives the
real, unmodified open_term_review_dialog() end-to-end through its actual
Confirm/Reject buttons, same fail-loud-on-direct-call standard as 3b.
Also fixed a real mismatch found in this step: reject() originally
matched by Python object identity (mirroring reject_selected()'s own
`t is not term` filter), which cannot work against a coordinator method
that reloads the glossary fresh internally -- see reject()'s docstring
in glossary_coordinator.py for the full account. reject() now matches by
source instead; TestReject below was updated to match, plus a new test
confirming this explicitly against a term object sourced from an
independent load_glossary() call (the exact shape that broke identity
matching).

Phase 3d: TestOpenGlossaryDialogRoutesThroughCoordinator drives the real,
unmodified open_glossary_dialog() end-to-end through its actual Save and
Clear Glossary paths -- the highest-risk conversion in Phase 3, since
save_and_close() is the dialog save_snapshot() was originally lifted
from. clear_glossary() does NOT route through save_snapshot() -- a new,
dedicated GlossaryCoordinator.clear() method was added instead (see its
docstring), since a Clear is an unconditional reset the user explicitly
asked for, not an edited snapshot to merge against a concurrent writer,
and forcing it through save_snapshot()'s contract would silently lose
context_notes/honorific_policy_user_set. TestClear covers the new method
directly.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk

from pyplayground.webnovels.alphapolis_reader import ReaderApp
from pyplayground.webnovels.glossary import (
    DEFAULT_HONORIFIC_POLICY,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    make_confirmed_term,
    make_suggested_term,
)
from pyplayground.webnovels.glossary_coordinator import GlossaryCoordinator


def _glossary_at_open():
    return {
        "title": "Test Novel",
        "honorific_policy": "keep",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "terms": [
            make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
            {
                "type": "character",
                "source": "ハードキャッチ",
                "candidates": [{"target": "Hard Catch", "count": 1, "origin": "llm"}],
                "confirmed_target": None,
                "status": "suggested",
                "note": None,
            },
        ],
    }


def _glossary_after_concurrent_confirm():
    """The same glossary, but as if a concurrent writer had confirmed ハードキャッチ in the meantime -- a later updated_at, ハードキャッチ now confirmed."""
    return {
        "title": "Test Novel",
        "honorific_policy": "keep",
        "updated_at": "2026-01-01T00:05:00+00:00",
        "terms": [
            make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
            make_confirmed_term(term_type=TERM_TYPE_CHARACTER, source="ハードキャッチ", target="Hard Catch"),
        ],
    }


class TestSaveSnapshotMergeOnDivergence:
    """Regression coverage mirroring TestGlossaryDialogMergeOnDivergence, driven against the coordinator directly instead of the Tk dialog."""

    def test_concurrent_confirm_survives_a_save_that_edited_an_unrelated_term(self, mocker):
        """The exact original reproduction: edit 鉄パイプ, save_snapshot() -- ハードキャッチ's concurrent confirm must survive, not revert."""
        load_mock = mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.load_glossary",
            side_effect=[_glossary_after_concurrent_confirm()],
        )
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        coordinator = GlossaryCoordinator("375266002")
        opened = _glossary_at_open()
        local_terms = [dict(t) for t in opened["terms"]]
        # Edit 鉄パイプ (unrelated to the concurrently-confirmed ハードキャッチ),
        # matching the original live reproduction sequence exactly.
        for t in local_terms:
            if t["source"] == "鉄パイプ":
                t["confirmed_target"] = "iron pipe EDITED"

        result = coordinator.save_snapshot(
            opened_at=opened["updated_at"],
            local_terms=local_terms,
            edited_sources={"鉄パイプ"},
            deleted_sources=set(),
            honorific_policy="keep",
        )

        assert load_mock.call_count == 1, "save_snapshot() must reload the glossary fresh before writing, not rely solely on the caller's opened_at snapshot"
        saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
        assert saved_terms["鉄パイプ"]["confirmed_target"] == "iron pipe EDITED", "the edit made by the caller must still be applied"
        assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED, "the concurrent confirm must survive this save, not be reverted back to suggested"
        assert saved_terms["ハードキャッチ"]["confirmed_target"] == "Hard Catch"
        assert result["terms"] == saved["glossary"]["terms"], "save_snapshot() must return the same final glossary it wrote to disk"

    def test_no_divergence_saves_normally_without_merging(self, mocker):
        """When updated_at hasn't changed between the caller's open and save, no merge branch should fire -- plain overwrite is correct and sufficient."""
        glossary = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        coordinator = GlossaryCoordinator("375266002")
        local_terms = [dict(t) for t in glossary["terms"]]

        coordinator.save_snapshot(
            opened_at=glossary["updated_at"],
            local_terms=local_terms,
            edited_sources=set(),
            deleted_sources=set(),
            honorific_policy="keep",
        )

        saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
        assert saved_terms["ハードキャッチ"]["status"] == "suggested", "no concurrent change happened -- the caller's own unedited copy should be saved as-is"

    def test_explicit_delete_wins_over_a_concurrently_unrelated_change_even_on_divergence(self, mocker):
        """A term explicitly deleted by the caller must stay deleted after a merge, not get resurrected from the fresher on-disk copy."""
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.load_glossary",
            side_effect=[_glossary_after_concurrent_confirm()],
        )
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        coordinator = GlossaryCoordinator("375266002")
        opened = _glossary_at_open()
        # Delete 鉄パイプ (unrelated to the concurrently-confirmed ハードキャッチ).
        local_terms = [dict(t) for t in opened["terms"] if t["source"] != "鉄パイプ"]

        coordinator.save_snapshot(
            opened_at=opened["updated_at"],
            local_terms=local_terms,
            edited_sources=set(),
            deleted_sources={"鉄パイプ"},
            honorific_policy="keep",
        )

        saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
        assert "鉄パイプ" not in saved_terms, "explicit delete must survive the merge, not be resurrected from the fresher on-disk copy"
        assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED, "the concurrent confirm must still survive alongside the delete"


class TestUpsertConfirmed:
    """Tests for the reload-then-write immediate path (no snapshot to reconcile)."""

    def test_upsert_confirmed_writes_new_term_and_reloads_fresh(self, mocker):
        existing = _glossary_at_open()
        load_mock = mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        saved = {}
        save_mock = mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=g),
        )

        coordinator = GlossaryCoordinator("375266002")
        new_term = make_confirmed_term(term_type=TERM_TYPE_CHARACTER, source="ハードキャッチ", target="Hard Catch")
        result = coordinator.upsert_confirmed(new_term)

        assert load_mock.call_count == 1
        assert save_mock.call_count == 1
        assert saved["novel_id"] == "375266002"
        saved_terms = {t["source"]: t for t in result["terms"]}
        assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED
        assert saved_terms["ハードキャッチ"]["confirmed_target"] == "Hard Catch"
        # upsert_confirmed_term() dedupes by (type, source) -- confirming
        # an already-suggested term updates it in place rather than
        # appending a duplicate entry.
        assert len(result["terms"]) == 2

    def test_upsert_confirmed_adds_a_genuinely_new_term(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=g),
        )

        coordinator = GlossaryCoordinator("375266002")
        new_term = make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="新しい単語", target="new word")
        result = coordinator.upsert_confirmed(new_term)

        assert len(result["terms"]) == 3
        saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
        assert saved_terms["新しい単語"]["confirmed_target"] == "new word"


class TestReject:
    """Tests for the real-delete-by-source path.

    REFACTOR_DESIGN.md Phase 3c: reject() originally matched by Python
    object identity (mirroring reject_selected()'s own `t is not term`
    filter), which only works for a caller mutating the same in-memory
    dict it loaded once -- reject() reloads fresh via load() internally,
    so an object from an independent, earlier load_glossary() call can
    never match by identity even with identical content (confirmed
    directly: two separate load_glossary() calls produce equal-content,
    non-identical dicts). Fixed to match by source instead, same
    precedent as upsert_confirmed_term()'s dedupe-by-source rule.
    """

    def test_reject_removes_the_term_entirely_not_just_its_status(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=g),
        )

        coordinator = GlossaryCoordinator("375266002")

        result = coordinator.reject("ハードキャッチ")

        assert "ハードキャッチ" not in {t["source"] for t in result["terms"]}
        assert len(result["terms"]) == 1
        assert saved["glossary"]["terms"] == result["terms"]

    def test_reject_leaves_other_terms_untouched(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")

        result = coordinator.reject("ハードキャッチ")

        remaining = {t["source"] for t in result["terms"]}
        assert remaining == {"鉄パイプ"}

    def test_reject_by_source_works_even_against_a_term_object_from_a_separate_load_call(self, mocker):
        """The exact case that broke identity-based matching: a term read from one load_glossary() call, rejected via a coordinator that reloads internally."""
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")
        # A caller-side load, independent of the coordinator's own
        # internal reload inside reject() -- same shape as
        # open_term_review_dialog()'s dialog-open-time load_glossary()
        # call.
        caller_side_glossary = _glossary_at_open()
        term = next(t for t in caller_side_glossary["terms"] if t["source"] == "ハードキャッチ")
        assert term is not existing["terms"][1], "sanity check: these must be genuinely different objects for this test to mean anything"

        result = coordinator.reject(term["source"])

        assert "ハードキャッチ" not in {t["source"] for t in result["terms"]}


class TestClear:
    """Tests for the dedicated Clear method (REFACTOR_DESIGN.md Phase 3d) -- NOT routed through save_snapshot(), see clear()'s docstring."""

    def test_clear_empties_all_terms(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=dict(g)),
        )

        coordinator = GlossaryCoordinator("375266002")
        result = coordinator.clear()

        assert result["terms"] == []
        assert saved["glossary"]["terms"] == []

    def test_clear_resets_honorific_policy_to_default_and_unsets_user_set_flag(self, mocker):
        existing = _glossary_at_open()
        existing["honorific_policy"] = "keep"
        existing["honorific_policy_user_set"] = True
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")
        result = coordinator.clear()

        assert result["honorific_policy"] == DEFAULT_HONORIFIC_POLICY
        assert result["honorific_policy_user_set"] is False

    def test_clear_resets_context_notes(self, mocker):
        existing = _glossary_at_open()
        existing["context_notes"] = "some prior extraction context"
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")
        result = coordinator.clear()

        assert result["context_notes"] == ""

    def test_clear_reloads_fresh_before_writing(self, mocker):
        """clear() should reload via load(), not operate on a stale caller-held snapshot -- same re-check discipline as every other write path here."""
        existing = _glossary_at_open()
        load_mock = mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")
        coordinator.clear()

        assert load_mock.call_count == 1


class TestRebuildTracking:
    """Tests for is_rebuild_running()/start_rebuild()'s shared, coordinator-owned state."""

    def test_not_running_before_any_rebuild_starts(self):
        coordinator = GlossaryCoordinator("375266002")
        assert coordinator.is_rebuild_running() is False

    def test_start_rebuild_marks_running_then_clears_on_completion(self, mocker):
        release_event = threading.Event()

        def fake_build_glossary_for_novel(novel_id, max_episodes=20, status_cb=None):
            release_event.wait(timeout=5)
            return {"novel_id": novel_id}

        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel",
            side_effect=fake_build_glossary_for_novel,
        )

        coordinator = GlossaryCoordinator("375266002")
        coordinator.start_rebuild()
        assert coordinator.is_rebuild_running() is True, "is_rebuild_running() must report True while the background thread is still running"

        release_event.set()
        for _ in range(50):
            if not coordinator.is_rebuild_running():
                break
            time.sleep(0.05)
        assert coordinator.is_rebuild_running() is False, "is_rebuild_running() must clear once the background rebuild finishes"

    def test_start_rebuild_is_a_no_op_while_already_running(self, mocker):
        call_count = {"value": 0}
        release_event = threading.Event()

        def fake_build_glossary_for_novel(novel_id, max_episodes=20, status_cb=None):
            call_count["value"] += 1
            release_event.wait(timeout=5)
            return {"novel_id": novel_id}

        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel",
            side_effect=fake_build_glossary_for_novel,
        )

        coordinator = GlossaryCoordinator("375266002")
        coordinator.start_rebuild()
        coordinator.start_rebuild()  # must be a no-op: a rebuild is already running

        release_event.set()
        for _ in range(50):
            if not coordinator.is_rebuild_running():
                break
            time.sleep(0.05)

        assert call_count["value"] == 1, "a second start_rebuild() call while one is already running must not fire a second real extraction pass"

    def test_start_rebuild_clears_running_state_even_when_the_worker_raises(self, mocker):
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel",
            side_effect=RuntimeError("simulated extraction failure"),
        )

        coordinator = GlossaryCoordinator("375266002")
        coordinator.start_rebuild()

        for _ in range(50):
            if not coordinator.is_rebuild_running():
                break
            time.sleep(0.05)
        assert coordinator.is_rebuild_running() is False, "a raised exception in the background worker must still clear _rebuild_in_progress, not leave it stuck True"

    def _run_rebuild_and_join_its_thread(self, coordinator, on_complete):
        """start_rebuild(), then join the actual background thread it spawns before returning.

        start_rebuild() doesn't expose its internal threading.Thread, and
        on_complete() fires inside the worker's own finally block --
        slightly *before* the thread function fully returns and the
        Thread object itself terminates. Waiting only on an Event set by
        on_complete() (an earlier version of this test did) leaves a real
        race window where mocker.patch's own automatic un-patching (this
        test's teardown) can run concurrently with the tail end of that
        still-finishing thread touching mock internals -- confirmed live:
        this reproduced a real, if rare, Illegal instruction crash in a
        full-suite run (Python 3.14 + Tk + threading + GC, the same
        general class of hazard already documented for two other,
        pre-existing tests elsewhere in this suite, but a third distinct
        trigger, introduced by these new tests specifically). Comparing
        the set of alive threads before/after start_rebuild() and
        joining the new one directly closes that window, rather than
        deselecting these tests the way the two pre-existing hazards
        were handled -- this one is fully within this test's own control
        to fix outright.
        """
        threads_before = set(threading.enumerate())
        coordinator.start_rebuild(on_complete=on_complete)
        new_threads = set(threading.enumerate()) - threads_before
        for t in new_threads:
            t.join(timeout=5)

    def test_on_complete_called_with_none_on_success(self, mocker):
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel",
            return_value={"terms": []},
        )
        complete_calls = []

        def on_complete(error):
            complete_calls.append(error)

        coordinator = GlossaryCoordinator("375266002")
        self._run_rebuild_and_join_its_thread(coordinator, on_complete)

        assert complete_calls == [None], "on_complete() must be called with None (no error) on a successful rebuild"

    def test_on_complete_called_with_the_exception_on_failure(self, mocker):
        exc = RuntimeError("simulated extraction failure")
        mocker.patch("pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel", side_effect=exc)
        complete_calls = []

        def on_complete(error):
            complete_calls.append(error)

        coordinator = GlossaryCoordinator("375266002")
        self._run_rebuild_and_join_its_thread(coordinator, on_complete)

        assert complete_calls == [exc], "on_complete() must be called with the actual raised exception on failure"

    def test_on_complete_is_optional_and_does_not_raise_when_omitted(self, mocker):
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.build_glossary_for_novel",
            return_value={"terms": []},
        )
        coordinator = GlossaryCoordinator("375266002")
        coordinator.start_rebuild()  # no on_complete passed -- must not raise

        for _ in range(50):
            if not coordinator.is_rebuild_running():
                break
            time.sleep(0.05)
        assert coordinator.is_rebuild_running() is False


class TestNotifyEdited:
    """Tests for the current no-op placeholder -- confirms it doesn't raise or require a registered callback yet."""

    def test_notify_edited_does_not_raise_with_no_callback_registered(self):
        coordinator = GlossaryCoordinator("375266002")
        coordinator.notify_edited(True)
        coordinator.notify_edited(False)


def _find_button_by_text(win, text):
    """Recursively search a dialog's widget tree for a ttk.Button with the given text.

    Local to this file rather than imported from
    test_alphapolis_reader.py -- a small, private helper duplicated once
    rather than cross-importing a test-only symbol from another test
    file.
    """
    for child in win.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


def _find_widgets_by_type(win, widget_type, found=None):
    """Recursively collect every widget of `widget_type` in a dialog's widget tree, in tree order."""
    if found is None:
        found = []
    for child in win.winfo_children():
        if isinstance(child, widget_type):
            found.append(child)
        _find_widgets_by_type(child, widget_type, found)
    return found


class _SyncThread:
    """threading.Thread stand-in that runs its target synchronously in the calling thread instead of a real thread.

    open_word_glossary_popup()'s fetch_guesses() normally runs on a real
    background thread and schedules build_form() via self.root.after(0,
    ...) once it returns. Outside a real mainloop() (as in a test), that
    after() call races the test thread and can hit Tk's C-layer "main
    thread is not in main loop" RuntimeError -- confirmed live: the
    background thread raised exactly that (silently, as an unhandled
    thread exception) when this test first tried polling root.update()
    in a loop and waiting for the real thread to finish on its own.
    check_llm_available()/translate_chunk() are already mocked to return
    instantly/deterministically, so there is no real concurrency worth
    testing here -- same fix already established in
    test_retranslation_dialog.py's TestAcceptSurvivesModeSwitch for the
    identical pattern in open_retranslate_popup(): run the "background"
    work synchronously, then a single root.update() pumps the now-main-
    thread-scheduled after() callback safely.
    """

    def __init__(self, target, daemon=True):
        self._target = target

    def start(self):
        self._target()


class TestOpenWordGlossaryPopupRoutesThroughCoordinator:
    """REFACTOR_DESIGN.md Phase 3b: open_word_glossary_popup()'s Save path now routes through GlossaryCoordinator.upsert_confirmed().

    Drives the real, unmodified open_word_glossary_popup() end-to-end
    (via the reader_app_shell fixture -- real ReaderApp method, real Tk
    widgets, real Save button click) rather than calling the coordinator
    directly, so this test would fail if the dialog reverted to calling
    glossary.load_glossary()/upsert_confirmed_term()/glossary.save_glossary()
    directly instead of GlossaryCoordinator.upsert_confirmed().
    check_llm_available() is mocked False (avoids a real explain_term()/LLM
    call) and translate_chunk() is mocked to a synchronous fake (avoids a
    real Google Translate network call) -- same mocking pattern already
    established in test_retranslation_dialog.py's TestPopupSingleInstanceGuard
    for this exact dialog.
    """

    def test_save_writes_via_coordinator_upsert_confirmed_not_direct_glossary_calls(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")
        monkeypatch.setattr(reader_module.threading, "Thread", _SyncThread)

        # Fail loudly if the dialog ever calls these directly again --
        # confirms the write genuinely goes through the coordinator, not
        # just that *a* write happens to land correctly.
        def _fail_if_called_directly(*args, **kwargs):
            raise AssertionError(
                "open_word_glossary_popup() must not call glossary.py functions directly -- it must route through GlossaryCoordinator (REFACTOR_DESIGN.md Phase 3b)"
            )

        monkeypatch.setattr(reader_module, "load_glossary", _fail_if_called_directly)
        monkeypatch.setattr(reader_module, "save_glossary", _fail_if_called_directly)
        # upsert_confirmed_term is no longer imported into alphapolis_reader
        # at all as of Phase 3c (both open_word_glossary_popup() and
        # open_term_review_dialog() now route through the coordinator) --
        # nothing left to patch here; load_glossary/save_glossary above
        # already cover the direct-call-fallback case for this dialog.

        upsert_calls = []
        monkeypatch.setattr(reader_module.GlossaryCoordinator, "upsert_confirmed", lambda self, new_term: upsert_calls.append((self.novel_id, new_term)) or {"terms": []})

        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/375266002/1/episode/1"
        reader_app_shell.open_word_glossary_popup("鉄パイプ", "iron pipe", context="鉄パイプを持っていた。")

        win = reader_app_shell._glossary_popup
        assert win is not None

        # fetch_guesses() ran synchronously (via _SyncThread above) and
        # scheduled build_form() via root.after(0, ...) -- pump the event
        # loop once so that callback actually runs and replaces the
        # "Looking up translations..." status label with the real form.
        reader_app_shell.root.update()
        save_btn = _find_button_by_text(win, "Save")
        assert save_btn is not None, "Save button never appeared -- build_form() did not run"

        save_btn.invoke()

        assert len(upsert_calls) == 1, "GlossaryCoordinator.upsert_confirmed() must have been called exactly once"
        novel_id, new_term = upsert_calls[0]
        assert novel_id == "375266002"
        assert new_term["source"] == "鉄パイプ"
        assert new_term["confirmed_target"] == "iron pipe"

    def test_save_result_matches_pre_refactor_on_disk_shape(self, reader_app_shell, monkeypatch, mocker):
        """The on-disk result of Save is unchanged from the user's perspective, now produced via the coordinator instead of the dialog's own direct calls."""
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")
        monkeypatch.setattr(reader_module.threading, "Thread", _SyncThread)

        existing_glossary = {
            "title": "Test Novel",
            "honorific_policy": "keep",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "terms": [],
        }
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing_glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/375266002/1/episode/1"
        reader_app_shell.open_word_glossary_popup("ハードキャッチ", "Hard Catch", context="")

        win = reader_app_shell._glossary_popup
        reader_app_shell.root.update()
        save_btn = _find_button_by_text(win, "Save")
        assert save_btn is not None, "Save button never appeared -- build_form() did not run"

        save_btn.invoke()

        assert saved["novel_id"] == "375266002"
        saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
        assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED
        assert saved_terms["ハードキャッチ"]["confirmed_target"] == "Hard Catch"
        assert saved_terms["ハードキャッチ"]["type"] == TERM_TYPE_GENERAL


class _ReviewDialogHarness:
    """Minimal stand-in exposing exactly what open_term_review_dialog() touches on self.

    Same shape as test_term_review_dialog.py's own _ReviewDialogHarness
    -- duplicated here (not imported) per this file's existing convention
    of small, private test helpers staying local rather than cross-
    imported between test files.
    """

    def __init__(self, root, current_url):
        self.root = root
        self.current_url = current_url
        self.refresh_calls = []

    def set_status(self, msg):
        pass

    def refresh_current_episode(self):
        self.refresh_calls.append(self.current_url)

    open_term_review_dialog = ReaderApp.open_term_review_dialog
    _maybe_refresh_after_glossary_edit = ReaderApp._maybe_refresh_after_glossary_edit


def _make_review_glossary(terms):
    return {"novel_id": "375266002", "title": "Test Novel", "terms": terms, "context_notes": "", "updated_at": ""}


class TestOpenTermReviewDialogRoutesThroughCoordinator:
    """REFACTOR_DESIGN.md Phase 3c: open_term_review_dialog()'s Confirm/Reject actions now route through GlossaryCoordinator.

    Same standard as 3b: drives the real, unmodified dialog end-to-end
    through its actual Confirm/Reject buttons, with monkeypatched
    load_glossary()/save_glossary() in alphapolis_reader configured to
    fail loudly if called directly -- confirms the write genuinely goes
    through the coordinator, not just that a write happens to land
    correctly.
    """

    def test_confirm_fails_loudly_if_dialog_calls_glossary_functions_directly(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_review_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)

        def _fail_if_called_directly(*args, **kwargs):
            raise AssertionError("open_term_review_dialog() must not call save_glossary() directly -- it must route through GlossaryCoordinator (REFACTOR_DESIGN.md Phase 3c)")

        monkeypatch.setattr(reader_module, "save_glossary", _fail_if_called_directly)

        upsert_calls = []
        monkeypatch.setattr(
            coordinator_module.GlossaryCoordinator, "upsert_confirmed", lambda self, new_term: upsert_calls.append((self.novel_id, new_term)) or {"terms": [], "updated_at": ""}
        )
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Review Terms")
            tree = win.winfo_children()[0].winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            confirm_btn = _find_button_by_text(win, "Confirm")
            assert confirm_btn is not None
            confirm_btn.invoke()

            assert len(upsert_calls) == 1
            novel_id, new_term = upsert_calls[0]
            assert novel_id == "375266002"
            assert new_term["source"] == "鉄パイプ"
        finally:
            root.destroy()

    def test_reject_fails_loudly_if_dialog_calls_glossary_functions_directly(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_review_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)

        def _fail_if_called_directly(*args, **kwargs):
            raise AssertionError("open_term_review_dialog() must not call save_glossary() directly -- it must route through GlossaryCoordinator (REFACTOR_DESIGN.md Phase 3c)")

        monkeypatch.setattr(reader_module, "save_glossary", _fail_if_called_directly)
        monkeypatch.setattr(reader_module.messagebox, "askyesno", lambda *a, **k: True)

        reject_calls = []
        monkeypatch.setattr(coordinator_module.GlossaryCoordinator, "reject", lambda self, source: reject_calls.append((self.novel_id, source)) or {"terms": [], "updated_at": ""})
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Review Terms")
            tree = win.winfo_children()[0].winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            reject_btn = _find_button_by_text(win, "Reject")
            assert reject_btn is not None
            reject_btn.invoke()

            assert reject_calls == [("375266002", "鉄パイプ")]
        finally:
            root.destroy()

    def test_confirm_after_type_correction_persists_the_corrected_type(self, monkeypatch, mocker):
        """The 弁護士 case from the Phase 3 prep step's real extraction: a term misclassified as character, corrected to term, then confirmed -- the correction must survive."""
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_review_glossary([make_suggested_term(TERM_TYPE_CHARACTER, "弁護士", "lawyer")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            type_combo = None
            for w in form.winfo_children():
                if isinstance(w, ttk.Combobox):
                    type_combo = w
            assert type_combo is not None, "type Combobox not found -- 弁護士 was originally classified as character, form should show that as the current selection"
            # The real extraction misclassified this as character --
            # correct it to term (this dialog's whole reason for editable
            # type, per build_form()'s own docstring on the character-vs-
            # term misclassification problem).
            type_combo.set(TERM_TYPE_GENERAL)

            confirm_btn = _find_button_by_text(win, "Confirm")
            assert confirm_btn is not None
            confirm_btn.invoke()

            assert saved["novel_id"] == "375266002"
            confirmed = saved["glossary"]["terms"][0]
            assert confirmed["source"] == "弁護士"
            assert (
                confirmed["type"] == TERM_TYPE_GENERAL
            ), "the type correction (character -> term) made in this dialog must persist, not silently revert to the original misclassification"
            assert confirmed["status"] == STATUS_CONFIRMED
        finally:
            root.destroy()


def _find_toplevel_by_title_prefix(root, prefix):
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel) and child.title().startswith(prefix):
            return child
    return None


class _GlossaryDialogHarness:
    """Minimal stand-in exposing exactly what open_glossary_dialog() touches on self.

    Same shape as test_alphapolis_reader.py's own _GlossaryDialogHarness
    -- duplicated here (not imported), per this file's existing
    convention of small, private test helpers staying local rather than
    cross-imported between test files.
    """

    def __init__(self, root, current_url):
        self.root = root
        self.current_url = current_url
        self.refresh_calls = []

    def set_status(self, msg):
        pass

    def refresh_current_episode(self):
        self.refresh_calls.append(self.current_url)

    open_glossary_dialog = ReaderApp.open_glossary_dialog
    _maybe_refresh_after_glossary_edit = ReaderApp._maybe_refresh_after_glossary_edit


def _make_glossary_dialog_glossary(terms):
    return {"novel_id": "375266002", "title": "Test Novel", "honorific_policy": "keep", "terms": terms, "context_notes": "", "updated_at": "2026-01-01T00:00:00+00:00"}


class TestOpenGlossaryDialogRoutesThroughCoordinator:
    """REFACTOR_DESIGN.md Phase 3d: open_glossary_dialog()'s Save and Clear Glossary actions now route through GlossaryCoordinator.

    Same standard as 3b/3c: drives the real, unmodified dialog end-to-end
    through its actual Save/Clear Glossary buttons, with monkeypatched
    load_glossary()/save_glossary() in alphapolis_reader configured to
    fail loudly if called directly -- confirms the write genuinely goes
    through the coordinator, not just that a write happens to land
    correctly.
    """

    def test_save_fails_loudly_if_dialog_calls_glossary_functions_directly(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary_dialog_glossary([make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)

        def _fail_if_called_directly(*args, **kwargs):
            raise AssertionError("open_glossary_dialog() must not call save_glossary() directly -- it must route through GlossaryCoordinator (REFACTOR_DESIGN.md Phase 3d)")

        monkeypatch.setattr(reader_module, "save_glossary", _fail_if_called_directly)

        save_snapshot_calls = []
        monkeypatch.setattr(
            coordinator_module.GlossaryCoordinator,
            "save_snapshot",
            lambda self, **kwargs: save_snapshot_calls.append((self.novel_id, kwargs)) or {"terms": [], "updated_at": ""},
        )
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            save_btn = _find_button_by_text(win, "Save")
            assert save_btn is not None
            save_btn.invoke()

            assert len(save_snapshot_calls) == 1
            novel_id, kwargs = save_snapshot_calls[0]
            assert novel_id == "375266002"
            assert kwargs["honorific_policy"] == "keep"
        finally:
            root.destroy()

    def test_clear_glossary_fails_loudly_if_dialog_calls_save_glossary_directly(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary_dialog_glossary([make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)

        def _fail_if_called_directly(*args, **kwargs):
            raise AssertionError(
                "open_glossary_dialog()'s clear_glossary() must not call save_glossary() directly -- it must route through GlossaryCoordinator.clear() (REFACTOR_DESIGN.md Phase 3d)"
            )

        monkeypatch.setattr(reader_module, "save_glossary", _fail_if_called_directly)
        monkeypatch.setattr(reader_module.messagebox, "askyesno", lambda *a, **k: True)

        clear_calls = []
        monkeypatch.setattr(coordinator_module.GlossaryCoordinator, "clear", lambda self: clear_calls.append(self.novel_id) or {"terms": [], "updated_at": ""})
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            clear_btn = _find_button_by_text(win, "Clear Glossary")
            assert clear_btn is not None
            clear_btn.invoke()

            assert clear_calls == ["375266002"]
        finally:
            root.destroy()

    def test_save_result_matches_pre_refactor_on_disk_shape(self, monkeypatch, mocker):
        """The on-disk result of Save is unchanged from the user's perspective, now produced via the coordinator instead of the dialog's own direct calls."""
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary_dialog_glossary([make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            save_btn = _find_button_by_text(win, "Save")
            assert save_btn is not None
            save_btn.invoke()

            assert saved["novel_id"] == "375266002"
            saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
            assert saved_terms["鉄パイプ"]["confirmed_target"] == "iron pipe"
            assert saved["glossary"]["honorific_policy"] == "keep"
        finally:
            root.destroy()

    def test_clear_result_matches_pre_refactor_on_disk_shape(self, monkeypatch, mocker):
        """The on-disk result of Clear Glossary is unchanged from the user's perspective, now produced via GlossaryCoordinator.clear()."""
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary_dialog_glossary(
            [
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
                make_confirmed_term(term_type=TERM_TYPE_CHARACTER, source="ケイト", target="Kate"),
            ]
        )
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")
        monkeypatch.setattr(reader_module.messagebox, "askyesno", lambda *a, **k: True)

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            clear_btn = _find_button_by_text(win, "Clear Glossary")
            assert clear_btn is not None
            clear_btn.invoke()

            assert saved["novel_id"] == "375266002"
            assert saved["glossary"]["terms"] == []
            assert saved["glossary"]["honorific_policy"] == DEFAULT_HONORIFIC_POLICY
            assert saved["glossary"]["honorific_policy_user_set"] is False
        finally:
            root.destroy()


class TestGlobalVocabularyReferenceAndApplyGlobally:
    """RETRANSLATION_DESIGN.md Phase 5 additions to open_glossary_dialog()'s build_form().

    Covers the global-vocabulary click-to-use reference field and the
    "Apply Globally" action, both term-typed-row-only (character entries
    are never globally eligible -- a name is only correct for one
    specific story). Same standard as the coordinator-routing tests
    above: drives the real, unmodified dialog end-to-end through its
    actual widgets, not a reimplementation of the logic under test.
    """

    def _select_row(self, win, index):
        tree = win.winfo_children()[1].winfo_children()[0]
        tree.selection_set(str(index))
        tree.event_generate("<<TreeviewSelect>>")
        win.update()

    def test_apply_globally_button_absent_for_character_type_rows(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        term = make_confirmed_term(term_type=TERM_TYPE_CHARACTER, source="ハードキャッチ", target="Hard Catch")
        glossary = _make_glossary_dialog_glossary([term])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "get_global_entry", lambda source: None)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            self._select_row(win, 0)

            assert _find_button_by_text(win, "Apply Globally") is None
        finally:
            root.destroy()

    def test_apply_globally_button_absent_for_unconfirmed_term_rows(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        term = make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")
        assert term["status"] == STATUS_SUGGESTED
        glossary = _make_glossary_dialog_glossary([term])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "get_global_entry", lambda source: None)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            self._select_row(win, 0)

            assert _find_button_by_text(win, "Apply Globally") is None
        finally:
            root.destroy()

    def test_apply_globally_button_present_and_writes_via_upsert_global_entry(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        term = make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="バッターボックスに立", target="batting box")
        glossary = _make_glossary_dialog_glossary([term])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "get_global_entry", lambda source: None)
        monkeypatch.setattr(reader_module.messagebox, "showinfo", lambda *a, **k: None)

        calls = []
        monkeypatch.setattr(reader_module, "upsert_global_entry", lambda source, target, note=None: calls.append((source, target, note)))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            self._select_row(win, 0)

            apply_btn = _find_button_by_text(win, "Apply Globally")
            assert apply_btn is not None, "Apply Globally must be offered for a confirmed term-typed row"
            apply_btn.invoke()

            assert calls == [("バッターボックスに立", "batting box", None)]
        finally:
            root.destroy()

    def test_reference_button_shown_and_sets_target_on_click_when_global_entry_exists(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        term = make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="醤油顔", target="dark complexion")
        glossary = _make_glossary_dialog_glossary([term])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "get_global_entry", lambda source: {"source": "醤油顔", "target": "plain-featured", "note": None})
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            self._select_row(win, 0)

            ref_btn = _find_button_by_text(win, "Global: plain-featured")
            assert ref_btn is not None, "click-to-use reference button must be offered when a matching global entry exists"
            ref_btn.invoke()

            # ttk.Combobox is a ttk.Entry subclass, so this list also
            # picks up the honorific-policy and type comboboxes ahead of
            # the form's own Source/Target/Note entries -- confirmed by
            # inspection: [0]=honorific policy, [1]=type, [2]=source,
            # [3]=target, [4]=note. Target reading the global reference's
            # value confirms the click set form_vars["target"].
            entries = _find_widgets_by_type(win, ttk.Entry)
            assert entries[3].get() == "plain-featured"
        finally:
            root.destroy()

    def test_reference_label_shown_when_no_global_entry_exists(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        term = make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe")
        glossary = _make_glossary_dialog_glossary([term])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "get_global_entry", lambda source: None)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "375266002")

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/1/episode/1")
            harness.open_glossary_dialog()
            root.update()

            win = _find_toplevel_by_title_prefix(root, "Glossary")
            self._select_row(win, 0)

            assert _find_button_by_text(win, "Global: (none)") is None
            labels = [w.cget("text") for w in _find_widgets_by_type(win, ttk.Label)]
            assert "Global: (none)" in labels
        finally:
            root.destroy()
