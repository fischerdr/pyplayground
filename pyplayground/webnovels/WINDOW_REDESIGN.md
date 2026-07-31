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

- **Phase 1**: not started.
- **Phases 2-4**: not started, contingent on Phase 1's findings.
