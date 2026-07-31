#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for glossary.py's term data model (DESIGN.md Section 9) and mask_targets producer (DESIGN.md Section 9's trigger rule)."""

from pyplayground.webnovels.glossary import (
    ORIGIN_LLM,
    ORIGIN_MT,
    ORIGIN_USER,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    _empty_glossary,
    best_candidate_for_term,
    build_mask_targets,
    build_splice_fallbacks,
    find_glossary_term_spans,
    format_glossary_for_prompt,
    make_confirmed_term,
    make_suggested_term,
    merge_terms,
    mixed_case_note,
    update_candidate_counts,
    upsert_confirmed_term,
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

    def test_mixed_case_confirmed_target_gets_reinforcement_note(self):
        """RETRANSLATION_DESIGN.md's 2026-07-31 finding.

        A multi-word capitalized target must carry the capitalization-
        reinforcement note in the per-novel formatter too, not just the
        global one.
        """
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_CHARACTER, "ハードキャッチ", "Hard Catch")]

        rendered = format_glossary_for_prompt(glossary)

        assert "(keep this exact capitalization)" in rendered

    def test_single_word_confirmed_target_gets_no_reinforcement_note(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]

        rendered = format_glossary_for_prompt(glossary)

        assert "(keep this exact capitalization)" not in rendered


class TestMixedCaseNote:
    """Tests for mixed_case_note() -- RETRANSLATION_DESIGN.md's 2026-07-31 finding's capitalization-reinforcement helper."""

    def test_multi_word_capitalized_target_gets_note(self):
        """The documented failure case: 2+ capitalized words triggers the reinforcement note."""
        assert mixed_case_note("Hard Catch") == "(keep this exact capitalization)"

    def test_single_capitalized_word_gets_no_note(self):
        """Ordinary single-capitalized names must not trigger the reinforcement note.

        E.g. "Kate" was honored reliably in the 2026-07-31 investigation
        with no reinforcement needed -- the narrowed rule deliberately
        excludes this case, not the broader "any upper+lower mix" test.
        """
        assert mixed_case_note("Kate") is None

    def test_all_lowercase_target_gets_no_note(self):
        assert mixed_case_note("iron pipe") is None

    def test_all_uppercase_single_word_gets_no_note(self):
        assert mixed_case_note("TOKAREV") is None


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


class TestUpsertConfirmedTerm:
    """Tests for upsert_confirmed_term() -- the manual dialog-save path, distinct from merge_terms()."""

    def test_no_existing_entry_appends(self):
        existing = [make_confirmed_term(TERM_TYPE_GENERAL, "ルリ", "Ruri")]
        new_term = make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "Me")

        result = upsert_confirmed_term(existing, new_term)

        assert len(result) == 2

    def test_same_type_same_source_replaces_existing(self):
        existing = [make_suggested_term(TERM_TYPE_GENERAL, "オレ", "I")]
        new_term = make_confirmed_term(TERM_TYPE_GENERAL, "オレ", "Me")

        result = upsert_confirmed_term(existing, new_term)

        assert len(result) == 1
        assert result[0]["status"] == STATUS_CONFIRMED
        assert result[0]["confirmed_target"] == "Me"

    def test_reproduces_and_fixes_the_live_bug_mismatched_type_replaces_not_duplicates(self):
        """The exact live bug: a character-typed extraction, then a human confirms the same source as type=term.

        merge_terms() would keep both (different (type, source) keys --
        see TestMergeTerms.test_same_source_different_type_both_kept, which
        documents that as merge_terms()'s own intentional behavior). This
        function must not: a human confirming a source word is confirming
        that word, not "that word only as this specific type."
        """
        existing = [make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "I/Me")]
        # Simulate the old-shape entry actually seen in the live bug: no
        # status field at all (pre-Section-9 schema, never migrated).
        existing[0].pop("status", None)
        existing[0].pop("confirmed_target", None)
        existing[0].pop("candidates", None)
        existing[0]["target"] = "I/Me"

        new_term = make_confirmed_term(TERM_TYPE_GENERAL, "オレ", "Me")

        result = upsert_confirmed_term(existing, new_term)

        assert len(result) == 1
        assert result[0]["type"] == TERM_TYPE_GENERAL
        assert result[0]["status"] == STATUS_CONFIRMED
        assert result[0]["confirmed_target"] == "Me"

    def test_new_confirmed_entry_no_longer_masked(self):
        """The actual thing the live bug was breaking: build_mask_targets() must not mask a source a human just confirmed."""
        glossary = _empty_glossary("1")
        old_shape_entry = make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "I/Me")
        old_shape_entry.pop("status", None)
        glossary["terms"] = [old_shape_entry]

        new_term = make_confirmed_term(TERM_TYPE_GENERAL, "オレ", "Me")
        glossary["terms"] = upsert_confirmed_term(glossary["terms"], new_term)

        targets = build_mask_targets(["オレは彼を見た。"], glossary)

        assert targets == []

    def test_multiple_stale_duplicates_all_replaced_by_one(self):
        """Defensive: even if more than one stale entry somehow exists for a source, upsert collapses to exactly one."""
        existing = [
            make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "I"),
            make_suggested_term(TERM_TYPE_GENERAL, "オレ", "Me (guess)"),
        ]
        new_term = make_confirmed_term(TERM_TYPE_GENERAL, "オレ", "Me")

        result = upsert_confirmed_term(existing, new_term)

        assert len(result) == 1
        assert result[0]["confirmed_target"] == "Me"

    def test_unrelated_sources_untouched(self):
        existing = [
            make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate"),
            make_confirmed_term(TERM_TYPE_GENERAL, "魔法", "magic"),
        ]
        new_term = make_confirmed_term(TERM_TYPE_CHARACTER, "オレ", "Me")

        result = upsert_confirmed_term(existing, new_term)

        assert len(result) == 3
        sources = {t["source"] for t in result}
        assert sources == {"ケイト", "魔法", "オレ"}


class TestBuildMaskTargets:
    """Tests for build_mask_targets() -- the mask_targets producer (DESIGN.md Section 9's v1 rule: status != confirmed)."""

    def test_confirmed_term_not_masked(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]

        targets = build_mask_targets(["ケイトが振り返った。"], glossary)

        assert targets == []

    def test_suggested_term_is_masked(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]

        targets = build_mask_targets(["ケイトが振り返った。"], glossary)

        assert targets == [(0, "ケイト")]

    def test_mixed_glossary_only_masks_unconfirmed(self):
        """Reproduces the 5-sentinel stress case from the sentinel-masking test suite (DESIGN.md Section 4), now driven by real glossary status instead of a hand-picked target list."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun"),
            make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate"),
            make_suggested_term(TERM_TYPE_GENERAL, "維多教授", "Professor Vito"),
        ]
        lines = [
            "「ケイト、ルリ、音夢くん、みんな揃った?」と維多教授が尋ねた。",
            "ケイトは頷き、ルリは笑顔で答えた。「はい、揃いました」",
            "音夢くんだけは少し遅れて到着した。",
        ]

        targets = build_mask_targets(lines, glossary)

        assert targets == [(0, "音夢くん"), (0, "維多教授"), (2, "音夢くん")]

    def test_empty_glossary_returns_no_targets(self):
        glossary = _empty_glossary("1")

        assert build_mask_targets(["何かの文章。"], glossary) == []

    def test_term_not_present_in_lines_returns_no_targets(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun")]

        targets = build_mask_targets(["この文には出てこない。"], glossary)

        assert targets == []

    def test_repeated_occurrence_in_one_line_produces_one_target_per_occurrence(self):
        """mask_terms() consumes one tuple per literal occurrence (single-count str.replace() each) -- the producer must match that shape, not just report presence once per line."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]

        targets = build_mask_targets(["ケイトとケイトは似ている。"], glossary)

        assert targets == [(0, "ケイト"), (0, "ケイト")]


class TestFindGlossaryTermSpans:
    """Tests for find_glossary_term_spans() -- span-level needs_review highlighting/click resolution."""

    def test_single_term_span_located(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")]

        spans = find_glossary_term_spans("Because of オレ's hard catch, they were crushed.", glossary)

        assert spans == [(11, 13, "オレ")]

    def test_multiple_occurrences_of_same_term_found_separately_no_overlap(self):
        """The オレ オレ splice-fallback case (DESIGN.md's 2026-07-26 needs_review fix entry) -- each occurrence must resolve to its own span, not just the first."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")]

        spans = find_glossary_term_spans("...than them. オレ オレ", glossary)

        assert spans == [(14, 16, "オレ"), (17, 19, "オレ")]

    def test_confirmed_status_does_not_exclude_a_term_from_span_search(self):
        """Critical requirement: this must NOT filter by status, unlike build_mask_targets().

        A term confirmed after an episode was cached must still resolve for
        span highlighting/click on that already-cached episode -- the raw
        spliced text is still sitting in the line regardless of the term's
        current status.
        """
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_confirmed_term(TERM_TYPE_GENERAL, "オレ", "Me")]

        spans = find_glossary_term_spans("Because of オレ's hard catch, they were crushed.", glossary)

        assert spans == [(11, 13, "オレ")]

    def test_no_matching_term_returns_empty(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")]

        spans = find_glossary_term_spans("A perfectly ordinary translated line.", glossary)

        assert spans == []

    def test_empty_glossary_returns_empty(self):
        glossary = _empty_glossary("1")

        assert find_glossary_term_spans("Some line with オレ in it.", glossary) == []

    def test_longer_source_matched_before_shorter_substring(self):
        """Same overlap discipline as build_mask_targets(): 音夢くん must claim its span before 音夢 fragments it."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun"),
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢", "Otomu"),
        ]

        spans = find_glossary_term_spans("Only 音夢くん arrived late.", glossary)

        assert spans == [(5, 9, "音夢くん")]

    def test_different_terms_on_same_line_both_found_in_position_order(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me"),
            make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
        ]

        spans = find_glossary_term_spans("オレ crushed their hands along with 鉄パイプ.", glossary)

        assert spans == [(0, 2, "オレ"), (34, 38, "鉄パイプ")]

    def test_same_term_across_multiple_lines(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]
        lines = ["ケイトとルリは、幼い頃からの親友だった。", "「ルリ、今日は付き合ってくれてありがとう」とケイトが言った。"]

        targets = build_mask_targets(lines, glossary)

        assert targets == [(0, "ケイト"), (1, "ケイト")]

    def test_longer_term_wins_over_overlapping_shorter_substring(self):
        """If a shorter unconfirmed term's source text is a substring of a longer unconfirmed term's source text, only the longer match should be emitted -- masking both would produce overlapping spans that break mask_terms()'s sequential single-count replace()."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢", "Otomu"),
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun"),
        ]

        targets = build_mask_targets(["音夢くんが到着した。"], glossary)

        assert targets == [(0, "音夢くん")]

    def test_shorter_term_still_matched_when_not_overlapping_a_longer_one(self):
        """The longer-match-wins rule should only suppress genuinely overlapping spans, not every occurrence of a shorter term elsewhere in the same line."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢", "Otomu"),
            make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun"),
        ]
        # "音夢くん" (longer) appears first; a standalone "音夢" appears later, not overlapping.
        targets = build_mask_targets(["音夢くんと音夢は別の呼び方だ。"], glossary)

        assert targets == [(0, "音夢くん"), (0, "音夢")]

    def test_output_shape_feeds_directly_into_translate_chunk_with_masking(self):
        """Contract check: build_mask_targets()'s return shape must match translate_chunk_with_masking()'s mask_targets parameter with no adapter needed."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")]

        targets = build_mask_targets(["ケイトが振り返った。"], glossary)

        assert isinstance(targets, list)
        for entry in targets:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            line_idx, word = entry
            assert isinstance(line_idx, int)
            assert isinstance(word, str)


class TestBestCandidateForTerm:
    """Tests for best_candidate_for_term()."""

    def test_single_candidate_returned(self):
        term = make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")

        assert best_candidate_for_term(term) == "Me"

    def test_highest_count_wins(self):
        term = {
            "source": "维多教授",
            "candidates": [
                {"target": "Professor Weiduo", "count": 1, "origin": ORIGIN_LLM},
                {"target": "Professor Victor", "count": 23, "origin": ORIGIN_USER},
                {"target": "Professor Vito", "count": 4, "origin": ORIGIN_MT},
            ],
        }

        assert best_candidate_for_term(term) == "Professor Victor"

    def test_tie_on_count_broken_by_origin_user_beats_mt_beats_llm(self):
        term = {
            "source": "x",
            "candidates": [
                {"target": "from-llm", "count": 5, "origin": ORIGIN_LLM},
                {"target": "from-mt", "count": 5, "origin": ORIGIN_MT},
                {"target": "from-user", "count": 5, "origin": ORIGIN_USER},
            ],
        }

        assert best_candidate_for_term(term) == "from-user"

    def test_tie_on_count_and_origin_falls_back_to_list_order(self):
        term = {
            "source": "x",
            "candidates": [
                {"target": "first", "count": 5, "origin": ORIGIN_LLM},
                {"target": "second", "count": 5, "origin": ORIGIN_LLM},
            ],
        }

        assert best_candidate_for_term(term) == "first"

    def test_no_candidates_returns_none(self):
        term = {"source": "x", "candidates": []}

        assert best_candidate_for_term(term) is None

    def test_missing_candidates_key_returns_none(self):
        term = {"source": "x"}

        assert best_candidate_for_term(term) is None

    def test_confirmed_term_returns_its_own_confirmed_target(self):
        """A confirmed term's sole candidate is always identical to confirmed_target (make_confirmed_term()'s own construction) -- confirms the 'harmless even if reachable' note in build_splice_fallbacks()'s docstring."""
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")

        assert best_candidate_for_term(term) == term["confirmed_target"] == "Kate"


class TestBuildSpliceFallbacks:
    """Tests for build_splice_fallbacks()."""

    def test_word_with_suggested_candidate_maps_to_best_candidate(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")]
        mask_targets = [(0, "オレ")]

        fallbacks = build_splice_fallbacks(mask_targets, glossary)

        assert fallbacks == {"オレ": "Me"}

    def test_word_with_no_glossary_entry_falls_back_to_itself(self):
        """A term genuinely not yet extracted/known -- preserves the original raw-source-text behavior."""
        glossary = _empty_glossary("1")
        mask_targets = [(0, "オレ")]

        fallbacks = build_splice_fallbacks(mask_targets, glossary)

        assert fallbacks == {"オレ": "オレ"}

    def test_term_with_empty_candidates_list_falls_back_to_itself(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [{"source": "オレ", "type": "character", "candidates": []}]
        mask_targets = [(0, "オレ")]

        fallbacks = build_splice_fallbacks(mask_targets, glossary)

        assert fallbacks == {"オレ": "オレ"}

    def test_duplicate_words_across_lines_only_computed_once(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me")]
        mask_targets = [(0, "オレ"), (2, "オレ")]

        fallbacks = build_splice_fallbacks(mask_targets, glossary)

        assert fallbacks == {"オレ": "Me"}

    def test_multiple_distinct_words(self):
        glossary = _empty_glossary("1")
        glossary["terms"] = [
            make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me"),
            make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
        ]
        mask_targets = [(0, "オレ"), (0, "鉄パイプ")]

        fallbacks = build_splice_fallbacks(mask_targets, glossary)

        assert fallbacks == {"オレ": "Me", "鉄パイプ": "iron pipe"}


class TestUpdateCandidateCounts:
    """Tests for update_candidate_counts() -- the count-building loop (DESIGN.md Section 12)."""

    def test_confirmed_term_match_increments_count(self):
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        term["candidates"][0]["count"] = 5
        glossary["terms"] = [term]

        updated = update_candidate_counts(["ケイトが振り返った。"], ["Kate turned around."], glossary)

        assert updated["terms"][0]["candidates"][0]["count"] == 6

    def test_suggested_terms_are_never_counted(self):
        """A suggested/masked term's line contains the raw source word, not a model translation -- no candidate string to match against, per Section 12's scope."""
        glossary = _empty_glossary("1")
        glossary["terms"] = [make_suggested_term(TERM_TYPE_CHARACTER, "音夢くん", "Otomu-kun")]

        updated = update_candidate_counts(["音夢くんが手を振った。"], ["音夢くん waved."], glossary)

        assert updated["terms"][0]["candidates"][0]["count"] == 1  # unchanged from make_suggested_term()'s initial count

    def test_needs_review_line_excluded_from_counting(self):
        """A line whose translation attempt needed the fallback isn't evidence of anything the model successfully did -- must not count."""
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        updated = update_candidate_counts(
            ["ケイトが振り返った。"],
            ["Kate turned around."],
            glossary,
            needs_review_flags=[True],
        )

        assert updated["terms"][0]["candidates"][0]["count"] == 1  # unchanged

    def test_no_match_in_chunk_leaves_count_unchanged(self):
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        updated = update_candidate_counts(["ルリが微笑んだ。"], ["Ruri smiled."], glossary)

        assert updated["terms"][0]["candidates"][0]["count"] == 1  # unchanged

    def test_source_present_but_target_not_translated_as_expected_leaves_count_unchanged(self):
        """Source term appears in the chunk, but the translated line doesn't contain the confirmed_target string -- e.g. the model used different phrasing. Not a match, no increment."""
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        updated = update_candidate_counts(["ケイトが振り返った。"], ["She turned around."], glossary)

        assert updated["terms"][0]["candidates"][0]["count"] == 1  # unchanged

    def test_only_the_matching_candidate_is_incremented_not_others(self):
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "维多教授", "Professor Victor")
        term["candidates"] = [
            {"target": "Professor Victor", "count": 23, "origin": "user"},
            {"target": "Professor Vito", "count": 4, "origin": "mt"},
        ]
        term["confirmed_target"] = "Professor Victor"
        glossary["terms"] = [term]

        updated = update_candidate_counts(["维多教授が尋ねた。"], ["Professor Victor asked."], glossary)

        candidates = {c["target"]: c["count"] for c in updated["terms"][0]["candidates"]}
        assert candidates["Professor Victor"] == 24
        assert candidates["Professor Vito"] == 4  # unchanged

    def test_multiple_lines_in_chunk_only_counts_once_per_chunk_per_term(self):
        """A term appearing twice within the same translate call still only gets one increment -- matches "which candidate won for this chunk," not a per-occurrence tally."""
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        updated = update_candidate_counts(
            ["ケイトが振り返った。", "ケイトは頷いた。"],
            ["Kate turned around.", "Kate nodded."],
            glossary,
        )

        assert updated["terms"][0]["candidates"][0]["count"] == 2

    def test_unrelated_confirmed_terms_untouched(self):
        glossary = _empty_glossary("1")
        matched = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        unrelated = make_confirmed_term(TERM_TYPE_CHARACTER, "ルリ", "Ruri")
        glossary["terms"] = [matched, unrelated]

        updated = update_candidate_counts(["ケイトが振り返った。"], ["Kate turned around."], glossary)

        by_source = {t["source"]: t for t in updated["terms"]}
        assert by_source["ケイト"]["candidates"][0]["count"] == 2
        assert by_source["ルリ"]["candidates"][0]["count"] == 1  # unchanged

    def test_original_glossary_not_mutated(self):
        """update_candidate_counts() returns a new glossary, matching merge_terms()'s convention -- the caller's original dict must be unaffected."""
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        update_candidate_counts(["ケイトが振り返った。"], ["Kate turned around."], glossary)

        assert glossary["terms"][0]["candidates"][0]["count"] == 1  # original untouched

    def test_empty_source_lines_leaves_glossary_unchanged(self):
        glossary = _empty_glossary("1")
        term = make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")
        glossary["terms"] = [term]

        updated = update_candidate_counts([], [], glossary)

        assert updated["terms"][0]["candidates"][0]["count"] == 1
