#!/usr/bin/env python3
"""test_sentinel_survival_chat.py - Sentinel survival via /v1/chat/completions.

Companion to test_sentinel_survival.py, which hits llama-server's raw
/completion endpoint. That script's Qwen3 rejection (DESIGN.md §4) was
specifically diagnosed as "no chat template" -- raw completion mode gives
the model no structure for handling unfamiliar sentinel tokens. This script
tests the actual fix: /v1/chat/completions with --jinja on the server and
per-request `chat_template_kwargs: {"enable_thinking": ...}` to control
reasoning explicitly, rather than hoping the model behaves without a
template at all.

Requires the server to be started with --jinja (chat template applied) --
NOT required to pass --chat-template-kwargs at the server level, since this
script sets enable_thinking per-request, which is the more useful mode for
comparing thinking vs non-thinking behavior without restarting the server.

Mirrors test_sentinel_survival.py's TEST_CASES and SENTINEL_FORMATS
structure intentionally, so results are comparable side by side. If both
scripts prove out, worth factoring the shared bits (test cases, formats,
survival-checking) into one module -- not done here to keep this a quick
standalone probe rather than a refactor.

Usage:
    # default: thinking disabled, matches the DESIGN.md decision for
    # structured-extraction-style tasks
    python test_sentinel_survival_chat.py --endpoint http://flyyn:10002

    # compare thinking on vs off in one run
    python test_sentinel_survival_chat.py --endpoint http://flyyn:10002 --thinking both

    # only the validated-elsewhere format, to keep this run fast
    python test_sentinel_survival_chat.py --endpoint http://flyyn:10002 --format opaque_placeholder --thinking both

Server-side requirement: llama-server must be started with --jinja so the
model's actual chat template (with its enable_thinking conditionals) gets
applied. Without --jinja, /v1/chat/completions may still respond, but the
enable_thinking kwarg has nothing to hook into -- results won't be
meaningful. This script does not check server flags; verify manually.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Sentinel formats -- identical set to test_sentinel_survival.py, retested
# here because chat-template'd role separation might change whether the
# model treats bracket/XML wrapping as translatable content (it did, under
# raw completion). Worth re-confirming rather than assuming the earlier
# 0% verdict still holds once a template's involved.
# ---------------------------------------------------------------------------

_OPEN_BRACKETS = r"\u27e6\u3010\uff3b\["  # ⟦ 【 ［ [
_CLOSE_BRACKETS = r"\u27e7\u3011\uff3d\]"  # ⟧ 】 ］ ]
_DIGIT_NORMALIZE = str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")


def _normalize(text: str) -> str:
    return text.translate(_DIGIT_NORMALIZE)


@dataclass
class SentinelFormat:
    name: str
    opaque: bool
    wrap: Callable[[str, int], str]
    pattern: Callable[[int], "re.Pattern"]


def _opaque_pattern(n: int) -> "re.Pattern":
    return re.compile(rf"[{_OPEN_BRACKETS}]\s*TERM_{n}\s*[{_CLOSE_BRACKETS}]")


def _bracket_pattern(n: int) -> "re.Pattern":
    return re.compile(rf"[{_OPEN_BRACKETS}]{n}:(.*?)[{_CLOSE_BRACKETS}]")


def _xml_pattern(n: int) -> "re.Pattern":
    return re.compile(rf"<t{n}>(.*?)</t{n}>")


SENTINEL_FORMATS = {
    "opaque_placeholder": SentinelFormat("opaque_placeholder", True, lambda w, n: f"\u27e6TERM_{n}\u27e7", _opaque_pattern),
    "bracket_id_inline": SentinelFormat("bracket_id_inline", False, lambda w, n: f"\u27e6{n}:{w}\u27e7", _bracket_pattern),
    "xml_tag": SentinelFormat("xml_tag", False, lambda w, n: f"<t{n}>{w}</t{n}>", _xml_pattern),
}

# ---------------------------------------------------------------------------
# Test cases -- copied verbatim from test_sentinel_survival.py. Keep in sync
# manually for now; see module docstring re: eventual shared-module refactor.
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    description: str
    lines: List[str]
    targets: List[Tuple[int, str]] = field(default_factory=list)


TEST_CASES = [
    TestCase(
        description="isolated name, short standalone sentence",
        lines=["早朝の陽が射してきた畑で、雛形結月が楽しそうに微笑む。"],
        targets=[(0, "雛形結月")],
    ),
    TestCase(
        description="honorific-attached name, mid-dialogue",
        lines=["「見て、るりちゃん！こんなに赤くて大きいのっ！」"],
        targets=[(0, "るりちゃん")],
    ),
    TestCase(
        description="katakana foreign-style name",
        lines=["ケイトが振り返った。「あら、噂をすれば」"],
        targets=[(0, "ケイト")],
    ),
    TestCase(
        description="two different sentinels in the same multi-line chunk (the shape that broke raw /completion)",
        lines=[
            "ケイトとルリは、幼い頃からの親友だった。",
            "「ルリ、今日は付き合ってくれてありがとう」とケイトが言った。",
        ],
        targets=[(0, "ケイト"), (0, "ルリ"), (1, "ルリ"), (1, "ケイト")],
    ),
    TestCase(
        description="stress: 5 sentinels across 3 lines (dense-chunk case that produced empty-string collapse under raw /completion)",
        lines=[
            "「ケイト、ルリ、音夢くん、みんな揃った?」と維多教授が尋ねた。",
            "ケイトは頷き、ルリは笑顔で答えた。「はい、揃いました」",
            "音夢くんだけは少し遅れて到着した。",
        ],
        targets=[(0, "ケイト"), (0, "ルリ"), (0, "音夢くん"), (0, "維多教授"), (2, "音夢くん")],
    ),
]

TRANSLATION_INSTRUCTION = (
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


def parse_json_response(text: str):
    """Mirrors pyplayground.webnovels.llm_translate.parse_json_response --
    first complete JSON value, ignoring trailing content. Reimplemented here
    (not imported) since this script is meant to run standalone against
    whatever endpoint you point it at; keep logic in sync if that one changes.
    """
    value, _end = json.JSONDecoder().raw_decode(text)
    return value


def build_masked_lines(case: TestCase, fmt: SentinelFormat) -> List[str]:
    lines = list(case.lines)
    for n, (line_idx, word) in enumerate(case.targets, start=1):
        if word not in lines[line_idx]:
            raise ValueError(f"{word!r} not found in line {line_idx} of {case.description!r}")
        lines[line_idx] = lines[line_idx].replace(word, fmt.wrap(word, n), 1)
    return lines


def call_llm_chat(endpoint: str, model: str, source_lines: List[str], enable_thinking: bool, timeout: int) -> Optional[dict]:
    """POST to /v1/chat/completions with chat_template_kwargs controlling
    enable_thinking. Returns {"content": ..., "reasoning_content": ... or None}
    or None on failure.
    """
    user_content = TRANSLATION_INSTRUCTION.format(
        source_lang="Japanese",
        target_lang="English",
        lines_json=json.dumps(source_lines, ensure_ascii=False),
    )
    if not enable_thinking:
        # Belt-and-suspenders per Qwen's own docs: /no_think as a text-level
        # hint works even outside strict chat_template_kwargs support, in
        # addition to the kwarg itself.
        user_content += "\n/no_think"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
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


def check_survival(case: TestCase, fmt: SentinelFormat, output_lines: List[str]) -> List[dict]:
    results = []
    for n, (line_idx, word) in enumerate(case.targets, start=1):
        if line_idx >= len(output_lines):
            results.append({"id": n, "word": word, "found": False, "reason": "output shorter than input (line dropped)"})
            continue
        out_line = _normalize(output_lines[line_idx])
        match = fmt.pattern(n).search(out_line)
        if not match:
            empty_flag = " (line was empty)" if not out_line.strip() else ""
            results.append({"id": n, "word": word, "found": False, "reason": f"sentinel not found in output line{empty_flag}"})
            continue
        if fmt.opaque:
            results.append({"id": n, "word": word, "found": True, "unchanged": True})
        else:
            inner = match.group(1)
            results.append({"id": n, "word": word, "found": True, "unchanged": inner == word, "inner_value": inner})
    return results


def run_suite(endpoint: str, model: str, formats: List[SentinelFormat], enable_thinking: bool, timeout: int, raw_dump: list) -> dict:
    label = f"{model} thinking={enable_thinking}"
    scoreboard = {fmt.name: {"pass": 0, "fail": 0} for fmt in formats}
    reasoning_lengths = []

    for case in TEST_CASES:
        print(f"=== [{label}] {case.description} ===")
        for fmt in formats:
            masked_lines = build_masked_lines(case, fmt)
            result = call_llm_chat(endpoint, model, masked_lines, enable_thinking, timeout)
            raw_dump.append({"label": label, "case": case.description, "format": fmt.name, "input": masked_lines, "raw_result": result})

            if result is None:
                scoreboard[fmt.name]["fail"] += len(case.targets)
                print(f"  [{fmt.name}] REQUEST FAILED")
                continue

            if result["reasoning_content"]:
                reasoning_lengths.append(len(result["reasoning_content"]))
                print(f"  [{fmt.name}] (reasoning_content present, {len(result['reasoning_content'])} chars -- server separated it out cleanly)")

            content = strip_code_fence(result["content"])
            try:
                parsed = parse_json_response(content)
                if not isinstance(parsed, list):
                    raise ValueError("not a list")
                output_lines = [str(x) for x in parsed]
            except (json.JSONDecodeError, ValueError) as e:
                scoreboard[fmt.name]["fail"] += len(case.targets)
                leaked = "<think>" in content or "Okay, let" in content or "Let me" in content
                hint = " -- looks like leaked reasoning in content despite enable_thinking={}".format(enable_thinking) if leaked else ""
                print(f"  [{fmt.name}] JSON parse failed: {e}{hint}")
                print(f"      content preview: {content[:200]!r}")
                continue

            results = check_survival(case, fmt, output_lines)
            for r in results:
                ok = r["found"] and r.get("unchanged", True)
                scoreboard[fmt.name]["pass" if ok else "fail"] += 1
                status = "OK" if ok else "FAIL"
                detail = "" if ok else f" -- {r.get('reason', '')}{(' got: ' + repr(r.get('inner_value'))) if 'inner_value' in r and not r.get('unchanged', True) else ''}"
                print(f"  [{fmt.name}] id={r['id']} word={r['word']!r}: {status}{detail}")
        print()

    if reasoning_lengths:
        print(f"[{label}] reasoning_content seen in {len(reasoning_lengths)} response(s), avg {sum(reasoning_lengths)//len(reasoning_lengths)} chars\n")

    return scoreboard


def print_summary(label: str, scoreboard: dict) -> None:
    print(f"=== Summary: {label} ===")
    for fmt_name, score in scoreboard.items():
        total = score["pass"] + score["fail"]
        rate = (score["pass"] / total * 100) if total else 0.0
        print(f"  {fmt_name}: {score['pass']}/{total} survived intact ({rate:.0f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test sentinel survival via /v1/chat/completions with enable_thinking control")
    parser.add_argument("--endpoint", required=True, help="llama-server base URL, e.g. http://flyyn:10002 (must be started with --jinja)")
    parser.add_argument("--model", default="qwen3-14b", help="Label only -- llama-server serves whatever's currently loaded")
    parser.add_argument("--thinking", choices=["on", "off", "both"], default="off", help="Default 'off' matches the DESIGN.md decision for structured-extraction-style tasks")
    parser.add_argument("--format", choices=list(SENTINEL_FORMATS) + ["all"], default="all")
    parser.add_argument("--timeout", type=int, default=180, help="Higher default than the /completion script -- thinking mode, even when nominally disabled, can be slower to first token")
    parser.add_argument("--json-out", help="Optional path to dump raw request/response pairs for manual inspection")
    args = parser.parse_args()

    formats = list(SENTINEL_FORMATS.values()) if args.format == "all" else [SENTINEL_FORMATS[args.format]]
    raw_dump: list = []

    thinking_modes = [False, True] if args.thinking == "both" else [args.thinking == "on"]

    print(f"Endpoint: {args.endpoint} (expects --jinja on the server)")
    print(f"Testing {len(formats)} format(s) x {len(TEST_CASES)} case(s) x thinking={thinking_modes}\n")

    scoreboards = []
    for enable_thinking in thinking_modes:
        scoreboards.append((enable_thinking, run_suite(args.endpoint, args.model, formats, enable_thinking, args.timeout, raw_dump)))

    for enable_thinking, sb in scoreboards:
        print_summary(f"{args.model} thinking={enable_thinking}", sb)
        print()

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, indent=2, ensure_ascii=False)
        print(f"Raw request/response pairs saved to {args.json_out}")


if __name__ == "__main__":
    main()
