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


class TestTranslatedSpanAfter:
    """Tests for _translated_span_after().

    REFACTOR_DESIGN.md Phase 2: previously ran against a hand-rolled
    _SpanHarness; now the real ReaderRenderer via the shared conftest.py
    `renderer` fixture, since _translated_span_after() only reads
    self._rendered_spans (a ReaderRenderer-owned attribute).
    """

    def test_returns_the_next_span_after_an_original_span(self, renderer, fake_reader_app):
        original_span = ("1.0", "1.5", "original", "ケイトが振り返った。")
        translated_span = ("1.5", "1.10", "translated", "ケイトが振り返った。")
        renderer._rendered_spans = [original_span, translated_span]

        result = renderer._translated_span_after(original_span)

        assert result == translated_span

    def test_returns_next_span_correctly_for_second_pair(self, renderer, fake_reader_app):
        pair1_orig = ("1.0", "1.5", "original", "line1")
        pair1_trans = ("1.5", "1.10", "translated", "line1")
        pair2_orig = ("2.0", "2.5", "original", "line2")
        pair2_trans = ("2.5", "2.10", "translated", "line2")
        renderer._rendered_spans = [pair1_orig, pair1_trans, pair2_orig, pair2_trans]

        assert renderer._translated_span_after(pair2_orig) == pair2_trans

    def test_returns_none_when_span_not_found(self, renderer, fake_reader_app):
        renderer._rendered_spans = [("1.0", "1.5", "original", "line1")]

        result = renderer._translated_span_after(("9.0", "9.5", "original", "not present"))

        assert result is None

    def test_returns_none_when_span_is_the_last_entry(self, renderer, fake_reader_app):
        """A malformed/last-entry original span with nothing after it -- must not raise IndexError."""
        only_span = ("1.0", "1.5", "original", "line1")
        renderer._rendered_spans = [only_span]

        result = renderer._translated_span_after(only_span)

        assert result is None


class TestRetranslateMenuGating:
    """Confirms retranslate is offered only for original text in Interleaved mode, per phase 3's mode-availability decision.

    REFACTOR_DESIGN.md Phase 2: previously ran against a hand-rolled
    _RetranslateMenuHarness; now the reader_app_shell fixture (real
    ReaderApp._on_text_right_click() bound against a real ReaderRenderer
    for view_mode/_rendered_spans/_span_at_index/_translated_span_after).
    """

    def _render_pair(self, renderer, text, source, translated):
        start = text.index("end-1c")
        text.insert("end", source + "\n", "original")
        renderer._rendered_spans.append((start, text.index("end-1c"), "original", source))
        start = text.index("end-1c")
        text.insert("end", translated + "\n", "translated")
        renderer._rendered_spans.append((start, text.index("end-1c"), "translated", source))

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

    def test_retranslate_offered_on_original_text_in_interleaved_mode(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        text = reader_app_shell.text
        reader_app_shell.renderer.view_mode.set("interleaved")
        self._render_pair(reader_app_shell.renderer, text, "ケイトが振り返った。", "Kate turned around.")
        reader_app_shell.root.update_idletasks()

        monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

        bbox = text.bbox("1.0")
        assert bbox is not None

        class _FakeEvent:
            pass

        event = _FakeEvent()
        event.x, event.y = bbox[0] + 1, bbox[1] + 1
        event.x_root, event.y_root = 0, 0

        reader_app_shell._on_text_right_click(event)

        assert "Retranslate this line..." in self.last_menu.labels

    def test_retranslate_not_offered_on_translated_text(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        text = reader_app_shell.text
        reader_app_shell.renderer.view_mode.set("interleaved")
        self._render_pair(reader_app_shell.renderer, text, "ケイトが振り返った。", "Kate turned around.")
        reader_app_shell.root.update_idletasks()

        monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

        bbox = text.bbox("2.0")
        assert bbox is not None

        class _FakeEvent:
            pass

        event = _FakeEvent()
        event.x, event.y = bbox[0] + 1, bbox[1] + 1
        event.x_root, event.y_root = 0, 0

        reader_app_shell._on_text_right_click(event)

        assert "Retranslate this line..." not in self.last_menu.labels

    def test_retranslate_not_offered_outside_interleaved_mode(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        text = reader_app_shell.text
        reader_app_shell.renderer.view_mode.set("original")
        self._render_pair(reader_app_shell.renderer, text, "ケイトが振り返った。", "Kate turned around.")
        reader_app_shell.root.update_idletasks()

        monkeypatch.setattr(reader_module.tk, "Menu", self._make_fake_menu_class())

        bbox = text.bbox("1.0")
        assert bbox is not None

        class _FakeEvent:
            pass

        event = _FakeEvent()
        event.x, event.y = bbox[0] + 1, bbox[1] + 1
        event.x_root, event.y_root = 0, 0

        reader_app_shell._on_text_right_click(event)

        assert "Retranslate this line..." not in self.last_menu.labels


class TestNeedsReviewLineAlsoRetranslateTarget:
    """Required regression test: a line that is both a needs_review span-highlight target AND a valid retranslation click target must still resolve correctly on both paths after span-level highlighting was added.

    REFACTOR_DESIGN.md Phase 2: previously ran against a hand-rolled
    _NeedsReviewAndRetranslateHarness; now the real ReaderRenderer via
    the shared conftest.py `renderer`/`fake_reader_app` fixtures.
    """

    def test_translated_span_after_and_needs_review_span_both_resolve_on_same_line(self, renderer, fake_reader_app, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(
            reader_module,
            "load_glossary",
            lambda novel_id: {"terms": [{"source": "オレ", "type": "character", "status": "suggested"}]},
        )
        monkeypatch.setattr(
            renderer,
            "_render_translated_view",
            lambda ep, tag: (_ for _ in ()).throw(AssertionError("fallback should not fire -- pairs must be length-consistent in this test")),
        )

        text = fake_reader_app.text
        fake_reader_app.current_url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"
        ep = {
            "content": [{"type": "text", "text": "オレは彼を見た。"}],
            "lines": ["オレは彼を見た。"],
            "translated_lines": ["Because of オレ, he was seen."],
            "needs_review_flags": [True],
        }

        renderer._render_interleaved_content(ep, "original", "translated")

        # _rendered_spans' one-pair-per-line (original, translated)
        # invariant must be intact -- RETRANSLATION_DESIGN.md's
        # _translated_span_after() depends on it directly.
        assert len(renderer._rendered_spans) == 2
        original_span = renderer._rendered_spans[0]
        translated_span = renderer._rendered_spans[1]
        assert original_span[2] == "original"
        assert translated_span[2] == "translated"

        # Retranslation's span-pairing lookup still resolves correctly.
        resolved = renderer._translated_span_after(original_span)
        assert resolved == translated_span

        # needs_review span-level highlighting also resolved correctly
        # on the very same line, independently.
        assert len(renderer._review_terms_by_span) == 1
        (start, end), (word, source_line) = next(iter(renderer._review_terms_by_span.items()))
        assert word == "オレ"
        assert source_line == "オレは彼を見た。"
        assert text.get(start, end) == "オレ"
        assert "needs_review" in text.tag_names(start)


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

    REFACTOR_DESIGN.md Phase 2: previously ran against a hand-rolled
    _AcceptSurvivesModeSwitchHarness that combined render_text()'s and
    open_retranslate_popup()'s dependencies by hand; now the
    reader_app_shell fixture (real ReaderApp.open_retranslate_popup()
    bound against a real ReaderRenderer for render_text()/_rendered_spans/
    _translated_span_after/_translated_line_index_by_span) -- this is
    the single most load-bearing test in this migration, since it's the
    concrete proof the B/A/D three-way coupling around
    _translated_line_index_by_span still works after the module
    boundary moved.
    """

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

    def test_accepted_retranslation_survives_switching_to_translated_and_back(self, reader_app_shell, monkeypatch):
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

        episode = self._make_episode()
        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"
        reader_app_shell.episode = episode
        reader_app_shell.renderer.view_mode.set("interleaved")
        text = reader_app_shell.text

        reader_app_shell.renderer.render_text()
        original_span = reader_app_shell.renderer._rendered_spans[0]
        translated_span = reader_app_shell.renderer._translated_span_after(original_span)
        assert translated_span is not None

        reader_app_shell.open_retranslate_popup("彼は醤油顔でモテる。", translated_span, "醤油顔で")

        popup = reader_app_shell._retranslate_popup
        assert popup is not None

        # fetch_candidate() (run synchronously in-thread, per the
        # _SyncThread patch above) schedules build_form() via
        # root.after(0, ...) -- pump the event loop so that callback
        # actually runs and replaces the "Retranslating..." status
        # label with the real Accept/Discard buttons.
        reader_app_shell.root.update()
        accept_btn = _find_button(popup, "Accept")
        assert accept_btn is not None, "Accept button never appeared -- build_form() did not run"
        accept_btn.invoke()
        reader_app_shell.root.update()

        # Accept must write through to the shared episode structure,
        # not just the transient widget/_rendered_spans -- this is the
        # actual mechanism render_text() reads from on every mode
        # switch, so this assertion is the crux of the fix.
        assert episode["translated_lines"][0] == "He is popular because of his dark complexion."

        # Simulate switching to Translated mode: a full render_text()
        # rebuild from self.episode, same as _on_view_mode_change() does.
        reader_app_shell.renderer.view_mode.set("translated")
        reader_app_shell.renderer.render_text()
        translated_mode_text = text.get("1.0", "end")
        assert "He is popular because of his dark complexion." in translated_mode_text
        assert "He is popular with a dark complexion." not in translated_mode_text

        # And switching back to Interleaved -- the correction must
        # still be there, not just transiently visible in one mode.
        reader_app_shell.renderer.view_mode.set("interleaved")
        reader_app_shell.renderer.render_text()
        interleaved_mode_text = text.get("1.0", "end")
        assert "He is popular because of his dark complexion." in interleaved_mode_text
        assert "He is popular with a dark complexion." not in interleaved_mode_text


class TestPopupSingleInstanceGuard:
    """A second call to open the same popup kind while one is already open must not stack a duplicate -- found live: repeated clicks during xdotool verification opened multiple independent dialogs.

    REFACTOR_DESIGN.md Phase 2: previously ran against a hand-rolled
    _PopupGuardHarness; now the reader_app_shell fixture (real
    ReaderApp.open_word_glossary_popup()/open_retranslate_popup()).
    """

    def test_second_glossary_popup_call_reuses_existing_window(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")

        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"

        reader_app_shell.open_word_glossary_popup("ケイト", "", context="ケイトが振り返った。")
        first_popup = reader_app_shell._glossary_popup
        assert first_popup is not None

        reader_app_shell.open_word_glossary_popup("ルリ", "", context="ルリが微笑んだ。")

        # Still the same window -- no second Toplevel was created.
        assert reader_app_shell._glossary_popup is first_popup

    def test_glossary_popup_guard_clears_after_close(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module, "check_llm_available", lambda: False)
        monkeypatch.setattr(reader_module, "translate_chunk", lambda *a, **k: "translated")

        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"

        reader_app_shell.open_word_glossary_popup("ケイト", "", context="ケイトが振り返った。")
        first_popup = reader_app_shell._glossary_popup
        first_popup.destroy()
        reader_app_shell.root.update()

        assert reader_app_shell._glossary_popup is None

        reader_app_shell.open_word_glossary_popup("ルリ", "", context="ルリが微笑んだ。")

        assert reader_app_shell._glossary_popup is not None
        assert reader_app_shell._glossary_popup is not first_popup

    def test_second_retranslate_popup_call_reuses_existing_window(self, reader_app_shell, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        monkeypatch.setattr(reader_module, "retranslate_line_with_hint", lambda *a, **k: "candidate")
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: {"terms": []})
        monkeypatch.setattr(reader_module, "format_glossary_for_prompt", lambda glossary: "")

        reader_app_shell.current_url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"
        reader_app_shell.text.insert("1.0", "Kate turned around.\n", "translated")
        translated_span = ("1.0", "1.19", "translated", "ケイトが振り返った。")

        reader_app_shell.open_retranslate_popup("ケイトが振り返った。", translated_span, "ケイト")
        first_popup = reader_app_shell._retranslate_popup
        assert first_popup is not None

        reader_app_shell.open_retranslate_popup("ケイトが振り返った。", translated_span, "ケイト")

        assert reader_app_shell._retranslate_popup is first_popup
