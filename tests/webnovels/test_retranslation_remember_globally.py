#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the "remember this" checkbox's global-vocabulary write path (RETRANSLATION_DESIGN.md Phase 5).

Tracked in a separate test file, matching phase 1/2/3's own precedent of
splitting each phase's tests out from test_alphapolis_reader.py /
test_retranslation_dialog.py -- this covers a materially different concern
(writing to the new global vocabulary store) than that file's existing
accept/discard session-scope tests.
"""

import tkinter as tk

import pyplayground.webnovels.alphapolis_reader as reader_module
from pyplayground.webnovels.alphapolis_reader import _diff_single_substring


def _find_button(container, text):
    for w in container.winfo_children():
        if isinstance(w, tk.ttk.Button) and w.cget("text") == text:
            return w
        found = _find_button(w, text)
        if found is not None:
            return found
    return None


def _find_entries(container, found=None):
    if found is None:
        found = []
    for w in container.winfo_children():
        if isinstance(w, tk.ttk.Entry):
            found.append(w)
        _find_entries(w, found)
    return found


class TestDiffSingleSubstring:
    """Tests for _diff_single_substring() -- the Target pre-fill heuristic."""

    def test_single_contiguous_replacement_is_extracted(self):
        before = "He is attractive because of his dark complexion."
        after = "He is attractive because of his tanned complexion."

        assert _diff_single_substring(before, after) == "tanned"

    def test_identical_strings_return_none(self):
        assert _diff_single_substring("same text", "same text") is None

    def test_multiple_non_contiguous_replacements_return_none(self):
        before = "The dark man wore a black hat and blue shoes."
        after = "The tanned man wore a red hat and blue shoes changed."

        assert _diff_single_substring(before, after) is None

    def test_whole_remainder_replaced_as_one_block_is_extracted(self):
        """A correction changing everything after a shared anchor word is still one contiguous replace op.

        Even though it spans many words, this is not the "ambiguous" case
        this heuristic needs to reject; only genuinely separate,
        non-adjacent changed spans should return None.
        """
        before = "He does not wear underwear and wears black underwear."
        after = "He is a fan of briefs."

        assert _diff_single_substring(before, after) == "is a fan of briefs."


class TestRememberGloballyPopup:
    """Tests for ReaderApp._open_remember_globally_popup(), triggered by the retranslation dialog's checkbox."""

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

    def _accept_with_remember_checked(self, reader_app_shell, monkeypatch, candidate="He is popular because of his tanned complexion."):
        monkeypatch.setattr(reader_module, "retranslate_line_with_hint", lambda *a, **k: candidate)
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: {"terms": []})
        monkeypatch.setattr(reader_module, "format_glossary_for_prompt", lambda glossary: "")
        monkeypatch.setattr(reader_module, "load_global_vocabulary", lambda: {"entries": []})
        monkeypatch.setattr(reader_module, "format_global_vocabulary_for_prompt", lambda store, glossary=None: "")
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

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

        reader_app_shell.renderer.render_text()
        original_span = reader_app_shell.renderer._rendered_spans[0]
        translated_span = reader_app_shell.renderer._translated_span_after(original_span)

        reader_app_shell.open_retranslate_popup("彼は醤油顔でモテる。", translated_span, "醤油顔")
        popup = reader_app_shell._retranslate_popup
        reader_app_shell.root.update()

        remember_checkbox = None
        for w in popup.winfo_children():
            if isinstance(w, tk.ttk.Checkbutton):
                remember_checkbox = w
                break
        assert remember_checkbox is not None, "'Also remember this for next time' checkbox not found"
        return popup

    def test_checkbox_checked_opens_remember_globally_popup(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)

        accept_btn = _find_button(popup, "Accept")
        assert accept_btn is not None
        children_before = set(reader_app_shell.root.winfo_children())
        accept_btn.invoke()
        reader_app_shell.root.update()

        new_children = set(reader_app_shell.root.winfo_children()) - children_before
        remember_popups = [w for w in new_children if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally"]
        assert len(remember_popups) == 1, "Remember Globally popup did not open when checkbox was checked"

    def test_checkbox_unchecked_does_not_open_popup(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)

        for w in popup.winfo_children():
            if isinstance(w, tk.ttk.Checkbutton):
                w.invoke()  # toggles off, since it defaults to checked

        accept_btn = _find_button(popup, "Accept")
        children_before = set(reader_app_shell.root.winfo_children())
        accept_btn.invoke()
        reader_app_shell.root.update()

        new_children = set(reader_app_shell.root.winfo_children()) - children_before
        remember_popups = [w for w in new_children if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally"]
        assert remember_popups == []

    def test_source_field_prefilled_from_hint_word(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        remember_win = next(w for w in reader_app_shell.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally")
        entries = _find_entries(remember_win)
        assert entries[0].get() == "醤油顔"

    def test_target_field_prefilled_via_diff_when_unambiguous(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch, candidate="He is popular because of his tanned complexion.")
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        remember_win = next(w for w in reader_app_shell.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally")
        entries = _find_entries(remember_win)
        # The whole "with a dark" -> "because of his tanned" span is one
        # contiguous replace op (no unchanged anchor word sits between
        # them), so the extracted substring is the full replacement
        # phrase, not just the single word "tanned" -- correct behavior
        # for this specific before/after pair, not a narrower "one word
        # only" heuristic.
        assert entries[1].get() == "because of his tanned"

    def test_target_field_blank_when_diff_is_ambiguous(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch, candidate="She is popular with a tanned complexion.")
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        remember_win = next(w for w in reader_app_shell.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally")
        entries = _find_entries(remember_win)
        assert entries[1].get() == ""

    def test_save_globally_calls_upsert_global_entry_with_edited_fields(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        remember_win = next(w for w in reader_app_shell.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally")
        entries = _find_entries(remember_win)
        entries[0].delete(0, "end")
        entries[0].insert(0, "醤油顔")
        entries[1].delete(0, "end")
        entries[1].insert(0, "plain-featured")

        calls = []
        monkeypatch.setattr(reader_module, "upsert_global_entry", lambda source, target, note=None: calls.append((source, target, note)))

        save_btn = _find_button(remember_win, "Save Globally")
        save_btn.invoke()

        assert calls == [("醤油顔", "plain-featured", None)]

    def test_skip_does_not_write_anything(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        remember_win = next(w for w in reader_app_shell.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Remember Globally")

        calls = []
        monkeypatch.setattr(reader_module, "upsert_global_entry", lambda *a, **k: calls.append((a, k)))

        skip_btn = _find_button(remember_win, "Skip")
        skip_btn.invoke()

        assert calls == []

    def test_outer_accept_still_applies_session_correction_regardless_of_remember_globally_popup_outcome(self, reader_app_shell, monkeypatch):
        popup = self._accept_with_remember_checked(reader_app_shell, monkeypatch)
        accept_btn = _find_button(popup, "Accept")
        accept_btn.invoke()
        reader_app_shell.root.update()

        # The outer Accept's session-only line-apply logic runs
        # immediately regardless of what happens in the Remember Globally
        # sub-popup (never opened/closed here) -- fire-and-forget, not a
        # blocking dependency.
        assert reader_app_shell.episode["translated_lines"][0] == "He is popular because of his tanned complexion."
