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

from pyplayground.webnovels.llm_translate import TranslatedLine, translate_lines_with_masking


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
        assert result[0].needs_review is False
        assert result[1].text == "Ruri smiled."

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
        assert result[1].text == "維多教授 asked."
        assert result[1].needs_review is False

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

    def test_chunk_failure_produces_placeholder_translated_line(self, mocker):
        """A chunk-level exception still produces a TranslatedLine rather than raising out."""

        def raise_error(url, json=None, timeout=None):
            raise ConnectionError("simulated failure")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        result = translate_lines_with_masking(["こんにちは。"], [], max_chunk_chars=400)

        assert len(result) == 1
        assert isinstance(result[0], TranslatedLine)
        assert "translation failed" in result[0].text
