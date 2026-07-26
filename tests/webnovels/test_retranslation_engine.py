#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for llm_translate.py's retranslate_line_with_hint() (RETRANSLATION_DESIGN.md phase 2).

Tracked in a separate test file from test_llm_translate.py on purpose,
matching RETRANSLATION_DESIGN.md's own "tracked separately" framing (this
is the line-level retranslation engine, a distinct feature from
translate_lines_with_masking()'s glossary-term masking -- different call
shape, different failure class, different prompt).

Mocks requests.post rather than hitting a live llama-server -- these tests
target prompt construction (hint/glossary text actually present in the
request) and output handling (plain-text parsing, empty/malformed
response), which is deterministic and doesn't need a real model. Live
verification against a real server, including the 醤油顔/ノーズボン
known-bad cases, is documented in RETRANSLATION_DESIGN.md's phase 2 status
entry, not repeated here as an automated test.
"""

from pyplayground.webnovels.llm_translate import retranslate_line_with_hint


def _mock_completion_response(mocker, content):
    """Patch requests.post to return a single fixed raw `content` string."""
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {"content": content}
    mock_post = mocker.patch("pyplayground.webnovels.llm_translate.requests.post", return_value=resp)
    return mock_post


class TestRetranslateLineWithHint:
    """Tests for retranslate_line_with_hint()."""

    def test_returns_corrected_translation_on_clean_plain_text_response(self, mocker):
        _mock_completion_response(mocker, "\nHe is attractive because of his tanned complexion.\n")

        result = retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        assert result == "He is attractive because of his tanned complexion."

    def test_prompt_includes_hint_word(self, mocker):
        mock_post = _mock_completion_response(mocker, "corrected")

        retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "醤油顔" in sent_prompt
        assert "Pay particular attention to accurately translating this word/phrase: 醤油顔" in sent_prompt

    def test_prompt_includes_source_line_and_current_translation(self, mocker):
        mock_post = _mock_completion_response(mocker, "corrected")

        retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "彼は醤油顔でモテる。" in sent_prompt
        assert "He is attractive because of his dark complexion." in sent_prompt

    def test_glossary_text_included_when_provided(self, mocker):
        mock_post = _mock_completion_response(mocker, "corrected")

        retranslate_line_with_hint(
            "彼は醤油顔でモテる。",
            "He is attractive because of his dark complexion.",
            "醤油顔",
            glossary_text="- ケイト -> Kate",
        )

        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "ケイト -> Kate" in sent_prompt

    def test_no_glossary_text_omits_glossary_section(self, mocker):
        mock_post = _mock_completion_response(mocker, "corrected")

        retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "Reference only" not in sent_prompt

    def test_surrounding_quotes_stripped(self, mocker):
        """A stray pair of quotes around the answer (common enough in free-text LLM output generally) is stripped defensively."""
        _mock_completion_response(mocker, '"He is a fan of briefs."')

        result = retranslate_line_with_hint("彼はノーズボンを愛用している。", "He does not wear underwear and wears black underwear.", "ノーズボン")

        assert result == "He is a fan of briefs."

    def test_code_fence_stripped(self, mocker):
        _mock_completion_response(mocker, "```\nHe is a fan of briefs.\n```")

        result = retranslate_line_with_hint("彼はノーズボンを愛用している。", "He does not wear underwear and wears black underwear.", "ノーズボン")

        assert result == "He is a fan of briefs."

    def test_empty_response_returns_none(self, mocker):
        _mock_completion_response(mocker, "")

        result = retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        assert result is None

    def test_whitespace_only_response_returns_none(self, mocker):
        _mock_completion_response(mocker, "   \n\n  ")

        result = retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        assert result is None

    def test_request_failure_returns_none(self, mocker):
        """Catches requests.exceptions.RequestException specifically, matching explain_term()'s pattern -- a plain builtin ConnectionError is NOT a RequestException subclass and would propagate uncaught, so this uses the real requests exception type to test the actual contract."""
        import requests

        def raise_error(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("simulated failure")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        result = retranslate_line_with_hint("彼は醤油顔でモテる。", "He is attractive because of his dark complexion.", "醤油顔")

        assert result is None
