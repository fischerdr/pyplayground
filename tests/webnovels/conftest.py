#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixtures for tests/webnovels/ (REFACTOR_DESIGN.md Phase 2).

Replaces the fragile hand-rolled harness pattern named in
REFACTOR_DESIGN.md's "why this started" section
(_DispatchHarness/_InterleaveHarness/_NeedsReviewAndRetranslateHarness,
and the several structurally-identical siblings found alongside them
while doing this migration -- _RenderHarness, _RightClickHarness,
_RetranslateMenuHarness, _AcceptSurvivesModeSwitchHarness): each
hand-built its own __init__ mimicking a subset of ReaderApp's/
ReaderRenderer's real attributes, rather than constructing the real
class, so a new instance attribute silently broke whichever harnesses
didn't happen to get it copied in.

fake_reader_app exposes exactly what ReaderRenderer.__init__ and its
methods actually declare they need from the app back-reference (app.root,
app.text, app.current_url, app.episode, app.open_word_glossary_popup,
app._save_settings) -- grep-confirmed against every `self.app.` call
site in ReaderRenderer before writing this, not guessed. A new
ReaderRenderer dependency on app surfaces here as a loud AttributeError/
TypeError at the fixture's own construction point (or the first call
site that touches it), not a silent, hard-to-trace failure three test
files later.
"""

import tkinter as tk

import pytest

from pyplayground.webnovels.alphapolis_reader import ReaderApp, ReaderRenderer


@pytest.fixture
def headless_text_widget():
    """Real (not withdrawn) tk.Text + root, tag_configured with the real palette.

    Deliberately NOT root.withdraw() -- a withdrawn window never gets
    real geometry in this environment (winfo_width()/height() stay at
    1x1), which makes bbox()/dlineinfo() return None for every index
    past the very first character. pack()+update() gives the widget
    real (if offscreen-in-CI-sense) dimensions so bbox-based
    click-coordinate tests are meaningful -- the exact pattern every
    prior hand-rolled harness's own _make_widget() duplicated
    independently.

    Yields (root, text); root.destroy() runs automatically on teardown
    (fixture-owned cleanup, not left to each test's own try/finally --
    every existing test in this directory previously duplicated that
    same destroy() call around its own hand-built widget).
    """
    root = tk.Tk()
    text = tk.Text(root, width=80, height=24)
    text.pack()
    text.tag_configure("heading", font=("TkDefaultFont", 12, "bold"))
    text.tag_configure("original", foreground="#333333")
    text.tag_configure("translated", foreground="#1a56c4")
    text.tag_configure("needs_review", foreground="#b45309", underline=True)
    root.update()
    yield root, text
    root.destroy()


class _FakeReaderApp:
    """Minimal ReaderApp stand-in exposing exactly ReaderRenderer's declared back-reference dependencies.

    Not a hand-copied attribute list -- these are the specific
    attributes/methods ReaderRenderer's own code reaches for via
    self.app (root, text, current_url, episode, open_word_glossary_popup,
    _save_settings), confirmed by reading ReaderRenderer's source before
    writing this class. If ReaderRenderer grows a new self.app.X
    dependency, it fails here loudly (AttributeError at the call site)
    rather than being silently absent the way a hand-rolled per-test
    harness could stay stale indefinitely.
    """

    def __init__(self, root, text_widget):
        self.root = root
        self.text = text_widget
        self.current_url = None
        self.episode = None
        self.open_word_glossary_popup_calls = []
        self.save_settings_calls = 0

    def open_word_glossary_popup(self, source_prefill, target_prefill, context=None):
        self.open_word_glossary_popup_calls.append((source_prefill, target_prefill, context))

    def _save_settings(self):
        self.save_settings_calls += 1


@pytest.fixture
def fake_reader_app(headless_text_widget):
    """A minimal object exposing exactly ReaderRenderer's declared dependencies, plus the real headless widget."""
    root, text = headless_text_widget
    return _FakeReaderApp(root, text)


@pytest.fixture
def renderer(fake_reader_app):
    """A real ReaderRenderer constructed against fake_reader_app -- not a stand-in pretending to be one."""
    return ReaderRenderer(fake_reader_app)


class _ReaderAppShell:
    """A ReaderApp-shaped object for tests exercising Group A/C/D methods together with a real ReaderRenderer.

    Covers open_word_glossary_popup, open_retranslate_popup,
    _on_text_right_click, and _prefill_for_word.

    Not a hand-rolled reimplementation -- every method is bound straight
    off the real ReaderApp class (same idiom this file's fixtures use
    throughout: construct the real thing, don't approximate it), so this
    is a genuine ReaderApp method call, just against a lighter-weight
    instance than a full live-browser ReaderApp. Exists because
    REFACTOR_DESIGN.md Phase 2 moved rendering/span-tracking state onto
    a separate ReaderRenderer component that these Group A/C/D methods
    now reach into via self.renderer -- this shell provides both a real
    ReaderRenderer and the handful of ReaderApp-owned attributes those
    methods also touch (current_url, episode, target_lang, root, text,
    the popup-tracking attributes), constructed explicitly here rather
    than duplicated per test file.
    """

    def __init__(self, root, text_widget, current_url=None, episode=None, target_lang="en"):
        self.root = root
        self.text = text_widget
        self.current_url = current_url
        self.episode = episode
        self.target_lang = target_lang
        self._glossary_popup = None
        self._retranslate_popup = None
        self._word_guess_cache = {}
        self.renderer = ReaderRenderer(self)

    def set_status(self, msg):
        pass

    def _save_settings(self):
        pass

    _on_text_right_click = ReaderApp._on_text_right_click
    _prefill_for_word = ReaderApp._prefill_for_word
    open_word_glossary_popup = ReaderApp.open_word_glossary_popup
    open_retranslate_popup = ReaderApp.open_retranslate_popup
    _open_remember_globally_popup = ReaderApp._open_remember_globally_popup


@pytest.fixture
def reader_app_shell(headless_text_widget):
    """A _ReaderAppShell (real ReaderApp methods + a real ReaderRenderer) against the shared headless widget."""
    root, text = headless_text_widget
    return _ReaderAppShell(root, text)
