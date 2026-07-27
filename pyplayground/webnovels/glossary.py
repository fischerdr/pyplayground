#!/usr/bin/env python3
"""glossary.py - Per-novel character/terminology glossary storage.

Stores a persistent list of character names and key terms, plus short
running context notes, keyed by Alphapolis novel ID. Used to keep names and
terminology consistent across chunks and episodes when translating with the
LLM backend.

Each term carries a ranked candidate list and a status (STATUS_CONFIRMED /
STATUS_SUGGESTED) rather than a single flat target -- see the STATUS_CONFIRMED
constant's docstring for the full shape, and DESIGN.md Section 9 for why:
only human-confirmed terms should steer live translation output, so an
unreviewed LLM extraction sits in a review queue instead of immediately
being trusted. Terms have a "type" of either "character" or "term" (general
vocabulary -- places, magic systems, item names). Character entries carry
extra optional detail that general terms don't need: gender, pronoun_style
(a short note on the character's first-person pronoun/voice, since Japanese
frequently omits subject pronouns and the ones used encode gender/formality/
personality that a flat name mapping loses), and honorific_override
(per-character override of the novel-wide honorific_policy -- e.g. keep
"-sensei" for a teacher even if honorifics are dropped everywhere else).

Glossaries are always injected into the prompt in full (never retrieved via
embeddings/search) -- a novel's cast and key terms are small enough (a few
KB at most) to always fit, so retrieval-based selection isn't needed.

Storage location: ~/.config/alphapolis_reader/glossaries/{novel_id}.json

No backward compatibility with the pre-Section-9 flat {source, target, type,
note} term shape -- this is pre-production, existing glossary files under
the old shape should be deleted/regenerated rather than migrated.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

STATUS_CONFIRMED = "confirmed"
STATUS_SUGGESTED = "suggested"
"""Term review-gate status (see DESIGN.md Section 9). A term's
confirmed_target is only injected into the translation prompt via
format_glossary_for_prompt() when status is STATUS_CONFIRMED. STATUS_SUGGESTED
terms (from LLM extraction, or an unresolved click-pick) sit in a review
queue instead -- not yet trusted enough to steer translation output.

A term dict's shape (see make_confirmed_term()/make_suggested_term()):
{
  "source": str,
  "type": str (TERM_TYPE_CHARACTER or TERM_TYPE_GENERAL),
  "candidates": [{"target": str, "count": int, "origin": str}, ...],
  "confirmed_target": str or None,
  "status": STATUS_CONFIRMED or STATUS_SUGGESTED,
  "note": str or None,
  # character-only, otherwise absent:
  "gender": str or None,
  "pronoun_style": str or None,
  "honorific_override": str or None,
}
"""

ORIGIN_USER = "user"
ORIGIN_LLM = "llm"
ORIGIN_MT = "mt"
"""Candidate origin identifiers -- who/what proposed this candidate target,
shown alongside its usage count in the term editor."""


def make_confirmed_term(term_type: str, source: str, target: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Build a term dict for a manually-entered, immediately-trusted term.

    Used by the "Highlight -> Add Term" path (right-click a word in chapter
    text, or the glossary editor's Add Term/Add Character buttons): a human
    typed this deliberately, so it's trusted on entry -- no review queue.

    Args:
        term_type: TERM_TYPE_CHARACTER or TERM_TYPE_GENERAL.
        source: Source-language term text.
        target: The confirmed translation.
        note: Optional free-form note.

    Returns:
        A term dict with status=STATUS_CONFIRMED and a single
        origin="user" candidate at count 1.
    """
    return {
        "type": term_type,
        "source": source,
        "candidates": [{"target": target, "count": 1, "origin": ORIGIN_USER}],
        "confirmed_target": target,
        "status": STATUS_CONFIRMED,
        "note": note,
    }


def make_suggested_term(term_type: str, source: str, target: str, note: Optional[str] = None, origin: str = ORIGIN_LLM) -> Dict[str, Any]:
    """Build a term dict for an unreviewed, machine-proposed term.

    Used by build_glossary.py's LLM extraction: a fresh extraction is a
    guess, not a confirmed fact, so it lands in the review queue
    (status=STATUS_SUGGESTED, confirmed_target=None) rather than
    immediately affecting translation output.

    Args:
        term_type: TERM_TYPE_CHARACTER or TERM_TYPE_GENERAL.
        source: Source-language term text.
        target: The proposed translation.
        note: Optional free-form note.
        origin: Candidate origin identifier (default ORIGIN_LLM).

    Returns:
        A term dict with status=STATUS_SUGGESTED, confirmed_target=None,
        and a single candidate at count 1.
    """
    return {
        "type": term_type,
        "source": source,
        "candidates": [{"target": target, "count": 1, "origin": origin}],
        "confirmed_target": None,
        "status": STATUS_SUGGESTED,
        "note": note,
    }


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

    Only status=STATUS_CONFIRMED terms are included -- an unreviewed
    STATUS_SUGGESTED term (fresh LLM extraction, or an unresolved click-pick)
    hasn't been vetted, so injecting it as "use this exact translation" would
    let an unconfirmed guess steer live translation output the same way a
    human-confirmed term does. See DESIGN.md Section 9.

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
        Formatted glossary text, or an empty string if the glossary has no
        confirmed terms.
    """
    all_terms: List[Dict[str, Any]] = glossary.get("terms", [])
    confirmed_terms = [t for t in all_terms if t.get("status") == STATUS_CONFIRMED][:MAX_TERMS_IN_PROMPT]

    if not confirmed_terms:
        return ""

    honorific_policy = glossary.get("honorific_policy", DEFAULT_HONORIFIC_POLICY)

    lines = ["Character names and terms (use these exact translations):"]
    for term in confirmed_terms:
        source = term.get("source", "")
        target = term.get("confirmed_target", "")
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


def build_mask_targets(lines: List[str], glossary: Dict[str, Any]) -> List[Tuple[int, str]]:
    """Decide which term occurrences in `lines` should be masked before translation.

    v1 trigger rule (decided in DESIGN.md Section 9, implemented here):
    mask every occurrence of every term whose status is not
    STATUS_CONFIRMED. An unreviewed STATUS_SUGGESTED term hasn't been
    vetted, so it shouldn't be translated through -- masking it lets the
    model translate around it and leaves the original word in place,
    flagged for review, instead of the model guessing at (and possibly
    corrupting) a term nobody has confirmed yet. Feeds directly into
    llm_translate.translate_chunk_with_masking()'s `mask_targets` parameter,
    which expects exactly this (line_idx, word) shape.

    Deliberately narrow: this only decides *which* spans to mask. It does
    not call translate_chunk_with_masking() itself, does not change how
    translate_lines() is called in production, and does not touch
    needs_review handling -- those are separate, not-yet-made decisions
    (see DESIGN.md Section 6/8).

    Matching is exact-substring, case-sensitive, one entry per literal
    occurrence -- if a term's source text appears twice in one line, this
    returns two (line_idx, word) tuples for that line, matching how
    mask_terms() consumes its targets list (one masked occurrence per
    tuple, via a single-count str.replace() each). Longer term sources are
    matched before shorter ones so a term that's a substring of another
    (e.g. "音夢" inside "音夢くん") doesn't fragment the longer match's
    first occurrence out from under it.

    Args:
        lines: Source lines/paragraphs about to be translated, in order.
        glossary: Glossary dict as returned by load_glossary().

    Returns:
        (line_idx, word) pairs, one per literal term occurrence found,
        ordered by line then by position within the line. Empty list if
        the glossary has no non-confirmed terms or none of them appear in
        `lines`.
    """
    unconfirmed_sources = sorted(
        {term.get("source", "") for term in glossary.get("terms", []) if term.get("status") != STATUS_CONFIRMED and term.get("source")},
        key=len,
        reverse=True,
    )
    if not unconfirmed_sources:
        return []

    targets: List[Tuple[int, str]] = []
    for line_idx, line in enumerate(lines):
        # Collect (start, end, word) matches with longer sources scanned
        # first so a longer match claims its span before a shorter
        # substring term can; then re-sort by position for a deterministic,
        # line-order-following result independent of term length/set order.
        covered: List[Tuple[int, int]] = []
        matches: List[Tuple[int, int, str]] = []
        for source in unconfirmed_sources:
            search_from = 0
            while True:
                pos = line.find(source, search_from)
                if pos == -1:
                    break
                end = pos + len(source)
                if not any(pos < c_end and end > c_start for c_start, c_end in covered):
                    matches.append((pos, end, source))
                    covered.append((pos, end))
                search_from = pos + 1
        matches.sort(key=lambda m: m[0])
        targets.extend((line_idx, word) for _pos, _end, word in matches)
    return targets


def update_candidate_counts(
    source_lines: List[str],
    translated_lines: List[str],
    glossary: Dict[str, Any],
    needs_review_flags: Optional[List[bool]] = None,
) -> Dict[str, Any]:
    """Increment a confirmed term's winning candidate's count for each chunk it actually appears in.

    The count-building loop from DESIGN.md Section 3/6: for every
    STATUS_CONFIRMED term whose source string appears in `source_lines`,
    checks whether the corresponding `translated_lines` entry contains that
    term's `confirmed_target` string, and if so increments that candidate's
    count -- lets consistency reinforce a candidate organically, without
    requiring a human to confirm every occurrence.

    Deliberately narrow, matching the DESIGN.md Section 12 scoping (three
    things named there as separate, later work, not attempted here):

    - STATUS_SUGGESTED terms are not counted. A suggested/masked term's
      line contains the raw source word (splice_terms()'s fallback), not a
      model-generated translation -- there's no translated candidate
      string to substring-match against for those. Recurrence tracking for
      suggested terms is a real, different idea (count how often the term
      itself appears, not which candidate translation wins) -- not
      attempted here; see DESIGN.md Section 12 for why conflating the two
      under one mechanism would repeat the flag-means-two-things mistake
      needs_review's design already caught once.
    - Discovering a *new* candidate translation not already in a term's
      `candidates` list is out of scope -- only existing candidate strings
      are matched against. Attributing an arbitrary span of translated
      text to a specific source term with no positional/masking anchor is
      a real alignment problem, not solved incidentally here.
    - A source line whose corresponding translated_lines entry came from a
      needs_review=True translation attempt is excluded from counting --
      that attempt failed and was recovered via fallback, so it's not
      evidence the model successfully produced (or avoided) any candidate
      translation. Only relevant when `needs_review_flags` is passed
      (confirmed terms are never masked, so this mainly guards against a
      line failing for an unrelated reason in the same chunk).

    Args:
        source_lines: Source-language lines from the chunk just translated.
        translated_lines: Corresponding translated lines, same length/order.
        glossary: Glossary dict as returned by load_glossary().
        needs_review_flags: Optional, same length/order as source_lines --
            True for a line whose translation attempt needed the
            missing-sentinel/empty-line fallback (see
            llm_translate.translate_chunk_with_masking()). Lines flagged
            True are skipped. If omitted, no lines are excluded on this
            basis (matches callers that only ever pass unmasked/confirmed
            content, where the flag doesn't apply).

    Returns:
        A new glossary dict (shallow copy at the top level and the terms
        list; individual term dicts that had a count incremented are
        replaced with new dicts, not mutated in place -- unmodified term
        dicts are shared by reference, same convention as merge_terms()).
    """
    flags = needs_review_flags if needs_review_flags is not None else [False] * len(source_lines)

    updated_terms = []
    for term in glossary.get("terms", []):
        if term.get("status") != STATUS_CONFIRMED:
            updated_terms.append(term)
            continue

        source = term.get("source", "")
        confirmed_target = term.get("confirmed_target")
        if not source or not confirmed_target:
            updated_terms.append(term)
            continue

        matched = False
        for src_line, tgt_line, flagged in zip(source_lines, translated_lines, flags):
            if flagged:
                continue
            if source in src_line and confirmed_target in tgt_line:
                matched = True
                break

        if not matched:
            updated_terms.append(term)
            continue

        new_candidates = []
        for candidate in term.get("candidates", []):
            if candidate.get("target") == confirmed_target:
                new_candidates.append({**candidate, "count": candidate.get("count", 0) + 1})
            else:
                new_candidates.append(candidate)
        updated_terms.append({**term, "candidates": new_candidates})

    return {**glossary, "terms": updated_terms}


def merge_terms(existing: List[Dict[str, Any]], new_terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge new terms into an existing term list.

    Existing entries win on conflict (a user may have hand-confirmed/edited
    a term via the term editor), so this only appends terms whose (type,
    source) isn't already present. Deduping on type as well as source means
    a "character" and a "term" entry could theoretically share the same
    source text without colliding, though in practice that's unlikely to
    come up.

    Callers decide status on the way in (see make_confirmed_term()/
    make_suggested_term()) -- this function is status-agnostic and just
    dedupes/appends whatever term dicts it's given. build_glossary.py's LLM
    extraction should build new_terms with make_suggested_term() (unreviewed
    guesses land in the review queue); the reader's manual "Add to Glossary"
    path should use make_confirmed_term() (a human typed it deliberately,
    trusted on entry). See DESIGN.md Section 9.

    Args:
        existing: Current list of term dicts (see module docstring for shape).
        new_terms: New term dicts to merge in.

    Returns:
        Merged term list.
    """
    known_keys = {(term.get("type", DEFAULT_TERM_TYPE), term.get("source")) for term in existing}
    merged = list(existing)
    for term in new_terms:
        source = term.get("source")
        key = (term.get("type", DEFAULT_TERM_TYPE), source)
        if key not in known_keys:
            merged.append(term)
            known_keys.add(key)
    return merged


def upsert_confirmed_term(existing: List[Dict[str, Any]], new_term: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Insert or replace a single manually-confirmed term, deduping on source alone.

    Distinct from merge_terms(), which dedupes on (type, source) and is
    documented (see its own docstring, DESIGN.md Section 9) as a
    deliberate tradeoff for its actual use case: bulk-merging fresh LLM
    extraction results, where a "character" and a "term" entry
    coincidentally sharing source text are allowed to coexist as
    different things nobody has looked at yet.

    This function is for a different call site with unambiguous human
    intent -- the reader's "Add to Glossary" dialog, where a person just
    looked at a specific source word and confirmed a translation for it.
    A human confirming a term is confirming *that word*, not "that word
    considered as a character" specifically as opposed to "that word
    considered as a general term" -- the type is just a field on the one
    entry they mean, not part of what makes it a distinct thing. Found via
    a real live bug: build_glossary.py's LLM extraction had already saved
    an entry for a source word under one type (e.g. "character"); a human
    later confirmed the same word via the dialog with a different type
    selected (e.g. "term", since explain_term()'s live classification
    doesn't necessarily agree with the original extraction's guess) --
    merge_terms()'s (type, source) key didn't match the existing entry, so
    a second, redundant entry was appended instead of the first being
    updated. Left one source with two entries, one still unconfirmed,
    which still caused build_mask_targets() to mask a term a human had
    already confirmed.

    On a source collision, the new (freshly human-confirmed) entry always
    wins and replaces every existing entry for that source, regardless of
    those entries' type or status -- same trust principle make_confirmed_term()
    already documents ("a human typed this deliberately, trusted on
    entry"), extended to also override a stale, possibly-differently-typed
    prior entry rather than merely coexisting with it.

    Args:
        existing: Current list of term dicts.
        new_term: A single term dict, normally from make_confirmed_term(),
            to insert or use to replace any existing entry(ies) with the
            same source.

    Returns:
        New term list with exactly one entry for new_term's source.
    """
    source = new_term.get("source")
    result = [term for term in existing if term.get("source") != source]
    result.append(new_term)
    return result
