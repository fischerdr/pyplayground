#!/usr/bin/env python3
"""glossary.py - Per-novel character/terminology glossary storage.

Stores a persistent list of character names and key terms with their
canonical target-language translations, plus short running context notes,
keyed by Alphapolis novel ID. Used to keep names and terminology consistent
across chunks and episodes when translating with the LLM backend.

Glossaries are always injected into the prompt in full (never retrieved via
embeddings/search) -- a novel's cast and key terms are small enough (a few
KB at most) to always fit, so retrieval-based selection isn't needed.

Storage location: ~/.config/alphapolis_reader/glossaries/{novel_id}.json
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from pyplayground.utils.logging_utils import get_logger

logger = get_logger(__name__)

GLOSSARY_DIR = Path.home() / ".config" / "alphapolis_reader" / "glossaries"
"""Directory for storing per-novel glossary files."""

MAX_TERMS_IN_PROMPT = 200
"""Defensive cap on how many glossary terms get injected into a prompt."""

MAX_CONTEXT_NOTES_CHARS = 1000
"""Defensive cap on context_notes length injected into a prompt."""


def _glossary_path(novel_id: str) -> Path:
    """Return the glossary file path for a given novel ID.

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        Path object pointing to the glossary JSON file.
    """
    return GLOSSARY_DIR / f"{novel_id}.json"


def load_glossary(novel_id: str) -> Dict[str, Any]:
    """Load a novel's glossary from disk, returning an empty glossary if none exists.

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        Glossary dict with novel_id, title, terms, context_notes, updated_at.
    """
    path = _glossary_path(novel_id)
    if not path.exists():
        return {"novel_id": novel_id, "title": "", "terms": [], "context_notes": "", "updated_at": ""}
    try:
        loaded: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load glossary for novel {novel_id}: {e}")
        return {"novel_id": novel_id, "title": "", "terms": [], "context_notes": "", "updated_at": ""}


def save_glossary(novel_id: str, glossary: Dict[str, Any]) -> None:
    """Save a novel's glossary to disk.

    Args:
        novel_id: The Alphapolis novel ID.
        glossary: Glossary dict to save (novel_id, title, terms, context_notes, updated_at).
    """
    path = _glossary_path(novel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(glossary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug(f"Saved glossary for novel {novel_id} to {path}")


def format_glossary_for_prompt(glossary: Dict[str, Any]) -> str:
    """Render a glossary dict into compact text suitable for prompt injection.

    Args:
        glossary: Glossary dict as returned by load_glossary().

    Returns:
        Formatted glossary text, or an empty string if the glossary has no
        terms and no context notes.
    """
    terms: List[Dict[str, str]] = glossary.get("terms", [])[:MAX_TERMS_IN_PROMPT]
    context_notes = (glossary.get("context_notes") or "")[:MAX_CONTEXT_NOTES_CHARS]

    if not terms and not context_notes:
        return ""

    lines = []
    if terms:
        lines.append("Character names and terms (use these exact translations):")
        for term in terms:
            source = term.get("source", "")
            target = term.get("target", "")
            note = term.get("note", "")
            entry = f"- {source} -> {target}"
            if note:
                entry += f" ({note})"
            lines.append(entry)

    if context_notes:
        if lines:
            lines.append("")
        lines.append(f"Context: {context_notes}")

    return "\n".join(lines)


def merge_terms(existing: List[Dict[str, str]], new_terms: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Merge newly extracted terms into an existing term list.

    Existing entries win on conflict (a user may have hand-edited target/note),
    so this only appends terms whose source isn't already present.

    Args:
        existing: Current list of {"source", "target", "note"} dicts.
        new_terms: Newly extracted term dicts to merge in.

    Returns:
        Merged term list.
    """
    known_sources = {term.get("source") for term in existing}
    merged = list(existing)
    for term in new_terms:
        if term.get("source") not in known_sources:
            merged.append(term)
            known_sources.add(term.get("source"))
    return merged
