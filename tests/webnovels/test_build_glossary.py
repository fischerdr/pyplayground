#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for build_glossary.py's build_glossary_for_novel() (REFACTOR_DESIGN.md Phase 3e).

Phase 3e's extraction-vs-dialog race fix: build_glossary_for_novel() used
to hold a single in-memory glossary snapshot from one load_glossary() call
at the very start of its (potentially long, one-LLM-call-per-episode)
extraction loop, and write it back with one save_glossary() call at the
end -- no re-check-before-write at all, unlike every dialog write path
(GlossaryCoordinator.save_snapshot()/upsert_confirmed()/reject()/clear(),
Phase 3a-3d). Live-reproduced (not assumed) that this silently clobbers a
concurrent dialog write landing anywhere in that window: a real race
script confirmed a GlossaryCoordinator.upsert_confirmed() call for an
unrelated term, made while a slow extraction loop was mid-flight, got
completely discarded by the rebuild's final blind overwrite.

TestRaceWithConcurrentDialogWrite below is the regression coverage for
that exact scenario, reproduced deterministically via a controllable
extraction stand-in (a real background thread, gated by a
threading.Event, standing in for "a rebuild slow enough to interleave
with a real dialog write") rather than a real, slow LLM call.
"""

import threading

from pyplayground.webnovels import build_glossary
from pyplayground.webnovels.glossary import STATUS_CONFIRMED, TERM_TYPE_GENERAL, make_confirmed_term
from pyplayground.webnovels.glossary_coordinator import GlossaryCoordinator


def _make_glossary(novel_id, terms=None, updated_at="2026-01-01T00:00:00+00:00"):
    return {
        "novel_id": novel_id,
        "title": "Race Test Novel",
        "honorific_policy": "keep",
        "honorific_policy_user_set": False,
        "context_notes": "",
        "terms": terms or [],
        "updated_at": updated_at,
    }


class _FakeGlossaryStore:
    """A tiny in-memory stand-in for the on-disk glossary file, shared by mocked load_glossary()/save_glossary() in both build_glossary and glossary_coordinator.

    A real threading.Lock guards reads/writes -- this models the file
    genuinely being a single shared resource multiple threads/callers
    read and write, same as the real on-disk JSON file, without needing
    actual disk I/O in a unit test.
    """

    def __init__(self, initial):
        self._glossary = initial
        self._lock = threading.Lock()

    def load(self, novel_id):
        with self._lock:
            return dict(self._glossary, terms=[dict(t) for t in self._glossary["terms"]])

    def save(self, novel_id, glossary):
        with self._lock:
            self._glossary = dict(glossary, terms=[dict(t) for t in glossary["terms"]])


class TestRaceWithConcurrentDialogWrite:
    """The actual scenario Phase 3e exists to fix: a real dialog write landing while build_glossary_for_novel() is mid-extraction."""

    def test_concurrent_dialog_write_and_rebuild_extraction_both_survive(self, mocker):
        novel_id = "999999998"
        store = _FakeGlossaryStore(_make_glossary(novel_id))

        mocker.patch.object(build_glossary, "load_glossary", store.load)
        mocker.patch.object(build_glossary, "save_glossary", store.save)
        mocker.patch.object(
            build_glossary,
            "_load_cached_episodes_for_novel",
            return_value=[{"lines": ["line1"], "translated_lines": ["line1"], "episode_title": "ep1", "url": "u1"}],
        )

        extraction_started = threading.Event()
        release_extraction = threading.Event()

        def slow_extract_glossary_terms(source_lines, translated_lines):
            extraction_started.set()
            # Stand-in for a real, slow LLM call -- gated by an Event
            # instead of a fixed sleep, so the test controls the exact
            # interleaving deterministically rather than hoping a sleep
            # duration is long enough.
            release_extraction.wait(timeout=5)
            return {"terms": [{"source": "ダンジョン能力者", "type": "term", "target": "Dungeon Ability-user"}]}

        mocker.patch.object(build_glossary, "extract_glossary_terms", side_effect=slow_extract_glossary_terms)

        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        mocker.patch.object(coordinator_module, "load_glossary", store.load)
        mocker.patch.object(coordinator_module, "save_glossary", store.save)

        rebuild_thread = threading.Thread(target=build_glossary.build_glossary_for_novel, args=(novel_id,))
        rebuild_thread.start()

        assert extraction_started.wait(timeout=5), "extraction never started -- test setup issue, not the race itself"

        # The real dialog write, via the real (unmocked) GlossaryCoordinator
        # method -- for a genuinely different, unrelated source than
        # anything the rebuild's extraction is touching.
        coordinator = GlossaryCoordinator(novel_id)
        coordinator.upsert_confirmed(make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"))

        release_extraction.set()
        rebuild_thread.join(timeout=5)
        assert not rebuild_thread.is_alive(), "rebuild thread did not finish -- test setup issue"

        final = store.load(novel_id)
        sources_by_name = {t["source"]: t for t in final["terms"]}

        assert "鉄パイプ" in sources_by_name, "the concurrent dialog write must survive the rebuild's write, not be silently clobbered"
        assert sources_by_name["鉄パイプ"]["status"] == STATUS_CONFIRMED
        assert sources_by_name["鉄パイプ"]["confirmed_target"] == "iron pipe"

        assert "ダンジョン能力者" in sources_by_name, "the rebuild's own extraction result must also survive, not be lost by the merge"

    def test_rebuild_result_alone_survives_when_no_concurrent_write_happens(self, mocker):
        """Sanity check: without any concurrent write, the rebuild's own result is unaffected by the new merge-on-divergence logic."""
        novel_id = "999999997"
        store = _FakeGlossaryStore(_make_glossary(novel_id))

        mocker.patch.object(build_glossary, "load_glossary", store.load)
        mocker.patch.object(build_glossary, "save_glossary", store.save)
        mocker.patch.object(
            build_glossary,
            "_load_cached_episodes_for_novel",
            return_value=[{"lines": ["line1"], "translated_lines": ["line1"], "episode_title": "ep1", "url": "u1"}],
        )
        mocker.patch.object(
            build_glossary,
            "extract_glossary_terms",
            return_value={"terms": [{"source": "魔導書", "type": "term", "target": "grimoire"}]},
        )

        build_glossary.build_glossary_for_novel(novel_id)

        final = store.load(novel_id)
        assert {t["source"] for t in final["terms"]} == {"魔導書"}


class TestIncrementalExtraction:
    """Phase 3f: build_glossary_for_novel() must not re-run extraction on episodes it has already processed.

    Before this fix, every rebuild re-processed up to max_episodes cached
    episodes via a real LLM call each, regardless of whether anything new
    had been cached since the last rebuild -- confirmed real and growing
    cost (DESIGN.md's background-extraction investigation entry).
    extracted_episode_urls is a plain, additive glossary field (same
    .setdefault()-on-load precedent as honorific_policy) tracking which
    episode URLs a rebuild has already extracted from.
    """

    def test_second_rebuild_with_no_new_episodes_does_not_reextract_anything(self, mocker):
        novel_id = "999999996"
        store = _FakeGlossaryStore(_make_glossary(novel_id))

        mocker.patch.object(build_glossary, "load_glossary", store.load)
        mocker.patch.object(build_glossary, "save_glossary", store.save)
        mocker.patch.object(
            build_glossary,
            "_load_cached_episodes_for_novel",
            return_value=[
                {"lines": ["line1"], "translated_lines": ["line1"], "episode_title": "ep1", "url": "u1"},
                {"lines": ["line2"], "translated_lines": ["line2"], "episode_title": "ep2", "url": "u2"},
            ],
        )
        extract_mock = mocker.patch.object(
            build_glossary,
            "extract_glossary_terms",
            return_value={"terms": [{"source": "魔導書", "type": "term", "target": "grimoire"}]},
        )

        build_glossary.build_glossary_for_novel(novel_id)
        assert extract_mock.call_count == 2, "first rebuild must extract from both (new) episodes"

        extract_mock.reset_mock()
        build_glossary.build_glossary_for_novel(novel_id)
        assert extract_mock.call_count == 0, "second rebuild against the same, already-extracted episode set must not re-invoke extraction at all"

        final = store.load(novel_id)
        assert set(final["extracted_episode_urls"]) == {"u1", "u2"}

    def test_new_episode_added_between_rebuilds_only_extracts_the_new_one(self, mocker):
        novel_id = "999999995"
        store = _FakeGlossaryStore(_make_glossary(novel_id))

        mocker.patch.object(build_glossary, "load_glossary", store.load)
        mocker.patch.object(build_glossary, "save_glossary", store.save)
        episodes = [{"lines": ["line1"], "translated_lines": ["line1"], "episode_title": "ep1", "url": "u1"}]
        cached_episodes_mock = mocker.patch.object(build_glossary, "_load_cached_episodes_for_novel", return_value=episodes)
        extract_mock = mocker.patch.object(
            build_glossary,
            "extract_glossary_terms",
            return_value={"terms": [{"source": "魔導書", "type": "term", "target": "grimoire"}]},
        )

        build_glossary.build_glossary_for_novel(novel_id)
        assert extract_mock.call_count == 1

        extract_mock.reset_mock()
        episodes.append({"lines": ["line2"], "translated_lines": ["line2"], "episode_title": "ep2", "url": "u2"})
        cached_episodes_mock.return_value = episodes

        build_glossary.build_glossary_for_novel(novel_id)
        assert extract_mock.call_count == 1, "only the genuinely new episode should be extracted from, not both again"
        assert extract_mock.call_args.args == (["line2"], ["line2"])

        final = store.load(novel_id)
        assert set(final["extracted_episode_urls"]) == {"u1", "u2"}
