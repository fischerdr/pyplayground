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

from pyplayground.webnovels.llm_translate import (
    TranslatedLine,
    _is_collective_shout,
    _strip_collective_shout_brackets,
    splice_terms,
    translate_chunk,
    translate_chunk_with_masking,
    translate_lines_with_masking,
)


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


def _mock_completion_echoing_prompt_lines(mocker, translator):
    """Patch requests.post so each call decodes the actual `lines_json` sent and returns translator(line) per entry.

    Used to prove what the prompt-building code actually sent to the model
    (post-strip), not just what the caller originally passed in -- the
    prior helper's fixed line_batches can't express "assert the sent
    prompt had no brackets" since it never inspects the outgoing payload.
    """
    import re

    def fake_post(url, json=None, timeout=None):
        prompt = json["prompt"]
        match = re.search(r"array: (\[.*\])\n\nJSON array:", prompt, re.DOTALL)
        sent_lines = json_module.loads(match.group(1))
        resp = mocker.Mock()
        resp.raise_for_status = mocker.Mock()
        resp.json.return_value = {"content": json_module.dumps([translator(line) for line in sent_lines], ensure_ascii=False)}
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


# The 21 real doubled/tripled-bracket lines found in cache during the
# DESIGN.md 2026-08-01 investigation (`「{2,}|」{2,}` classifier), 6 of
# which were confirmed corrupt in production cached output and all 21 of
# which were live-tested against translategemma in the follow-up
# validation entry. (name, source line, was_corrupt_in_cache) -- kept as
# the actual real-world corpus, not synthetic examples, so these tests
# regression-guard the exact cases the investigation found.
COLLECTIVE_SHOUT_CASES = [
    ("01ce04390f13", "「「「キャアアアー！！」」」", True),
    ("01ce04390f13", "「「「キャアアアアアー！！」」」", True),
    ("01ce04390f13", "「「「…ぅ、…う～む」」」", False),
    ("178ca2c7c9e0", "「「「ハイッ！！」」」", False),
    ("42c67fbb65b3", "「「なんだとぉ！！」」", False),
    ("751919a6e78f", "「「お世話になりました～！」」", False),
    ("9e7aa43c8187", "「「「………」」」", False),
    ("9e7aa43c8187", "「「ッ！？」」", False),
    ("a805ab43d99a", "「「「わぁぁああ～～！」」」", True),
    ("c574a6d5316d", "「「ぎゃああああぁぁ！！」」", False),
    ("c574a6d5316d", "「「「……！？」」」", False),
    ("c574a6d5316d", "「「ぎひぃ～～…ッ！」」", False),
    ("c574a6d5316d", "「「グボッ！？」」", False),
    ("c574a6d5316d", "「「「……」」」", False),
    ("c574a6d5316d", "「「「……」」」", False),
    ("ed3520ec8e4a", "「「…！？」」", False),
    ("ed3520ec8e4a", "「「「なんだとぉ！」」」", True),
    ("f82c65a29f19", "「「「（わぁ～！）」」」", False),
    ("f82c65a29f19", "「「「ざわざわ…」」」", False),
    ("f82c65a29f19", "「「「おおぉ～～～ッ！」」」", True),
    ("fd4782aeffc7", "「「「ざわざわ…」」」", True),
]

# Ordinary dialogue/narration lines that must NOT trigger the detector --
# single-bracket-layer short exclamations and long narration, both
# confirmed in the investigation to never corrupt. Over-triggering on
# these would strip legitimate dialogue markers from lines the fix has no
# business touching.
ORDINARY_LINES = [
    "「なにっ！？」",
    "「く、おのれ…！」",
    "「ハン、こけおどしがッ！」",
    "だがこのままでは遅れてやってくるダブルソルトブーメランに巻き込まれてしまうので、",
    "途端に観客からは悲鳴があがる。拳を抜かれた風の貴公子とやらの顔面中心部はミンチよ",
    "オレの鉄パイプ",
]


class TestCollectiveShoutDetection:
    """_is_collective_shout()/_strip_collective_shout_brackets() -- the narrow, doubled-bracket-only trigger validated in DESIGN.md's 2026-08-01 entries.

    Deliberately tests against the tightened `「{2,}|」{2,}` shape, not the
    investigation's earlier, looser `<=12 char` heuristic -- that looser
    rule would have applied to 138 lines, only 6 of which ever corrupted;
    the implemented rule is the doubled-layer shape specifically.
    """

    def test_detects_every_real_doubled_bracket_case(self):
        for name, src, _was_corrupt in COLLECTIVE_SHOUT_CASES:
            assert _is_collective_shout(src), f"{name}: expected {src!r} to be detected as a collective shout"

    def test_does_not_detect_ordinary_lines(self):
        for src in ORDINARY_LINES:
            assert not _is_collective_shout(src), f"expected {src!r} NOT to be detected as a collective shout"

    def test_strip_removes_all_bracket_characters(self):
        assert _strip_collective_shout_brackets("「「「キャアアアー！！」」」") == "キャアアアー！！"
        assert _strip_collective_shout_brackets("「「なんだとぉ！！」」") == "なんだとぉ！！"

    def test_strip_preserves_non_bracket_content_exactly(self):
        # Confirmed via live validation: stripping must not touch anything
        # but the bracket glyphs themselves -- punctuation/ellipsis/tilde
        # content is meaning-bearing and must survive unmodified.
        assert _strip_collective_shout_brackets("「「「ざわざわ…」」」") == "ざわざわ…"
        assert _strip_collective_shout_brackets("「「「おおぉ～～～ッ！」」」") == "おおぉ～～～ッ！"


class TestCollectiveShoutStripInTranslateChunk:
    """End-to-end (mocked model) coverage of the strip-before/re-wrap-after hook in _translate_chunk_once(), reached via translate_chunk()."""

    def test_all_21_real_cases_prompt_sent_without_brackets_and_output_rewrapped(self, mocker):
        """Regression test for every real case DESIGN.md's investigation and live validation found.

        Mocks the model to simply echo back whatever line it was actually
        asked to translate (proving the *sent* prompt had brackets
        stripped, not just asserting on the final result) prefixed with
        "T:", then confirms every collective-shout case's final output is
        re-wrapped in a single 「」 pair around the stripped-and-translated
        text, with no doubled/stray quote artifacts -- the exact
        corruption shape the live validation eliminated.
        """
        sources = [src for _, src, _ in COLLECTIVE_SHOUT_CASES]
        _mock_completion_echoing_prompt_lines(mocker, lambda line: f"T:{line}")

        # One line per chunk (single-line requests), matching how the live
        # validation script called the model -- avoids relying on
        # max_chunk_chars packing behavior, which isn't what this test is
        # about.
        for src in sources:
            result = translate_chunk([src], chunk_idx=0, total_chunks=1)
            assert len(result) == 1
            out = result[0]
            assert '""' not in out, f"{src!r} -> {out!r}: stray doubled-quote artifact present"
            stripped_src = _strip_collective_shout_brackets(src)
            assert out == f"「T:{stripped_src}」", f"{src!r} -> {out!r}: expected clean re-wrapped output"

    def test_ordinary_lines_unaffected_by_strip_or_rewrap(self, mocker):
        """The detector must not over-trigger -- ordinary lines pass through exactly as before this fix."""
        _mock_completion_echoing_prompt_lines(mocker, lambda line: f"T:{line}")

        for src in ORDINARY_LINES:
            result = translate_chunk([src], chunk_idx=0, total_chunks=1)
            assert result == [f"T:{src}"], f"{src!r}: ordinary line was modified by the collective-shout hook"

    def test_multi_line_chunk_only_rewraps_the_matching_line(self, mocker):
        """A chunk mixing a collective-shout line with ordinary lines re-wraps only the matching entry."""
        lines = ["「なにっ！？」", "「「「なんだとぉ！」」」", "オレの鉄パイプ"]
        _mock_completion_echoing_prompt_lines(mocker, lambda line: f"T:{line}")

        result = translate_chunk(lines, chunk_idx=0, total_chunks=1)

        assert result[0] == "T:「なにっ！？」"
        assert result[1] == "「T:なんだとぉ！」"
        assert result[2] == "T:オレの鉄パイプ"


class TestCollectiveShoutStripWithSentinelMasking:
    """Explicit regression test for the one interaction the live validation flagged as untested: a doubled-bracket line sharing a chunk with sentinel-masked terms on adjacent lines.

    mask_terms() runs before _translate_chunk_once() (in
    translate_chunk_with_masking(), before translate_chunk() is called),
    so by the time the collective-shout hook sees a masked line it only
    ever needs to leave ⟦TERM_n⟧ untouched -- confirmed here against a
    live-shaped chunk, not just asserted from reading the code.
    """

    def test_sentinel_position_and_splice_survive_bracket_stripping_on_adjacent_line(self, mocker):
        # Line 0: ordinary line with a masked glossary term (sentinel).
        # Line 1: collective-shout line, no masking -- adjacent, same chunk.
        # Line 2: ordinary line, no masking.
        lines = ["ケイトが振り返った。", "「「「なんだとぉ！」」」", "ルリが微笑んだ。"]
        mask_targets = [(0, "ケイト")]

        def translator(line):
            if "TERM_1" in line:
                return "⟦TERM_1⟧ turned around."
            if line == "なんだとぉ！":
                return "What did you say?!"
            if line == "ルリが微笑んだ。":
                return "Ruri smiled."
            raise AssertionError(f"unexpected line reached the model: {line!r}")

        _mock_completion_echoing_prompt_lines(mocker, translator)

        result = translate_chunk_with_masking(lines, mask_targets, chunk_idx=0, total_chunks=1)

        assert len(result) == 3
        # Sentinel splice on line 0 is unaffected by the bracket-stripping
        # hook running on line 1 in the same request.
        assert result[0].text == "ケイト turned around."
        assert result[0].needs_review is True
        # Line 1's collective-shout brackets were stripped from the prompt
        # (proven by translator() only matching the bracket-free string)
        # and the output re-wrapped -- no stray-quote corruption, no
        # interference with line 0's sentinel.
        assert result[1].text == "「What did you say?!」"
        assert result[1].needs_review is False
        assert result[2].text == "Ruri smiled."
        assert result[2].needs_review is False

    def test_masked_term_inside_a_collective_shout_line_itself(self, mocker):
        """A doubled-bracket line whose own content is masked -- stripping must not disturb the sentinel it wraps."""
        lines = ["「「「鉄パイプだ！」」」"]
        mask_targets = [(0, "鉄パイプ")]

        def translator(line):
            assert "「" not in line and "」" not in line, f"brackets were not stripped from the prompt line: {line!r}"
            assert "⟦TERM_1⟧" in line, f"sentinel missing/corrupted in prompt line: {line!r}"
            return line.replace("⟦TERM_1⟧", "⟦TERM_1⟧").replace("だ！", " it is!")

        _mock_completion_echoing_prompt_lines(mocker, translator)

        result = translate_chunk_with_masking(lines, mask_targets, chunk_idx=0, total_chunks=1)

        assert len(result) == 1
        assert result[0].text == "「鉄パイプ it is!」"
        assert result[0].needs_review is True
