# Window / Toolbar Redesign — Design Doc

Living record of decisions for this effort. Update alongside code changes,
not after — chat history is not the system of record. Fourth doc
alongside `DESIGN.md`, `RETRANSLATION_DESIGN.md`, and `REFACTOR_DESIGN.md`,
tracked separately because this is a UI reorganization plus one genuinely
new interaction capability (quick type-editing from the reading pane),
not an extension of any of the other three docs' feature scope.

Last updated: 2026-07-30

---

## Why this started

The toolbar (`< Previous`/`Next >`, four view-mode radio buttons,
`A-`/`A+`/`Dark`/`Img-`/`Img+`, and five dialog-launcher buttons —
`Load Novel...`/`Refresh`/`Glossary...`/`Review Terms...`/`Settings...`)
has grown to hold four functionally distinct categories of control in one
horizontal strip, and is visibly crowded even at the app's default
window width (screenshot-confirmed 2026-07-30). This also directly
overlaps two already-queued pickup-list items — the still-pending
four-mode-to-two-mode reduction, and the page-count/word-count status-bar
additions — all three touch the same real estate, so this doc absorbs
and resolves the mode-reduction question rather than leaving it as a
separate, later decision that would require redoing this layout work
twice.

## Decisions locked in (via discussion, before any code)

- **Menu bar added**, holding all five dialog launchers.
- **Selective button retention, not menu-only for everything**:
  `Refresh`, `Glossary...`, `Review Terms...` keep visible toolbar
  buttons *in addition to* the menu (two redundant access paths for
  frequently-used actions). `Load Novel...` and `Settings...` become
  menu-only.
- **Display controls** (`A-`/`A+`/`Dark`/`Img-`/`Img+`) move into a menu
  (a `View` menu, alongside the mode selector — see below) — confirmed
  rarely used, fine to tuck away.
- **Four-mode reduction resolved as part of this redesign**: Original
  and Both are removed. Only **Translated** (default) and **Interleaved**
  remain. This is the item that was previously on hold on the pickup
  list — now folded in here rather than tracked separately.
- **Toolbar right-click context menu**: right-clicking the toolbar
  itself surfaces the same dialog-launcher actions as a context menu.
  Primary value is restoring quick access to the now menu-only actions
  (`Load Novel...`, `Settings...`) without a full menu-bar navigation —
  worth stating this reasoning explicitly, since it's largely redundant
  for the three actions that already have visible buttons.
- **New capability: right-click "edit type" in the reading pane**, two
  distinct contexts, both in scope:
  1. **Text that's already a glossary term** (confirmed or suggested):
     a new quick action to change its `type`
     (`TERM_TYPE_CHARACTER`/`TERM_TYPE_GENERAL`) directly from the
     context menu, without opening the full Glossary or Review Terms
     dialog. This is genuinely new — no such shortcut exists today.
  2. **Text that isn't yet a glossary term**: the existing
     "Add to Glossary..." popup (`open_word_glossary_popup()`) already
     has a Type picker at creation time — this context is likely already
     covered by current behavior. Phase 1 should confirm this rather
     than assume it, and only add new logic if a real gap is found (e.g.
     if right-click currently forces a specific default type without
     giving the user the choice at the point of creation).

## Phases

Same discipline as `REFACTOR_DESIGN.md`'s Phase 3 sub-plan — investigate
real code before designing further, checkpoint each step, commit at each
checkpoint, stop and report on anything unexpected rather than pushing
forward speculatively.

### Phase 1: Investigation and concrete proposal — no code changes

Map the current toolbar construction code (widget layout, how
`view_mode` radios are wired to `ReaderRenderer`/`render_text()`'s mode
dispatch per `REFACTOR_DESIGN.md`), the existing right-click context menu
construction (`_on_text_right_click()`, already known from
`REFACTOR_DESIGN.md` Phase 2 to be a three-way hybrid not cleanly owned
by any one component), and confirm exactly what
`open_word_glossary_popup()` currently does with `type` at creation time.
Propose: the menu bar's exact structure (menu names, which action under
which menu), where in the codebase a Tk menu bar is best constructed
given the existing `ReaderApp`/`ReaderRenderer` composition split, the
mechanism for the toolbar right-click menu, and the mechanism for the
new type-quick-edit action (how it locates "is this text an existing
glossary term" — likely reusing `find_glossary_term_spans()` per
`GLOSSARY_ARCHITECTURE.md` — and what UI it uses to change type: an
inline submenu with the two type options, or a tiny picker).

**Checkpoint**: proposal appended to this doc, no code changed.

### Phase 2: Menu bar + button/mode reorganization

Build the menu bar per Phase 1's proposal. Move `Load Novel...`/
`Settings...` to menu-only. Move display controls into the `View` menu.
Reduce view-mode selection to Translated/Interleaved only, updating the
saved-preference fallback for old `"original"`/`"both"` values per the
established no-migration-needed pattern (same as prior view-mode
default changes in this project).

**Checkpoint**: live verification via `pyplayground/webnovels/ui_testing/`
— every relocated action still reachable and functional from its new
location, screenshot + log per action, `windowclose` never used.

### Phase 3: Toolbar right-click context menu

Wire the toolbar's right-click menu per Phase 1's proposal.

**Checkpoint**: live verification that right-clicking the toolbar opens
the menu and each action fires correctly.

### Phase 4: Text right-click "edit type" quick action

Implement the new quick type-change action for existing glossary terms,
and confirm (or fix, if Phase 1 found a real gap) the new-term creation
path's type selection.

**Checkpoint**: live verification — right-click an existing term, change
its type, confirm the write lands correctly via `GlossaryCoordinator`
(not a new, parallel write path — reuse the coordinator per
`REFACTOR_DESIGN.md`'s established pattern); right-click new/unrecognized
text, confirm type selection at creation still works as expected.

## Status

- **Phase 1**: complete (2026-08-01, investigation and proposal only, see
  dated entry below). No code changes.
- **Phase 2**: complete (2026-08-02, menu bar + button/mode reorganization,
  see dated entry below).
- **Phases 3-4**: not started.

### 2026-08-01: Phase 1 -- investigation and proposal (no code changes)

Confirmed all line numbers directly against the current
`alphapolis_reader.py` (3462 lines) rather than trusting
`REFACTOR_DESIGN.md`'s Phase 1 mapping, which predates Phase 3 (the
`GlossaryCoordinator` build-out) and is explicitly documented there as
drifting release to release. `GLOSSARY_ARCHITECTURE.md` (current-state
reference, last verified 2026-07-30) was used for architecture facts
directly rather than re-deriving them.

#### 1. Toolbar construction, confirmed current

Built in `ReaderApp.__init__`, `alphapolis_reader.py:1378-1410`, one
`ttk.Frame` (`toolbar`, `alphapolis_reader.py:1378-1379`) packed
`fill="x"` at the top of the window, children packed left-to-right with
`ttk.Separator` dividers marking the four functional groups:

| Widget | Line | Command | Group |
|---|---|---|---|
| `< Previous` button | 1381-1382 | `self.go_prev` | Navigation |
| `Next >` button | 1383-1384 | `self.go_next` | Navigation |
| *(separator)* | 1392 | -- | -- |
| Radiobuttons: Original/Translated/Both/Interleaved | 1393-1394 | `self.renderer._on_view_mode_change`, bound to `self.renderer.view_mode` | View mode |
| *(separator)* | 1396 | -- | -- |
| `A-` button | 1397 | `self.renderer.decrease_font` | Display controls |
| `A+` button | 1398 | `self.renderer.increase_font` | Display controls |
| `Dark` button | 1399 | `self.renderer.toggle_dark_mode` | Display controls |
| *(separator)* | 1401 | -- | -- |
| `Img-` button | 1402 | `self.renderer.decrease_image_width` | Display controls |
| `Img+` button | 1403 | `self.renderer.increase_image_width` | Display controls |
| *(separator)* | 1405 | -- | -- |
| `Load Novel...` button | 1406 | `self.open_load_url_dialog` | Dialog launcher |
| `Refresh` button | 1407 | `self.refresh_current_episode` | Dialog launcher |
| `Glossary...` button | 1408 | `self.open_glossary_dialog` | Dialog launcher |
| `Review Terms...` button | 1409 | `self.open_term_review_dialog` | Dialog launcher |
| `Settings...` button | 1410 | `self.open_settings_dialog` | Dialog launcher |

`self.renderer = ReaderRenderer(self)` is constructed at
`alphapolis_reader.py:1390`, deliberately *before* the view-mode/display
widgets that reference it (comment at 1386-1389 confirms this ordering
is intentional, not incidental) -- the toolbar wires directly into
`self.renderer.view_mode` (a `tk.StringVar`) and the renderer's own
methods as `command=` callbacks, not through any `ReaderApp`-level
indirection. This matches this doc's "Decisions locked in" section
exactly: five dialog launchers (`Load Novel...`/`Refresh`/`Glossary...`/
`Review Terms...`/`Settings...`), display controls as a separate group,
view mode as its own group. Below the toolbar: a URL bar
(`alphapolis_reader.py:1412-1417`, read-only `ttk.Entry` showing
`self.url_var`) and a status bar (`1421-1424`) docked to the window
bottom -- neither is part of the toolbar frame itself and neither is in
scope for this redesign per the doc's own framing.

Window geometry (`alphapolis_reader.py:1376`, `"1220x700"`) has its own
comment trail (1373-1375) documenting three separate widenings as
buttons were added over time (900 -> 990 -> 1090 -> 1220) purely to stop
the toolbar clipping -- concrete, in-code evidence for this doc's own
"Why this started" framing, not just the screenshot-confirmed crowding
already cited there.

#### 2. Right-click context menu, confirmed current

`_on_text_right_click()` (`alphapolis_reader.py:2703-2776`), bound at
`alphapolis_reader.py:1435` via `self.text.bind("<Button-3>", ...)`.
Confirmed still exactly the three-way hybrid `REFACTOR_DESIGN.md`'s
Phase 2 entry flagged: reads `self.renderer._span_at_index()` and
`self.renderer.view_mode` (Group B/rendering state, lines 2722, 2728,
2767, 2769), builds a `tk.Menu` with one command always present --
`Add to Glossary...` (2747), calling `self.open_word_glossary_popup()`
(Group C/glossary) -- and one command conditionally present --
`Retranslate this line...` (2771-2774), calling
`self.open_retranslate_popup()` (Group D/retranslation), gated on
`tag == "original"` and `self.renderer.view_mode.get() == "interleaved"`
(2767). The method's own comment block (2761-2766) explicitly
self-documents this as a genuine three-way dependency left on
`ReaderApp` rather than forced into `ReaderRenderer`, matching
`REFACTOR_DESIGN.md` Phase 1 section 2's finding verbatim. No new
right-click surface exists yet outside this one method -- this is the
only `<Button-3>` binding in the file (confirmed via grep for
`Button-3`/`bind.*3`).

The menu today offers exactly two actions total, never more, and never
anything toolbar-related -- there is no existing toolbar right-click
binding anywhere in the file (confirmed via grep for `toolbar.bind`);
Phase 3's toolbar context menu is genuinely new, not an extension of
this method.

#### 3. `open_word_glossary_popup()`'s `type` handling at creation time, confirmed current

`alphapolis_reader.py:2796-3031`. This case is **already fully covered
by current behavior -- no gap, no new logic needed.** Confirmed by
direct reading, not assumed:

- A `Type` field is always present in the popup's form
  (`type_row`/`type_var`, `alphapolis_reader.py:2902-2907`), rendered as
  two `ttk.Radiobutton`s (`Term` / `Character`, values `TERM_TYPE_GENERAL`/
  `TERM_TYPE_CHARACTER`), always editable by the user regardless of how
  the popup was reached (right-click "Add to Glossary..." at
  `alphapolis_reader.py:2747`, or a needs-review-span click via
  `_on_needs_review_click()` per `GLOSSARY_ARCHITECTURE.md`).
- `initial_type` (`alphapolis_reader.py:2901`) is only a *pre-selection*,
  not a forced default: `TERM_TYPE_CHARACTER` if the LLM's
  `explain_term()` classification says `"character"`, else
  `TERM_TYPE_GENERAL` -- and this pre-selection only fires when an LLM
  explanation was actually returned (LLM backend + successful lookup);
  otherwise it silently falls through to `TERM_TYPE_GENERAL` as the
  radio default, still user-editable before Save.
- `save_and_close()` (`alphapolis_reader.py:2998-3026`) reads
  `type_var.get()` at save time (line 3004,
  `make_confirmed_term(term_type=type_var.get(), ...)`) -- whatever the
  user left selected, not whatever was pre-selected, is what gets
  written.

This confirms the exact question WINDOW_REDESIGN.md's item 2 asked
Phase 1 to check ("does right-click currently force a specific default
type without giving the user the choice") -- it does not. Phase 4 needs
no new logic for the "new text, not yet a glossary term" case; that
case is already correctly handled today.

#### 4. Proposal: menu bar structure

New `tk.Menu` cascade set, constructed in `ReaderApp.__init__` right
after `self.renderer = ReaderRenderer(self)` (`alphapolis_reader.py:1390`)
and before the toolbar's own widget construction begins (1392 onward) --
the renderer must exist first since the `View` menu's items bind to
`self.renderer.view_mode`/`self.renderer.decrease_font`/etc, exactly the
same ordering constraint the toolbar itself already has today. Proposed
structure, per this doc's own "Decisions locked in" section:

- **File** menu: `Load Novel...` (`self.open_load_url_dialog`),
  separator, `Settings...` (`self.open_settings_dialog`). Both menu-only
  per the existing decision -- these two lose their toolbar buttons.
- **View** menu: the four-reduced-to-two mode selection as
  `tk.Menu`-native radio items (`add_radiobutton(variable=self.renderer.view_mode, value=..., command=self.renderer._on_view_mode_change)`,
  same variable/command the toolbar Radiobuttons use today, just a
  different widget type presenting them), separator, then the display
  controls as plain commands: `Increase Font Size`
  (`self.renderer.increase_font`), `Decrease Font Size`
  (`self.renderer.decrease_font`), `Toggle Dark Mode`
  (`self.renderer.toggle_dark_mode`), `Increase Image Width`
  (`self.renderer.increase_image_width`), `Decrease Image Width`
  (`self.renderer.decrease_image_width`). All five of these keep zero
  toolbar presence per the existing decision.
- **Glossary** menu: `Glossary...` (`self.open_glossary_dialog`),
  `Review Terms...` (`self.open_term_review_dialog`). Both also keep
  their toolbar buttons (redundant access path, per the existing
  decision) -- this menu exists so every dialog launcher is reachable
  from one place, not because these two specifically need a new access
  path.
- `Refresh` (`self.refresh_current_episode`) is the one button that
  keeps its toolbar presence but arguably doesn't need its own top-level
  menu -- proposed placement is under **File**, immediately after
  `Load Novel...` (`File > Load Novel..., Refresh, ---, Settings...`),
  since "the five dialog launchers" in this doc's own framing groups it
  with Load/Settings functionally (all three are "do something to the
  loaded novel/app," distinct from the Glossary/Review Terms pair which
  are both "open a glossary-editing surface").

This gives four menus (`File`, `View`, `Glossary`) -- three, not four;
re-counted directly against the five-launcher decision to confirm no
launcher is dropped: `Load Novel...`, `Refresh`, `Settings...` -> File;
`Glossary...`, `Review Terms...` -> Glossary. All five accounted for,
matches the "menu bar holding all five dialog launchers" decision
exactly.

Construction mechanism: `menubar = tk.Menu(root)` then
`root.config(menu=menubar)`, with each cascade built via
`tk.Menu(menubar, tearoff=0)` and `menubar.add_cascade(label=..., menu=...)`
-- the same `tk.Menu`/`tearoff=0` idiom already used for the right-click
context menu (`alphapolis_reader.py:2746`), so no new Tk pattern enters
the codebase.

**Where it lives**: `ReaderApp.__init__`, inline with the rest of the
window-shell construction (toolbar, URL bar, status bar, text widget) --
not a new method, not a new module. This matches
`REFACTOR_DESIGN.md`'s own Group A framing (window-shell construction is
core-app-shell territory) and the toolbar's own precedent (also built
inline in `__init__`, not factored into a helper). Given
`REFACTOR_DESIGN.md` Phase 5 (core app shell revisit) is explicitly
"not started, contingent on how much Phases 2-4 already shrink it" --
adding ~30-40 lines of menu construction inline is consistent with that
doc's own current scope, not a preemptive shell refactor this doc has no
mandate to do.

#### 5. Proposal: toolbar right-click menu mechanism

Bind `<Button-3>` on the `toolbar` frame itself
(`toolbar.bind("<Button-3>", self._on_toolbar_right_click)`), placed
immediately after the toolbar's own widget construction finishes
(after `alphapolis_reader.py:1410`, before `url_bar` construction
begins). New method `_on_toolbar_right_click(self, event)`, same
`tk.Menu(self.root, tearoff=0)` / `menu.tk_popup(event.x_root, event.y_root)`
shape as `_on_text_right_click()`, built as a static menu (no
span/selection resolution needed, unlike the text right-click menu --
the toolbar's context doesn't vary by click position). Per this doc's
own decision, the menu surfaces the same five dialog-launcher actions as
the new `File`/`Glossary` menus -- reusing the exact same bound
commands (`self.open_load_url_dialog`, `self.refresh_current_episode`,
`self.open_glossary_dialog`, `self.open_term_review_dialog`,
`self.open_settings_dialog`), not new wrapper functions. Placed on
`ReaderApp` (not `ReaderRenderer`) since it's a toolbar/shell-level
binding with no rendering-state dependency, same placement logic as
`open_load_url_dialog()`/`open_settings_dialog()` etc. themselves.

#### 6. Proposal: type-quick-edit mechanism for existing glossary terms

**Confirmed right reuse**: `find_glossary_term_spans()`
(`glossary.py:501`) is the correct mechanism, not an assumption --
verified against its own docstring (`glossary.py:501-527`) and
`GLOSSARY_ARCHITECTURE.md`'s description of it: it searches every
glossary term's `source` string regardless of current `status`
(deliberately, since status can change after the fact), which is
exactly "is this text an existing glossary term" -- the question this
new action needs answered, independent of confirmed/suggested state.
This differs from `build_mask_targets()` (`glossary.py:298`), which
filters to `status != STATUS_CONFIRMED` only -- wrong tool here, since a
user should be able to quick-edit the type of an already-*confirmed*
term too, not just an unconfirmed one.

Today `find_glossary_term_spans()` is only called from
`_apply_needs_review_spans()` (`alphapolis_reader.py:1089` per
`GLOSSARY_ARCHITECTURE.md`), which only tags spans on lines already
flagged `needs_review=True` -- a narrower trigger than "any text the
user right-clicks." The new action needs a second call path: given the
clicked/selected word (already resolved by `_on_text_right_click()`'s
existing selection/word-boundary logic, lines 2717-2744 -- reused
as-is, not duplicated) and `load_glossary(novel_id)`'s full term list,
call `find_glossary_term_spans()` against a single-line string
containing just that word (or check membership by calling it against
the clicked line and checking whether the clicked word's offset falls
inside a returned span) to determine "is this specific
clicked/selected text an existing term's source." Exact call shape
(whole-line span-containment check vs. a single-word lookup) is a Phase
4 implementation detail, not resolved further here -- both are cheap,
synchronous, in-memory operations against an already-loaded glossary
dict, no new data flow.

**UI mechanism**: propose a submenu, not a separate popup/picker.
`_on_text_right_click()`'s existing `menu` (`alphapolis_reader.py:2746`)
gains a conditional third item -- `menu.add_cascade(label="Change Type",
menu=type_submenu)` where `type_submenu` has two `add_command` entries
(`Term`, `Character`), each calling a new small helper (e.g.
`self._change_term_type(source, new_type)`) that constructs
`GlossaryCoordinator(novel_id).upsert_confirmed(...)` with the existing
term's `source` and all its other fields preserved except `type`. A
submenu (not a full popup window) fits this action's actual complexity:
changing `type` is a single-field edit with exactly two valid values,
the same shape `open_word_glossary_popup()`'s own Type radio buttons
already present, just without needing Source/Target/Note/reference
guesses -- opening a full popup for a one-field, two-value change would
be heavier than the action warrants, and Tk's native `add_cascade`
submenu is already the exact pattern this file uses for exactly this
"pick one of a few things" shape (e.g. this doc's own View-menu radio
items, section 4 above).

**Write path**: `GlossaryCoordinator(novel_id).upsert_confirmed(new_term)`
-- the same call `open_word_glossary_popup()`'s own Save already uses
(`alphapolis_reader.py:3023`), not a new, parallel write path, per this
doc's Phase 4 acceptance criterion and `upsert_confirmed_term()`'s own
documented dedupe-by-source-alone contract (`glossary.py:699-724`),
which is exactly the semantics a type change needs: the new entry
(same `source`, new `type`, everything else copied from the existing
term) replaces the one existing entry for that source outright,
regardless of the existing entry's own type. No new coordinator method
needed -- `upsert_confirmed()` (`glossary_coordinator.py:192`, per
`GLOSSARY_ARCHITECTURE.md`) already has the right shape for "load fresh,
upsert-by-source, save."

One real design question Phase 4 needs to resolve, not answered here:
whether changing `type` from `TERM_TYPE_GENERAL` to `TERM_TYPE_CHARACTER`
should also prompt for the character-only fields
(`gender`/`pronoun_style`/`honorific_override`, all `None` on a term
that was never a character) or leave them `None`/absent until edited
later via the full Glossary dialog. Leaving them `None` (matching
whatever `upsert_confirmed_term()`'s replace-the-whole-entry behavior
naturally does when the new term dict simply omits those keys) is the
minimal-scope option and is this proposal's default recommendation, but
is a genuine product decision, not a code-mapping fact Phase 1 can
settle unilaterally.

#### 7. Proposal: saved-preference fallback for the four-mode-to-two-mode reduction

Current state, confirmed: `self.view_mode = tk.StringVar(value=settings.get("view_mode", "translated"))`
(`alphapolis_reader.py:740`), inside `ReaderRenderer.__init__`. The
comment immediately above it (737-739) confirms the established
precedent this doc's Phase 2 description points to: when the default
changed from `"both"` to `"translated"` (`RETRANSLATION_DESIGN.md`
Phase 1), the fix was purely in the `.get(..., "translated")` fallback
*default* -- no migration of already-persisted `"both"` values was
added, since a plain `.get()` default only ever fires for a
never-before-saved key, not for a key already holding a stale value.
**That precedent does not, by itself, cover this case.** A user whose
`~/.config/alphapolis_reader/reader_state.json` (or equivalent, per
`load_reader_state()`/`update_reader_state()`) already has
`"view_mode": "original"` or `"view_mode": "both"` saved from before
this reduction will have that literal string loaded into
`self.view_mode` unchanged -- confirmed by reading `render_text()`
(`alphapolis_reader.py:1206-1230`): its `mode in ("original", "both",
"interleaved")` / `mode in ("translated", "both")` dispatch checks are
plain string membership tests with no validation against the
currently-offered radio values, so a stale `"original"`/`"both"` value
would keep rendering exactly as it does today even after the toolbar/menu
radio buttons are reduced to Translated/Interleaved only -- it would not
crash, but it would render a mode the UI no longer exposes any control
for (no radio button would show as selected), a real, if soft, bug
distinct from the "no migration needed" precedent this doc cites.

**Proposed fix**: add an explicit normalization step, not a silent
`.get()` default, since this case is "an old *value* needs remapping,"
not "a key was never saved." At the same line (740), replace the bare
`.get()` with a small inline fallback: read the saved value, and if it's
`"original"` or `"both"`, remap to `"translated"` (the existing default
target, keeping one canonical fallback rather than introducing a second
one) before constructing the `StringVar`. Concretely:

```python
saved_view_mode = settings.get("view_mode", "translated")
if saved_view_mode in ("original", "both"):
    saved_view_mode = "translated"
self.view_mode = tk.StringVar(value=saved_view_mode)
```

This is a one-time load-time remap, not a persisted migration -- the
next `_save_settings()` call (fired on the next `_on_view_mode_change()`,
`alphapolis_reader.py:1203-1204`) naturally overwrites the stale value
with whatever the user has selected from the two remaining options, so
no on-disk schema-version bump or explicit rewrite-on-load is needed,
consistent with `GLOSSARY_ARCHITECTURE.md`'s and this project's broader
"no migration shim, clean fallback" convention for settings-shaped data
(the same convention `REFACTOR_DESIGN.md` Phase 1 section 5 confirmed
for `honorific_policy`-shaped glossary fields, applied here to
`reader_state.json` instead).

#### Not done in this pass

No code changes -- confirmed via `git status`/`git diff` scope check
that only this doc changed. No implementation of the `Change Type`
submenu's character-field prompt behavior (flagged above as a genuine
Phase 4 product decision, not settled here). No decision on exact menu
accelerator keys/mnemonics (Tk supports them; not mentioned in this
doc's own locked-in decisions, so left for Phase 2 to add or skip based
on what feels appropriate once the menu bar exists for real). No
investigation of whether the toolbar's remaining post-reduction width
still needs the geometry widened/narrowed from `1220x700` -- Phase 2's
own checkpoint (live verification) is the right place to confirm actual
post-reduction layout, not a static read here.

### 2026-08-02: Phase 2 -- menu bar + button/mode reorganization

Implemented exactly Phase 1's proposal (sections 4 and 7); no design
deviation found once actually editing the code. No sub-agent delegation
used -- every step was small enough, and dependent enough on the live
verification findings below, to not benefit from parallel independent
work.

**Menu bar** (`alphapolis_reader.py:1372-1414` post-change): built
inline in `ReaderApp.__init__`, right after `self.renderer =
ReaderRenderer(self)`, exactly as proposed. Three cascades: `File`
(`Load Novel...` / `Refresh` / separator / `Settings...`), `View` (two
`add_radiobutton` items bound to the same `self.renderer.view_mode`
`StringVar` the toolbar radios use, separator, then the five display
commands as plain `add_command`s), `Glossary` (`Glossary...` /
`Review Terms...`). Confirmed via live sweep (below) that all five
original dialog launchers are reachable from the menu bar, matching the
"menu bar holding all five dialog launchers" decision.

**Toolbar** (`alphapolis_reader.py:1416-1433` post-change): `Load
Novel...` and `Settings...` removed entirely (menu-only now); the five
display-control buttons (`A-`/`A+`/`Dark`/`Img-`/`Img+`) removed
entirely (View-menu-only now); the four view-mode radios reduced to two
(`Translated`, `Interleaved`) sharing the same toolbar row as before.
`Refresh`/`Glossary...`/`Review Terms...` keep their toolbar buttons,
per the decision that these three get redundant access paths. Window
geometry (`root.geometry("1220x700")`) deliberately left unchanged --
Phase 1 flagged narrowing it as a cosmetic follow-up, not required for
every remaining control to stay reachable, and live verification
(below) confirmed nothing clips at that size now that five widgets are
gone.

**View-mode reduction and stale-value remap**
(`alphapolis_reader.py:740-758` region, `ReaderRenderer.__init__`):
implemented Phase 1's proposed explicit remap, not the simpler
"just change the `.get()` default" pattern used for the prior
both-to-translated default change -- Phase 1's own investigation found
that pattern doesn't cover an *already-persisted* stale value, only a
missing key. Concretely: `saved_view_mode = settings.get("view_mode",
"translated")`, then `if saved_view_mode in ("original", "both"):
saved_view_mode = "translated"`, then
`self.view_mode = tk.StringVar(value=saved_view_mode)`. `render_text()`'s
`mode in (...)` dispatch checks for `"original"`/`"both"` were left
in place, deliberately -- they become dead code from the UI's
perspective (no control can select those modes anymore) but several
existing tests (`test_retranslation_dialog.py`,
`test_retranslation_remember_globally.py`) call
`renderer.view_mode.set("original")` directly to exercise rendering
dispatch for a given mode value, independent of the persistence/remap
question this phase addresses; removing the dispatch branches was out
of scope and would have broken those tests for no benefit.

**Tests**: `test_retranslation_display.py`'s
`TestDefaultViewMode.test_default_view_mode_is_translated_not_both`
(the existing grep-level regression guard) updated only in its
docstring -- the source string it asserts against
(`settings.get("view_mode", "translated")`) is unchanged, since the
remap is additional code after that line, not a replacement of it. New
`TestStaleViewModeRemap` class, 5 tests: `test_stale_value_remaps_to_translated`
(parametrized over `"original"`/`"both"`), `test_current_value_translated_is_unaffected`,
`test_current_value_interleaved_is_unaffected`,
`test_missing_key_still_defaults_to_translated` (the ordinary
fresh-install case) -- each constructs a real `ReaderRenderer` against
the shared `fake_reader_app`/`headless_text_widget` fixtures
(`conftest.py`), with `load_reader_state()` mocked per-case rather than
touching the real on-disk state file. Full `tests/webnovels/` suite
(excluding `ui_automation/`, which needs a live display): **341 passed**
(up from 336 -- exactly the 5 new tests, zero regressions). With
`DISPLAY` set to a live Xvfb display and `ui_automation/` included, the
full combined run segfaults -- confirmed via isolated re-run (non-UI
suite alone, same display set: 340 passed, no segfault) that this is
the same pre-existing Python 3.14/Tk/threading/GC interaction
`REFACTOR_DESIGN.md`'s Phase 3 entries already document (two named
flaky sources: `TestFetchAndTranslateDuplicateGuard`,
`TestPopupSingleInstanceGuard`), not a new fault introduced by this
phase -- reproducing only when the full in-process Tk suite and the
separate subprocess-launching `ui_automation` suite share one pytest
session, same trigger shape as the documented cases. `black`/`isort`/
`flake8` clean on all four touched files.

**Live verification**, via `pyplayground/webnovels/ui_testing/
run_ui_tests.sh xvfb-keep` (real Xvfb+fluxbox on `:99`, `windowclose`
never used, every dialog closed via its own real button, app terminated
via `kill -TERM`/`kill -9`): every relocated action confirmed reachable
and functional from its new location, screenshot + log check per
action, all clean (no `ERROR`/`CRITICAL`):

- `File > Load Novel...` opens the same dialog as before, Cancel closes
  it cleanly.
- `File > Refresh`, `File > Settings...` both confirmed (Settings via
  screenshot showing no leftover Original/Both anywhere in the dialog).
- `View > Translated` / `View > Interleaved` radio items correctly
  drive the same `StringVar` the toolbar radios use -- selecting
  Interleaved from the menu re-rendered the episode and updated the
  toolbar's own radio button to match in the same screenshot.
- `View > Toggle Dark Mode` confirmed live (screenshot before/after
  showing the background actually change).
- `Glossary > Glossary...` and the toolbar's own `Glossary...` /
  `Review Terms...` buttons all confirmed opening their real dialogs,
  closed via their own Cancel/Close buttons.
- Text right-click context menu (Phase 3's future territory, untouched
  by this phase) reconfirmed still fires with no errors, unaffected by
  the toolbar/menu changes.
- **Stale-config live test** (the specific scenario the prompt
  required): backed up the real `~/.config/alphapolis_reader/state.json`,
  injected a literal `"view_mode": "both"` value matching a pre-Phase-2
  save, launched the app fresh against it. Screenshot confirmed
  `Translated` selected (not `Both`, which no longer has any control)
  in both the toolbar radio and the `View` menu's radio item, with the
  episode rendering only translated content -- no crash, no error, no
  silently-unselectable stale mode. Restored the original state file
  (`"view_mode": "interleaved"`) afterward.

**A real bug found and fixed during test-writing, not in the app
itself**: while adding `test_menu_dialog_opens_cleanly` to
`test_menu_smoke.py` (updating its toolbar-click coordinate map for the
new layout, since `Load Novel...`/`Settings...` lost their toolbar
buttons), the new parametrized test intermittently failed to find the
`Settings` dialog window immediately after the `Load Novel...` case ran.
Root-caused by direct reproduction, not guessed: the `Load Novel...`
case's `close` coordinate was wrong (measured against the wrong
reference frame), so its dialog never actually closed -- it stayed open
and modal-ish enough (via `win.transient(self.root)`) to block the next
test's File-menu interaction, which manifested as an unrelated-looking
"Settings dialog never appeared" failure. Fixed by re-measuring the real
Cancel button position via a live screenshot. Separately, confirmed
(and documented inline in the test) that a `tk.Menu` submenu item click
must not go through `xdo_helper.click()`, since that helper calls
`windowactivate` before every click and a `tk.Menu` installs a
pointer/keyboard grab the moment it opens -- re-activating the parent
window mid-grab silently closes the still-open dropdown instead of
clicking its item. Same principle `send_global_keys()`'s own docstring
already documents for keyboard input into a grabbed popup; applied here
to the submenu's pointer click via a plain `xdotool mousemove`+`click`
with no `windowactivate` step. Both fixes are in the test file only --
no corresponding app-code bug existed.

**Not done in this phase, deliberately**: the toolbar right-click
context menu (Phase 3) and the text right-click type-quick-edit action
(Phase 4) were not touched, per the prompt's explicit scope boundary.
No menu accelerator keys/mnemonics added (Phase 1 left this
undecided/optional; none felt necessary once the menu bar was live).
No narrowing of `root.geometry("1220x700")` -- confirmed via live
screenshots that nothing clips at the current size post-reduction, so
narrowing remains a cosmetic-only follow-up, not a correctness need.
