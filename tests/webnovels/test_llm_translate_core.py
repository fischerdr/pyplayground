#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for llm_translate.py core functions.

Covers the functions that had zero direct tests:
- strip_code_fence
- parse_json_response
- _language_name
- _clean_output
- _translate_chunk_once (the single-request core)
- translate_chunk (retry logic, fallback placeholders)
- mask_terms (standalone)

All tests mock requests.post rather than hitting a live llama-server.
"""

import json as json_module

import pytest
import requests

from pyplayground.webnovels.llm_translate import (
    _clean_output,
    _language_name,
    _sentinel_pattern,
    _translate_chunk_once,
    mask_terms,
    parse_json_response,
    strip_code_fence,
    translate_chunk,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_completion_response(mocker, content_or_batches):
    """Patch requests.post to return controlled responses.

    Args:
        mocker: pytest-mock mocker fixture.
        content_or_batches: A single content string, or a list of
            JSON-serializable batches (one per call).
    """
    if isinstance(content_or_batches, list):
        calls = {"i": 0}

        def fake_post(url, json=None, timeout=None):
            batch = content_or_batches[calls["i"]]
            calls["i"] += 1
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            if isinstance(batch, str):
                resp.json.return_value = {"content": batch}
            else:
                resp.json.return_value = {"content": json_module.dumps(batch, ensure_ascii=False)}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=fake_post)
    else:
        resp = mocker.Mock()
        resp.raise_for_status = mocker.Mock()
        resp.json.return_value = {"content": content_or_batches}
        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", return_value=resp)


# ---------------------------------------------------------------------------
# strip_code_fence
# ---------------------------------------------------------------------------


class TestStripCodeFence:
    """Tests for strip_code_fence()."""

    def test_no_fence_returns_text_stripped(self):
        """Input without a code fence is returned with whitespace stripped."""
        assert strip_code_fence("  hello world  ") == "hello world"

    def test_fence_with_json_language(self):
        """```json ... ``` is unwrapped."""
        assert strip_code_fence('```json\n["a", "b"]\n```') == '["a", "b"]'

    def test_fence_without_language(self):
        """``` ... ``` (no language tag) is unwrapped."""
        assert strip_code_fence('```\n["a", "b"]\n```') == '["a", "b"]'

    def test_fence_case_insensitive_language(self):
        """JSON language tag is case-insensitive."""
        assert strip_code_fence('```JSON\n["a"]\n```') == '["a"]'
        assert strip_code_fence('```Json\n["a"]\n```') == '["a"]'

    def test_fence_preserves_content_with_backticks_inside(self):
        """Content that contains ``` is handled by rsplit."""
        result = strip_code_fence("```json\nhello\n```\nworld```")
        assert result == "hello\n```\nworld"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert strip_code_fence("") == ""

    def test_fence_with_extra_whitespace(self):
        """Leading/trailing whitespace is stripped before and after."""
        assert strip_code_fence('  \n```json\n  ["x"]  \n```\n  ') == '["x"]'


# ---------------------------------------------------------------------------
# parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    """Tests for parse_json_response()."""

    def test_simple_array(self):
        """A plain JSON array is parsed correctly."""
        assert parse_json_response('["a", "b", "c"]') == ["a", "b", "c"]

    def test_simple_object(self):
        """A plain JSON object is parsed correctly."""
        assert parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_trailing_content_ignored(self):
        """Content after the closing bracket is silently ignored."""
        result = parse_json_response('["a", "b"] some trailing text')
        assert result == ["a", "b"]

    def test_trailing_glossary_echo(self):
        """Model echoing glossary text after valid JSON is handled."""
        result = parse_json_response('["translation"] 封禁: ban, prohibit')
        assert result == ["translation"]

    def test_nested_json(self):
        """Nested JSON structures are parsed correctly."""
        result = parse_json_response('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_empty_array(self):
        """An empty JSON array is parsed."""
        assert parse_json_response("[]") == []

    def test_empty_object(self):
        """An empty JSON object is parsed."""
        assert parse_json_response("{}") == {}

    def test_invalid_json_raises(self):
        """Completely invalid JSON raises JSONDecodeError."""
        with pytest.raises(json_module.JSONDecodeError):
            parse_json_response("not json at all [[[")

    def test_string_json(self):
        """A plain JSON string value is parsed."""
        assert parse_json_response('"hello"') == "hello"

    def test_number_json(self):
        """A plain JSON number is parsed."""
        assert parse_json_response("42") == 42


# ---------------------------------------------------------------------------
# _language_name
# ---------------------------------------------------------------------------


class TestLanguageName:
    """Tests for _language_name()."""

    def test_ja(self):
        assert _language_name("ja") == "Japanese"

    def test_en(self):
        assert _language_name("en") == "English"

    def test_ko(self):
        assert _language_name("ko") == "Korean"

    def test_zh(self):
        assert _language_name("zh") == "Chinese"

    def test_uppercase_code(self):
        """Language codes are case-insensitive."""
        assert _language_name("JA") == "Japanese"
        assert _language_name("EN") == "English"

    def test_unknown_code_returns_as_is(self):
        """Unknown codes are returned unchanged."""
        assert _language_name("fr") == "fr"
        assert _language_name("de") == "de"

    def test_display_name_passed_through(self):
        """If a display name is already passed, it's returned as-is."""
        assert _language_name("Japanese") == "Japanese"


# ---------------------------------------------------------------------------
# _clean_output
# ---------------------------------------------------------------------------


class TestCleanOutput:
    """Tests for _clean_output()."""

    def test_strips_whitespace(self):
        """Leading and trailing whitespace is stripped."""
        assert _clean_output("  hello  ") == "hello"

    def test_strips_surrounding_quotes(self):
        """A pair of surrounding double quotes is stripped."""
        assert _clean_output('"hello"') == "hello"

    def test_strips_quotes_and_whitespace(self):
        """Quotes and whitespace are both stripped."""
        assert _clean_output('  "hello"  ') == "hello"

    def test_no_quotes_preserved(self):
        """Text without surrounding quotes is preserved."""
        assert _clean_output("hello world") == "hello world"

    def test_single_quote_not_stripped(self):
        """A single quote at the start is not stripped."""
        assert _clean_output('"hello') == '"hello'

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert _clean_output("") == ""

    def test_quote_only(self):
        """A single quote character is preserved (len < 2 check)."""
        assert _clean_output('"') == '"'

    def test_unicode_text(self):
        """Unicode text is preserved."""
        assert _clean_output('"こんにちは"') == "こんにちは"

    def test_single_quoted_dialogue_not_stripped(self):
        """A whole string wrapped in single quotes is left untouched.

        DESIGN.md 2026-08-04: TRANSLATION_PROMPT now instructs single
        quotes ('...') for 「」-sourced dialogue, specifically so it never
        collides with this function's double-quote strip -- a correctly
        double-quoted whole-line dialogue translation (e.g. '"Uriuri!"')
        and the JSON double-wrap artifact this function was built to undo
        are the same string shape (starts and ends with "), impossible to
        tell apart after the fact. Moving dialogue to single quotes avoids
        the ambiguity instead of trying to resolve it here. This test
        pins _clean_output() itself as unchanged -- it must remain a
        no-op on single-quoted strings, since that's the whole point.
        """
        assert _clean_output("'Uriuri!'") == "'Uriuri!'"


# ---------------------------------------------------------------------------
# _translate_chunk_once
# ---------------------------------------------------------------------------


class TestTranslateChunkOnce:
    """Tests for _translate_chunk_once().

    This is the core single-request function that:
    1. Constructs the prompt (with optional context/glossary prefixes)
    2. Calculates n_predict based on input size
    3. Sends to llama-server /completion
    4. Strips code fences, parses JSON
    5. Deduplicates single-line duplication
    6. Validates array length
    7. Cleans and returns output

    Note: HTTP errors (ConnectionError, Timeout, HTTPError) propagate up
    from _translate_chunk_once -- they are NOT caught here. They are
    caught at the translate_lines() level. Only JSONDecodeError is
    caught internally and converted to a None return.
    """

    def test_basic_translation(self, mocker):
        """A single-line request returns a single translated line."""
        _mock_completion_response(mocker, [["Hello world"]])

        result = _translate_chunk_once(
            ["こんにちは世界"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello world"]

    def test_multi_line_translation(self, mocker):
        """A multi-line request returns a matching-length list."""
        _mock_completion_response(mocker, [["Hello", "World"]])

        result = _translate_chunk_once(
            ["こんにちは", "世界"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello", "World"]

    def test_prompt_contains_language_names(self, mocker):
        """The prompt includes resolved language names."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["prompt"] = json["prompt"]
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert "Japanese" in captured["prompt"]
        assert "English" in captured["prompt"]

    def test_prompt_contains_lines_json(self, mocker):
        """The prompt includes the source lines as JSON."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["prompt"] = json["prompt"]
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["こんにちは", "世界"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert "こんにちは" in captured["prompt"]
        assert "世界" in captured["prompt"]

    def test_context_prefix_prepended(self, mocker):
        """Context text is prepended to the prompt."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["prompt"] = json["prompt"]
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context="Previous paragraph for context.",
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert "BACKGROUND ONLY" in captured["prompt"]
        assert "Previous paragraph for context." in captured["prompt"]

    def test_glossary_prefix_prepended(self, mocker):
        """Glossary text is prepended to the prompt."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["prompt"] = json["prompt"]
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text="ケイト = Kate (character name)",
            chunk_idx=0,
            total_chunks=1,
        )

        assert "Reference only" in captured["prompt"]
        assert "ケイト = Kate (character name)" in captured["prompt"]

    def test_context_and_glossary_both_prepended(self, mocker):
        """Both context and glossary are prepended, glossary first then context."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["prompt"] = json["prompt"]
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context="Context text.",
            glossary_text="Glossary text.",
            chunk_idx=0,
            total_chunks=1,
        )

        # Build order: base -> prepend context -> prepend glossary
        # Final order: glossary -> context -> base
        glossary_pos = captured["prompt"].index("Reference only")
        context_pos = captured["prompt"].index("BACKGROUND ONLY")
        base_pos = captured["prompt"].index("You are a translation API")
        assert glossary_pos < context_pos < base_pos

    def test_n_predict_scales_with_input_size(self, mocker):
        """n_predict is calculated as max(256, sum(len(line) for line in lines) * 4)."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        # Short line: 1 char * 4 = 4, floored to 256
        _translate_chunk_once(
            ["あ"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert captured["payload"]["n_predict"] == 256

    def test_n_predict_above_floor(self, mocker):
        """n_predict scales above 256 for larger input."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        # 50 chars * 4 = 200, still below 256
        _translate_chunk_once(
            ["あ" * 25 + "い" * 25],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert captured["payload"]["n_predict"] == 256

    def test_n_predict_large_input(self, mocker):
        """n_predict scales correctly for large input."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        # 100 chars * 4 = 400 > 256
        _translate_chunk_once(
            ["あ" * 50 + "い" * 50],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert captured["payload"]["n_predict"] == 400

    def test_temperature_is_0_1(self, mocker):
        """Temperature is set to 0.1 (near-greedy)."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert captured["payload"]["temperature"] == 0.1

    def test_stop_token_is_triple_newline(self, mocker):
        """The stop token is a triple newline."""
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = {"content": '["ok"]'}
            return resp

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=capture_post)

        _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert captured["payload"]["stop"] == ["\n\n\n"]

    def test_json_parse_failure_returns_none(self, mocker):
        """Non-JSON response returns None."""
        _mock_completion_response(mocker, "not json at all")

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result is None

    def test_truncated_json_array_from_live_log_returns_none(self, mocker):
        """The literal shape seen in a real live-test failure log (2026-07-27, novel 375266002 episode 7800123, chunk 3): a response cut off mid-string, missing the closing quote/bracket. Investigated whether this was reproducible against the real server (see DESIGN.md's dated entry) -- it wasn't, across 3 live re-runs, so this pins down the already-existing parse-failure handling for this exact malformed shape rather than a confirmed root cause."""
        truncated = '[\n"The sounds of many insects echoed, and the night sky was filled with twinkling stars.",\n"However, when I looked at the road, I saw that the vehicles'
        _mock_completion_response(mocker, truncated)

        result = _translate_chunk_once(
            ["line one", "line two"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result is None

    def test_code_fence_stripped_before_parsing(self, mocker):
        """Code fences are stripped before JSON parsing."""
        _mock_completion_response(mocker, '```json\n["translated"]\n```')

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["translated"]

    def test_trailing_content_after_json_handled(self, mocker):
        """Trailing content after valid JSON is ignored (not an error)."""
        _mock_completion_response(mocker, '["translated"] some trailing text')

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["translated"]

    def test_single_line_dedup_collapses_identical_entries(self, mocker):
        """Single-line request with duplicated answer is collapsed."""
        _mock_completion_response(mocker, [["same", "same"]])

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context="Context that might cause duplication.",
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["same"]

    def test_single_line_dedup_does_not_collapse_different_entries(self, mocker):
        """Single-line request with genuinely different entries is NOT collapsed."""
        _mock_completion_response(mocker, [["first", "second"]])

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        # Different entries -> length mismatch -> None
        assert result is None

    def test_length_mismatch_returns_none(self, mocker):
        """Response array length mismatch returns None."""
        _mock_completion_response(mocker, [["a", "b", "c"]])

        result = _translate_chunk_once(
            ["line1", "line2"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result is None

    def test_non_array_response_returns_none(self, mocker):
        """Non-array JSON response returns None."""
        _mock_completion_response(mocker, '{"not": "an array"}')

        result = _translate_chunk_once(
            ["test"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result is None

    def test_output_quotes_stripped(self, mocker):
        """Surrounding quotes on output strings are stripped."""
        _mock_completion_response(mocker, [['"hello"', '"world"']])

        result = _translate_chunk_once(
            ["test1", "test2"],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["hello", "world"]

    def test_empty_list_of_lines(self, mocker):
        """An empty list of lines returns an empty list."""
        _mock_completion_response(mocker, [[]])

        result = _translate_chunk_once(
            [],
            target_lang="en",
            source_lang="ja",
            context=None,
            glossary_text=None,
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == []

    def test_http_error_propagates(self, mocker):
        """HTTP errors (raise_for_status) propagate up -- not caught internally."""
        resp = mocker.Mock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", return_value=resp)

        with pytest.raises(requests.exceptions.HTTPError):
            _translate_chunk_once(
                ["test"],
                target_lang="en",
                source_lang="ja",
                context=None,
                glossary_text=None,
                chunk_idx=0,
                total_chunks=1,
            )

    def test_connection_error_propagates(self, mocker):
        """Connection errors propagate up -- not caught internally."""

        def raise_error(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("server down")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        with pytest.raises(requests.exceptions.ConnectionError):
            _translate_chunk_once(
                ["test"],
                target_lang="en",
                source_lang="ja",
                context=None,
                glossary_text=None,
                chunk_idx=0,
                total_chunks=1,
            )


# ---------------------------------------------------------------------------
# translate_chunk (retry logic)
# ---------------------------------------------------------------------------


class TestTranslateChunk:
    """Tests for translate_chunk() retry logic.

    translate_chunk wraps _translate_chunk_once with two safety nets:
    1. If the chunk fails and has >1 line, retry each line individually.
    2. If everything still fails, return [translation failed: ...] placeholders.

    Note: HTTP errors (ConnectionError, Timeout, HTTPError) propagate up from
    translate_chunk -- they are NOT caught here. Exception handling is at the
    translate_lines() level. Only None returns (from JSON parse failures)
    trigger the retry/fallback logic.
    """

    def test_success_returns_translation(self, mocker):
        """Successful translation returns the translated lines."""
        _mock_completion_response(mocker, [["Hello", "World"]])

        result = translate_chunk(
            ["こんにちは", "世界"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello", "World"]

    def test_single_line_failure_returns_placeholder(self, mocker):
        """Single-line failure returns a placeholder."""
        _mock_completion_response(mocker, "not json")

        result = translate_chunk(
            ["test"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["[translation failed: unparseable response]"]

    def test_multi_line_failure_retries_per_line(self, mocker):
        """Multi-line failure retries each line individually."""
        # First call fails (chunk), then each line succeeds individually
        _mock_completion_response(
            mocker,
            [
                "not json",  # chunk fails
                ["Hello"],  # line 0 succeeds
                ["World"],  # line 1 succeeds
            ],
        )

        result = translate_chunk(
            ["line1", "line2"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello", "World"]

    def test_per_line_retry_returning_non_identical_array_falls_back_to_placeholder(self, mocker):
        """The exact nested-failure shape from the live log ('expected a JSON array of 1 string(s), got list of length 2'): a per-line retry (single line in) itself comes back as a non-identical multi-element array. _translate_chunk_once()'s dedup guard only collapses identical duplicates (see test_single_line_dedup_does_not_collapse_different_entries), so this correctly returns None for that line rather than guessing -- translate_chunk() must fall back to the placeholder for it, not raise or silently drop it."""
        _mock_completion_response(
            mocker,
            [
                "not json",  # chunk-level call fails, triggers per-line retry
                ["Hello"],  # line 0 retry succeeds
                ["World", "A different World"],  # line 1 retry itself wrong-length, non-identical
            ],
        )

        result = translate_chunk(
            ["line1", "line2"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello", "[translation failed: unparseable response]"]

    def test_per_line_partial_failure(self, mocker):
        """Some lines succeed, others fail during per-line retry."""
        _mock_completion_response(
            mocker,
            [
                "not json",  # chunk fails
                ["Hello"],  # line 0 succeeds
                "still bad",  # line 1 fails
            ],
        )

        result = translate_chunk(
            ["line1", "line2"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Hello", "[translation failed: unparseable response]"]

    def test_all_lines_fail_returns_all_placeholders(self, mocker):
        """All lines fail during per-line retry -> all placeholders."""
        _mock_completion_response(
            mocker,
            [
                "not json",  # chunk fails
                "bad",  # line 0 fails
                "bad",  # line 1 fails
            ],
        )

        result = translate_chunk(
            ["line1", "line2"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == [
            "[translation failed: unparseable response]",
            "[translation failed: unparseable response]",
        ]

    def test_progress_callback_invoked_on_success(self, mocker):
        """Progress callback is called on success."""
        _mock_completion_response(mocker, [["Translation"]])
        cb = mocker.Mock()

        translate_chunk(
            ["test"],
            target_lang="en",
            source_lang="ja",
            progress_cb=cb,
            chunk_idx=1,
            total_chunks=3,
        )

        cb.assert_called_once_with(2, 3)

    def test_progress_callback_invoked_on_failure(self, mocker):
        """Progress callback is called even on failure (placeholder path)."""
        _mock_completion_response(mocker, "not json")
        cb = mocker.Mock()

        translate_chunk(
            ["test"],
            target_lang="en",
            source_lang="ja",
            progress_cb=cb,
            chunk_idx=0,
            total_chunks=1,
        )

        cb.assert_called_once_with(1, 1)

    def test_no_progress_callback_does_not_error(self, mocker):
        """No progress callback -> no error."""
        _mock_completion_response(mocker, [["Translation"]])

        result = translate_chunk(
            ["test"],
            target_lang="en",
            source_lang="ja",
            chunk_idx=0,
            total_chunks=1,
        )

        assert result == ["Translation"]

    def test_http_error_propagates(self, mocker):
        """HTTP errors propagate up from translate_chunk -- not caught internally."""
        resp = mocker.Mock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", return_value=resp)

        with pytest.raises(requests.exceptions.HTTPError):
            translate_chunk(
                ["test"],
                target_lang="en",
                source_lang="ja",
                chunk_idx=0,
                total_chunks=1,
            )

    def test_connection_error_propagates(self, mocker):
        """Connection errors propagate up from translate_chunk -- not caught internally."""

        def raise_error(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("server down")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        with pytest.raises(requests.exceptions.ConnectionError):
            translate_chunk(
                ["test"],
                target_lang="en",
                source_lang="ja",
                chunk_idx=0,
                total_chunks=1,
            )

    def test_multi_line_connection_error_propagates(self, mocker):
        """Connection errors on multi-line also propagate.

        per-line retry is only triggered by None returns, not by exceptions.
        """

        def raise_error(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("server down")

        mocker.patch("pyplayground.webnovels.llm_translate.requests.post", side_effect=raise_error)

        with pytest.raises(requests.exceptions.ConnectionError):
            translate_chunk(
                ["line1", "line2"],
                target_lang="en",
                source_lang="ja",
                chunk_idx=0,
                total_chunks=1,
            )


# ---------------------------------------------------------------------------
# mask_terms (standalone)
# ---------------------------------------------------------------------------


class TestMaskTerms:
    """Tests for mask_terms().

    mask_terms(line, targets) takes targets as List[Tuple[str, int]]
    where each tuple is (word, term_id).
    """

    def test_single_term_masked(self):
        """A single term is replaced with a sentinel."""
        result = mask_terms("ケイトが言った", [("ケイト", 1)])
        assert "⟦TERM_1⟧" in result
        assert "ケイト" not in result

    def test_multiple_terms_masked(self):
        """Multiple terms are each replaced with distinct sentinels."""
        result = mask_terms("ケイトとルリ", [("ケイト", 1), ("ルリ", 2)])
        assert "⟦TERM_1⟧" in result
        assert "⟦TERM_2⟧" in result
        assert "ケイト" not in result
        assert "ルリ" not in result

    def test_term_appears_once(self):
        """Only the first occurrence is replaced (replace with count=1)."""
        result = mask_terms("ケイト ケイト", [("ケイト", 1)])
        assert result.count("⟦TERM_1⟧") == 1
        assert result.count("ケイト") == 1

    def test_unmasked_terms_preserved(self):
        """Terms not in the targets list are preserved."""
        result = mask_terms("ケイトとルリ", [("ケイト", 1)])
        assert "ルリ" in result

    def test_raises_on_missing_word(self):
        """Raises ValueError if a target word is not in the line."""
        with pytest.raises(ValueError, match="ルリ.*not found"):
            mask_terms("ケイトが言った", [("ルリ", 1)])

    def test_empty_targets_returns_line_unchanged(self):
        """Empty targets list returns the original line."""
        result = mask_terms("ケイトが言った", [])
        assert result == "ケイトが言った"

    def test_sentinel_format_is_correct(self):
        """Sentinel uses the correct format: ⟦TERM_n⟧."""
        result = mask_terms("テスト word テスト", [("word", 1)])
        assert result == "テスト ⟦TERM_1⟧ テスト"

    def test_sentinel_uses_fullwidth_brackets(self):
        """Sentinel uses fullwidth math brackets ⟦⟧, not ASCII []."""
        result = mask_terms("テスト word テスト", [("word", 1)])
        assert "⟦" in result
        assert "⟧" in result

    def test_term_id_starts_at_one(self):
        """Term IDs start at 1, not 0 (as used by callers)."""
        result = mask_terms("テスト word テスト", [("word", 1)])
        assert "TERM_1" in result


# ---------------------------------------------------------------------------
# _sentinel_pattern (regex)
# ---------------------------------------------------------------------------


class TestSentinelPattern:
    """Tests for _sentinel_pattern() regex matching.

    Note: _sentinel_pattern() matches the sentinel format in raw output.
    Digit normalization (fullwidth -> ASCII) is done in splice_terms()
    BEFORE calling _sentinel_pattern(), not inside the pattern itself.
    """

    def test_standard_sentinel(self):
        """Standard ⟦TERM_1⟧ is matched."""
        pattern = _sentinel_pattern(1)
        assert pattern.search("⟦TERM_1⟧")

    def test_bracket_variant(self):
        """Plain ASCII [...] variant is matched."""
        pattern = _sentinel_pattern(1)
        assert pattern.search("[TERM_1]")

    def test_fullwidth_bracket_variant(self):
        """Fullwidth ［ ］ variant is matched."""
        pattern = _sentinel_pattern(1)
        assert pattern.search("［TERM_1］")

    def test_angled_bracket_variant(self):
        """【 】 variant is matched."""
        pattern = _sentinel_pattern(1)
        assert pattern.search("【TERM_1】")

    def test_no_match_wrong_number(self):
        """Different term numbers don't match."""
        pattern = _sentinel_pattern(1)
        assert not pattern.search("⟦TERM_2⟧")

    def test_whitespace_around_sentinel(self):
        """Sentinels with surrounding whitespace are matched."""
        pattern = _sentinel_pattern(1)
        assert pattern.search("⟦ TERM_1 ⟧")

    def test_no_match_missing_brackets(self):
        """Text without proper bracket structure doesn't match."""
        pattern = _sentinel_pattern(1)
        assert not pattern.search("TERM_1")
        assert not pattern.search("⟦TERM_1")
        assert not pattern.search("TERM_1⟧")
