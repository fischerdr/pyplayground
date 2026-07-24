#!/usr/bin/env python3
"""glossary.py - Per-novel character/terminology glossary storage.

Stores a persistent list of character names and key terms with their
canonical target-language translations, plus short running context notes,
keyed by Alphapolis novel ID. Used to keep names and terminology consistent
across chunks and episodes when translating with the LLM backend.

Terms have a "type" of either "character" or "term" (general vocabulary --
places, magic systems, item names). Character entries carry extra optional
detail that general terms don't need: gender, pronoun_style (a short note on
the character's first-person pronoun/voice, since Japanese frequently omits
subject pronouns and the ones used encode gender/formality/personality that
a flat name mapping loses), and honorific_override (per-character override
of the novel-wide honorific_policy -- e.g. keep "-sensei" for a teacher even
if honorifics are dropped everywhere else). All extra fields are optional;
older glossary files without them still load fine via .get() defaults.

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

TERM_TYPE_CHARACTER = "character"
TERM_TYPE_GENERAL = "term"
DEFAULT_TERM_TYPE = TERM_TYPE_GENERAL
"""Term type identifiers -- "character" entries get extra optional fields
(gender, pronoun_style, honorific_override); "term" entries (the default,
for backward compatibility with pre-existing flat-shape glossaries) are
general vocabulary and only use source/target/note."""

HONORIFIC_POLICIES = ["keep", "drop", "romanize"]
DEFAULT_HONORIFIC_POLICY = "drop"
"""Novel-wide default for how to handle source-language honorifics
(e.g. Japanese -san/-chan/-kun/-sama, Chinese kinship address terms)."""


def _glossary_path(novel_id: str) -> Path:
    """Return the glossary file path for a given novel ID.

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        Path object pointing to the glossary JSON file.
    """
    return GLOSSARY_DIR / f"{novel_id}.json"


def _empty_glossary(novel_id: str) -> Dict[str, Any]:
    """Build an empty glossary dict with all fields defaulted.

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        A fresh glossary dict with no terms.
    """
    return {
        "novel_id": novel_id,
        "title": "",
        "honorific_policy": DEFAULT_HONORIFIC_POLICY,
        # False until a user explicitly sets it via the term editor dialog --
        # lets build_glossary.py apply its own extracted suggestion without
        # clobbering a deliberate user choice, while still being able to
        # fill in a reasonable default for a glossary nobody has touched yet.
        "honorific_policy_user_set": False,
        "terms": [],
        "context_notes": "",
        "updated_at": "",
    }


def load_glossary(novel_id: str) -> Dict[str, Any]:
    """Load a novel's glossary from disk, returning an empty glossary if none exists.

    Older glossary files saved before honorific_policy/term "type"/character
    fields existed still load fine -- honorific_policy defaults in here, and
    per-term fields default via .get() wherever they're read (see
    format_glossary_for_prompt() and the term editor dialog).

    Args:
        novel_id: The Alphapolis novel ID.

    Returns:
        Glossary dict with novel_id, title, honorific_policy, terms,
        context_notes, updated_at.
    """
    path = _glossary_path(novel_id)
    if not path.exists():
        return _empty_glossary(novel_id)
    try:
        loaded: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        loaded.setdefault("honorific_policy", DEFAULT_HONORIFIC_POLICY)
        loaded.setdefault("honorific_policy_user_set", False)
        return loaded
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load glossary for novel {novel_id}: {e}")
        return _empty_glossary(novel_id)


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

    Only the structured term list is included -- context_notes (a free-form
    narrative summary) is deliberately excluded. Confirmed via a real
    mismatch report: injecting context_notes caused the model to sometimes
    hallucinate a scene matching the note's theme (in the source language,
    embedded mid-translation) instead of translating the given text, since
    it read as continuable story content rather than background metadata.
    The term list hasn't shown this failure -- it's a short lookup table,
    not narrative text the model can "continue." context_notes is still
    stored in the glossary file for human reference and still generated by
    build_glossary.py; it's just never sent to the translator.

    Args:
        glossary: Glossary dict as returned by load_glossary().

    Returns:
        Formatted glossary text, or an empty string if the glossary has no terms.
    """
    terms: List[Dict[str, Any]] = glossary.get("terms", [])[:MAX_TERMS_IN_PROMPT]

    if not terms:
        return ""

    honorific_policy = glossary.get("honorific_policy", DEFAULT_HONORIFIC_POLICY)

    lines = ["Character names and terms (use these exact translations):"]
    for term in terms:
        source = term.get("source", "")
        target = term.get("target", "")
        entry = f"- {source} -> {target}"

        # Character entries get compact parenthetical detail (gender,
        # pronoun/voice note, honorific handling); general terms just get
        # their note, same as before. Kept as short fragments, not prose --
        # a JSON-array output format elsewhere in this codebase fixed a
        # model hallucination failure mode tied to narrative-shaped prompt
        # content, so this stays a lookup-table style even as it grows.
        details = []
        if term.get("type") == TERM_TYPE_CHARACTER:
            if term.get("gender"):
                details.append(term["gender"])
            if term.get("pronoun_style"):
                details.append(term["pronoun_style"])
            honorific = term.get("honorific_override") or honorific_policy
            if honorific and honorific != "drop":
                details.append(f"{honorific} honorific")
        elif term.get("note"):
            details.append(term["note"])

        if details:
            entry += f" ({'; '.join(details)})"
        lines.append(entry)

    return "\n".join(lines)


def merge_terms(existing: List[Dict[str, Any]], new_terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge newly extracted terms into an existing term list.

    Existing entries win on conflict (a user may have hand-edited target/note
    or character detail fields via the term editor), so this only appends
    terms whose (type, source) isn't already present. Deduping on type as
    well as source means a "character" and a "term" entry could theoretically
    share the same source text without colliding, though in practice that's
    unlikely to come up.

    An existing entry with no "type" field at all (from a glossary saved
    before term types existed) matches an incoming term of ANY type with the
    same source, rather than only DEFAULT_TERM_TYPE -- otherwise re-running
    extraction on a glossary with old untyped entries would add a duplicate
    "character"-typed copy of a name that's already present untyped.

    Args:
        existing: Current list of term dicts (see module docstring for shape).
        new_terms: Newly extracted term dicts to merge in.

    Returns:
        Merged term list.
    """
    known_keys = {(term.get("type", DEFAULT_TERM_TYPE), term.get("source")) for term in existing}
    untyped_sources = {term.get("source") for term in existing if "type" not in term}
    merged = list(existing)
    for term in new_terms:
        source = term.get("source")
        if source in untyped_sources:
            continue
        key = (term.get("type", DEFAULT_TERM_TYPE), source)
        if key not in known_keys:
            merged.append(term)
            known_keys.add(key)
    return merged
