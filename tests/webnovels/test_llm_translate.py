#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for llm_translate.py's translate_lines_with_masking() (DESIGN.md Section 11).

Mocks requests.post rather than hitting a live llama-server -- these tests
target the chunk-offset re-indexing logic (mask_targets is expressed
against the full input, chunking is internal, so each chunk's targets must
be re-indexed to be chunk-relative before being handed to
translate_chunk_with_masking()), which is deterministic and doesn't need a
real model. Live verification against a real server is covered separately
(see DESIGN.md Section 11's live end-to-end run).
"""

import json as json_module

from pyplayground.webnovels.llm_translate import TranslatedLine, splice_terms, translate_lines_with_masking


def _mock_completion_response(mocker, line_batches):
    """Patch requests.post so each call echoes back one item from line_batches, in order."""
    calls = {"i": 0}

    def fake_post(url, json=None, timeout=None):
        batch = line_batches[calls["i"]]
        calls["i"] += 1
        resp = mocker.Mock()
        resp.raise_for_status = mocker.Mock()
        resp.json.return_value = {"content": json_module.dumps(batch, ensure_ascii=False)}
        return resp

    mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=fake_post)


class TestTranslateLinesWithMasking:
    """Tests for translate_lines_with_masking()'s chunking and mask_targets re-indexing."""

    def test_single_chunk_passes_through_unmodified_mask_targets(self, mocker):
        """When everything fits in one chunk, chunk-relative indices equal the original indices."""
        lines = ["ケイトが振り返った。", "ルリが微笑んだ。"]
        _mock_completion_response(mocker, [["⟦TERM_1⟧ turned around.", "Ruri smiled."]])

        result = translate_lines_with_masking(lines, [(0, "ケイト")], max_chunk_chars=400)

        assert len(result) == 2
        assert all(isinstance(r, TranslatedLine) for r in result)
        assert result[0].text == "ケイト turned around."
        # A clean sentinel splice still leaves raw source text in place --
        # splicing never translates a masked term either way -- so this is
        # needs_review=True too, not just the missing-sentinel fallback.
        assert result[0].needs_review is True
        assert result[1].text == "Ruri smiled."
        assert result[1].needs_review is False

    def test_mask_targets_reindexed_correctly_across_chunk_boundary(self, mocker):
        """A mask target on a line in the second chunk must be translated to chunk-relative index."""
        # Force a chunk split: max_chunk_chars small enough that line 0 and
        # line 1 land in separate chunks.
        lines = ["短い文。", "維多教授が尋ねた。"]
        _mock_completion_response(
            mocker,
            [
                ["A short sentence."],  # chunk 0: just line 0
                ["⟦TERM_1⟧ asked."],  # chunk 1: just line 1, sentinel for the masked term
            ],
        )

        # mask target is on line 1 (global index), which will be
        # chunk-relative index 0 within chunk 1 -- if re-indexing is wrong,
        # this either masks nothing or raises inside mask_terms().
        result = translate_lines_with_masking(lines, [(1, "維多教授")], max_chunk_chars=10)

        assert len(result) == 2
        assert result[0].text == "A short sentence."
        assert result[0].needs_review is False
        assert result[1].text == "維多教授 asked."
        assert result[1].needs_review is True

    def test_no_mask_targets_behaves_like_plain_translation(self, mocker):
        lines = ["こんにちは。"]
        _mock_completion_response(mocker, [["Hello."]])

        result = translate_lines_with_masking(lines, [], max_chunk_chars=400)

        assert result == [TranslatedLine(text="Hello.", needs_review=False)]

    def test_missing_sentinel_produces_needs_review_true(self, mocker):
        """A dropped sentinel's needs_review=True fallback must surface through this wrapper."""
        lines = ["ケイトが微笑んだ。"]
        # Model returns a translation with no sentinel at all -- the
        # missing-sentinel fallback path.
        _mock_completion_response(mocker, [["She smiled."]])

        result = translate_lines_with_masking(lines, [(0, "ケイト")], max_chunk_chars=400)

        assert len(result) == 1
        assert result[0].needs_review is True
        assert "ケイト" in result[0].text

    def test_fallbacks_threaded_through_to_splice_terms(self, mocker):
        """`fallbacks` is passed through unmodified (not re-indexed, unlike mask_targets -- it's keyed by word, not line index) to every chunk's splice."""
        lines = ["ケイトが振り返った。"]
        _mock_completion_response(mocker, [["⟦TERM_1⟧ turned around."]])

        result = translate_lines_with_masking(lines, [(0, "ケイト")], max_chunk_chars=400, fallbacks={"ケイト": "Kate"})

        assert result[0].text == "Kate turned around."
        assert result[0].needs_review is True

    def test_no_fallbacks_argument_preserves_original_behavior(self, mocker):
        lines = ["ケイトが振り返った。"]
        _mock_completion_response(mocker, [["⟦TERM_1⟧ turned around."]])

        result = translate_lines_with_masking(lines, [(0, "ケイト")], max_chunk_chars=400)

        assert result[0].text == "ケイト turned around."

    def test_chunk_failure_produces_placeholder_translated_line(self, mocker):
        """A chunk-level exception still produces a TranslatedLine rather than raising out."""

        def raise_error(url, json=None, timeout=None):
            raise ConnectionError("simulated failure")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        result = translate_lines_with_masking(["こんにちは。"], [], max_chunk_chars=400)

        assert len(result) == 1
        assert isinstance(result[0], TranslatedLine)
        assert "translation failed" in result[0].text


class TestLogContext:
    """Tests for log_context -- prefixes every warning/error a translation call logs with a caller-supplied label (e.g. the episode URL).

    Found necessary via a real live-test log: a chunk-level failure logged
    only "Chunk 3/10: ..." with no way to tell which episode it belonged
    to short of cross-referencing timestamps against a separate
    "Fetching and translating episode: ..." line elsewhere in the file.
    """

    def test_failure_log_includes_log_context_prefix(self, mocker, caplog):
        import logging

        def raise_error(url, json=None, timeout=None):
            raise ConnectionError("simulated failure")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        with caplog.at_level(logging.ERROR):
            translate_lines_with_masking(["こんにちは。"], [], max_chunk_chars=400, log_context="https://example.com/novel/1/episode/2")

        assert any("https://example.com/novel/1/episode/2" in record.message for record in caplog.records)

    def test_omitted_log_context_produces_no_prefix(self, mocker, caplog):
        import logging

        def raise_error(url, json=None, timeout=None):
            raise ConnectionError("simulated failure")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        with caplog.at_level(logging.ERROR):
            translate_lines_with_masking(["こんにちは。"], [], max_chunk_chars=400)

        assert any(record.message.startswith("Chunk") for record in caplog.records)
        assert not any(record.message.startswith("[") for record in caplog.records)


class TestSpliceTerms:
    """Direct tests for splice_terms(), the function actually responsible for setting needs_review.

    Found via a real production run (DESIGN.md's dated entry): the
    clean-splice path -- sentinel present, spliced back with no warning --
    was not flagged needs_review, even though it substitutes the same raw,
    untranslated source word as the missing-sentinel path. Both paths leave
    identical raw-Japanese-in-English-text results for the reader, so both
    must set needs_review=True.
    """

    def test_clean_sentinel_splice_still_sets_needs_review_true(self):
        """The sentinel survived and spliced cleanly, but the result is still raw source text -- must be flagged."""
        result = splice_terms("⟦TERM_1⟧ turned around.", [("ケイト", 1)])

        assert result.text == "ケイト turned around."
        assert result.needs_review is True

    def test_missing_sentinel_still_sets_needs_review_true(self):
        result = splice_terms("She turned around.", [("ケイト", 1)])

        assert "ケイト" in result.text
        assert result.needs_review is True

    def test_no_targets_leaves_needs_review_false(self):
        """A line with nothing to splice was never masked -- nothing to flag."""
        result = splice_terms("Kate turned around.", [])

        assert result.text == "Kate turned around."
        assert result.needs_review is False

    def test_multiple_targets_all_clean_still_flagged(self):
        result = splice_terms("⟦TERM_1⟧ and ⟦TERM_2⟧ talked.", [("ケイト", 1), ("ルリ", 2)])

        assert result.text == "ケイト and ルリ talked."
        assert result.needs_review is True

    def test_fallback_used_instead_of_raw_word_on_clean_splice(self):
        """glossary.build_splice_fallbacks()'s best-candidate result substitutes for the bare raw word, per DESIGN.md's dated entry -- display-quality only."""
        result = splice_terms("⟦TERM_1⟧ crouched down.", [("オレ", 1)], fallbacks={"オレ": "Me"})

        assert result.text == "Me crouched down."
        assert result.needs_review is True

    def test_fallback_used_on_missing_sentinel_path_too(self):
        result = splice_terms("He crouched down.", [("オレ", 1)], fallbacks={"オレ": "Me"})

        assert "Me" in result.text
        assert "オレ" not in result.text
        assert result.needs_review is True

    def test_word_not_in_fallbacks_dict_uses_raw_word(self):
        """Only words present in fallbacks get substituted -- a word with no glossary entry keeps the original raw-source-text behavior."""
        result = splice_terms("⟦TERM_1⟧ crouched down.", [("オレ", 1)], fallbacks={"鉄パイプ": "iron pipe"})

        assert result.text == "オレ crouched down."

    def test_no_fallbacks_argument_preserves_original_behavior(self):
        """Purely additive -- omitting fallbacks entirely must behave identically to before this change."""
        result = splice_terms("⟦TERM_1⟧ crouched down.", [("オレ", 1)])

        assert result.text == "オレ crouched down."
        assert result.needs_review is True

    def test_empty_fallbacks_dict_same_as_no_fallbacks(self):
        result = splice_terms("⟦TERM_1⟧ crouched down.", [("オレ", 1)], fallbacks={})

        assert result.text == "オレ crouched down."
