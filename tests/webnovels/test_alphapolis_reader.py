#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for alphapolis_reader.py's needs_review reader-UI support (DESIGN.md Sections 6 and 11).

Originally (Section 6) tested against synthetic/hand-constructed
TranslatedLine data only, since translate_chunk_with_masking() had no
production callers yet. Section 11 wired real production use
(fetch_and_translate() -> translate_lines_with_masking(), cache storage,
_render_translated_view() reconstructing TranslatedLine from the cached
shape) -- TestRenderTranslatedView below covers that reconstruction/dispatch
logic specifically. Live end-to-end verification against a real
masked-translation run (not just these unit tests) is documented in
DESIGN.md Section 11, not repeated here as an automated test (would require
a live llama-server).

Coverage tiers:
  - TestBuildReviewTermMap: the pure, Tkinter-independent logic
    (build_review_term_map()), fully unit tested.
  - TestRenderAndClick: the Tk rendering/click-handling methods
    (_render_translated_content_from_translated_lines(),
    _on_needs_review_click()), exercised against a real tk.Text widget (Tk
    initializes headlessly in this environment) via a minimal stand-in
    object -- NOT a real ReaderApp instance, since that requires a live
    browser/Playwright object to construct. This verifies tag application
    and click-to-term resolution mechanically, but is not the same as
    visually confirming the styling renders distinguishably on screen.
  - TestRenderTranslatedView: the cache-shape reconstruction/dispatch logic
    added in Section 11 (_render_translated_view() choosing between the
    needs_review-aware and plain renderers based on what's in the cached
    episode dict).
"""

import tkinter as tk

from pyplayground.webnovels.alphapolis_reader import ReaderApp, build_review_term_map
from pyplayground.webnovels.llm_translate import TranslatedLine


class TestBuildReviewTermMap:
    """Tests for build_review_term_map()."""

    def test_no_mask_targets_returns_empty_map(self):
        translated_lines = [TranslatedLine(text="Hello there.")]

        assert build_review_term_map(translated_lines, []) == {}

    def test_needs_review_line_maps_to_its_masked_word(self):
        translated_lines = [TranslatedLine(text="Look, ケイト! So big!", needs_review=True)]
        mask_targets = [(0, "ケイト")]

        result = build_review_term_map(translated_lines, mask_targets)

        assert result == {0: ["ケイト"]}

    def test_clean_splice_not_flagged_even_with_mask_targets(self):
        """A cleanly-spliced term (needs_review=False) shouldn't appear in the map, even though it was a mask target."""
        translated_lines = [TranslatedLine(text="Look, ケイト! So big!", needs_review=False)]
        mask_targets = [(0, "ケイト")]

        assert build_review_term_map(translated_lines, mask_targets) == {}

    def test_multiple_flagged_lines_in_one_chunk(self):
        translated_lines = [
            TranslatedLine(text="Kate and Ruri were friends.", needs_review=False),
            TranslatedLine(text="Ruri said thanks. 維多教授", needs_review=True),
            TranslatedLine(text="Only 音夢くん arrived late. 音夢くん", needs_review=True),
        ]
        mask_targets = [(1, "維多教授"), (2, "音夢くん")]

        result = build_review_term_map(translated_lines, mask_targets)

        assert result == {1: ["維多教授"], 2: ["音夢くん"]}

    def test_multiple_masked_words_on_same_flagged_line(self):
        """A needs_review line with more than one masked word collects all of them, in order."""
        translated_lines = [TranslatedLine(text="ケイト and ルリ talked. ルリ", needs_review=True)]
        mask_targets = [(0, "ケイト"), (0, "ルリ")]

        result = build_review_term_map(translated_lines, mask_targets)

        assert result == {0: ["ケイト", "ルリ"]}

    def test_mask_targets_referencing_out_of_range_line_ignored(self):
        """An out-of-range line_idx (mismatched inputs) shouldn't raise -- just gets excluded."""
        translated_lines = [TranslatedLine(text="Only one line.", needs_review=False)]
        mask_targets = [(5, "何か")]

        assert build_review_term_map(translated_lines, mask_targets) == {}

    def test_confirmed_and_unconfirmed_terms_in_same_chunk(self):
        """A line with no mask target at all (a confirmed term translated normally) is absent from the result."""
        translated_lines = [
            TranslatedLine(text="Kate said hello.", needs_review=False),  # confirmed term, never masked
            TranslatedLine(text="音夢くん waved.", needs_review=True),  # suggested term, dropped
        ]
        mask_targets = [(1, "音夢くん")]

        result = build_review_term_map(translated_lines, mask_targets)

        assert result == {1: ["音夢くん"]}
        assert 0 not in result


class _RenderHarness:
    """Minimal stand-in exposing just what the render/click methods touch on self -- not a real ReaderApp."""

    def __init__(self, text_widget):
        self.text = text_widget
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self.popup_calls = []

    def open_word_glossary_popup(self, source_prefill, target_prefill, context=None):
        self.popup_calls.append((source_prefill, target_prefill, context))

    _render_translated_content_from_translated_lines = ReaderApp._render_translated_content_from_translated_lines
    _on_needs_review_click = ReaderApp._on_needs_review_click


class TestRenderAndClick:
    """Tk-level tests for the rendering/click-handling methods, against a real (headless) tk.Text widget.

    Bug found and fixed while writing these tests, in pre-existing code, not
    just the new needs-review path: self.text.index("end") always refers to
    the position AFTER Tk's mandatory trailing newline -- one line past
    where .insert("end", ...) actually places new text. _render_content()
    and _render_translated_content() both captured span start/end with
    plain "end", which meant _rendered_spans tracked every paragraph's
    range shifted by one line versus where its tag actually landed --
    confirmed against the real, unmodified (pre-fix) ReaderApp._render_content(),
    not a hypothetical. Practical effect: the first paragraph of every
    rendered episode never matched in _span_at_index(), so right-click ->
    Add to Glossary silently did nothing there. Fixed by using "end-1c" (the
    actual insertion point) in all four capture sites, including the two in
    the new _render_translated_content_from_translated_lines() added here,
    which inherited the same pattern. TestRightClickRegression below is the
    regression coverage for the pre-existing right-click flow specifically,
    since the needs-review tests alone wouldn't prove that path is fixed.
    """

    def _make_widget(self):
        # Deliberately NOT root.withdraw() -- a withdrawn window never gets
        # real geometry in this environment (winfo_width()/height() stay at
        # 1x1), which makes bbox()/dlineinfo() return None for every index
        # past the very first character. pack()+update() below gives the
        # widget real (if offscreen-in-CI-sense) dimensions so bbox-based
        # click-coordinate tests are meaningful.
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("needs_review", foreground="#b45309", underline=True)
        text.tag_configure("translated", foreground="#1a56c4")
        root.update()
        return root, text

    def test_needs_review_line_gets_needs_review_tag(self):
        """Checks via tag_ranges() rather than tag_names(start) -- see class docstring's note on the pre-existing index-offset quirk this surfaced; tag_ranges() reports what's actually tagged in the widget regardless of it."""
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Look, ケイト! So big!", needs_review=True)]

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, [(0, "ケイト")])

            start, end, tag, source = harness._rendered_spans[0]
            assert tag == "needs_review"
            assert text.tag_ranges("needs_review") != ()
            assert text.get(*text.tag_ranges("needs_review")[:2]).rstrip("\n") == "Look, ケイト! So big!"
        finally:
            root.destroy()

    def test_clean_line_gets_base_tag_not_needs_review(self):
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Kate turned around.", needs_review=False)]

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, [])

            start, end, tag, source = harness._rendered_spans[0]
            assert tag == "translated"
            assert text.tag_ranges("needs_review") == ()
        finally:
            root.destroy()

    def test_click_on_needs_review_span_prefills_correct_source_term(self):
        """Derives click coordinates from the tag's own reported range, not a hardcoded line-number guess."""
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {
                "content": [
                    {"type": "text", "text": "ケイトが振り返った。"},
                    {"type": "text", "text": "ルリが微笑んだ。"},
                ]
            }
            translated_lines = [
                TranslatedLine(text="Kate turned around.", needs_review=False),
                TranslatedLine(text="Ruri smiled. ルリ", needs_review=True),
            ]
            mask_targets = [(1, "ルリ")]

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, mask_targets)

            root.update_idletasks()
            review_start = text.tag_ranges("needs_review")[0]
            bbox = text.bbox(review_start)
            assert bbox is not None, "needs_review span has no bounding box -- widget not realized"
            x, y = bbox[0] + 1, bbox[1] + 1

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = x, y
            harness._on_needs_review_click(event)

            assert harness.popup_calls == [("ルリ", "", "ルリが微笑んだ。")]
        finally:
            root.destroy()

    def test_click_on_non_review_span_does_nothing(self):
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Kate turned around.", needs_review=False)]

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, [])

            root.update_idletasks()
            start, end, tag, source = harness._rendered_spans[0]
            bbox = text.bbox(start)
            assert bbox is not None

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = bbox[0] + 1, bbox[1] + 1
            harness._on_needs_review_click(event)

            assert harness.popup_calls == []
        finally:
            root.destroy()


class _RightClickHarness:
    """Minimal stand-in for the pre-existing right-click flow -- not a real ReaderApp."""

    def __init__(self, text_widget):
        self.text = text_widget
        self._rendered_spans = []

    def _make_photo_image(self, src):
        return None

    _render_content = ReaderApp._render_content
    _render_translated_content = ReaderApp._render_translated_content
    _span_at_index = ReaderApp._span_at_index


class TestRightClickRegression:
    """Regression coverage for the pre-existing right-click flow, on the first-paragraph case the end-1c fix addresses."""

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("original", foreground="#333333")
        text.tag_configure("translated", foreground="#1a56c4")
        root.update()
        return root, text

    def test_first_paragraph_resolves_via_span_at_index(self):
        """Before the end-1c fix, this returned None for the first paragraph specifically."""
        root, text = self._make_widget()
        try:
            harness = _RightClickHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}

            harness._render_content(ep, "original")
            root.update_idletasks()

            bbox = text.bbox("1.0")
            assert bbox is not None, "first line has no bounding box -- widget not realized"
            idx = text.index(f"@{bbox[0] + 1},{bbox[1] + 1}")

            span = harness._span_at_index(idx)

            assert span is not None
            assert span[3] == "ケイトが振り返った。"
        finally:
            root.destroy()

    def test_second_paragraph_also_resolves_correctly(self):
        """Guards against a fix that only shifts the bug rather than removing it."""
        root, text = self._make_widget()
        try:
            harness = _RightClickHarness(text)
            ep = {
                "content": [
                    {"type": "text", "text": "ケイトが振り返った。"},
                    {"type": "text", "text": "ルリが微笑んだ。"},
                ]
            }

            harness._render_content(ep, "original")
            root.update_idletasks()

            first_bbox = text.bbox("1.0")
            second_bbox = text.bbox("2.0")
            assert first_bbox is not None and second_bbox is not None

            first_idx = text.index(f"@{first_bbox[0] + 1},{first_bbox[1] + 1}")
            second_idx = text.index(f"@{second_bbox[0] + 1},{second_bbox[1] + 1}")

            first_span = harness._span_at_index(first_idx)
            second_span = harness._span_at_index(second_idx)

            assert first_span is not None and first_span[3] == "ケイトが振り返った。"
            assert second_span is not None and second_span[3] == "ルリが微笑んだ。"
        finally:
            root.destroy()

    def test_translated_view_first_paragraph_also_resolves(self):
        """Same regression via _render_translated_content() -- both view paths had the identical bug."""
        root, text = self._make_widget()
        try:
            harness = _RightClickHarness(text)
            ep = {
                "content": [{"type": "text", "text": "ケイトが振り返った。"}],
                "translated_lines": ["Kate turned around."],
            }

            harness._render_translated_content(ep, "translated")
            root.update_idletasks()

            bbox = text.bbox("1.0")
            assert bbox is not None
            idx = text.index(f"@{bbox[0] + 1},{bbox[1] + 1}")

            span = harness._span_at_index(idx)

            assert span is not None
            assert span[3] == "ケイトが振り返った。"
        finally:
            root.destroy()


class _DispatchHarness:
    """Minimal stand-in for testing _render_translated_view()'s dispatch/reconstruction logic."""

    def __init__(self, text_widget, current_url=None):
        self.text = text_widget
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self.current_url = current_url
        self.render_calls = []

    def _make_photo_image(self, src):
        return None

    def _render_translated_content(self, ep, tag):
        self.render_calls.append(("plain", ep, tag))

    def _render_translated_content_from_translated_lines(self, ep, tag, translated_lines, mask_targets):
        self.render_calls.append(("needs_review_aware", ep, tag, translated_lines, mask_targets))

    _render_translated_view = ReaderApp._render_translated_view


class TestRenderTranslatedView:
    """Tests for _render_translated_view()'s dispatch and TranslatedLine reconstruction from the cache shape."""

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        root.update()
        return root, text

    def test_dispatches_to_plain_renderer_when_no_needs_review_flags(self):
        """An episode with no needs_review_flags (older cache, or LLM backend never used) falls back to the plain renderer."""
        root, text = self._make_widget()
        try:
            harness = _DispatchHarness(text)
            ep = {"translated_lines": ["Hello.", "World."]}

            harness._render_translated_view(ep, "translated")

            assert len(harness.render_calls) == 1
            assert harness.render_calls[0][0] == "plain"
        finally:
            root.destroy()

    def test_dispatches_to_plain_renderer_on_length_mismatch(self):
        """A length mismatch between needs_review_flags and translated_lines falls back rather than zip()-truncating."""
        root, text = self._make_widget()
        try:
            harness = _DispatchHarness(text)
            ep = {"translated_lines": ["Hello.", "World."], "needs_review_flags": [False]}

            harness._render_translated_view(ep, "translated")

            assert harness.render_calls[0][0] == "plain"
        finally:
            root.destroy()

    def test_reconstructs_translated_line_objects_from_cache_shape(self, mocker):
        """Plain strings + parallel bool flags reconstruct into the same TranslatedLine objects translate_chunk_with_masking() would have produced directly."""
        root, text = self._make_widget()
        try:
            mocker.patch("pyplayground.webnovels.alphapolis_reader.load_glossary", return_value={"terms": []})
            mocker.patch("pyplayground.webnovels.alphapolis_reader.build_mask_targets", return_value=[(1, "音夢くん")])
            mocker.patch("pyplayground.webnovels.alphapolis_reader._extract_novel_id", return_value="12345")

            harness = _DispatchHarness(text, current_url="https://example.com/novel/12345/x/episode/1")
            ep = {
                "translated_lines": ["Kate turned around.", "音夢くん waved."],
                "needs_review_flags": [False, True],
                "lines": ["ケイトが振り返った。", "音夢くんが手を振った。"],
            }

            harness._render_translated_view(ep, "translated")

            assert len(harness.render_calls) == 1
            kind, call_ep, tag, translated_lines, mask_targets = harness.render_calls[0]
            assert kind == "needs_review_aware"
            assert translated_lines == [
                TranslatedLine(text="Kate turned around.", needs_review=False),
                TranslatedLine(text="音夢くん waved.", needs_review=True),
            ]
            assert mask_targets == [(1, "音夢くん")]
        finally:
            root.destroy()

    def test_no_current_url_falls_back_to_empty_mask_targets(self, mocker):
        """No current_url set means mask_targets is empty rather than raising -- needs_review tagging still works from persisted flags, just without click-to-add pre-fill data."""
        root, text = self._make_widget()
        try:
            build_mask_targets_spy = mocker.patch("pyplayground.webnovels.alphapolis_reader.build_mask_targets")

            harness = _DispatchHarness(text, current_url=None)
            ep = {
                "translated_lines": ["Hello."],
                "needs_review_flags": [True],
                "lines": ["こんにちは。"],
            }

            harness._render_translated_view(ep, "translated")

            kind, call_ep, tag, translated_lines, mask_targets = harness.render_calls[0]
            assert mask_targets == []
            build_mask_targets_spy.assert_not_called()
        finally:
            root.destroy()
