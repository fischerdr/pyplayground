#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the interleaved display mode (RETRANSLATION_DESIGN.md phase 1).

Tracked in a separate design doc and separate test file from
DESIGN.md/test_alphapolis_reader.py on purpose, per
RETRANSLATION_DESIGN.md's own framing: this is a distinct feature
(general translation-quality correction) from the glossary/term-
consistency work, and conflating them would repeat the same
flag-means-two-things mistake DESIGN.md Section 11 already caught once.

Coverage tiers:
  - TestBuildInterleavedPairs: the pure, Tkinter-independent pairing/
    fallback-detection logic (build_interleaved_pairs()).
  - TestRenderInterleavedContent: the Tk rendering method
    (_render_interleaved_content()), exercised against a real tk.Text
    widget via a minimal stand-in object, same pattern as
    test_alphapolis_reader.py's TestRenderAndClick/TestRenderTranslatedView.
  - TestDefaultViewMode: confirms the new default (translated, not both).
"""

import tkinter as tk

from pyplayground.webnovels.alphapolis_reader import ReaderApp, build_interleaved_pairs
from pyplayground.webnovels.llm_translate import TranslatedLine  # noqa: F401  (kept for parity/future needs_review-aware tests)


class TestBuildInterleavedPairs:
    """Tests for build_interleaved_pairs()."""

    def test_equal_length_lines_pair_correctly_and_in_order(self):
        source = ["ケイトが振り返った。", "ルリが微笑んだ。"]
        translated = ["Kate turned around.", "Ruri smiled."]

        pairs = build_interleaved_pairs(source, translated)

        assert pairs == [
            ("ケイトが振り返った。", "Kate turned around."),
            ("ルリが微笑んだ。", "Ruri smiled."),
        ]

    def test_single_line_pairs_correctly(self):
        assert build_interleaved_pairs(["こんにちは。"], ["Hello."]) == [("こんにちは。", "Hello.")]

    def test_empty_lines_produce_empty_pairs(self):
        assert build_interleaved_pairs([], []) == []

    def test_mismatched_lengths_returns_none(self):
        """The documented fallback signal -- callers must not pair lines that don't actually correspond."""
        source = ["ケイトが振り返った。", "ルリが微笑んだ。"]
        translated = ["Kate turned around."]

        assert build_interleaved_pairs(source, translated) is None

    def test_translated_longer_than_source_also_returns_none(self):
        """Mismatch detection isn't one-directional -- translated_lines being longer is just as invalid as shorter."""
        source = ["こんにちは。"]
        translated = ["Hello.", "Extra unexpected line."]

        assert build_interleaved_pairs(source, translated) is None


class _InterleaveHarness:
    """Minimal stand-in for testing _render_interleaved_content(), matching test_alphapolis_reader.py's _DispatchHarness pattern."""

    def __init__(self, text_widget, current_url=None):
        self.text = text_widget
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self._translated_line_index_by_span = {}
        self.fallback_calls = []
        self.current_url = current_url

    def _make_photo_image(self, src):
        return None

    def _render_translated_view(self, ep, tag):
        self.fallback_calls.append((ep, tag))

    _render_interleaved_content = ReaderApp._render_interleaved_content
    _apply_needs_review_spans = ReaderApp._apply_needs_review_spans


class TestRenderInterleavedContent:
    """Tk-level tests for _render_interleaved_content(), against a real (headless) tk.Text widget."""

    def _make_widget(self):
        # Not root.withdraw() -- see test_alphapolis_reader.py's
        # TestRenderAndClick._make_widget() for why a withdrawn window
        # never gets real geometry in this environment.
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("original", foreground="#333333")
        text.tag_configure("translated", foreground="#1a56c4")
        text.tag_configure("needs_review", foreground="#b45309", underline=True)
        root.update()
        return root, text

    def test_pairs_rendered_in_source_then_translated_order(self):
        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text)
            ep = {
                "content": [
                    {"type": "text", "text": "ケイトが振り返った。"},
                    {"type": "text", "text": "ルリが微笑んだ。"},
                ],
                "lines": ["ケイトが振り返った。", "ルリが微笑んだ。"],
                "translated_lines": ["Kate turned around.", "Ruri smiled."],
            }

            harness._render_interleaved_content(ep, "original", "translated")

            texts_and_tags = [(tag, self._span_text(text, start, end)) for start, end, tag, _src in harness._rendered_spans]
            assert texts_and_tags == [
                ("original", "ケイトが振り返った。"),
                ("translated", "Kate turned around."),
                ("original", "ルリが微笑んだ。"),
                ("translated", "Ruri smiled."),
            ]
        finally:
            root.destroy()

    def _span_text(self, text, start, end):
        return text.get(start, end).rstrip("\n")

    def test_mismatched_lengths_falls_back_to_render_translated_view(self):
        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text)
            ep = {
                "content": [{"type": "text", "text": "ケイトが振り返った。"}, {"type": "text", "text": "ルリが微笑んだ。"}],
                "lines": ["ケイトが振り返った。", "ルリが微笑んだ。"],
                "translated_lines": ["Kate turned around."],  # one short -- mismatch
            }

            harness._render_interleaved_content(ep, "original", "translated")

            assert harness.fallback_calls == [(ep, "translated")]
            # Nothing was rendered by the interleaved path itself -- the
            # fallback owns rendering entirely once invoked.
            assert harness._rendered_spans == []
        finally:
            root.destroy()

    def test_needs_review_flag_applies_needs_review_tag_to_translated_half_only(self):
        """The translated half of a flagged pair gets span-level "needs_review" over the matched term text; _rendered_spans' base tag stays "translated" -- see DESIGN.md's span-level highlighting entry.

        No glossary term matches this line's translated text ("Kate ケイト"
        contains no glossary source string here since no glossary is
        seeded), so needs_review_flags[0]=True still records the fact but
        find_glossary_term_spans() finds nothing to highlight -- covered
        separately by test_needs_review_span_only_covers_matched_term_text
        below, which seeds a matching glossary term.
        """
        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text)
            ep = {
                "content": [{"type": "text", "text": "ケイトが振り返った。"}],
                "lines": ["ケイトが振り返った。"],
                "translated_lines": ["Kate ケイト"],
                "needs_review_flags": [True],
            }

            harness._render_interleaved_content(ep, "original", "translated")

            tags = [tag for _start, _end, tag, _src in harness._rendered_spans]
            assert tags == ["original", "translated"]
        finally:
            root.destroy()

    def test_needs_review_span_only_covers_matched_term_text(self, monkeypatch):
        """Span-level highlighting: only the exact masked-term text gets "needs_review" tagged, not the whole translated line."""
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(
            reader_module,
            "load_glossary",
            lambda novel_id: {"terms": [{"source": "ケイト", "type": "character", "status": "confirmed"}]},
        )

        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            ep = {
                "content": [{"type": "text", "text": "ケイトが振り返った。"}],
                "lines": ["ケイトが振り返った。"],
                "translated_lines": ["Because of ケイト, they were shocked."],
                "needs_review_flags": [True],
            }

            harness._render_interleaved_content(ep, "original", "translated")

            (start, end), (word, source_line) = next(iter(harness._review_terms_by_span.items()))
            assert word == "ケイト"
            assert source_line == "ケイトが振り返った。"
            assert text.get(start, end) == "ケイト"
            assert "needs_review" in text.tag_names(start)
            # The surrounding text must NOT carry needs_review -- confirms
            # span-level, not line-level, highlighting.
            assert "needs_review" not in text.tag_names("2.0")
        finally:
            root.destroy()

    def test_needs_review_flags_length_mismatch_ignored_not_applied(self):
        """A needs_review_flags list that doesn't match the paired-lines length shouldn't be trusted -- render normally rather than risk applying a flag to the wrong line."""
        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text)
            ep = {
                "content": [{"type": "text", "text": "ケイトが振り返った。"}, {"type": "text", "text": "ルリが微笑んだ。"}],
                "lines": ["ケイトが振り返った。", "ルリが微笑んだ。"],
                "translated_lines": ["Kate turned around.", "Ruri smiled."],
                "needs_review_flags": [True],  # length 1, but 2 pairs -- mismatched
            }

            harness._render_interleaved_content(ep, "original", "translated")

            tags = [tag for _start, _end, tag, _src in harness._rendered_spans]
            assert tags == ["original", "translated", "original", "translated"]
        finally:
            root.destroy()

    def test_image_items_interleaved_correctly_between_line_pairs(self):
        """ep["content"] can contain images between text paragraphs -- the line_idx counter must only advance on text items, not images, or every pair after an image misaligns."""
        root, text = self._make_widget()
        try:
            harness = _InterleaveHarness(text)
            ep = {
                "content": [
                    {"type": "text", "text": "ケイトが振り返った。"},
                    {"type": "image", "src": "http://example.com/fake.png"},
                    {"type": "text", "text": "ルリが微笑んだ。"},
                ],
                "lines": ["ケイトが振り返った。", "ルリが微笑んだ。"],
                "translated_lines": ["Kate turned around.", "Ruri smiled."],
            }

            harness._render_interleaved_content(ep, "original", "translated")

            # _make_photo_image() is stubbed to return None (no real image
            # fetch), so the image item contributes nothing to
            # _rendered_spans -- only the two text pairs should appear,
            # correctly paired despite the image sitting between them.
            texts_and_tags = [(tag, self._span_text(text, start, end)) for start, end, tag, _src in harness._rendered_spans]
            assert texts_and_tags == [
                ("original", "ケイトが振り返った。"),
                ("translated", "Kate turned around."),
                ("original", "ルリが微笑んだ。"),
                ("translated", "Ruri smiled."),
            ]
        finally:
            root.destroy()


class TestDefaultViewMode:
    """Confirms the RETRANSLATION_DESIGN.md phase 1 default-view-mode change."""

    def test_default_view_mode_is_translated_not_both(self):
        """Grep-level regression guard: settings.get("view_mode", ...) must default to "translated", matching the design decision -- was "both" before this phase."""
        import inspect

        source = inspect.getsource(ReaderApp.__init__)
        assert 'settings.get("view_mode", "translated")' in source
        assert 'settings.get("view_mode", "both")' not in source
