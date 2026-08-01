#!/usr/bin/env python3
"""global_vocabulary.py - Cross-novel general-vocabulary/idiom correction store.

RETRANSLATION_DESIGN.md Phase 5. Separate from glossary.py's per-novel
character/term glossaries on purpose: a fix for an ordinary vocabulary/idiom
mistranslation (e.g. an idiom the model got wrong) isn't specific to one
novel's cast or setting the way a confirmed character name or in-world term
is -- it should apply everywhere. Coexists with per-novel data; does not
replace it. At prompt-injection time, per-novel confirmed terms always take
precedence over a same-source global note (see
format_global_vocabulary_for_prompt()).

No status/candidates/origin ceremony (contrast with glossary.py's term
schema): both write paths into this store (the retranslation dialog's
"remember this" popup, and the glossary dialog's "Apply Globally" action)
are human-confirmed-only actions -- there is no LLM-extraction/review-queue
path feeding this store, so every entry that exists here is trusted on
write.

Storage location: ~/.config/alphapolis_reader/global_vocabulary.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pyplayground.utils.logging_utils import get_logger
from pyplayground.utils.safe_persistence import atomic_write
from pyplayground.webnovels.glossary import MAX_TERMS_IN_PROMPT, STATUS_CONFIRMED, mixed_case_note

logger = get_logger(__name__)

GLOBAL_VOCAB_PATH = Path.home() / ".config" / "alphapolis_reader" / "global_vocabulary.json"
"""Single flat file for the global vocabulary-notes store -- unlike
glossary.py's per-novel files, there is exactly one of these, process-wide,
so no directory-plus-ID convention is needed."""


def _empty_store() -> Dict[str, Any]:
    """Build an empty global vocabulary store dict.

    Returns:
        A fresh store dict with no entries.
    """
    return {"updated_at": "", "entries": []}


def load_global_vocabulary() -> Dict[str, Any]:
    """Load the global vocabulary store from disk, returning an empty store if none exists.

    Returns:
        Store dict with updated_at and entries.
    """
    if not GLOBAL_VOCAB_PATH.exists():
        return _empty_store()
    try:
        loaded: Dict[str, Any] = json.loads(GLOBAL_VOCAB_PATH.read_text(encoding="utf-8"))
        loaded.setdefault("entries", [])
        loaded.setdefault("updated_at", "")
        return loaded
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load global vocabulary store: {e}")
        return _empty_store()


def save_global_vocabulary(store: Dict[str, Any]) -> None:
    """Save the global vocabulary store to disk.

    Args:
        store: Store dict to save (updated_at, entries).
    """
    GLOBAL_VOCAB_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(GLOBAL_VOCAB_PATH, json.dumps(store, indent=2, ensure_ascii=False))
    logger.debug(f"Saved global vocabulary store to {GLOBAL_VOCAB_PATH}")


def upsert_global_entry(source: str, target: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Reload the store fresh and write one entry into it immediately, keyed by source.

    Same reload-fresh-immediately-before-write discipline as
    GlossaryCoordinator's simple write methods (upsert_confirmed(),
    reject(), clear()) -- neither of this store's two write entry points
    (the retranslation dialog's "remember this" popup, the glossary
    dialog's "Apply Globally" action) holds a long-lived in-memory
    snapshot across a dialog session the way open_glossary_dialog() does,
    so no merge-on-divergence logic is needed, just reload -> mutate ->
    write.

    Args:
        source: The original-language term/idiom this entry corrects.
        target: The corrected global rendering.
        note: Optional free-text note, same shape as a per-novel "term"
            entry's note field.

    Returns:
        The final store dict as written to disk.
    """
    store = load_global_vocabulary()
    now = datetime.now(timezone.utc).isoformat()
    entries: List[Dict[str, Any]] = store.get("entries", [])
    existing = next((e for e in entries if e.get("source") == source), None)
    if existing is not None:
        existing["target"] = target
        existing["note"] = note
        existing["updated_at"] = now
    else:
        entries.append({"source": source, "target": target, "note": note, "added_at": now, "updated_at": now})
    store["entries"] = entries
    store["updated_at"] = now
    save_global_vocabulary(store)
    logger.info(f"Global vocabulary entry saved: {source!r} -> {target!r}")
    return store


def get_global_entry(source: str) -> Optional[Dict[str, Any]]:
    """Load the store fresh and return the entry matching `source`, or None.

    Used by the click-to-use reference field in open_glossary_dialog()'s
    term editor.

    Args:
        source: The original-language term/idiom to look up.

    Returns:
        The matching entry dict, or None if no entry has this source.
    """
    store = load_global_vocabulary()
    for entry in store.get("entries", []):
        if entry.get("source") == source:
            result: Dict[str, Any] = entry
            return result
    return None


def format_global_vocabulary_for_prompt(store: Dict[str, Any], current_novel_glossary: Optional[Dict[str, Any]] = None) -> str:
    """Render global vocabulary entries into prompt text, excluding sources already confirmed in the current novel.

    Precedence rule: a per-novel confirmed term always wins over a
    same-source global note -- if current_novel_glossary already has a
    STATUS_CONFIRMED term for a given source, that global entry is
    excluded here rather than injected redundantly (or in conflict)
    alongside the per-novel one.

    Args:
        store: Global vocabulary store dict, as returned by
            load_global_vocabulary().
        current_novel_glossary: The current novel's glossary dict (as
            returned by glossary.load_glossary()), used only to compute
            the precedence exclusion above. If None, no exclusion is
            applied (all entries are included).

    Returns:
        Formatted global vocabulary text, or an empty string if there are
        no entries to include.
    """
    excluded_sources = set()
    if current_novel_glossary is not None:
        excluded_sources = {t.get("source") for t in current_novel_glossary.get("terms", []) if t.get("status") == STATUS_CONFIRMED}

    entries = [e for e in store.get("entries", []) if e.get("source") not in excluded_sources][:MAX_TERMS_IN_PROMPT]

    if not entries:
        return ""

    lines = ["General vocabulary/idiom notes (use these exact translations unless the text above already overrides them):"]
    for entry in entries:
        source = entry.get("source", "")
        target = entry.get("target", "")
        line = f"- {source} -> {target}"

        details = []
        if entry.get("note"):
            details.append(entry["note"])
        capitalization_note = mixed_case_note(target)
        if capitalization_note:
            details.append(capitalization_note)

        if details:
            line += f" ({'; '.join(details)})"
        lines.append(line)

    return "\n".join(lines)
