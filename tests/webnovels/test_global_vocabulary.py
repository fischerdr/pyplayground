#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for global_vocabulary.py (RETRANSLATION_DESIGN.md Phase 5).

Covers the cross-novel general-vocabulary/idiom correction store, separate
from glossary.py's per-novel character/term glossaries.
"""

import json

import pyplayground.webnovels.global_vocabulary as global_vocabulary_module
from pyplayground.webnovels.global_vocabulary import (
    _empty_store,
    format_global_vocabulary_for_prompt,
    get_global_entry,
    load_global_vocabulary,
    save_global_vocabulary,
    upsert_global_entry,
)
from pyplayground.webnovels.glossary import STATUS_SUGGESTED, _empty_glossary, make_confirmed_term, make_suggested_term


class TestLoadSaveGlobalVocabulary:
    """Tests for load_global_vocabulary()/save_global_vocabulary()'s file I/O."""

    def test_load_missing_file_returns_empty_store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")

        store = load_global_vocabulary()

        assert store == _empty_store()

    def test_save_then_load_roundtrips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "nested" / "global_vocabulary.json")
        store = {"updated_at": "2026-07-31T00:00:00+00:00", "entries": [{"source": "醤油顔", "target": "plain-featured", "note": None, "added_at": "x", "updated_at": "x"}]}

        save_global_vocabulary(store)
        loaded = load_global_vocabulary()

        assert loaded == store

    def test_load_corrupt_json_returns_empty_store(self, tmp_path, monkeypatch):
        path = tmp_path / "global_vocabulary.json"
        path.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", path)

        store = load_global_vocabulary()

        assert store == _empty_store()


class TestUpsertGlobalEntry:
    """Tests for upsert_global_entry()'s reload-fresh-immediately-before-write discipline."""

    def test_new_source_is_added(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")

        upsert_global_entry("醤油顔", "plain-featured", note="idiom")

        entries = load_global_vocabulary()["entries"]
        assert len(entries) == 1
        assert entries[0]["source"] == "醤油顔"
        assert entries[0]["target"] == "plain-featured"
        assert entries[0]["note"] == "idiom"

    def test_existing_source_is_overwritten_not_duplicated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")

        upsert_global_entry("醤油顔", "dark complexion")
        upsert_global_entry("醤油顔", "plain-featured")

        entries = load_global_vocabulary()["entries"]
        assert len(entries) == 1
        assert entries[0]["target"] == "plain-featured"

    def test_reloads_fresh_before_write(self, tmp_path, monkeypatch):
        """Confirms upsert reloads fresh rather than writing from a stale in-memory copy.

        A concurrent writer's addition (written directly to disk between
        two upsert_global_entry() calls in this test) must survive.
        """
        path = tmp_path / "global_vocabulary.json"
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", path)

        upsert_global_entry("醤油顔", "plain-featured")

        # Simulate a concurrent writer adding a second entry directly to disk.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        on_disk["entries"].append({"source": "ノーズボン", "target": "briefs", "note": None, "added_at": "x", "updated_at": "x"})
        path.write_text(json.dumps(on_disk), encoding="utf-8")

        upsert_global_entry("鉄パイプ", "iron pipe")

        sources = {e["source"] for e in load_global_vocabulary()["entries"]}
        assert sources == {"醤油顔", "ノーズボン", "鉄パイプ"}

    def test_sets_added_at_only_on_first_write_and_refreshes_updated_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")

        upsert_global_entry("醤油顔", "dark complexion")
        first_added_at = load_global_vocabulary()["entries"][0]["added_at"]
        first_updated_at = load_global_vocabulary()["entries"][0]["updated_at"]

        upsert_global_entry("醤油顔", "plain-featured")
        entry = load_global_vocabulary()["entries"][0]
        assert entry["added_at"] == first_added_at
        assert entry["updated_at"] != first_updated_at or entry["target"] == "plain-featured"


class TestGetGlobalEntry:
    """Tests for get_global_entry() -- used by the click-to-use reference field."""

    def test_returns_none_for_missing_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")

        assert get_global_entry("醤油顔") is None

    def test_returns_matching_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(global_vocabulary_module, "GLOBAL_VOCAB_PATH", tmp_path / "global_vocabulary.json")
        upsert_global_entry("醤油顔", "plain-featured", note="idiom")

        entry = get_global_entry("醤油顔")

        assert entry["target"] == "plain-featured"
        assert entry["note"] == "idiom"


class TestFormatGlobalVocabularyForPrompt:
    """Tests for format_global_vocabulary_for_prompt()'s precedence rule and capitalization reinforcement."""

    def test_empty_store_returns_empty_string(self):
        assert format_global_vocabulary_for_prompt(_empty_store()) == ""

    def test_entry_included_when_no_novel_glossary_conflict(self):
        store = {"entries": [{"source": "醤油顔", "target": "plain-featured", "note": None}]}
        novel_glossary = _empty_glossary("1")

        rendered = format_global_vocabulary_for_prompt(store, novel_glossary)

        assert "醤油顔 -> plain-featured" in rendered

    def test_entry_excluded_when_current_novel_confirms_same_source(self):
        """Precedence: a per-novel confirmed term always wins over a same-source global note."""
        store = {"entries": [{"source": "醤油顔", "target": "plain-featured", "note": None}]}
        novel_glossary = _empty_glossary("1")
        novel_glossary["terms"] = [make_confirmed_term("term", "醤油顔", "understated features")]

        rendered = format_global_vocabulary_for_prompt(store, novel_glossary)

        assert rendered == ""

    def test_entry_included_when_current_novel_has_same_source_but_only_suggested(self):
        """An unconfirmed per-novel term must not suppress the global note -- only STATUS_CONFIRMED wins."""
        store = {"entries": [{"source": "醤油顔", "target": "plain-featured", "note": None}]}
        novel_glossary = _empty_glossary("1")
        term = make_suggested_term("term", "醤油顔", "something else")
        assert term["status"] == STATUS_SUGGESTED
        novel_glossary["terms"] = [term]

        rendered = format_global_vocabulary_for_prompt(store, novel_glossary)

        assert "醤油顔 -> plain-featured" in rendered

    def test_none_current_novel_glossary_includes_all_entries(self):
        store = {"entries": [{"source": "醤油顔", "target": "plain-featured", "note": None}]}

        rendered = format_global_vocabulary_for_prompt(store, None)

        assert "醤油顔 -> plain-featured" in rendered

    def test_mixed_case_target_gets_reinforcement_note(self):
        store = {"entries": [{"source": "ハードキャッチ", "target": "Hard Catch", "note": None}]}

        rendered = format_global_vocabulary_for_prompt(store)

        assert "(keep this exact capitalization)" in rendered

    def test_all_lowercase_target_gets_no_reinforcement_note(self):
        store = {"entries": [{"source": "鉄パイプ", "target": "iron pipe", "note": None}]}

        rendered = format_global_vocabulary_for_prompt(store)

        assert "(keep this exact capitalization)" not in rendered

    def test_note_field_rendered_when_present(self):
        store = {"entries": [{"source": "醤油顔", "target": "plain-featured", "note": "idiom, not literal"}]}

        rendered = format_global_vocabulary_for_prompt(store)

        assert "idiom, not literal" in rendered
