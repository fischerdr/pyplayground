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
- **Phase 3**: complete (2026-08-02, toolbar right-click context menu, see
  dated entry below).
- **Phase 4**: complete (2026-08-02, text right-click type-quick-edit
  action, see dated entry below). All four phases of this doc now
  complete.

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

### 2026-08-02: Phase 3 -- toolbar right-click context menu

Implemented exactly Phase 1's proposal (§5); no deviation found once
actually editing the code. No sub-agent delegation used -- the whole
phase was one small, tightly-scoped addition with no independent
sub-tasks that would have benefited from parallel work.

**Binding** (`alphapolis_reader.py:1450-1455`): `toolbar.bind("<Button-3>",
self._on_toolbar_right_click)`, placed immediately after the toolbar's
last button (`Review Terms...`) and before `url_bar` construction
begins, exactly as proposed -- confirmed the surrounding line numbers
directly before editing rather than trusting Phase 1's references,
since those had already drifted once (Phase 2 renumbered everything
from Phase 1's original citations).

**Handler** (`alphapolis_reader.py:2748-2765`, `_on_toolbar_right_click()`):
placed on `ReaderApp`, immediately before `_on_text_right_click()` for
proximity. Same `tk.Menu(self.root, tearoff=0)` / `menu.tk_popup(event.x_root,
event.y_root)` shape as `_on_text_right_click()`. Static menu, five
`add_command` entries in the same order as the `File`/`Glossary` menus
list them (`Load Novel...`, `Refresh`, `Glossary...`, `Review Terms...`,
`Settings...`), each bound to the exact same method reference the menu
bar and toolbar buttons already use (`self.open_load_url_dialog`,
`self.refresh_current_episode`, `self.open_glossary_dialog`,
`self.open_term_review_dialog`, `self.open_settings_dialog`) -- no new
wrapper functions, confirmed by grep that no new callable was
introduced anywhere in this diff.

**Tests**: none added. This phase is pure Tk event-wiring (a `<Button-3>`
bind plus a static menu of existing, already-tested command references)
with no new branching logic to unit-test -- the prompt's own checkpoint
requirements call for live verification instead, which is what actually
exercises this code path. Full `tests/webnovels/` suite (excluding
`ui_automation/`): **340 passed**, unchanged from the pre-Phase-3
baseline (confirmed by running the identical command against the prior
commit via `git stash`) -- zero regressions, and no reason to expect a
change since nothing touched by this phase has unit coverage either
before or after. (Note: Phase 2's entry cited "341" as this baseline;
re-measured directly at the tip of the Phase 2 commit and confirmed the
correct baseline is 340 -- the "341" figure came from a run that
happened to have a live `DISPLAY` set, which lets a couple of
otherwise-erroring `ui_automation`-adjacent tests execute instead, not
a real count difference. Corrected here rather than left standing.)
`black`/`isort`/`flake8` clean on the one touched file.

**Live verification**, via `pyplayground/webnovels/ui_testing/
run_ui_tests.sh xvfb-keep` (real Xvfb+fluxbox on `:99`, `windowclose`
never used, every dialog closed via its own real button, app terminated
via `kill -TERM`). Initial manual `xdotool`+screenshot attempts
appeared to show no menu opening at all -- investigated rather than
assumed broken: this was a screenshot/detection-timing artifact, not a
real failure. Confirmed by testing the detection method itself against
the known-working, unmodified text right-click menu, which showed the
identical false-negative under the same raw `xdotool search --name` +
`import -window root` approach. Switched to this project's own
established, confirmed-correct technique
(`xdo_helper.find_popup_by_name("!menu")`, polling immediately after
the click, per `agents-ui-testing.md`) and every interaction below
resolved cleanly on the first real attempt:

- Right-clicking the toolbar's empty background area (right of `Review
  Terms...`) opens the menu, screenshot-confirmed showing exactly the
  five expected items in the proposed order (`Load Novel...`,
  `Refresh`, `Glossary...`, `Review Terms...`, `Settings...`).
- All five actions exercised in one continuous sweep against a real
  cached episode: `Load Novel...` opens the same dialog as the File
  menu's entry; `Glossary...` and `Review Terms...` open their real
  dialogs (screenshots match the File/Glossary-menu-triggered versions
  from the Phase 2 entry exactly); `Settings...` opens with no leftover
  Original/Both anywhere; `Refresh` genuinely deleted the cached
  episode and re-fetched/re-translated it for real against the live
  `alphapolis.co.jp` URL (log shows the full real fetch -> parse ->
  translate -> re-display cycle completing, `08:19:35` to `08:21:05`,
  one `WARNING` for an expected/documented sentinel-splice case, zero
  `ERROR`/`CRITICAL`) -- confirmed as a genuinely different, heavier
  verification than Phase 2's synthetic-fixture-only sweep, since this
  ran against this session's live novel. Each of the five actions
  individually confirmed via `log_correlator.assert_clean()` against
  its own action-time window, plus one final whole-session sweep across
  the entire log file: zero `ERROR`/`CRITICAL` lines from start to
  finish.
- **Text right-click menu reconfirmed unaffected**: same
  `find_popup_by_name()` technique, right-clicking translated text
  (Interleaved mode) opened the expected two-item menu (`Add to
  Glossary...`, `Retranslate this line...`), log clean -- this phase's
  toolbar binding is a separate widget (`toolbar`, not `self.text`)
  with its own independent `<Button-3>` binding, so no interference was
  expected, and none was found.

**Not done in this phase, deliberately**: the text right-click
type-quick-edit action (Phase 4) was not touched, per the prompt's
explicit scope boundary. No new wrapper functions or menu-construction
helpers introduced -- the five `add_command` calls are inline in
`_on_toolbar_right_click()`, matching `_on_text_right_click()`'s own
inline-construction style rather than introducing a shared "build my
five dialog-launcher menu items" helper Phase 1 never proposed.

### 2026-08-02: Phase 4 -- investigation for the type-quick-edit action (no code changes)

Investigates the two open questions Phase 4's implementation needs
answered before design work starts: whether the character-only fields
(`gender`/`pronoun_style`/`honorific_override`) are actually consumed
anywhere today (relevant because the "edit type" action changes a term's
`type` from `TERM_TYPE_GENERAL` to `TERM_TYPE_CHARACTER` or back, and
Phase 1's proposal left open whether that transition should also prompt
for these fields -- see Phase 1's §6, "one real design question Phase 4
needs to resolve"), and whether an existing honorific-suffix detector
could be reused rather than built fresh for that same transition. Grep
was used throughout, not absence-from-docs -- confirmed the hard way
after `GLOSSARY_ARCHITECTURE.md`'s own refresh (done immediately before
this investigation) initially assumed these fields were display-only and
had to be corrected once `format_glossary_for_prompt()` was actually
read, not just grepped for a keyword match. No sub-agent delegation used
-- this is a single, self-contained grep-and-read investigation with no
independent sub-tasks.

**Question 1: are `gender`/`pronoun_style`/`honorific_override` read
anywhere?**

```bash
grep -n "\bgender\b" pyplayground/webnovels/*.py
grep -n "pronoun_style" pyplayground/webnovels/*.py
grep -n "honorific_override" pyplayground/webnovels/*.py
```

**Yes -- all three are read, and load-bearing for live translation
output, not display-only.** `format_glossary_for_prompt()`
(`glossary.py:262`, specifically lines `311-315`) reads all three for
`TERM_TYPE_CHARACTER` entries and appends whichever are non-empty as
short parenthetical detail after the term's name mapping in the prompt
text sent to the model on every LLM-backend translation call (e.g.
`- ケイト -> Kate (female, keep honorific)`). `honorific_override` falls
back to the glossary's novel-wide `honorific_policy` when unset per term,
and is only appended if the resolved value isn't `"drop"`. This is the
*only* real consumer found -- confirmed by checking every other match
`grep` returned:

- `build_glossary.py`: all matches are either extraction-prompt text
  (asking the LLM to *produce* `gender`/`pronoun_style` values for
  character entries it extracts, `build_glossary.py:70-118`) or
  `_to_suggested_term_dicts()` (`build_glossary.py:305-337`) carrying the
  three fields over from raw extraction output into the suggested-term
  shape -- a write path into the term dict, not a read/consumer of an
  already-confirmed term's fields.
- `glossary.py`: the module docstring (lines 16-19, 53) describing the
  shape, the term dict shape itself (lines 65-77), and
  `format_glossary_for_prompt()` (the one real consumer, above).
- `llm_translate.py`: every match is unrelated -- comments/prompt text
  for `explain_term()`'s *own*, separate feature (telling the model not
  to assert a character's gender as fact when explaining a term's
  meaning, `llm_translate.py:692-714`), not a read of a glossary term
  dict's `gender` field at all. Checked directly: `explain_term()`
  never touches `glossary.py` or reads a term dict.
- `alphapolis_reader.py`: every match is inside the term-editing dialogs
  themselves (`open_glossary_dialog()`'s form-building/writing code,
  roughly lines 2100-2300, and `open_word_glossary_popup()`'s character
  fields, roughly lines 2980-3080) -- these are the UI that *writes*
  these fields when a human edits a character term, not a second
  consumer.

Confirmed via a second, narrower grep specifically excluding the
dialog-code line ranges, to be certain nothing else was missed:

```bash
grep -n "gender\|pronoun_style\|honorific_override" pyplayground/webnovels/alphapolis_reader.py | grep -v "^23[0-9][0-9]\|^26[0-9][0-9]\|^29[0-9][0-9]\|^30[0-9][0-9]\|^21[0-9][0-9]"
```

Returned only the dialog form-writing lines already accounted for above
-- nothing in rendering (`ReaderRenderer`'s methods) or anywhere else in
`alphapolis_reader.py` reads these fields.

**Implication for Phase 4's open design question**: since these three
fields are genuinely translation-load-bearing (not cosmetic), prompting
for them when a term transitions from `TERM_TYPE_GENERAL` to
`TERM_TYPE_CHARACTER` via the type-quick-edit action is a more
substantive product decision than Phase 1's proposal framed it as --
leaving them `None`/absent after a type change means the term's
translation-prompt entry silently loses the character-specific detail a
full "Add Character" flow would have captured, not just an empty display
field in a dialog nobody's currently looking at. This raises the
practical weight of "leave them None, matching upsert's natural
replace-the-whole-entry behavior" as the minimal-scope default (still
Phase 1's recommendation) versus "prompt for them inline" -- both remain
live options, this investigation only corrects the premise the tradeoff
was being judged against.

**Question 2: does anything already detect an honorific suffix adjacent
to a name/term in source text?**

```bash
grep -n "さん\|くん\|ちゃん\|様\|-san\|-kun\|-chan\|-sama\|honorific.*suffix\|suffix.*honorific" pyplayground/webnovels/*.py
```

**No structured per-name honorific-suffix detector exists anywhere.**
Every real match falls into one of three unrelated categories, checked
individually:

- **`explain_term()`'s prompt** (`EXPLAIN_TERM_PROMPT`,
  `llm_translate.py:702-722`, specifically lines 711-714) instructs the
  model to *use* honorific evidence (e.g. "-kun/-chan/-san, how other
  characters address them") when judging whether an *alternative name
  translation's connotation* is gender-consistent -- a soft, prose-level
  instruction inside a free-text prompt, not a structured output. The
  function's actual return shape (`category`/`meaning`/`characters`/
  `alternatives`) has no honorific-related key at all -- confirmed by
  reading the function's full body and return statement
  (`llm_translate.py:777-782`), not just the prompt text.
- **`build_glossary.py`'s extraction prompt** asks for one **novel-wide**
  `honorific_policy_suggestion` (`build_glossary.py:75-80, 101, 116-117`,
  one of the fixed `HONORIFIC_POLICIES` values `["keep", "drop",
  "romanize"]`, `glossary.py:143`) -- an aggregate judgment about which
  convention the *whole novel* generally uses, not a per-term/per-name
  detection tied to a specific occurrence in source text. This is a
  different question shape entirely from "does this specific name have
  an honorific suffix attached right here."
- **`test_sentinel_survival*.py`** matches (e.g. `るりちゃん`,
  `音夢くん`) are masking-sentinel-survival test fixtures confirming that
  an honorific-attached name masks/splices correctly as a single literal
  string -- not detection logic, just test data that happens to contain
  an honorific suffix as part of the literal text being masked.
- **`honorific_override` itself is never actually populated by
  extraction**, confirmed by reading `_to_suggested_term_dicts()`
  (`build_glossary.py:332-335`) directly: it does `term["honorific_override"]
  = raw.get("honorific_override")`, but the extraction prompt's own
  worked example and field-description text
  (`build_glossary.py:88-105, 113-117`) never asks the model to produce
  an `honorific_override` key per term at all -- only `type`/`source`/
  `target`/`note`/`gender`/`pronoun_style` for a character entry, plus
  the one separate novel-wide `honorific_policy_suggestion`. In practice
  `raw.get("honorific_override")` always evaluates to `None` for
  LLM-extracted suggested terms; only a human manually editing the field
  in a dialog ever sets it to a real value. Confirmed this is a genuine,
  pre-existing gap (not something this investigation needs to fix) --
  worth knowing for Phase 4 since it means "detect an honorific suffix
  to pre-fill `honorific_override`" would be new work, not a matter of
  wiring up dead code that already computes the answer.

**Implication for Phase 4**: if the type-quick-edit action (or any
future work) wants to pre-fill `honorific_override` or offer an
honorific-aware suggestion at the moment of turning a term into a
character, that detection logic does not exist yet in any form --
neither a regex/string-based suffix matcher nor a structured LLM-output
field. It would be new work, either a narrow regex check against a
small, known suffix list (cheap, deterministic, no network/model call)
or a new structured field added to one of the two existing LLM prompts
(`EXPLAIN_TERM_PROMPT` already has the closest-adjacent context --
`context` is passed in for exactly this kind of judgment -- but would
need its return shape extended). Neither approach is started; this is a
finding to inform Phase 4's design, not a recommendation between them.

**Not done in this pass**: no code changes, no design decision made on
either open question above -- both are left for Phase 4's actual
implementation to decide, informed by these findings. No investigation
into how the type-quick-edit action's submenu itself will be built (that
mechanism was already proposed in Phase 1 §6 and re-confirmed correct
there; this investigation only covers the two questions the prompt
specifically asked for).

### 2026-08-02: Phase 4 investigation addendum -- source-language assumptions (no code changes)

Continuation of the entry directly above, same investigation session.
Three further questions, asked specifically to determine whether any
per-term honorific auto-detection work Phase 4 might attempt is actually
safe to build language-agnostically today, or whether it would be
building on (or masking) a hidden Japanese-only assumption elsewhere in
the pipeline. No design proposal made here, per the prompt's own
instruction -- findings only. No sub-agent delegation used, same
reasoning as the entry above (single self-contained grep-and-read task).

**Question 1: is there a per-novel/per-episode source-language field
anywhere?**

```bash
grep -n "language\|\blang\b\|source_lang\|target_lang" pyplayground/webnovels/glossary.py
```

No structured field -- every match is prose in a docstring/comment
referring to "source language" generically (`glossary.py:96, 124, 145,
274, 505, 609`), never a persisted dict key.

Confirmed directly against the actual persisted shapes, not inferred
from the grep above alone:

- **Glossary file** (`_empty_glossary()`, `glossary.py:161-187`): full
  field list is `novel_id`, `title`, `honorific_policy`,
  `honorific_policy_user_set`, `terms`, `context_notes`, `updated_at`,
  `extracted_episode_urls`. No `language`/`source_lang` field.
- **Episode cache** (`parse_episode()`'s return shape,
  `alphapolis_reader.py:429-436`, plus what `save_cached_episode()`
  adds, `alphapolis_reader.py:178-187`): `title`, `author`,
  `episode_title`, `lines`, `content`, `prev_url`, `next_url`, plus
  `_cache_schema_version`/`url`/`novel_id` added at save time. No
  `language`/`source_lang` field here either.
- **Reader state** (`save_reader_state()`, `alphapolis_reader.py:202-219`)
  persists `target_lang` (the *translation output* language, a real,
  user-facing setting) but has no corresponding source-language field at
  all -- confirmed by reading the function's full body, not just its
  name.

**"Japanese" is both purely implicit in most of the pipeline and
explicit in exactly one place.** Implicit: every real translation call
site relies on `source_lang`'s hardcoded default. Confirmed via:

```bash
grep -rn "source_lang" pyplayground/webnovels/*.py
```

`source_lang` **is** a real, threaded-through parameter across
`llm_translate.py` (`translate_chunk()`, `translate_chunk_with_masking()`,
`explain_term()`, `retranslate_line_with_hint()`, `translate_lines()`,
`translate_lines_with_masking()`) -- not absent, just never varied.
Every one of those functions defaults it to `source_lang: str = "ja"`,
and the actual production call path never overrides it: read
`_do_fetch_and_translate()`'s body directly
(`alphapolis_reader.py:1712-1791`) and confirmed neither of its two real
translation calls (`translate_lines_with_masking()` at line 1762,
`translate_lines()` at line 1768) passes `source_lang` at all -- both
rely entirely on the function default. `alphapolis_reader.py`'s other
three call sites (`google_guess` at line 2938, `explain_term()` at line
2952, `retranslate_line_with_hint()` at line 3256) all pass the literal
`source_lang="ja"` explicitly, hardcoded, not read from any
configuration. No UI control for source language exists anywhere --
confirmed by grep, the only "Language" controls in `alphapolis_reader.py`
are `target_lang`-related (the Settings dialog's backend/font/etc.
controls have no language selector besides the implicit target).

"Japanese" **is** explicit, though, in `LANGUAGE_NAMES`
(`llm_translate.py:118-124`): `{"ja": "Japanese", "en": "English", "ko":
"Korean", "zh": "Chinese"}`, used by `_language_name()`
(`llm_translate.py:256-265`) to resolve a language code to a display
name for prompt interpolation. This mapping already includes Chinese and
Korean entries, unused by any current call site -- the *mechanism* for
naming a different source language in a prompt already exists and isn't
Japanese-only, even though nothing currently drives it with a
non-`"ja"` value.

**Question 2: is `honorific_policy` consumed anywhere beyond the
already-known prompt-text injection?**

```bash
grep -rn "honorific_policy\b" pyplayground/webnovels/*.py
```

**No -- `format_glossary_for_prompt()` (`glossary.py:315-317`, confirmed
in the prior investigation) is the only place `honorific_policy` (or a
per-term `honorific_override`) affects anything.** Every other match is
either write-plumbing with no interpretation of the value
(`glossary_coordinator.py:99, 136, 180, 206` -- `save_snapshot()`/
`clear()` just pass the string through to the saved dict) or read
default/storage (`glossary.py:173, 194-195, 211`;
`build_glossary.py:75, 451, 494` -- the LLM *suggests* a policy value
during extraction, which just gets stored) or plain dialog `StringVar`
plumbing in `alphapolis_reader.py:2032, 2428` (Combobox display/read,
no text manipulation).

Checked specifically for any code that does literal string manipulation
on source or translated text keyed off this policy (searching/stripping/
adding honorific suffixes directly, as opposed to instructing the
model):

```bash
grep -n "honorific" pyplayground/webnovels/llm_translate.py
```

All four matches (`llm_translate.py:689, 695-696, 711, 714`) are comment
or prompt text for `explain_term()`'s unrelated classification feature
(telling the model to *use* honorific evidence when judging whether an
alternative name translation is gender-consistent) -- not literal
text manipulation, and not the `honorific_policy` mechanism at all.
Checked `mask_terms()`/`splice_terms()` (`llm_translate.py:176-224`) and
`build_mask_targets()`/`find_glossary_term_spans()`
(`glossary.py:332-420, 501-540`) directly by reading their full bodies:
none reference `honorific` in any form, and none do anything more
sophisticated than plain `str.replace()`/substring search on exact term
text -- no honorific-suffix stripping or detection logic exists in the
masking/splicing path.

**This confirms the mechanism is already language-agnostic at the code
level, with the caveat that its semantic framing is not.**
`honorific_policy`'s effect is entirely "append a short English
instruction fragment to the LLM prompt" (`glossary.py:315-317`: `"keep
honorific"`/`"drop"`/`"romanize"`, gated on the value not being
`"drop"`) -- a prompt instruction works regardless of what script or
convention the source language actually uses, since the model (not this
codebase) is what interprets it against the real source text. There is
no code path anywhere that searches source or translated strings for a
literal honorific character/suffix. The only Japanese-specific framing
is in comments/docstrings and the `HONORIFIC_POLICIES` concept's own
naming (`glossary.py:143-146`, explicitly documented as "e.g. Japanese
-san/-chan/-kun/-sama, Chinese kinship address terms" -- the docstring
itself already treats this as a general, not Japanese-only, concept).

**Question 3: does the scraping/parsing path assume a single
site/language?**

```bash
grep -n "alphapolis.co.jp\|novelBody\|p-novel-episode\|#app-cover-data" pyplayground/webnovels/alphapolis_reader.py
```

**Yes, structurally single-site -- but this is a site-selector
dependency, not itself a language assumption.** `BASE_URL`
(`alphapolis_reader.py:82`), the CSS selectors
`parse_episode()`/`BrowserWorker.fetch()` use
(`#novelBody`/`.p-novel-episode__text`/`.p-novel-episode__title`/
`.p-novel-episode__author`/`.p-novel-episode__episode-title`/
`#app-cover-data`, `alphapolis_reader.py:339, 443, 453-455, 462`), and
`_extract_novel_id()`'s URL pattern (`alphapolis_reader.py:134-144`,
matched via a single `NOVEL_ID_RE`) are all hardcoded to Alphapolis's
specific markup. No site-abstraction layer, dispatch table, or
per-site-selector-config exists -- confirmed by grep, there is exactly
one `BASE_URL` and one set of selectors in the file, and no second
scraper is wired into this pipeline. (`novelfire_library_pw.py`/
`novelfire_library.py`/`novelfire_publishgist_library.py` exist in the
same directory but are confirmed, by checking their imports directly,
to be completely standalone scripts with zero connection to
`glossary.py`/`llm_translate.py`/the reader's translation pipeline --
not a second source already wired in, and not relevant to this
question.) This confirms a second site would need real scraper work
regardless of language, which is out of this investigation's scope to
assess further -- the prompt only asked about language-specific
assumptions *past* HTML parsing.

Beyond site selectors, one real language-specific assumption exists,
already partially surfaced by the prior investigation's Question 2:
**word-boundary/tokenization logic in the click-to-add-term feature is
Japanese-specific by construction, and says so.** `ja_tokenize.py`'s own
module docstring (`ja_tokenize.py:12-16`) states this explicitly, not
discovered by inference: "Chinese is out of scope here -- MeCab/fugashi
dictionaries don't parse Chinese, and the reader has no Chinese source
pipeline today. A future Chinese equivalent (e.g. using jieba) should
live in its own function (find_zh_word_at) and be dispatched on
source_lang by the caller, not folded into this module." `find_ja_word_at()`
(`ja_tokenize.py:43-70`) is called unconditionally from
`_on_text_right_click()` (`alphapolis_reader.py:2805`), with no
`source_lang`-based dispatch -- confirmed by grep, this is the only
caller. `_is_cjk()` (`ja_tokenize.py:73-83`) checks three Unicode
ranges (Hiragana, Katakana, CJK Unified Ideographs) -- the third range
is shared between Chinese and Japanese, so it would not itself reject
Chinese characters, but the *tokenization* (fugashi/MeCab, a
Japanese-morphology dictionary) that determines word boundaries around
those characters would produce wrong boundaries for Chinese text, which
has different morpheme/word segmentation entirely. This is the one
genuine, load-bearing, already-self-documented Japanese-specific gap
found in this investigation -- everything else checked (masking,
honorific handling, prompt construction, the glossary data model) is
already mechanically source-language-agnostic.

No other character-set/language-specific handling was found -- confirmed
via a targeted grep across the whole module for any other CJK-range or
language-conditional logic:

```bash
grep -rn "_is_cjk\|is_cjk\|0x3040\|0x30A0\|0x4E00\|CJK" pyplayground/webnovels/*.py
```

All five matches are the single `_is_cjk()` definition and its one call
site inside `ja_tokenize.py` itself -- no other file references a CJK
range or does character-set-conditional logic anywhere.

**Net summary for Phase 4's design question**: the glossary/masking/
honorific mechanism itself (data model, `build_mask_targets()`,
`mask_terms()`/`splice_terms()`, `format_glossary_for_prompt()`'s prompt
construction) is already language-agnostic in code -- it would work
unmodified against a hypothetical Chinese source, since none of it does
source-language-specific string manipulation. The one real, currently-existing
Japanese-only dependency in the whole reader pipeline is
`ja_tokenize.py`'s morpheme-boundary lookup for the click-to-add-term
UI feature, and that dependency is unrelated to honorific detection --
it's about *finding what word the user clicked*, not about detecting an
honorific suffix once a word/term is already known. Building a per-term
honorific-suffix detector for Phase 4 today would not be reinforcing or
depending on any hidden Japanese-only assumption elsewhere -- the
pipeline's honorific handling is prompt-instruction-based and would
transfer to a different source language's own honorific/address-term
conventions (if any) exactly as easily as it works for Japanese today,
*if* such a detector were built generically (e.g. against a
per-source-language configurable suffix list, not a hardcoded Japanese
one) rather than assuming Japanese implicitly the way `ja_tokenize.py`
does today. Since no second source language exists in the pipeline yet
(confirmed above -- no scraper, no `source_lang` variation anywhere in
practice), there is no current evidence either for or against building
that generically today; this is a scoping input for Phase 4's design,
not a recommendation.

**Not done in this pass**: no design proposal, no decision on whether
Phase 4 should build per-term honorific detection now or scope it out
as premature -- both remain open, per the prompt's explicit instruction
not to propose a design yet. No code changes.

### 2026-08-02: Phase 4 -- text right-click type-quick-edit action (implementation)

Implemented per Phase 1's §6 proposal and the two follow-up
investigations above, with one real deviation found and fixed during
implementation (see below). No sub-agent delegation used -- this was one
self-contained feature with no independent sub-tasks.

**Trigger and menu** (`alphapolis_reader.py:2811-2841`, inside
`_on_text_right_click()`): after the existing selection/word-boundary
resolution logic (unchanged, reused as-is), `resolved_word` is derived
from `prefill` (`prefill[0] or prefill[1]` -- exactly one of the pair is
the resolved word, depending on which side of the text was clicked, per
`_prefill_for_word()`). A new helper,
`_find_glossary_term_by_source()` (`alphapolis_reader.py:2872-2903`),
looks up whether `resolved_word` is the *exact* source string of an
existing glossary term for the current novel, reusing
`find_glossary_term_spans()` as proposed -- called against the resolved
word treated as a one-word string, keeping only a match whose span
covers the word's entire length (so a word merely *containing* a
shorter existing term, e.g. clicking "音夢くん" when only "音夢" is a
term, does not trigger the action for the longer word). When a match is
found, `menu.add_cascade(label="Change Type", menu=type_submenu)` is
added as a third menu item, with `type_submenu` holding `Term` (direct
`add_command`) and `Character` (a further `add_cascade` into a Gender
submenu -- see below). When no match is found, the menu is unchanged
from before this phase (`Add to Glossary...` plus, conditionally,
`Retranslate this line...`).

**A real deviation from Phase 1's proposal, found and fixed during
implementation, not before:** Phase 1 §6 proposed
`self._change_term_type(source, new_type)` called directly from each
submenu leaf, with the General -> Character gender question resolved
via "ask the user for gender inline." The first implementation attempt
did exactly that, via a helper that opened a second `tk.Menu` with
`tk_popup()` and returned the user's pick as a function return value.
**This does not work** -- confirmed live, not assumed: `tk.Menu.tk_popup()`
is non-blocking in Tkinter (posts the menu and returns immediately; the
actual selection is delivered later via the `command=` callback on the
normal event loop), verified with a standalone reproduction script
before touching the real implementation. A synchronous "ask and get an
answer back" helper is not a shape Tk's menu system supports. Fixed by
restructuring: `Character` is a cascade to a nested Gender submenu
(`Unspecified`/`Male`/`Female`, `alphapolis_reader.py:2837-2840`), and
each of the three gender leaf commands calls `_change_term_type()`
directly with the gender value already baked in
(`gender=None`/`"male"`/`"female"`) -- same pattern every other
`tk.Menu` item in this file already uses (the answer is chosen *by*
picking the menu item, not asked for *after*). This makes the actual UI
a three-level cascade (`Change Type > Character > <gender>`) rather than
Phase 1's two-level sketch plus a separate ask -- still the same
weight-class Phase 1's proposal called for (menu picks throughout, no
popup window), just one more level deep for this one path specifically.

**`_change_term_type()`** (`alphapolis_reader.py:2906-2961`): reloads
the term fresh via `_find_glossary_term_by_source()` immediately before
writing (not trusting a snapshot from when the right-click menu was
built), matching this codebase's established reload-fresh discipline.
Builds `new_term = dict(term)` (a full copy of the existing term dict --
preserves `candidates`, `confirmed_target`, `status`, and `note`
unconditionally, confirmed live against a real `STATUS_SUGGESTED` term,
see Verification below), sets `new_term["type"] = new_type`, then:
General -> Character sets `gender` to the caller-supplied value and
explicitly sets `pronoun_style`/`honorific_override` to `None` (per the
prior investigation's finding that these are genuinely prompt-load-bearing,
not cosmetic -- gender is asked for since it has a natural quick-pick
shape, the other two are deliberately left for the full Glossary dialog,
same reasoning as Phase 1's own §6 "one real design question" note, now
resolved this way). Character -> Term (or any non-Character `new_type`)
pops all three character-only keys unconditionally, so they're absent
from the written dict entirely -- matches
`upsert_confirmed_term()`'s documented replace-the-whole-entry semantics
exactly, no merge, no partial update. Writes via
`GlossaryCoordinator(novel_id).upsert_confirmed(new_term)`
(`alphapolis_reader.py:2958`) -- the exact same call
`open_word_glossary_popup()`'s Save already uses, no new coordinator
method, confirmed by grep that no new write-path function was
introduced anywhere in this diff. Per this phase's explicit scope: no
honorific-suffix auto-detection anywhere in this code -- `honorific_override`
is never set by this action under any path, matching the investigation's
finding that no such detector exists and none was built here.

**Test harness fix, found immediately by the test suite, not live
testing:** adding the two new `ReaderApp` methods broke three existing
tests (`test_retranslation_dialog.py::TestRetranslateMenuGating`) with
`AttributeError: '_ReaderAppShell' object has no attribute
'_find_glossary_term_by_source'` -- `tests/webnovels/conftest.py`'s
`_ReaderAppShell` binds a fixed, explicit list of real `ReaderApp`
methods (by design, per `REFACTOR_DESIGN.md`'s harness-fragility fix:
a new dependency should surface as a loud `AttributeError`, not a
silent gap). Fixed by adding both new methods to that binding list
(`tests/webnovels/conftest.py`, `_find_glossary_term_by_source =
ReaderApp._find_glossary_term_by_source`, `_change_term_type =
ReaderApp._change_term_type`) -- exactly the intended, designed-for
response to this failure mode, not a workaround.

**Tests**: no new unit tests added. This phase's logic is thin
(menu construction plus a small dict-copy-and-mutate write) and its
correctness is dominated by real Tk event/menu behavior (the
`tk_popup()` non-blocking discovery above is exactly the kind of thing a
mocked-Tk unit test would not have caught) -- live verification (below)
is what actually exercises this code path, consistent with Phase 2/3's
own precedent of relying on live verification over new unit coverage
for pure UI-wiring changes. Full `tests/webnovels/` suite (excluding
`ui_automation/`): **340 passed** (unchanged from baseline, after the
conftest.py fix above -- before that fix, 3 failed). `black`/`isort`/
`flake8` clean on both touched files.

**Live verification**, via `pyplayground/webnovels/ui_testing/
run_ui_tests.sh xvfb-keep` (real Xvfb+fluxbox on `:99`, `windowclose`
never used, app terminated via `kill -TERM`). Real on-disk glossary file
(`~/.config/alphapolis_reader/glossaries/375266002.json`) backed up
before this session and fully restored afterward (confirmed via `diff`,
identical) -- all live writes below were against the real file, not a
synthetic fixture, per the checkpoint's own requirement to check the
on-disk file directly:

- Right-clicking existing chapter text with no matching glossary term
  (the English word "school") showed only the pre-existing menu items
  (`Add to Glossary...`, `Retranslate this line...`) -- confirmed no
  `Change Type` cascade appears, log clean. This is the "unrecognized
  text unaffected" checkpoint.
- Created a real, known test term (`source="Ruga"`, `type="term"`, via
  the ordinary `Add to Glossary...` popup -- itself reconfirmed working
  identically to before this phase, Type radio buttons and gender field
  behaving as always) to get a term guaranteed to be both on-disk and
  clickable in the rendered chapter text (the episode's own real cached
  terms, e.g. `鉄パイプ`/`ケイト`, don't appear in this specific
  episode's text).
- Right-clicking "Ruga" (now a known term) showed the `Change Type`
  cascade with `Term`/`Character` options; hovering `Character` revealed
  the `Unspecified`/`Male`/`Female` Gender cascade, confirmed via
  screenshot at each level.
- **General -> Character with Female**: on-disk read directly afterward
  confirmed `type: "character"`, `gender: "female"`, `pronoun_style:
  null`, `honorific_override: null`, with `candidates`/`confirmed_target`/
  `status`/`note` all unchanged from the original entry. Log line
  `"Changed glossary term type via right-click for novel 375266002:
  'Ruga' -> 'character'"` present.
- **Character -> Term**: on-disk read confirmed `type: "term"` and all
  three character-only keys (`gender`/`pronoun_style`/`honorific_override`)
  completely absent from the entry (not `null` -- actually absent, since
  the dict never had them added back), other fields unchanged.
- **General -> Character with Unspecified**: on-disk read confirmed
  `type: "character"`, `gender: null` (not a string) -- confirmed the
  Unspecified option correctly writes `None`, distinct from `"male"`/`"female"`.
- **Status preservation on a real `STATUS_SUGGESTED` term**: since the
  loaded episode's text didn't contain any of the novel's real suggested
  terms to right-click directly, this was verified via a direct call
  against the same write path (`GlossaryCoordinator(novel_id).upsert_confirmed()`
  with a `dict(term)`-copied, type-mutated `鉄パイプ` entry, the actual
  real suggested term already in this novel's glossary) rather than
  skipped -- confirmed `status: "suggested"` and `confirmed_target: null`
  survive a type change unchanged, alongside the correctly-added
  character fields. This mutation was included in the pre/post-session
  `diff`-confirmed restore, same as the UI-driven writes above.
- Whole-session log swept for `ERROR`/`CRITICAL` across the full
  verification session: none found.

**Not done in this phase, deliberately, per the prompt's explicit scope
boundary**: no honorific-suffix detection logic anywhere (confirmed via
the finished diff -- no new regex, no new LLM prompt field, no new
lookup function touching honorifics at all); no source-language field
added anywhere (the prior investigation's finding stands unchanged, this
phase didn't touch it); no scraper work. `pronoun_style` remains
settable only via the full Glossary dialog, per the proposal's own
"no natural quick-pick shape" reasoning -- not attempted here.
