#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for glossary_coordinator.py (REFACTOR_DESIGN.md Phase 3a).

Standalone unit tests against GlossaryCoordinator directly -- no Tk, no
dialog harness, since this step deliberately does not wire the coordinator
into any dialog yet. save_snapshot()'s merge-on-divergence scenarios mirror
tests/webnovels/test_alphapolis_reader.py's TestGlossaryDialogMergeOnDivergence
exactly (same fixtures, same three scenarios), confirming the logic lifted
into the coordinator behaves identically to the original
open_glossary_dialog().save_and_close() it was copied from.
"""

import threading
import time

from pyplayground.webnovels.glossary import STATUS_CONFIRMED, TERM_TYPE_CHARACTER, TERM_TYPE_GENERAL, make_confirmed_term
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
    """Tests for the real-delete-by-identity path."""

    def test_reject_removes_the_term_entirely_not_just_its_status(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.glossary_coordinator.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=g),
        )

        coordinator = GlossaryCoordinator("375266002")
        # reject() matches by identity -- must operate on the exact object
        # returned by this coordinator's own load(), matching
        # reject_selected()'s `t is not term` filter exactly.
        loaded = coordinator.load()
        target = next(t for t in loaded["terms"] if t["source"] == "ハードキャッチ")

        result = coordinator.reject(target)

        assert "ハードキャッチ" not in {t["source"] for t in result["terms"]}
        assert len(result["terms"]) == 1
        assert saved["glossary"]["terms"] == result["terms"]

    def test_reject_leaves_other_terms_untouched(self, mocker):
        existing = _glossary_at_open()
        mocker.patch("pyplayground.webnovels.glossary_coordinator.load_glossary", return_value=existing)
        mocker.patch("pyplayground.webnovels.glossary_coordinator.save_glossary")

        coordinator = GlossaryCoordinator("375266002")
        loaded = coordinator.load()
        target = next(t for t in loaded["terms"] if t["source"] == "ハードキャッチ")

        result = coordinator.reject(target)

        remaining = {t["source"] for t in result["terms"]}
        assert remaining == {"鉄パイプ"}


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


class TestNotifyEdited:
    """Tests for the current no-op placeholder -- confirms it doesn't raise or require a registered callback yet."""

    def test_notify_edited_does_not_raise_with_no_callback_registered(self):
        coordinator = GlossaryCoordinator("375266002")
        coordinator.notify_edited(True)
        coordinator.notify_edited(False)
