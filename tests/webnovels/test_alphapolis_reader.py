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
from tkinter import ttk

from pyplayground.webnovels.alphapolis_reader import ReaderApp, build_review_term_map
from pyplayground.webnovels.glossary import STATUS_CONFIRMED, TERM_TYPE_CHARACTER, TERM_TYPE_GENERAL, make_confirmed_term
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
    _apply_needs_review_spans = ReaderApp._apply_needs_review_spans
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
        """Checks via tag_ranges() rather than tag_names(start) -- see class docstring's note on the pre-existing index-offset quirk this surfaced; tag_ranges() reports what's actually tagged in the widget regardless of it.

        Span-level, not line-level (DESIGN.md's span-level highlighting
        entry): only the matched term text ("ケイト") gets tagged, not the
        whole line -- confirmed by checking the tagged text directly.
        """
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Look, ケイト! So big!", needs_review=True)]
            glossary = {"terms": [{"source": "ケイト", "type": "character", "status": "suggested"}]}

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, glossary)

            start, end, tag, source = harness._rendered_spans[0]
            assert tag == "translated"
            assert text.tag_ranges("needs_review") != ()
            assert text.get(*text.tag_ranges("needs_review")[:2]) == "ケイト"
        finally:
            root.destroy()

    def test_needs_review_span_resolves_even_after_term_confirmed_post_caching(self):
        """Critical correctness requirement: a term confirmed AFTER an episode was cached with it spliced in must still resolve for span highlighting and click on that already-cached episode.

        needs_review_flags[i]=True is a historical fact about translation
        time (DESIGN.md Section 11) -- the term's current status must not
        gate whether its span is found, unlike build_mask_targets() which
        deliberately does filter by status for its own (translation-time,
        forward-looking) purpose. See find_glossary_term_spans()'s
        docstring.
        """
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Look, ケイト! So big!", needs_review=True)]
            # The term is now STATUS_CONFIRMED -- simulating a human
            # confirming it sometime after this episode was cached with
            # the raw spliced "ケイト" still sitting in the line.
            glossary = {"terms": [{"source": "ケイト", "type": "character", "status": "confirmed", "confirmed_target": "Kate"}]}

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, glossary)

            assert text.tag_ranges("needs_review") != ()
            assert text.get(*text.tag_ranges("needs_review")[:2]) == "ケイト"

            root.update_idletasks()
            review_start = text.tag_ranges("needs_review")[0]
            bbox = text.bbox(review_start)
            assert bbox is not None

            class _FakeEvent:
                pass

            event = _FakeEvent()
            event.x, event.y = bbox[0] + 1, bbox[1] + 1
            harness._on_needs_review_click(event)

            assert harness.popup_calls == [("ケイト", "", "ケイトが振り返った。")]
        finally:
            root.destroy()

    def test_clean_line_gets_base_tag_not_needs_review(self):
        root, text = self._make_widget()
        try:
            harness = _RenderHarness(text)
            ep = {"content": [{"type": "text", "text": "ケイトが振り返った。"}]}
            translated_lines = [TranslatedLine(text="Kate turned around.", needs_review=False)]

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, {"terms": []})

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
            glossary = {"terms": [{"source": "ルリ", "type": "character", "status": "suggested"}]}

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, glossary)

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

            harness._render_translated_content_from_translated_lines(ep, "translated", translated_lines, {"terms": []})

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

    def _render_translated_content_from_translated_lines(self, ep, tag, translated_lines, glossary):
        self.render_calls.append(("needs_review_aware", ep, tag, translated_lines, glossary))

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
        """Plain strings + parallel bool flags reconstruct into the same TranslatedLine objects translate_chunk_with_masking() would have produced directly.

        Passes the full glossary dict through (not build_mask_targets()'s
        filtered/unconfirmed-only list) -- find_glossary_term_spans() needs
        every term regardless of status, see its docstring.
        """
        root, text = self._make_widget()
        try:
            mocker.patch("pyplayground.webnovels.alphapolis_reader.load_glossary", return_value={"terms": [{"source": "音夢くん", "status": "suggested"}]})
            mocker.patch("pyplayground.webnovels.alphapolis_reader._extract_novel_id", return_value="12345")

            harness = _DispatchHarness(text, current_url="https://example.com/novel/12345/x/episode/1")
            ep = {
                "translated_lines": ["Kate turned around.", "音夢くん waved."],
                "needs_review_flags": [False, True],
                "lines": ["ケイトが振り返った。", "音夢くんが手を振った。"],
            }

            harness._render_translated_view(ep, "translated")

            assert len(harness.render_calls) == 1
            kind, call_ep, tag, translated_lines, glossary = harness.render_calls[0]
            assert kind == "needs_review_aware"
            assert translated_lines == [
                TranslatedLine(text="Kate turned around.", needs_review=False),
                TranslatedLine(text="音夢くん waved.", needs_review=True),
            ]
            assert glossary == {"terms": [{"source": "音夢くん", "status": "suggested"}]}
        finally:
            root.destroy()

    def test_no_current_url_falls_back_to_empty_glossary(self):
        """No current_url set means an empty glossary is passed rather than raising -- needs_review tagging still works from persisted flags, just without any term spans to highlight."""
        root, text = self._make_widget()
        try:
            harness = _DispatchHarness(text, current_url=None)
            ep = {
                "translated_lines": ["Hello."],
                "needs_review_flags": [True],
                "lines": ["こんにちは。"],
            }

            harness._render_translated_view(ep, "translated")

            kind, call_ep, tag, translated_lines, glossary = harness.render_calls[0]
            assert glossary == {"terms": []}
        finally:
            root.destroy()


class _GlossaryDialogHarness:
    """Minimal stand-in for open_glossary_dialog()'s self-dependencies.

    open_glossary_dialog() only touches self.current_url, self.root, and
    self.set_status() (grep-confirmed) -- not a full ReaderApp, which
    requires a live browser/Playwright object to construct. The dialog's
    actual selection/form/save/delete logic runs unmodified, since
    open_glossary_dialog is bound straight off ReaderApp.

    refresh_current_episode is stubbed (records calls instead of doing a
    real network fetch + LLM translation) -- _maybe_refresh_after_glossary_edit()
    is the real ReaderApp method, unmodified, so the auto-refresh
    trigger/gating logic under test is real; only the expensive operation
    it would ultimately call is replaced with a spy.
    """

    def __init__(self, root, current_url):
        self.root = root
        self.current_url = current_url
        self.status_calls = []
        self.refresh_calls = []

    def set_status(self, msg):
        self.status_calls.append(msg)

    def refresh_current_episode(self):
        self.refresh_calls.append(self.current_url)

    open_glossary_dialog = ReaderApp.open_glossary_dialog
    _maybe_refresh_after_glossary_edit = ReaderApp._maybe_refresh_after_glossary_edit


class TestGlossaryDialogSelection:
    """Regression coverage for the stale-form-on-row-switch bug (DESIGN.md, 2026-07-27).

    Root cause: on_select_with_commit() ran commit_selected_form() (to save
    in-progress form edits before switching rows) using a fresh
    tree.selection() read. But <<TreeviewSelect>> fires *after* Tk has
    already updated tree.selection() to the newly clicked row -- so
    commit_selected_form() was saving the still-on-screen PREVIOUS term's
    field values into the NEWLY selected row's term dict, corrupting it,
    before build_form() ever ran. The form then displayed that
    just-corrupted term, which looked identical to "the form didn't
    refresh." Fixed by tracking which row's data the form was actually
    built from (`displayed_index`) instead of re-deriving it from
    tree.selection() at commit time.

    These tests drive the dialog through real Tk widgets and real
    <<TreeviewSelect>> events (tree.selection_set() triggers the same
    virtual event a real click does -- confirmed against Tk directly before
    writing these), not by calling the closures' Python names directly
    (they're not attributes of anything reachable from outside
    open_glossary_dialog()).
    """

    def _make_glossary(self):
        return {
            "title": "Test Novel",
            "honorific_policy": "keep",
            "terms": [
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="ハードキャッチ", target="demanding catch"),
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="オレ", target="Me"),
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
            ],
        }

    def _open_dialog(self, mocker, glossary):
        mocker.patch("pyplayground.webnovels.alphapolis_reader.load_glossary", return_value=glossary)
        save_calls = []
        mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.save_glossary",
            side_effect=lambda novel_id, g: save_calls.append((novel_id, dict(g, terms=[dict(t) for t in g["terms"]]))),
        )
        mocker.patch("pyplayground.webnovels.alphapolis_reader._extract_novel_id", return_value="375266002")

        root = tk.Tk()
        harness = _GlossaryDialogHarness(root, current_url="https://www.alphapolis.co.jp/novel/375266002/x/episode/1")
        harness.open_glossary_dialog()
        root.update()

        win = root.winfo_children()[0]
        tree = None
        form_container = None
        for body in win.winfo_children():
            for child in body.winfo_children():
                if isinstance(child, ttk.Treeview):
                    tree = child
                elif isinstance(child, ttk.Frame):
                    form_container = child
        assert tree is not None, "Treeview not found in dialog"
        assert form_container is not None, "form Frame not found in dialog"
        return root, win, tree, form_container, save_calls

    def _form_values(self, form_container):
        """Read the current Source/Target/Note entry widgets' text, in grid order."""
        values = {}
        for widget in form_container.winfo_children():
            info = widget.grid_info()
            row = info.get("row")
            if isinstance(widget, ttk.Entry) and row in (1, 2, 3):
                label = {1: "source", 2: "target", 3: "note"}[row]
                values[label] = widget.get()
        return values

    def test_selecting_a_row_populates_form_with_its_own_data(self, mocker):
        root, win, tree, form_container, _ = self._open_dialog(mocker, self._make_glossary())
        try:
            tree.selection_set("0")
            root.update()
            values = self._form_values(form_container)
            assert values["source"] == "ハードキャッチ"
            assert values["target"] == "demanding catch"
        finally:
            root.destroy()

    def test_switching_selection_refreshes_form_to_new_row(self, mocker):
        """The bug: after selecting row 0 then row 1, the form kept showing row 0's data."""
        root, win, tree, form_container, _ = self._open_dialog(mocker, self._make_glossary())
        try:
            tree.selection_set("0")
            root.update()
            assert self._form_values(form_container)["source"] == "ハードキャッチ"

            tree.selection_set("1")
            root.update()
            values = self._form_values(form_container)
            assert values["source"] == "オレ", f"form still showing stale previous row's data: {values}"
            assert values["target"] == "Me"
        finally:
            root.destroy()

    def test_multiple_sequential_selections_each_refresh_correctly(self, mocker):
        """Selecting several rows in a row -- not just a single before/after pair."""
        root, win, tree, form_container, _ = self._open_dialog(mocker, self._make_glossary())
        try:
            expected = [
                ("0", "ハードキャッチ", "demanding catch"),
                ("1", "オレ", "Me"),
                ("2", "鉄パイプ", "iron pipe"),
                ("0", "ハードキャッチ", "demanding catch"),
                ("2", "鉄パイプ", "iron pipe"),
            ]
            for iid, expected_source, expected_target in expected:
                tree.selection_set(iid)
                root.update()
                values = self._form_values(form_container)
                assert values["source"] == expected_source, f"selecting iid={iid}: got {values}"
                assert values["target"] == expected_target
        finally:
            root.destroy()

    def test_select_a_then_b_then_edit_then_save_writes_to_b_not_a(self, mocker):
        """The exact data-corruption scenario this bug enabled.

        Select row A (ハードキャッチ), select row B (オレ) -- triggering the
        stale-form bug pre-fix -- then edit the form and Save. Before the
        fix, B's term dict would already have been corrupted with A's data
        by the selection-change handler itself, and the edit would land on
        top of that corruption rather than on B's real data.
        """
        root, win, tree, form_container, save_calls = self._open_dialog(mocker, self._make_glossary())
        try:
            tree.selection_set("0")
            root.update()

            tree.selection_set("1")
            root.update()

            values_before_edit = self._form_values(form_container)
            assert values_before_edit["source"] == "オレ"
            assert values_before_edit["target"] == "Me"

            for widget in form_container.winfo_children():
                info = widget.grid_info()
                if isinstance(widget, ttk.Entry) and info.get("row") == 2:
                    widget.delete(0, "end")
                    widget.insert(0, "I")

            for child in win.winfo_children():
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button) and btn.cget("text") == "Save":
                        btn.invoke()
                        break

            assert len(save_calls) == 1
            _novel_id, saved_glossary = save_calls[0]
            saved_terms = {t["source"]: t for t in saved_glossary["terms"]}

            assert "オレ" in saved_terms
            assert saved_terms["オレ"]["confirmed_target"] == "I", "edit should have landed on row B (オレ), not row A"
            assert "ハードキャッチ" in saved_terms
            assert saved_terms["ハードキャッチ"]["confirmed_target"] == "demanding catch", "row A must be unaffected by the edit made after switching to row B"
        finally:
            root.destroy()

    def test_fast_sequential_selection_no_pause_still_refreshes_correctly(self, mocker):
        """Race-hypothesis check: select A then immediately B with no intervening idle time.

        build_form()/on_select() do no threaded/background work (grep-
        confirmed -- no threading.Thread() call in this code path, unlike
        rebuild_glossary()'s worker thread elsewhere in the same dialog), so
        there's no slow work for a later selection's callback to race
        against. This test exercises that directly: two selection_set()
        calls back-to-back before any root.update() runs, then a single
        update() flushes both queued virtual events.
        """
        root, win, tree, form_container, _ = self._open_dialog(mocker, self._make_glossary())
        try:
            tree.selection_set("0")
            tree.selection_set("1")
            tree.selection_set("2")
            root.update()

            values = self._form_values(form_container)
            assert values["source"] == "鉄パイプ", f"fast sequential selection landed on stale data: {values}"
            assert values["target"] == "iron pipe"
        finally:
            root.destroy()

    def test_delete_removes_the_currently_selected_row_not_a_stale_one(self, mocker):
        """Delete-selected-row check (task step 5): verify it deletes the actually-selected row.

        delete_selected() reads tree.selection() directly from a button
        click (not from the <<TreeviewSelect>> handler), so it is not
        subject to the same "event fires after Tk already advanced the
        selection" race that broke commit_selected_form() -- a button click
        is a separate event from the selection change that preceded it, and
        tree.selection() at click time already correctly reflects the
        clicked row. This test verifies that behavior directly rather than
        assuming it from the code-reading argument alone.
        """
        root, win, tree, form_container, _ = self._open_dialog(mocker, self._make_glossary())
        try:
            tree.selection_set("0")
            root.update()
            tree.selection_set("1")
            root.update()

            for child in win.winfo_children():
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button) and btn.cget("text") == "Delete":
                        btn.invoke()
                        break

            remaining_iids = tree.get_children()
            remaining_sources = [tree.item(iid, "values")[0] for iid in remaining_iids]

            assert "オレ" not in remaining_sources, "Delete should have removed the selected row (オレ)"
            assert "ハードキャッチ" in remaining_sources
            assert "鉄パイプ" in remaining_sources
        finally:
            root.destroy()


def _find_button_by_text(win, text):
    """Recursively search a dialog's widget tree for a ttk.Button with the given text."""
    for child in win.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


class TestGlossaryDialogAutoRefresh:
    """Regression coverage for auto-refreshing the displayed episode after a glossary edit (RETRANSLATION_DESIGN.md-adjacent DESIGN.md entry, 2026-07-27).

    Both open_glossary_dialog() and open_term_review_dialog() write to
    disk but the currently-displayed episode's rendered content
    (needs_review flags, span highlighting) is computed and cached at
    translation time, not re-derived live from current glossary state on
    render -- so "auto-refresh" can only mean re-triggering
    refresh_current_episode() (confirmed by reading it: a full
    cache-evict + re-fetch + re-translate, not a cheap re-render).
    Deliberately debounced to dialog-close, not per-edit, so confirming
    several terms in one Review Terms session doesn't fire several
    expensive passes. Deliberately scoped to same-novel-as-displayed,
    checked at close time (not dialog-open time), and to "at least one
    edit actually happened" -- opening and closing with no changes must
    not trigger anything.
    """

    def _make_glossary(self):
        return {
            "title": "Test Novel",
            "honorific_policy": "keep",
            "terms": [
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="ハードキャッチ", target="demanding catch"),
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="オレ", target="Me"),
            ],
        }

    def _open_glossary_dialog(self, mocker, glossary, current_url):
        # _extract_novel_id() is a pure regex parse (NOVEL_ID_RE) -- not
        # mocked, since real /novel/{id}/ URLs already exercise it
        # correctly without needing a stub, including the
        # different-novel-than-displayed case (two different real URLs).
        mocker.patch("pyplayground.webnovels.alphapolis_reader.load_glossary", return_value=glossary)
        mocker.patch("pyplayground.webnovels.alphapolis_reader.save_glossary")

        root = tk.Tk()
        harness = _GlossaryDialogHarness(root, current_url=current_url)
        harness.open_glossary_dialog()
        root.update()
        win = root.winfo_children()[0]
        return root, harness, win

    def test_no_edits_triggers_no_refresh_on_cancel(self, mocker):
        root, harness, win = self._open_glossary_dialog(mocker, self._make_glossary(), "https://www.alphapolis.co.jp/novel/375266002/x/episode/1")
        try:
            cancel_btn = _find_button_by_text(win, "Cancel")
            assert cancel_btn is not None
            cancel_btn.invoke()

            assert harness.refresh_calls == [], "opening and closing with no edits must not trigger a refresh"
        finally:
            root.destroy()

    def test_save_with_edit_triggers_exactly_one_refresh(self, mocker):
        url = "https://www.alphapolis.co.jp/novel/375266002/x/episode/1"
        root, harness, win = self._open_glossary_dialog(mocker, self._make_glossary(), url)
        try:
            save_btn = _find_button_by_text(win, "Save")
            assert save_btn is not None
            save_btn.invoke()

            assert harness.refresh_calls == [url], "a Save that wrote to disk must trigger exactly one refresh of the displayed episode"
        finally:
            root.destroy()

    def test_editing_a_different_novel_than_displayed_does_not_refresh(self, mocker):
        """The dialog was opened for novel 375266002 (dialog_novel_id resolved from current_url at open time), but the main window's current_url changes to a different novel before Save -- Save must not refresh the now-displayed different novel."""
        root, harness, win = self._open_glossary_dialog(mocker, self._make_glossary(), "https://www.alphapolis.co.jp/novel/375266002/x/episode/1")
        try:
            # Simulate the main window switching to a different novel while
            # this dialog is still open -- both dialogs pin novel_id at
            # open time (confirmed in the prior write-timing investigation),
            # so the dialog keeps operating on 375266002's glossary, but
            # the auto-refresh check re-reads self.current_url at close
            # time and must see it no longer matches.
            harness.current_url = "https://www.alphapolis.co.jp/novel/999999999/x/episode/1"

            save_btn = _find_button_by_text(win, "Save")
            save_btn.invoke()

            assert harness.refresh_calls == [], "editing novel 375266002's glossary must not refresh a differently-displayed novel (999999999)"
        finally:
            root.destroy()


class TestGlossaryDialogMergeOnDivergence:
    """Regression coverage for the cross-dialog stale-overwrite bug (DESIGN.md, 2026-07-27 -- fixed in this entry).

    open_glossary_dialog() loads a snapshot once at open time and only
    writes on Save; open_term_review_dialog() writes immediately per
    Confirm/Reject. If both are open on the same novel, a stale Save
    from the Glossary dialog used to silently overwrite whatever the
    Review Terms dialog had written in the meantime -- confirmed real
    via live xdotool reproduction, documented in DESIGN.md. Fixed by
    having save_and_close() reload the glossary fresh immediately before
    writing, compare `updated_at` against what was loaded at open time,
    and merge by `source` instead of blindly overwriting when they
    diverge -- critically, only letting this dialog's copy win for
    sources it actually edited this session (`edited_sources`), not
    every source merely present in its stale in-memory snapshot (a bug
    in the merge logic itself, caught during live re-verification: an
    early version applied the dialog's full local snapshot on divergence
    and silently reverted the untouched concurrent term right back,
    reproducing the original bug through the merge path).

    These tests simulate the concurrent writer by having the mocked
    load_glossary() return a different (already-diverged) dict on the
    dialog's second call (Save-time reload) than on its first (dialog-open
    load) -- the same effect as another dialog/process writing to the file
    in between, without needing two real Tk dialogs open at once.
    """

    def _make_glossary_at_open(self):
        return {
            "title": "Test Novel",
            "honorific_policy": "keep",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "terms": [
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
                {
                    "type": "character",
                    "source": "ハードキャッチ",
                    "candidates": [{"target": "Hard Catch", "count": 1, "origin": "llm"}],
                    "confirmed_target": None,
                    "status": "suggested",
                    "note": None,
                },
            ],
        }

    def _make_glossary_after_concurrent_confirm(self):
        """The same glossary, but as if open_term_review_dialog() had confirmed ハードキャッチ in the meantime -- a later updated_at, ハードキャッチ now confirmed."""
        return {
            "title": "Test Novel",
            "honorific_policy": "keep",
            "updated_at": "2026-01-01T00:05:00+00:00",
            "terms": [
                make_confirmed_term(term_type=TERM_TYPE_GENERAL, source="鉄パイプ", target="iron pipe"),
                make_confirmed_term(term_type=TERM_TYPE_CHARACTER, source="ハードキャッチ", target="Hard Catch"),
            ],
        }

    def test_concurrent_confirm_survives_a_save_that_edited_an_unrelated_term(self, mocker):
        """The exact original reproduction: edit 鉄パイプ, Save -- ハードキャッチ's concurrent Confirm must survive, not revert."""
        url = "https://www.alphapolis.co.jp/novel/375266002/x/episode/1"
        load_glossary_mock = mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.load_glossary",
            side_effect=[self._make_glossary_at_open(), self._make_glossary_after_concurrent_confirm()],
        )
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.save_glossary",
            side_effect=lambda novel_id, g: saved.update(novel_id=novel_id, glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url=url)
            harness.open_glossary_dialog()
            root.update()
            win = root.winfo_children()[0]

            tree = None
            for body in win.winfo_children():
                for child in body.winfo_children():
                    if isinstance(child, ttk.Treeview):
                        tree = child
            assert tree is not None

            # Select and edit 鉄パイプ (row 0) -- an unrelated term to the
            # concurrently-confirmed ハードキャッチ (row 1), matching the
            # original live reproduction sequence exactly.
            tree.selection_set("0")
            root.update()

            form_container = None
            for body in win.winfo_children():
                for child in body.winfo_children():
                    if isinstance(child, ttk.Frame) and child is not win.winfo_children()[0]:
                        form_container = child
            for widget in form_container.winfo_children():
                info = widget.grid_info()
                if isinstance(widget, ttk.Entry) and info.get("row") == 2:
                    widget.delete(0, "end")
                    widget.insert(0, "iron pipe EDITED")

            save_btn = _find_button_by_text(win, "Save")
            assert save_btn is not None
            save_btn.invoke()

            assert load_glossary_mock.call_count == 2, "save_and_close() must reload the glossary fresh before writing, not rely solely on the open-time snapshot"
            saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}

            assert saved_terms["鉄パイプ"]["confirmed_target"] == "iron pipe EDITED", "the edit made in this dialog must still be applied"
            assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED, "the concurrent Confirm must survive this Save, not be reverted back to suggested"
            assert saved_terms["ハードキャッチ"]["confirmed_target"] == "Hard Catch"
        finally:
            root.destroy()

    def test_no_divergence_saves_normally_without_merging(self, mocker):
        """When updated_at hasn't changed between open and Save, no merge branch should be needed -- plain overwrite is correct and sufficient."""
        url = "https://www.alphapolis.co.jp/novel/375266002/x/episode/1"
        glossary = self._make_glossary_at_open()
        mocker.patch("pyplayground.webnovels.alphapolis_reader.load_glossary", return_value=glossary)
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url=url)
            harness.open_glossary_dialog()
            root.update()
            win = root.winfo_children()[0]

            save_btn = _find_button_by_text(win, "Save")
            save_btn.invoke()

            saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
            assert saved_terms["ハードキャッチ"]["status"] == "suggested", "no concurrent change happened -- the dialog's own unedited copy should be saved as-is"
        finally:
            root.destroy()

    def test_explicit_delete_wins_over_a_concurrently_unrelated_change_even_on_divergence(self, mocker):
        """A term explicitly deleted in this dialog must stay deleted after a merge, not get resurrected from the fresher on-disk copy."""
        url = "https://www.alphapolis.co.jp/novel/375266002/x/episode/1"
        mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.load_glossary",
            side_effect=[self._make_glossary_at_open(), self._make_glossary_after_concurrent_confirm()],
        )
        saved = {}
        mocker.patch(
            "pyplayground.webnovels.alphapolis_reader.save_glossary",
            side_effect=lambda novel_id, g: saved.update(glossary=dict(g, terms=[dict(t) for t in g["terms"]])),
        )

        root = tk.Tk()
        try:
            harness = _GlossaryDialogHarness(root, current_url=url)
            harness.open_glossary_dialog()
            root.update()
            win = root.winfo_children()[0]

            tree = None
            for body in win.winfo_children():
                for child in body.winfo_children():
                    if isinstance(child, ttk.Treeview):
                        tree = child
            assert tree is not None

            # Delete 鉄パイプ (row 0) -- unrelated to the concurrently
            # confirmed ハードキャッチ (row 1).
            tree.selection_set("0")
            root.update()
            delete_btn = _find_button_by_text(win, "Delete")
            assert delete_btn is not None
            delete_btn.invoke()

            save_btn = _find_button_by_text(win, "Save")
            save_btn.invoke()

            saved_terms = {t["source"]: t for t in saved["glossary"]["terms"]}
            assert "鉄パイプ" not in saved_terms, "explicit delete must survive the merge, not be resurrected from the fresher on-disk copy"
            assert saved_terms["ハードキャッチ"]["status"] == STATUS_CONFIRMED, "the concurrent Confirm must still survive alongside the delete"
        finally:
            root.destroy()
