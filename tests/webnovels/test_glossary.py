#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for glossary.py's term data model (DESIGN.md Section 9)."""

from pyplayground.webnovels.glossary import (
    ORIGIN_LLM,
    ORIGIN_USER,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    _empty_glossary,
    format_glossary_for_prompt,
    make_confirmed_term,
    make_suggested_term,
    merge_terms,
)


class TestEmptyGlossary:
    """Tests for _empty_glossary()'s shape."""

    def test_fresh_glossary_has_no_terms(self):
        """A fresh glossary has an empty term list, not the old flat shape."""
        glossary = _empty_glossary("12345")

        assert glossary["novel_id"] == "12345"
        assert glossary["terms"] == []


class TestMakeConfirmedTerm:
    """Tests for make_confirmed_term() -- the manual Add Term path."""

    def test_confirmed_term_shape(self):
        """A manually-added term is trusted on entry: confirmed, one user candidate."""
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")

        assert term["status"] == STATUS_CONFIRMED
        assert term["confirmed_target"] == "Professor Victor"
        assert term["candidates"] == [{"target": "Professor Victor", "count": 1, "origin": ORIGIN_USER}]
        assert term["source"] == "维多教授"
        assert term["type"] == TERM_TYPE_CHARACTER

    def test_confirmed_term_note_defaults_to_none(self):
        """Note is optional and defaults to None, not omitted from the dict."""
        term = make_confirmed_term(TERM_TYPE_GENERAL, "魔法", "magic")

        assert term["note"] is None

    def test_confirmed_term_note_preserved(self):
        """Note survives the schema migration (DESIGN.md Section 9 explicitly keeps it, unlike the rest of the flat shape)."""
        term = make_confirmed_term(TERM_TYPE_GENERAL, "世紀末モヒカンムーブ", "post-apocalyptic mohawk move", note="slang, one-off")

        assert term["note"] == "slang, one-off"


class TestMakeSuggestedTerm:
    """Tests for make_suggested_term() -- the LLM extraction path."""

    def test_suggested_term_shape(self):
        """A fresh extraction lands in the review queue, not immediately trusted."""
        term = make_suggested_term(TERM_TYPE_CHARACTER, "糧品瑠羽", "Ruha Kateshina")

        assert term["status"] == STATUS_SUGGESTED
        assert term["confirmed_target"] is None
        assert term["candidates"] == [{"target": "Ruha Kateshina", "count": 1, "origin": ORIGIN_LLM}]

    def test_suggested_term_custom_origin(self):
        """Origin is overridable (e.g. "mt" for a machine-translation guess)."""
        term = make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe", origin="mt")

        assert term["candidates"][0]["origin"] == "mt"


class TestFormatGlossaryForPrompt:
    """Tests for format_glossary_for_prompt()'s confirmed-only filtering."""

    def test_empty_glossary_returns_empty_string(self):
        glossary = _empty_glossary("1")

        assert format_glossary_for_prompt(glossary) == ""

    def test_suggested_only_glossary_returns_empty_string(self):
        """An unreviewed extraction must never reach the translation prompt (DESIGN.md Section 9's status gate)."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otoyo-kun")]

        assert format_glossary_for_prompt(glossary) == ""

    def test_confirmed_term_is_included(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")]

        rendered = format_glossary_for_prompt(glossary)

        assert "维多教授 -> Professor Victor" in rendered

    def test_mixed_confirmed_and_suggested_only_renders_confirmed(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor"),
            make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
        ]

        rendered = format_glossary_for_prompt(glossary)

        assert "Professor Victor" in rendered
        assert "iron pipe" not in rendered

    def test_confirmed_general_term_note_still_rendered(self):
        """Regression guard: note must still render for TERM_TYPE_GENERAL entries after the schema migration."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_GENERAL, "世紀末モヒカンムーブ", "post-apocalyptic mohawk move", note="one-off slang")]

        rendered = format_glossary_for_prompt(glossary)

        assert "one-off slang" in rendered

    def test_confirmed_character_detail_rendered(self):
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "一郎", "Ichiro")
        term["gender"] = "male"
        term["pronoun_style"] = "casual, uses 'ore'"
        glossary["terms"] = [term]

        rendered = format_glossary_for_prompt(glossary)

        assert "male" in rendered
        assert "casual, uses 'ore'" in rendered


class TestMergeTerms:
    """Tests for merge_terms()'s dedup/append behavior with the new shape."""

    def test_new_extraction_lands_as_suggested(self):
        """merge_terms() is status-agnostic -- callers decide status via which constructor they use before merging."""
        existing = []
        new_terms = [make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otoyo-kun")]

        merged = merge_terms(existing, new_terms)

        assert len(merged) == 1
        assert merged[0]["status"] == STATUS_SUGGESTED
        assert merged[0]["confirmed_target"] is None

    def test_manual_confirmed_term_stays_confirmed_through_merge(self):
        existing = []
        new_terms = [make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")]

        merged = merge_terms(existing, new_terms)

        assert merged[0]["status"] == STATUS_CONFIRMED

    def test_existing_confirmed_term_wins_on_conflict(self):
        """A user-confirmed term must not be clobbered by a re-extraction of the same source string."""
        existing = [make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")]
        new_terms = [make_suggested_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Weiduo")]

        merged = merge_terms(existing, new_terms)

        assert len(merged) == 1
        assert merged[0]["status"] == STATUS_CONFIRMED
        assert merged[0]["confirmed_target"] == "Professor Victor"

    def test_different_source_terms_both_kept(self):
        existing = [make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")]
        new_terms = [make_suggested_term(TERM_TYPE_GENERAL, "魔法", "magic")]

        merged = merge_terms(existing, new_terms)

        assert len(merged) == 2

    def test_same_source_different_type_both_kept(self):
        """A character and a general term can share source text without colliding -- dedup key is (type, source)."""
        existing = [make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "I (masculine)")]
        new_terms = [make_suggested_term(TERM_TYPE_GENERAL, "オレ", "I")]

        merged = merge_terms(existing, new_terms)

        assert len(merged) == 2
