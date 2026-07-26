#!/usr/bin/env python3
"""test_qwen3_extraction_validation.py - Does Qwen3-14B fix build_glossary.py's known extraction errors?

Standalone validation probe, not a production code change. Runs the exact
`build_glossary.py` extraction prompt (reused via import, not
re-transcribed, so results reflect the real prompt) against Qwen3-14B via
`/v1/chat/completions` (requires the server started with `--jinja`), and
diffs the result against the actual known-bad glossary that novel
375266002's original rebuild produced on translategemma
(~/.config/alphapolis_reader/glossaries/375266002.json, still on disk in
its pre-Section-9 flat shape -- confirmed to contain every error DESIGN.md
Section 1 describes).

This is the still-outstanding validation named in DESIGN.md Section 5/8:
Qwen3-14B has been tested (and rejected) for sentinel-masked chunk
translation, but never for extraction, which is a different task shape
(single-item JSON-object output, no sentinel masking).

Reuses `thinking=False` via `chat_template_kwargs` -- matches the
structured-output nature of extraction and avoids the sampling confound
documented in DESIGN.md's 2026-07-25 Section 4 update (Qwen's own docs
warn against near-greedy decoding in thinking mode; every call here fixes
temperature=0.1, same as production).

Episode used: "provocation" (cache file
c574a6d5316ddf7eca5b17ae5b6e1b21ed93e7bb7cf7c1729adb868ae60a5e5b.json,
https://www.alphapolis.co.jp/novel/375266002/37695490/episode/7799961) --
grep-confirmed to be the source of every error in the original bad
glossary: Lanchester's Law (source line contains ランチェスターの法則),
オレ, 鉄パイプ, 刑法 (Article 204 of the Penal Code), 世紀末モヒカンムーブ.
The Keito/Rinai mistransliteration's actual source names were traced to
line 31 of this same episode: 桂名 (mistranslated "Keito") and 仁菜
(mistranslated "Rinai") -- kanji names, not katakana as DESIGN.md's prose
shorthand implied; corrected here since this script had to trace the exact
source span to check whether Qwen3 gets them right.

Usage:
    python test_qwen3_extraction_validation.py --endpoint http://flyyn:10002
    python test_qwen3_extraction_validation.py --endpoint http://flyyn:10002 --model Qwen/Qwen3-14B-GGUF:Q8_0
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pyplayground.webnovels.build_glossary import MAX_EXTRACTION_LINES, _build_extraction_prompt, _looks_like_repetition_loop
from pyplayground.webnovels.glossary import TERM_TYPE_CHARACTER
from pyplayground.webnovels.llm_translate import parse_json_response, strip_code_fence

CACHE_DIR = Path.home() / ".cache" / "alphapolis_reader"

# The specific cached episode confirmed (via grep across all novel
# 375266002 episodes) to contain every source term behind the original
# bad-glossary errors documented in DESIGN.md Section 1. See module
# docstring for the confirmation trail.
TARGET_EPISODE_CACHE_FILE = "c574a6d5316ddf7eca5b17ae5b6e1b21ed93e7bb7cf7c1729adb868ae60a5e5b.json"
TARGET_NOVEL_ID = "375266002"


@dataclass
class OriginalError:
    """One documented error from the original translategemma-based rebuild."""

    description: str
    bad_source: str  # the source string as it appeared in the bad glossary
    bad_target: str  # the wrong translation/transliteration produced
    bad_type: Optional[str] = None  # wrong "type" classification, if that's the error


# Ground truth: the actual terms from the still-on-disk original glossary
# file (~/.config/alphapolis_reader/glossaries/375266002.json), matched
# against DESIGN.md Section 1's four documented failure classes. Not
# reconstructed from memory/prose -- read directly from that file.
ORIGINAL_ERRORS = [
    OriginalError(
        description="Factual hallucination: Lanchester's Law extracted as an unrelated real statistical principle",
        bad_source="ランチェスターの法則",
        bad_target="Pareto principle",
    ),
    OriginalError(
        description="Unreliable type classification: a pronoun typed as a character",
        bad_source="オレ",
        bad_target="I/Me",
        bad_type=TERM_TYPE_CHARACTER,
    ),
    OriginalError(
        description="Unreliable type classification: a person's name typed as a general term, not a character",
        bad_source="音夢くん",
        bad_target="Otomu-kun",
        bad_type="term",
    ),
    OriginalError(
        description="Mistransliteration baked in as ground truth (source name traced to 桂名, kanji, not katakana)",
        bad_source="Keito",  # the bad glossary stored the already-mistransliterated string as "source"
        bad_target="Keito",
    ),
    OriginalError(
        description="Mistransliteration baked in as ground truth (source name traced to 仁菜, kanji, not katakana)",
        bad_source="Rinai",
        bad_target="Rinai",
    ),
    OriginalError(
        description="No recurrence filter: one-off slang entered as if it needed cross-chapter consistency",
        bad_source="世紀末モヒカンムーブ",
        bad_target="century-end mohawk move",
    ),
    OriginalError(
        description="No recurrence filter: mundane literal compound entered as a term",
        bad_source="鉄パイプ",
        bad_target="iron pipes",
    ),
    OriginalError(
        description="Real-world reference treated as novel terminology",
        bad_source="Article 204 of the Penal Code",
        bad_target="Article 204 of the Penal Code",
    ),
]


def load_target_episode() -> Dict[str, Any]:
    """Load the specific cached episode confirmed to source every original error.

    Returns:
        The episode dict (lines, translated_lines, etc.) as cached on disk.

    Raises:
        FileNotFoundError: If the expected cache file isn't present.
    """
    path = CACHE_DIR / TARGET_EPISODE_CACHE_FILE
    episode: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return episode


def call_extraction_chat(endpoint: str, model: str, prompt: str, enable_thinking: bool, timeout: int) -> Optional[Dict[str, Any]]:
    """POST the extraction prompt to /v1/chat/completions with thinking control.

    Mirrors test_sentinel_survival_qwen3.py's call_llm_chat() calling
    convention (same payload shape, same enable_thinking + /no_think
    belt-and-suspenders), applied to the extraction prompt instead of the
    translation prompt -- a different task shape on the same endpoint.

    Args:
        endpoint: llama-server base URL (must be running with --jinja).
        model: Model name for the request payload (label only).
        prompt: The full extraction prompt (from build_glossary._build_extraction_prompt()).
        enable_thinking: Passed via chat_template_kwargs.
        timeout: Request timeout in seconds.

    Returns:
        {"content": str, "reasoning_content": str or None} or None on failure.
    """
    user_content = prompt
    if not enable_thinking:
        user_content += "\n/no_think"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
        "cache_prompt": False,
        # A repetition/runaway-generation failure has no natural stop token
        # to end on -- without a cap this can consume a shared llama-server
        # slot for the full context window (tens of minutes) instead of
        # failing fast. A extracted-terms JSON array is at most a few
        # hundred tokens; generous headroom still catches a genuine loop
        # quickly rather than let it run to the context ceiling.
        "max_tokens": 1024,
    }
    try:
        resp = requests.post(f"{endpoint}/v1/chat/completions", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        return {"content": message.get("content", ""), "reasoning_content": message.get("reasoning_content")}
    except requests.exceptions.RequestException as e:
        print(f"    [!] request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"    [!] unexpected response shape: {e}; raw={json.dumps(data)[:300] if 'data' in dir() else '?'}")
        return None


@dataclass
class ExtractionOutcome:
    """Classification result for one extraction attempt."""

    parse_succeeded: bool
    failure_mode: Optional[str] = None  # "unescaped_quote_corruption", "repetition_loop", "other_parse_failure", "not_json_object"
    raw_snippet: str = ""
    extracted_terms: List[Dict[str, Any]] = field(default_factory=list)


def classify_extraction_result(raw_output: str) -> ExtractionOutcome:
    """Classify a raw extraction response: parse success, and if not, which failure mode.

    Distinguishes the specific unescaped-quote JSON corruption documented
    in DESIGN.md's 2026-07-25 Section 4 update (Japanese dialogue markers
    translating to unescaped literal quote characters inside a JSON string
    value) from other parse failures, since that update flagged this as a
    symptom worth checking for specifically here, not just pass/fail.

    Args:
        raw_output: Model output after strip_code_fence().

    Returns:
        ExtractionOutcome with parse_succeeded, failure_mode (if any), and
        extracted_terms (if parse succeeded).
    """
    try:
        parsed = parse_json_response(raw_output)
    except json.JSONDecodeError as e:
        # Heuristic for the specific failure class DESIGN.md documented:
        # an unescaped literal " inside a string value produces a
        # "Expecting ',' delimiter" or "Extra data" error at a column
        # position that lands inside what looks like dialogue-bearing
        # text (heuristically: a corresponding 「 or 」 character appears
        # near the error position in the raw text). Not a certain
        # diagnosis -- reported as a hypothesis with the raw snippet as
        # evidence, same as DESIGN.md's own treatment of this symptom.
        error_region = raw_output[max(0, e.pos - 40) : e.pos + 40]
        looks_like_quote_corruption = '""' in error_region or ("\\'" in error_region and '"' in error_region)
        if looks_like_quote_corruption:
            return ExtractionOutcome(parse_succeeded=False, failure_mode="unescaped_quote_corruption", raw_snippet=error_region)
        if _looks_like_repetition_loop(raw_output):
            return ExtractionOutcome(parse_succeeded=False, failure_mode="repetition_loop", raw_snippet=raw_output[-200:])
        return ExtractionOutcome(parse_succeeded=False, failure_mode="other_parse_failure", raw_snippet=f"{e}; context={error_region!r}")

    if not isinstance(parsed, dict):
        return ExtractionOutcome(parse_succeeded=False, failure_mode="not_json_object", raw_snippet=f"got {type(parsed).__name__}")

    return ExtractionOutcome(parse_succeeded=True, extracted_terms=parsed.get("terms", []))


def compare_against_original_errors(extracted_terms: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Term-by-term diff of a fresh extraction against the documented original errors.

    For each of the 8 documented errors, checks whether the new extraction
    reproduces it exactly, fixes it (term absent, or present with a
    corrected target/type), or introduces a new error of the same shape at
    that source string (present but wrong in a different way than before).

    Args:
        extracted_terms: "terms" list from a successfully-parsed extraction.

    Returns:
        One result dict per original error: {"source", "verdict", "detail"}.
        verdict is one of "fixed", "reproduced", "new_error", "not_found".
    """
    by_source = {t.get("source"): t for t in extracted_terms}
    results = []
    for err in ORIGINAL_ERRORS:
        match = by_source.get(err.bad_source)
        if match is None:
            # Absence is ambiguous: could mean "correctly excluded a
            # one-off/real-world term" (fixed) or "failed to extract a
            # real character/term at all" (a different kind of miss).
            # Reported as not_found rather than assumed-fixed so a human
            # reads the extracted_terms list and judges which it is.
            results.append({"source": err.bad_source, "verdict": "not_found", "detail": f"'{err.bad_source}' not present in this extraction at all"})
            continue

        target_matches = match.get("target") == err.bad_target
        type_matches = err.bad_type is None or match.get("type") == err.bad_type

        if target_matches and type_matches:
            results.append(
                {"source": err.bad_source, "verdict": "reproduced", "detail": f"target={match.get('target')!r} type={match.get('type')!r} -- identical to original error"}
            )
        elif not target_matches and (err.bad_type is None or type_matches is True or match.get("type") != err.bad_type):
            results.append({"source": err.bad_source, "verdict": "fixed", "detail": f"new target={match.get('target')!r} type={match.get('type')!r}"})
        else:
            results.append(
                {
                    "source": err.bad_source,
                    "verdict": "new_error",
                    "detail": f"target={match.get('target')!r} type={match.get('type')!r} -- differs from original but still wrong in the same category",
                }
            )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Qwen3-14B extraction against build_glossary.py's documented known-bad glossary")
    parser.add_argument("--endpoint", required=True, help="llama-server base URL, e.g. http://flyyn:10002 (must be started with --jinja)")
    parser.add_argument("--model", default="Qwen/Qwen3-14B-GGUF:Q8_0", help="Model name for the request payload")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode (default off, per DESIGN.md's structured-output guidance)")
    parser.add_argument("--json-out", help="Optional path to dump the raw request/response for manual inspection")
    args = parser.parse_args()

    episode = load_target_episode()
    source_lines = episode.get("lines", [])[:MAX_EXTRACTION_LINES]
    translated_lines = episode.get("translated_lines", [])[:MAX_EXTRACTION_LINES]

    print(f"Episode: {episode.get('episode_title')!r} ({episode.get('url')})")
    print(f"Lines sent (after MAX_EXTRACTION_LINES={MAX_EXTRACTION_LINES} truncation): {len(source_lines)}")
    print(f"Endpoint: {args.endpoint}  Model: {args.model}  thinking={args.thinking}")
    print()

    prompt = _build_extraction_prompt("\n\n".join(source_lines), "\n\n".join(translated_lines))
    result = call_extraction_chat(args.endpoint, args.model, prompt, args.thinking, args.timeout)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"prompt": prompt, "response": result}, f, indent=2, ensure_ascii=False)
        print(f"Raw request/response saved to {args.json_out}\n")

    if result is None:
        print("REQUEST FAILED -- see error above. No extraction to evaluate.")
        return

    if result["reasoning_content"]:
        print(f"[reasoning_content present, {len(result['reasoning_content'])} chars -- not evaluated, thinking={args.thinking}]\n")

    raw_output = strip_code_fence(result["content"])
    outcome = classify_extraction_result(raw_output)

    print("=== Parse outcome ===")
    if not outcome.parse_succeeded:
        print(f"FAILED to parse -- failure_mode: {outcome.failure_mode}")
        print(f"Evidence snippet: {outcome.raw_snippet!r}")
        print()
        print("No term-level comparison possible; extraction produced no usable output.")
        return

    print(f"Parsed successfully. {len(outcome.extracted_terms)} term(s) extracted.")
    print()
    print("=== Extracted terms (raw) ===")
    for t in outcome.extracted_terms:
        print(f"  [{t.get('type', '?'):9s}] {t.get('source', '?'):20s} -> {t.get('target', '?')}")
    print()

    print("=== Comparison against the 8 documented original errors ===")
    comparisons = compare_against_original_errors(outcome.extracted_terms)
    verdict_counts: Dict[str, int] = {}
    for c in comparisons:
        verdict_counts[c["verdict"]] = verdict_counts.get(c["verdict"], 0) + 1
        print(f"  [{c['verdict']:10s}] {c['source']!r}: {c['detail']}")
    print()
    print(f"=== Summary: {verdict_counts} ===")


if __name__ == "__main__":
    main()
