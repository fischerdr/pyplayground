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


class _NeedsReviewAndRetranslateHarness:
    """Real _render_interleaved_content() + _translated_span_after(), for the required needs_review/retranslate interaction regression test."""

    def __init__(self, text_widget, current_url):
        self.text = text_widget
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self._translated_line_index_by_span = {}
        self.current_url = current_url

    def _make_photo_image(self, src):
        return None

    def _render_translated_view(self, ep, tag):
        raise AssertionError("fallback should not fire -- pairs must be length-consistent in this test")

    _render_interleaved_content = ReaderApp._render_interleaved_content
    _apply_needs_review_spans = ReaderApp._apply_needs_review_spans
    _translated_span_after = ReaderApp._translated_span_after


class TestNeedsReviewLineAlsoRetranslateTarget:
    """Required regression test: a line that is both a needs_review span-highlight target AND a valid retranslation click target must still resolve correctly on both paths after span-level highlighting was added."""

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("original", foreground="#333333")
        text.tag_configure("translated", foreground="#1a56c4")
        text.tag_configure("needs_review", foreground="#b45309", underline=True)
        root.update()
        return root, text

    def test_translated_span_after_and_needs_review_span_both_resolve_on_same_line(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(
            reader_module,
            "load_glossary",
            lambda novel_id: {"terms": [{"source": "オレ", "type": "character", "status": "suggested"}]},
        )

        root, text = self._make_widget()
        try:
            harness = _NeedsReviewAndRetranslateHarness(text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            ep = {
                "content": [{"type": "text", "text": "オレは彼を見た。"}],
                "lines": ["オレは彼を見た。"],
                "translated_lines": ["Because of オレ, he was seen."],
                "needs_review_flags": [True],
            }

            harness._render_interleaved_content(ep, "original", "translated")

            # _rendered_spans' one-pair-per-line (original, translated)
            # invariant must be intact -- RETRANSLATION_DESIGN.md's
            # _translated_span_after() depends on it directly.
            assert len(harness._rendered_spans) == 2
            original_span = harness._rendered_spans[0]
            translated_span = harness._rendered_spans[1]
            assert original_span[2] == "original"
            assert translated_span[2] == "translated"

            # Retranslation's span-pairing lookup still resolves correctly.
            resolved = harness._translated_span_after(original_span)
            assert resolved == translated_span

            # needs_review span-level highlighting also resolved correctly
            # on the very same line, independently.
            assert len(harness._review_terms_by_span) == 1
            (start, end), (word, source_line) = next(iter(harness._review_terms_by_span.items()))
            assert word == "オレ"
            assert source_line == "オレは彼を見た。"
            assert text.get(start, end) == "オレ"
            assert "needs_review" in text.tag_names(start)
        finally:
            root.destroy()


def _find_toplevel_titled(root, title_substring):
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel) and title_substring in child.title():
            return child
    return None


def _find_button(container, text):
    for w in container.winfo_children():
        if isinstance(w, tk.ttk.Button) and w.cget("text") == text:
            return w
        found = _find_button(w, text)
        if found is not None:
            return found
    return None


class _AcceptSurvivesModeSwitchHarness:
    """Real render_text() + open_retranslate_popup(), for the required same-session mode-switch regression test.

    Combines render_text()'s dependencies (self.text/self.episode/
    self.view_mode plus the real _render_content/_render_translated_view/
    _render_interleaved_content methods) with open_retranslate_popup()'s
    (self.root/self.text/self.current_url/self._retranslate_popup/
    self._word_guess_cache/self.target_lang) -- both real, unmodified
    methods, not reimplemented, so this exercises the actual Accept code
    path against the actual render/rebuild code path.
    """

    def __init__(self, root, text_widget, current_url, episode):
        self.root = root
        self.text = text_widget
        self.current_url = current_url
        self.episode = episode
        self.view_mode = tk.StringVar(value="interleaved")
        self._rendered_spans = []
        self._review_terms_by_span = {}
        self._translated_line_index_by_span = {}
        self._retranslate_popup = None
        self._word_guess_cache = {}
        self.target_lang = "en"

    def _make_photo_image(self, src):
        return None

    def set_status(self, msg):
        pass

    render_text = ReaderApp.render_text
    _render_content = ReaderApp._render_content
    _render_translated_view = ReaderApp._render_translated_view
    _render_translated_content = ReaderApp._render_translated_content
    _render_interleaved_content = ReaderApp._render_interleaved_content
    _apply_needs_review_spans = ReaderApp._apply_needs_review_spans
    _translated_span_after = ReaderApp._translated_span_after
    open_retranslate_popup = ReaderApp.open_retranslate_popup


class TestAcceptSurvivesModeSwitch:
    """Required regression test: an accepted retranslation in Interleaved mode must survive switching to a different view mode within the same session.

    Found live (not just suspected): Accept previously mutated only the
    live tk.Text widget and _rendered_spans, both of which render_text()
    unconditionally wipes and rebuilds from self.episode on every mode
    switch -- so the correction was silently discarded the moment the
    view mode changed, even though it had nothing to do with reloading
    the chapter (the already-known, expected-to-be-lost case). Fixed by
    having Accept also write the correction into
    self.episode["translated_lines"] itself, the shared structure every
    render mode reads from.
    """

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        text.tag_configure("heading", font=("TkDefaultFont", 12, "bold"))
        text.tag_configure("original", foreground="#333333")
        text.tag_configure("translated", foreground="#1a56c4")
        root.update()
        return root, text

    def _make_episode(self):
        return {
            "title": "Title",
            "author": "Author",
            "episode_title": "Ep 1",
            "translated_title": "Title",
            "translated_episode_title": "Ep 1",
            "lines": ["彼は醤油顔でモテる。"],
            "content": [{"type": "text", "text": "彼は醤油顔でモテる。"}],
            "translated_lines": ["He is popular with a dark complexion."],
        }

    def test_accepted_retranslation_survives_switching_to_translated_and_back(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "retranslate_line_with_hint", lambda *a, **k: "He is popular because of his dark complexion.")
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: {"terms": []})
        monkeypatch.setattr(reader_module, "format_glossary_for_prompt", lambda glossary: "")
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        # open_retranslate_popup() normally runs fetch_candidate() on a
        # background thread and schedules build_form() via
        # self.root.after(0, ...) once it returns -- outside a real
        # mainloop() (as in this test), that after() call races the test
        # thread and can hit "main thread is not in main loop" in Tk's C
        # layer. retranslate_line_with_hint() is mocked above to return
        # instantly/deterministically anyway, so there is no real
        # concurrency to test here -- run the "background" work
        # synchronously in the calling thread instead, exercising the
        # exact same fetch_candidate/build_form code, just without the
        # thread-timing race that has nothing to do with what this test
        # is actually checking (Accept's in-memory write-through).
        class _SyncThread:
            def __init__(self, target, daemon=True):
                self._target = target

            def start(self):
                self._target()

        monkeypatch.setattr(reader_module.threading, "Thread", _SyncThread)

        root, text = self._make_widget()
        try:
            episode = self._make_episode()
            harness = _AcceptSurvivesModeSwitchHarness(root, text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1", episode=episode)

            harness.render_text()
            original_span = harness._rendered_spans[0]
            translated_span = harness._translated_span_after(original_span)
            assert translated_span is not None

            harness.open_retranslate_popup("彼は醤油顔でモテる。", translated_span, "醤油顔で")

            popup = harness._retranslate_popup
            assert popup is not None

            # fetch_candidate() (run synchronously in-thread, per the
            # _SyncThread patch above) schedules build_form() via
            # root.after(0, ...) -- pump the event loop so that callback
            # actually runs and replaces the "Retranslating..." status
            # label with the real Accept/Discard buttons.
            root.update()
            accept_btn = _find_button(popup, "Accept")
            assert accept_btn is not None, "Accept button never appeared -- build_form() did not run"
            accept_btn.invoke()
            root.update()

            # Accept must write through to the shared episode structure,
            # not just the transient widget/_rendered_spans -- this is the
            # actual mechanism render_text() reads from on every mode
            # switch, so this assertion is the crux of the fix.
            assert episode["translated_lines"][0] == "He is popular because of his dark complexion."

            # Simulate switching to Translated mode: a full render_text()
            # rebuild from self.episode, same as _on_view_mode_change() does.
            harness.view_mode.set("translated")
            harness.render_text()
            translated_mode_text = text.get("1.0", "end")
            assert "He is popular because of his dark complexion." in translated_mode_text
            assert "He is popular with a dark complexion." not in translated_mode_text

            # And switching back to Interleaved -- the correction must
            # still be there, not just transiently visible in one mode.
            harness.view_mode.set("interleaved")
            harness.render_text()
            interleaved_mode_text = text.get("1.0", "end")
            assert "He is popular because of his dark complexion." in interleaved_mode_text
            assert "He is popular with a dark complexion." not in interleaved_mode_text
        finally:
            root.destroy()


class _PopupGuardHarness:
    """Minimal stand-in exposing exactly what open_word_glossary_popup()/open_retranslate_popup() touch on self, for testing the single-popup-at-a-time guard found live during this task's xdotool verification."""

    def __init__(self, root, text_widget, current_url):
        self.root = root
        self.text = text_widget
        self.current_url = current_url
        self._glossary_popup = None
        self._retranslate_popup = None
        self._word_guess_cache = {}
        self.target_lang = "en"

    def set_status(self, msg):
        pass

    open_word_glossary_popup = ReaderApp.open_word_glossary_popup
    open_retranslate_popup = ReaderApp.open_retranslate_popup


class TestPopupSingleInstanceGuard:
    """A second call to open the same popup kind while one is already open must not stack a duplicate -- found live: repeated clicks during xdotool verification opened multiple independent dialogs."""

    def _make_widget(self):
        root = tk.Tk()
        text = tk.Text(root, width=80, height=24)
        text.pack()
        root.update()
        return root, text

    def test_second_glossary_popup_call_reuses_existing_window(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")

        root, text = self._make_widget()
        try:
            harness = _PopupGuardHarness(root, text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")

            harness.open_word_glossary_popup("ケイト", "", context="ケイトが振り返った。")
            first_popup = harness._glossary_popup
            assert first_popup is not None

            harness.open_word_glossary_popup("ルリ", "", context="ルリが微笑んだ。")

            # Still the same window -- no second Toplevel was created.
            assert harness._glossary_popup is first_popup
        finally:
            root.destroy()

    def test_glossary_popup_guard_clears_after_close(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")

        root, text = self._make_widget()
        try:
            harness = _PopupGuardHarness(root, text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")

            harness.open_word_glossary_popup("ケイト", "", context="ケイトが振り返った。")
            first_popup = harness._glossary_popup
            first_popup.destroy()
            root.update()

            assert harness._glossary_popup is None

            harness.open_word_glossary_popup("ルリ", "", context="ルリが微笑んだ。")

            assert harness._glossary_popup is not None
            assert harness._glossary_popup is not first_popup
        finally:
            root.destroy()

    def test_second_retranslate_popup_call_reuses_existing_window(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "retranslate_line_with_hint", lambda *a, **k: "candidate")
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: {"terms": []})
        monkeypatch.setattr(reader_module, "format_glossary_for_prompt", lambda glossary: "")

        root, text = self._make_widget()
        try:
            harness = _PopupGuardHarness(root, text, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            text.insert("1.0", "Kate turned around.\n", "translated")
            translated_span = ("1.0", "1.19", "translated", "ケイトが振り返った。")

            harness.open_retranslate_popup("ケイトが振り返った。", translated_span, "ケイト")
            first_popup = harness._retranslate_popup
            assert first_popup is not None

            harness.open_retranslate_popup("ケイトが振り返った。", translated_span, "ケイト")

            assert harness._retranslate_popup is first_popup
        finally:
            root.destroy()
