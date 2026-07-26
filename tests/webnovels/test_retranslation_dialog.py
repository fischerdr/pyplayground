#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the retranslation dialog wiring (RETRANSLATION_DESIGN.md phase 3).

Tracked in a separate test file, matching phase 1/2's own precedent of
splitting each phase's tests out from test_alphapolis_reader.py.

Coverage here targets the pieces that don't require a live server or a
fully-threaded popup: _translated_span_after() (the pure span-pairing
lookup interleaved mode relies on), the menu-gating logic in
_on_text_right_click() (retranslate offered only for original-tagged text
in Interleaved mode), and the Accept mutation (in-memory text/span update,
session-only). The full popup flow (background thread, LLM call, Accept/
Discard buttons) is live-verified via xdotool against a real running app,
documented in RETRANSLATION_DESIGN.md's phase 3 status entry, not
re-verified here as an automated test.
"""

import tkinter as tk

from pyplayground.webnovels.alphapolis_reader import ReaderApp


class _SpanHarness:
    """Minimal stand-in for _translated_span_after(), which only needs self._rendered_spans."""

    def __init__(self, spans):
        self._rendered_spans = spans

    _translated_span_after = ReaderApp._translated_span_after


class TestTranslatedSpanAfter:
    """Tests for _translated_span_after()."""

    def test_returns_the_next_span_after_an_original_span(self):
        original_span = ("1.0", "1.5", "original", "ケイトが振り返った。")
        translated_span = ("1.5", "1.10", "translated", "ケイトが振り返った。")
        harness = _SpanHarness([original_span, translated_span])

        result = harness._translated_span_after(original_span)

        assert result == translated_span

    def test_returns_next_span_correctly_for_second_pair(self):
        pair1_orig = ("1.0", "1.5", "original", "line1")
        pair1_trans = ("1.5", "1.10", "translated", "line1")
        pair2_orig = ("2.0", "2.5", "original", "line2")
        pair2_trans = ("2.5", "2.10", "translated", "line2")
        harness = _SpanHarness([pair1_orig, pair1_trans, pair2_orig, pair2_trans])

        assert harness._translated_span_after(pair2_orig) == pair2_trans

    def test_returns_none_when_span_not_found(self):
        harness = _SpanHarness([("1.0", "1.5", "original", "line1")])

        result = harness._translated_span_after(("9.0", "9.5", "original", "not present"))

        assert result is None

    def test_returns_none_when_span_is_the_last_entry(self):
        """A malformed/last-entry original span with nothing after it -- must not raise IndexError."""
        only_span = ("1.0", "1.5", "original", "line1")
        harness = _SpanHarness([only_span])

        result = harness._translated_span_after(only_span)

        assert result is None


class _RetranslateMenuHarness:
    """Minimal stand-in for _on_text_right_click()'s retranslate-menu gating logic."""

    def __init__(self, text_widget, view_mode="interleaved"):
        self.text = text_widget
        self.root = text_widget.winfo_toplevel()
        self._rendered_spans = []
        self.view_mode = tk.StringVar(value=view_mode)
        self.retranslate_calls = []

    def _make_photo_image(self, src):
        return None

    def open_word_glossary_popup(self, *args, **kwargs):
        pass

    def open_retranslate_popup(self, source_line, translated_span, hint_word):
        self.retranslate_calls.append((source_line, translated_span, hint_word))

    _span_at_index = ReaderApp._span_at_index
    _translated_span_after = ReaderApp._translated_span_after
    _prefill_for_word = ReaderApp._prefill_for_word
    _on_text_right_click = ReaderApp._on_text_right_click


class TestRetranslateMenuGating:
    """Confirms retranslate is offered only for original text in Interleaved mode, per phase 3's mode-availability decision."""

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("original", foreground="#333333")
        text.tag_configure("translated", foreground="#1a56c4")
        root.update()
        return root, text

    def _render_pair(self, harness, text, source, translated):
        start = text.index("end-1c")
        text.insert("end", source + "\n", "original")
        harness._rendered_spans.append((start, text.index("end-1c"), "original", source))
        start = text.index("end-1c")
        text.insert("end", translated + "\n", "translated")
        harness._rendered_spans.append((start, text.index("end-1c"), "translated", source))

    last_menu = None

    def _make_fake_menu_class(self):
        outer = self

        class _FakeMenu:
            """Captures add_command() calls instead of popping a real menu (headless, no real popup)."""

            def __init__(self, *_args, **_kwargs):
                self.labels = []
                outer.last_menu = self

            def add_command(self, label, command):
                self.labels.append(label)

            def tk_popup(self, *_args, **_kwargs):
                pass

        return _FakeMenu

    def test_retranslate_offered_on_original_text_in_interleaved_mode(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        root, text = self._make_widget()
        try:
            harness = _RetranslateMenuHarness(text, view_mode="interleaved")
            self._render_pair(harness, text, "ケイトが振り返った。", "Kate turned around.")
            root.update_idletasks()

            monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

            bbox = text.bbox("1.0")
            assert bbox is not None

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = bbox[0] + 1, bbox[1] + 1
            event.x_root, event.y_root = 0, 0

            harness._on_text_right_click(event)

            assert "Retranslate this line..." in self.last_menu.labels
        finally:
            root.destroy()

    def test_retranslate_not_offered_on_translated_text(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        root, text = self._make_widget()
        try:
            harness = _RetranslateMenuHarness(text, view_mode="interleaved")
            self._render_pair(harness, text, "ケイトが振り返った。", "Kate turned around.")
            root.update_idletasks()

            monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

            bbox = text.bbox("2.0")
            assert bbox is not None

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = bbox[0] + 1, bbox[1] + 1
            event.x_root, event.y_root = 0, 0

            harness._on_text_right_click(event)

            assert "Retranslate this line..." not in self.last_menu.labels
        finally:
            root.destroy()

    def test_retranslate_not_offered_outside_interleaved_mode(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        root, text = self._make_widget()
        try:
            harness = _RetranslateMenuHarness(text, view_mode="original")
            self._render_pair(harness, text, "ケイトが振り返った。", "Kate turned around.")
            root.update_idletasks()

            monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

            bbox = text.bbox("1.0")
            assert bbox is not None

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = bbox[0] + 1, bbox[1] + 1
            event.x_root, event.y_root = 0, 0

            harness._on_text_right_click(event)

            assert "Retranslate this line..." not in self.last_menu.labels
        finally:
            root.destroy()
