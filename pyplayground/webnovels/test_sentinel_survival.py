#!/usr/bin/env python3
"""test_sentinel_survival.py - Does a sentinel marker survive LLM translation intact?

Standalone probe for the "mask a term, translate around it, splice the original
back in" design for the glossary review-queue feature. Reuses the exact JSON-array
prompt shape from pyplayground.webnovels.llm_translate.TRANSLATION_PROMPT (not a
simplified stand-in), so results are representative of what the real pipeline
would see -- a sentinel that survives a bare single-line prompt but not a
multi-line JSON-array chunk would give a false pass otherwise.

Tests 3 candidate sentinel formats against several real-shaped failure scenarios
(isolated name, mid-sentence, honorific-attached, katakana name, chunk-boundary
position, multiple sentinels in one chunk) and reports per-format survival.

Usage:
    python test_sentinel_survival.py
    python test_sentinel_survival.py --endpoint http://flyyn:10001 --model "mradermacher/translategemma-12b-it-GGUF:Q4_K_M"
    python test_sentinel_survival.py --format bracket_id_only   # test one format only
    python test_sentinel_survival.py --json-out results.json    # save raw outputs for manual inspection

Run this against each model you're considering (point --endpoint at whichever
llama-server instance is currently serving it) before committing the
masking/splicing design to depending on any one of them.
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests

from pyplayground.webnovels.llm_translate import parse_json_response

# ---------------------------------------------------------------------------
# Sentinel formats under test
# ---------------------------------------------------------------------------
# Each format provides:
#   wrap(word, n)   -> masked string to splice into the source line
#   find(text, n)   -> re.Match for this sentinel's occurrence in model output, or None
#   inner(match)    -> the text the model left between/at the marker, or None if opaque
#
# "opaque" formats replace the word entirely (model never sees the Japanese);
# "wrapping" formats leave the original word in place, bracketed, so a
# still-present-but-unchanged inner value is itself a pass condition.


@dataclass
class SentinelFormat:
    name: str
    opaque: bool  # True if wrap() hides the original word entirely
    wrap: Callable[[str, int], str]
    pattern: Callable[[int], "re.Pattern"]


# Bracket glyphs observed (or plausible) as model normalization targets for
# the canonical fullwidth math brackets ⟦ ⟧ (U+27E6/U+27E7). Confirmed live:
# translategemma normalized ⟦...⟧ to plain ASCII [...] in the honorific-attached
# case. Fullwidth square brackets and fullwidth digits are the same failure
# class (model "cleans up" unfamiliar glyphs into more common ones) and are
# guarded defensively even though not yet confirmed to occur.
_OPEN_BRACKETS = r"\u27e6\u3010\uff3b\["  # ⟦ 【 ［ [
_CLOSE_BRACKETS = r"\u27e7\u3011\uff3d\]"  # ⟧ 】 ］ ]
_DIGIT_NORMALIZE = str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")


def _normalize(text: str) -> str:
    """Normalize fullwidth digits to ASCII before pattern matching."""
    return text.translate(_DIGIT_NORMALIZE)


def _opaque_pattern(n: int) -> "re.Pattern":
    return re.compile(rf"[{_OPEN_BRACKETS}]\s*TERM_{n}\s*[{_CLOSE_BRACKETS}]")


def _bracket_pattern(n: int) -> "re.Pattern":
    # \u27e6 1 : ... \u27e7   e.g.  ⟦1:るりちゃん⟧
    return re.compile(rf"\u27e6{n}:(.*?)\u27e7")


def _xml_pattern(n: int) -> "re.Pattern":
    return re.compile(rf"<t{n}>(.*?)</t{n}>")


SENTINEL_FORMATS = {
    "opaque_placeholder": SentinelFormat(
        name="opaque_placeholder",
        opaque=True,
        wrap=lambda word, n: f"\u27e6TERM_{n}\u27e7",
        pattern=_opaque_pattern,
    ),
    "bracket_id_inline": SentinelFormat(
        name="bracket_id_inline",
        opaque=False,
        wrap=lambda word, n: f"\u27e6{n}:{word}\u27e7",
        pattern=_bracket_pattern,
    ),
    "xml_tag": SentinelFormat(
        name="xml_tag",
        opaque=False,
        wrap=lambda word, n: f"<t{n}>{word}</t{n}>",
        pattern=_xml_pattern,
    ),
}

# ---------------------------------------------------------------------------
# Test cases -- each is a "chunk" (list of source lines), with one or more
# (line_index, word) pairs to mask. Mirrors real chunk shape: multiple short
# paragraphs sent together in one JSON-array translation call.
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    description: str
    lines: List[str]
    # (line_index, exact substring to mask) -- substring must appear verbatim in lines[line_index]
    targets: List[tuple] = field(default_factory=list)


TEST_CASES = [
    TestCase(
        description="isolated name, short standalone sentence",
        lines=["早朝の陽が射してきた畑で、雛形結月が楽しそうに微笑む。"],
        targets=[(0, "雛形結月")],
    ),
    TestCase(
        description="honorific-attached name, mid-dialogue (matches the るりちゃん case from the app)",
        lines=["「見て、るりちゃん！こんなに赤くて大きいのっ！」"],
        targets=[(0, "るりちゃん")],
    ),
    TestCase(
        description="katakana foreign-style name (matches the Keito/Rinai mistransliteration case)",
        lines=["ケイトが振り返った。「あら、噂をすれば」"],
        targets=[(0, "ケイト")],
    ),
    TestCase(
        description="sentinel at the very start of a line",
        lines=["ケイトは、朝から機嫌が良さそうだった。"],
        targets=[(0, "ケイト")],
    ),
    TestCase(
        description="sentinel at the very end of a line",
        lines=["昨日の夜、彼女が助けたのはケイト"],
        targets=[(0, "ケイト")],
    ),
    TestCase(
        description="two different sentinels in the same multi-line chunk (cross-line contamination check)",
        lines=[
            "ケイトとルリは、幼い頃からの親友だった。",
            "「ルリ、今日は付き合ってくれてありがとう」とケイトが言った。",
        ],
        targets=[(0, "ケイト"), (0, "ルリ"), (1, "ルリ"), (1, "ケイト")],
    ),
    TestCase(
        description="chunk-boundary: masked name in the last line of a ~150-char multi-line chunk",
        lines=[
            "朝日を浴びた笑顔がまぶしい。そして利賀に向けだされた大物の収穫をみせられるりもまた腰を屈め、実っているトマトを愛おしそうに眺めていた。",
            "「ほらシャークったら、後ろも気を付けてね」雑に葉を返して収穫できるトマトを探すのに、心配そうにケイトが振り返った。",
        ],
        targets=[(1, "ケイト")],
    ),
    TestCase(
        description="stress: 5 sentinels across 3 lines (realistic dense-dialogue chunk)",
        lines=[
            "「ケイト、ルリ、音夢くん、みんな揃った?」と維多教授が尋ねた。",
            "ケイトは頷き、ルリは笑顔で答えた。「はい、揃いました」",
            "音夢くんだけは少し遅れて到着した。",
        ],
        targets=[
            (0, "ケイト"),
            (0, "ルリ"),
            (0, "音夢くん"),
            (0, "維多教授"),
            (2, "音夢くん"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Prompt -- copied verbatim from llm_translate.TRANSLATION_PROMPT so results
# are representative of the real pipeline, not a simplified stand-in.
# ---------------------------------------------------------------------------

TRANSLATION_PROMPT = (
    "You are a translation API. You output ONLY a JSON array of strings, "
    "nothing else -- no notes, no explanations, no markdown code fences.\n\n"
    "Translate each {source_lang} string in the array below to {target_lang}. "
    "Preserve order and array length exactly -- one output string per input "
    "string, even if a string is short or ambiguous. Do not merge, split, "
    "or add strings, and do not continue the story beyond what is given. "
    "If you are unsure about a proper noun (character name, place name), "
    "transliterate it using standard romanization conventions.\n\n"
    "{source_lang} array: {lines_json}\n\n"
    "JSON array:"
)


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()




def build_masked_lines(case: TestCase, fmt: SentinelFormat) -> List[str]:
    lines = list(case.lines)
    for n, (line_idx, word) in enumerate(case.targets, start=1):
        if word not in lines[line_idx]:
            raise ValueError(f"{word!r} not found in line {line_idx} of case {case.description!r} -- fix the test case")
        lines[line_idx] = lines[line_idx].replace(word, fmt.wrap(word, n), 1)
    return lines


def call_llm(endpoint: str, model: str, source_lines: List[str], timeout: int) -> Optional[List[str]]:
    prompt = TRANSLATION_PROMPT.format(
        source_lang="Japanese",
        target_lang="English",
        lines_json=json.dumps(source_lines, ensure_ascii=False),
    )
    payload = {"prompt": prompt, "n_predict": max(512, len(prompt) // 2), "temperature": 0.1}
    try:
        resp = requests.post(f"{endpoint}/completion", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        raw = strip_code_fence(data.get("content", ""))
        parsed = parse_json_response(raw)
        if not isinstance(parsed, list):
            print(f"    [!] response was not a JSON array: {raw[:200]!r}")
            return None
        return [str(x) for x in parsed]
    except requests.exceptions.RequestException as e:
        print(f"    [!] request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"    [!] JSON parse failed: {e}; raw={raw[:200]!r}")
        return None


def check_survival(case: TestCase, fmt: SentinelFormat, output_lines: List[str]) -> List[dict]:
    """Return one result dict per target sentinel: found, and (if wrapping) unchanged."""
    results = []
    for n, (line_idx, word) in enumerate(case.targets, start=1):
        if line_idx >= len(output_lines):
            results.append({"id": n, "word": word, "found": False, "reason": "output shorter than input (line dropped)"})
            continue
        out_line = _normalize(output_lines[line_idx])
        match = fmt.pattern(n).search(out_line)
        if not match:
            results.append({"id": n, "word": word, "found": False, "reason": "sentinel not found in output line"})
            continue
        if fmt.opaque:
            results.append({"id": n, "word": word, "found": True, "unchanged": True})
        else:
            inner = match.group(1)
            results.append({"id": n, "word": word, "found": True, "unchanged": inner == word, "inner_value": inner})
    return results


def run_suite(endpoint: str, model_label: str, formats: List[SentinelFormat], timeout: int, raw_dump: list) -> dict:
    """Run all TEST_CASES x formats against one endpoint. Returns {format_name: {pass, fail}}."""
    scoreboard = {fmt.name: {"pass": 0, "fail": 0} for fmt in formats}

    for case in TEST_CASES:
        print(f"=== [{model_label}] {case.description} ===")
        for fmt in formats:
            masked_lines = build_masked_lines(case, fmt)
            output_lines = call_llm(endpoint, model_label, masked_lines, timeout)
            raw_dump.append({"model": model_label, "case": case.description, "format": fmt.name, "input": masked_lines, "output": output_lines})

            if output_lines is None:
                scoreboard[fmt.name]["fail"] += len(case.targets)
                print(f"  [{fmt.name}] REQUEST FAILED")
                continue

            results = check_survival(case, fmt, output_lines)
            for r in results:
                ok = r["found"] and r.get("unchanged", True)
                scoreboard[fmt.name]["pass" if ok else "fail"] += 1
                status = "OK" if ok else "FAIL"
                detail = "" if ok else f" -- {r.get('reason', '')}{(' got: ' + repr(r.get('inner_value'))) if 'inner_value' in r and not r.get('unchanged', True) else ''}"
                print(f"  [{fmt.name}] id={r['id']} word={r['word']!r}: {status}{detail}")
        print()

    return scoreboard


def print_summary(label: str, scoreboard: dict) -> None:
    print(f"=== Summary: {label} ===")
    for fmt_name, score in scoreboard.items():
        total = score["pass"] + score["fail"]
        rate = (score["pass"] / total * 100) if total else 0.0
        print(f"  {fmt_name}: {score['pass']}/{total} survived intact ({rate:.0f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test whether sentinel markers survive LLM translation intact")
    parser.add_argument("--endpoint", default="http://flyyn:10001", help="llama-server base URL")
    parser.add_argument("--model", default="(server-loaded model)", help="Label only -- llama-server serves whatever's currently loaded")
    parser.add_argument("--compare-endpoint", help="Optional second llama-server URL (e.g. a Qwen3 instance on another port) to run the same suite against for comparison")
    parser.add_argument("--compare-model", default="(server-loaded model)", help="Label only, for the --compare-endpoint run")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--format", choices=list(SENTINEL_FORMATS) + ["all"], default="all")
    parser.add_argument("--json-out", help="Optional path to dump raw request/response pairs for manual inspection")
    args = parser.parse_args()

    formats = list(SENTINEL_FORMATS.values()) if args.format == "all" else [SENTINEL_FORMATS[args.format]]
    raw_dump: list = []

    print(f"Testing {len(formats)} sentinel format(s) against {len(TEST_CASES)} case(s)\n")
    scoreboard_a = run_suite(args.endpoint, args.model, formats, args.timeout, raw_dump)

    scoreboard_b = None
    if args.compare_endpoint:
        scoreboard_b = run_suite(args.compare_endpoint, args.compare_model, formats, args.timeout, raw_dump)

    print_summary(f"{args.endpoint} ({args.model})", scoreboard_a)
    if scoreboard_b:
        print()
        print_summary(f"{args.compare_endpoint} ({args.compare_model})", scoreboard_b)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, indent=2, ensure_ascii=False)
        print(f"\nRaw request/response pairs saved to {args.json_out}")


if __name__ == "__main__":
    main()
