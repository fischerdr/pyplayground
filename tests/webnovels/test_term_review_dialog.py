#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the bulk term-review dialog (open_term_review_dialog(), DESIGN.md's dated entry).

A separate, standalone dialog from open_glossary_dialog() -- see the
method's own docstring for why building new (not extending the general
editor) was the right call. These tests drive the real bound method
against a real (headless) Tk widget tree, with load_glossary()/
save_glossary() mocked so no real filesystem access happens -- same
pattern as TestPopupSingleInstanceGuard in test_retranslation_dialog.py.

Live/visual verification (xdotool against novel 375266002's real
glossary) is documented in DESIGN.md's dated entry, not repeated here.
"""

import tkinter as tk

from pyplayground.webnovels.alphapolis_reader import ReaderApp
from pyplayground.webnovels.glossary import (
    STATUS_CONFIRMED,
    TERM_TYPE_CHARACTER,
    TERM_TYPE_GENERAL,
    make_confirmed_term,
    make_suggested_term,
)


class _ReviewDialogHarness:
    """Minimal stand-in exposing exactly what open_term_review_dialog() touches on self.

    refresh_current_episode is stubbed (records calls instead of a real
    network fetch + LLM translation) -- _maybe_refresh_after_glossary_edit()
    is the real, unmodified ReaderApp method, so the auto-refresh trigger/
    gating logic under test is real.
    """

    def __init__(self, root, current_url):
        self.root = root
        self.current_url = current_url
        self.refresh_calls = []

    def set_status(self, msg):
        pass

    def refresh_current_episode(self):
        self.refresh_calls.append(self.current_url)

    open_term_review_dialog = ReaderApp.open_term_review_dialog
    _maybe_refresh_after_glossary_edit = ReaderApp._maybe_refresh_after_glossary_edit


def _make_glossary(terms):
    return {"novel_id": "12345", "title": "Test Novel", "terms": terms, "context_notes": "", "updated_at": ""}


def _find_toplevel_titled(root, prefix):
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel) and child.title().startswith(prefix):
            return child
    return None


class TestTermReviewDialogListing:
    """Tests for which terms the dialog's tree shows."""

    def test_lists_suggested_terms_and_excludes_confirmed(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary(
            [
                make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me"),
                make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate"),
                make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
            ]
        )
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            assert win is not None
            tree = win.nametowidget(win.winfo_children()[0].winfo_children()[0])
            row_sources = [tree.item(iid, "values")[0] for iid in tree.get_children()]

            assert row_sources == ["オレ", "鉄パイプ"]
        finally:
            root.destroy()

    def test_old_shape_terms_with_no_status_field_are_also_listed(self, monkeypatch):
        """Real live data (novel 375266002's actual glossary) has old pre-Section-9-shape terms with no status field at all -- these are exactly the terms most in need of review and must not be silently excluded by a narrower status == STATUS_SUGGESTED check."""
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary(
            [
                {"source": "ダンジョン能力者", "type": "term", "target": "dungeon ability user", "note": None},
                make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate"),
            ]
        )
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree = win.nametowidget(win.winfo_children()[0].winfo_children()[0])
            row_sources = [tree.item(iid, "values")[0] for iid in tree.get_children()]

            assert row_sources == ["ダンジョン能力者"]
        finally:
            root.destroy()

    def test_zero_reviewable_terms_shows_empty_state(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary([make_confirmed_term(TERM_TYPE_CHARACTER, "ケイト", "Kate")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            assert win is not None
            found_empty_label = any(isinstance(w, tk.ttk.Label) and "No unconfirmed terms" in w.cget("text") for w in win.winfo_children())
            assert found_empty_label
        finally:
            root.destroy()


class TestTermReviewDialogConfirm:
    """Tests for the Confirm action."""

    def test_confirm_writes_via_upsert_confirmed_term_and_persists(self, monkeypatch):
        """Confirming must go through the same upsert_confirmed_term() path the manual Add-to-Glossary dialog uses (now via GlossaryCoordinator, REFACTOR_DESIGN.md Phase 3c) -- not a third write path."""
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        saved = {}

        # open_term_review_dialog()'s own dialog-open load still calls the
        # module-level load_glossary() directly; Confirm/Reject now route
        # through GlossaryCoordinator, which reloads/saves via its own
        # module's load_glossary()/save_glossary() references -- both must
        # be patched, matching each real call site.
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g)))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            confirm_btn = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Frame):
                    for sub in w.winfo_children():
                        if isinstance(sub, tk.ttk.Button) and sub.cget("text") == "Confirm":
                            confirm_btn = sub
            assert confirm_btn is not None
            confirm_btn.invoke()

            assert saved["novel_id"] == "12345"
            terms = saved["glossary"]["terms"]
            assert len(terms) == 1
            assert terms[0]["source"] == "鉄パイプ"
            assert terms[0]["status"] == STATUS_CONFIRMED
            assert terms[0]["confirmed_target"] == "iron pipe"
        finally:
            root.destroy()

    def test_confirm_with_edited_target_uses_edited_value_not_candidate(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        saved = {}

        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: saved.update(glossary=dict(g)))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            target_entry = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Entry):
                    target_entry = w
            assert target_entry is not None
            target_entry.delete(0, "end")
            target_entry.insert(0, "steel pipe")

            confirm_btn = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Frame):
                    for sub in w.winfo_children():
                        if isinstance(sub, tk.ttk.Button) and sub.cget("text") == "Confirm":
                            confirm_btn = sub
            confirm_btn.invoke()

            assert saved["glossary"]["terms"][0]["confirmed_target"] == "steel pipe"
        finally:
            root.destroy()

    def test_type_change_then_confirm_uses_new_type(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "音夢くん", "Otomu-kun")])
        saved = {}

        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: saved.update(glossary=dict(g)))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            type_combo = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Combobox):
                    type_combo = w
            assert type_combo is not None
            type_combo.set(TERM_TYPE_CHARACTER)

            confirm_btn = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Frame):
                    for sub in w.winfo_children():
                        if isinstance(sub, tk.ttk.Button) and sub.cget("text") == "Confirm":
                            confirm_btn = sub
            confirm_btn.invoke()

            confirmed = saved["glossary"]["terms"][0]
            assert confirmed["type"] == TERM_TYPE_CHARACTER
            assert confirmed["status"] == STATUS_CONFIRMED
        finally:
            root.destroy()


class TestTermReviewDialogReject:
    """Tests for the Reject action."""

    def test_reject_removes_term_entirely(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary(
            [
                make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
                make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "Me"),
            ]
        )
        saved = {}

        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: saved.update(glossary=dict(g)))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module.messagebox, "askyesno", lambda *a, **k: True)

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            reject_btn = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Frame):
                    for sub in w.winfo_children():
                        if isinstance(sub, tk.ttk.Button) and sub.cget("text") == "Reject":
                            reject_btn = sub
            assert reject_btn is not None
            reject_btn.invoke()

            remaining_sources = [t["source"] for t in saved["glossary"]["terms"]]
            assert remaining_sources == ["オレ"]
        finally:
            root.destroy()

    def test_reject_declined_confirmation_leaves_glossary_unchanged(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        save_calls = []

        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "save_glossary", lambda novel_id, g: save_calls.append(g))
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")
        monkeypatch.setattr(reader_module.messagebox, "askyesno", lambda *a, **k: False)

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            form = tree_frame.winfo_children()[-1]
            reject_btn = None
            for w in form.winfo_children():
                if isinstance(w, tk.ttk.Frame):
                    for sub in w.winfo_children():
                        if isinstance(sub, tk.ttk.Button) and sub.cget("text") == "Reject":
                            reject_btn = sub
            reject_btn.invoke()

            assert save_calls == []
            assert len(glossary["terms"]) == 1
        finally:
            root.destroy()


def _find_action_button(win, text):
    """Find the Confirm/Reject/Close button by text, same tree-walk pattern as the tests above."""
    tree_frame = win.winfo_children()[0]
    form = tree_frame.winfo_children()[-1]
    for w in form.winfo_children():
        if isinstance(w, tk.ttk.Frame):
            for sub in w.winfo_children():
                if isinstance(sub, tk.ttk.Button) and sub.cget("text") == text:
                    return sub
    for w in win.winfo_children():
        if isinstance(w, tk.ttk.Frame):
            for sub in w.winfo_children():
                if isinstance(sub, tk.ttk.Button) and sub.cget("text") == text:
                    return sub
    return None


class TestTermReviewDialogAutoRefresh:
    """Regression coverage for auto-refreshing the displayed episode after Confirm/Reject actions (DESIGN.md, 2026-07-27).

    open_term_review_dialog() writes to disk immediately on every
    Confirm/Reject (unlike open_glossary_dialog()'s batch-on-Save model),
    so debouncing to dialog-close matters even more here: a backlog
    review session confirming several terms in a row must trigger one
    refresh on Close, not one per Confirm/Reject.
    """

    def test_no_confirm_or_reject_triggers_no_refresh_on_close(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(reader_module, "save_glossary", lambda novel_id, g: None)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            close_btn = _find_action_button(win, "Close")
            assert close_btn is not None
            close_btn.invoke()

            assert harness.refresh_calls == [], "opening and closing with no Confirm/Reject must not trigger a refresh"
        finally:
            root.destroy()

    def test_multiple_confirms_in_one_session_trigger_exactly_one_refresh_on_close(self, monkeypatch):
        """The exact scenario from the task: confirming several terms in a row must fire one refresh, not one per Confirm."""
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        url = "https://www.alphapolis.co.jp/novel/12345/1/episode/1"
        glossary = _make_glossary(
            [
                make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe"),
                make_suggested_term(TERM_TYPE_CHARACTER, "オレ", "I"),
                make_suggested_term(TERM_TYPE_GENERAL, "ダンジョン能力者", "Dungeon Abiliter"),
            ]
        )
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        # GlossaryCoordinator.upsert_confirmed() reloads via its own
        # load_glossary() reference before writing -- must return the
        # SAME glossary dict the dialog itself is holding (not a fresh
        # copy) so this test's row-renumbering assumption (each Confirm
        # removes the just-confirmed term, refresh_tree() re-numbers
        # remaining rows back to iid "0") still holds against the
        # dialog's own in-memory `glossary["terms"]` mirror.
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: None)
        monkeypatch.setattr(reader_module, "_extract_novel_id", lambda url: "12345")

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url=url)
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]

            # Confirm the first row three times in a row (each Confirm
            # removes the just-confirmed term from the reviewable list and
            # refresh_tree() re-numbers remaining rows back to iid "0", so
            # selecting "0" each time reaches a fresh not-yet-confirmed
            # term, not the same one three times).
            for _ in range(3):
                tree.selection_set("0")
                tree.event_generate("<<TreeviewSelect>>")
                root.update()
                confirm_btn = _find_action_button(win, "Confirm")
                assert confirm_btn is not None
                confirm_btn.invoke()
                root.update()

            assert harness.refresh_calls == [], "no refresh should fire yet -- only on Close, not per Confirm"

            close_btn = _find_action_button(win, "Close")
            assert close_btn is not None
            close_btn.invoke()

            assert harness.refresh_calls == [url], "three Confirms followed by one Close must trigger exactly one refresh, not three"
        finally:
            root.destroy()

    def test_editing_a_different_novel_than_displayed_does_not_refresh(self, monkeypatch):
        import pyplayground.webnovels.alphapolis_reader as reader_module
        import pyplayground.webnovels.glossary_coordinator as coordinator_module

        glossary = _make_glossary([make_suggested_term(TERM_TYPE_GENERAL, "鉄パイプ", "iron pipe")])
        monkeypatch.setattr(reader_module, "load_glossary", lambda novel_id: glossary)
        # GlossaryCoordinator.upsert_confirmed() (invoked by the Confirm
        # click below) reloads/saves via its own module's references --
        # patched here too so this test's Confirm doesn't silently write
        # to the real on-disk glossary file for novel_id "12345".
        monkeypatch.setattr(coordinator_module, "load_glossary", lambda novel_id: glossary)
        monkeypatch.setattr(coordinator_module, "save_glossary", lambda novel_id, g: None)
        # Real _extract_novel_id() (not mocked to a fixed value here) so
        # the two different URLs below actually resolve to two different
        # novel_ids -- a fixed-return mock would make this test unable to
        # tell "same novel" from "different novel" and pass either way.

        root = tk.Tk()
        try:
            harness = _ReviewDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/12345/1/episode/1")
            harness.open_term_review_dialog()
            root.update()

            win = _find_toplevel_titled(root, "Review Terms")
            tree_frame = win.winfo_children()[0]
            tree = tree_frame.winfo_children()[0]
            tree.selection_set("0")
            tree.event_generate("<<TreeviewSelect>>")
            root.update()

            confirm_btn = _find_action_button(win, "Confirm")
            confirm_btn.invoke()

            # Simulate the main window switching to a different novel
            # while this dialog is still open -- the dialog itself stays
            # pinned to novel 12345 (confirmed safe in the prior
            # write-timing investigation), but the auto-refresh check
            # re-reads self.current_url at close time.
            harness.current_url = "https://www.alphapolis.co.jp/novel/99999/x/episode/1"

            close_btn = _find_action_button(win, "Close")
            close_btn.invoke()

            assert harness.refresh_calls == [], "confirming a term for novel 12345 must not refresh a differently-displayed novel (99999)"
        finally:
            root.destroy()
