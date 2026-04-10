#!/usr/bin/env python3
"""Git commit message generator using a local llama-server.

Analyzes staged changes and generates a conventional commit message
using a local OpenAI-compatible LLM endpoint. No external dependencies.

Commands:
    generate    Preview commit message (default)
    commit      Generate message and optionally commit

Options:
    --endpoint URL      LLM endpoint (default: http://case.modmtrx.net:10001)
    --no-prompt         Skip confirmation before committing
    --include-unstaged  Include unstaged changes in analysis
    --verbose           Info-level logging
    --debug             Debug-level logging (includes prompt and raw response)

Environment Variables:
    LLAMA_ENDPOINT  Override --endpoint default
    LLAMA_MODEL     Override auto-detected model name
    MAX_TOKENS      Max tokens to generate (default: 1024)

Examples:
    git-commit-gen.py
    git-commit-gen.py commit
    git-commit-gen.py commit --no-prompt
    git-commit-gen.py --endpoint http://flyyn.modmtrx.net:10000 generate
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://case.modmtrx.net:10000"
LARGE_FILE_THRESHOLD = 20  # files — above this, switch to stat-only mode
LARGE_DIFF_THRESHOLD = 6000  # characters — above this, switch to stat-only mode
DEFAULT_MAX_TOKENS = 2048
REQUEST_TIMEOUT = 180  # seconds — thinking models need more time
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FileChange:
    """A single changed file with its add/delete line counts."""

    name: str
    additions: int
    deletions: int


@dataclass
class DiffResult:
    """Collected diff data including file list, totals, and optional patch text."""

    files: list[FileChange] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0
    patch: str = ""  # full diff text; empty in large/stat-only mode
    large_mode: bool = False  # True when file count or diff size exceeded threshold


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a git subcommand and return the CompletedProcess result."""
    cmd = ["git"] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.debug("git stderr: %s", result.stderr.strip())
    return result


def is_git_repo() -> bool:
    """Return True if the current working directory is inside a git repository."""
    r = _git("rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def get_branch() -> str:
    """Return the current git branch name, or 'unknown' on failure."""
    r = _git("rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _parse_numstat(numstat_output: str) -> dict[str, tuple[int, int]]:
    """Parse `git diff --numstat` into {filename: (additions, deletions)}.

    Binary files report '-' for both counts; we store (0, 0) for those.
    """
    counts: dict[str, tuple[int, int]] = {}
    for line in numstat_output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            add_s, del_s, name = parts
            try:
                counts[name.strip()] = (int(add_s), int(del_s))
            except ValueError:
                counts[name.strip()] = (0, 0)
    return counts


def get_diff(include_unstaged: bool = False) -> DiffResult:
    """Collect staged (and optionally unstaged) changes.

    Chooses between patch mode (small changesets) and stat-only mode
    (large changesets / bulk renames) based on file count and diff size.
    """
    extra: list[str] = [] if include_unstaged else ["--cached"]

    numstat_r = _git("diff", *extra, "--numstat")
    if numstat_r.returncode != 0:
        logger.error("git diff --numstat failed: %s", numstat_r.stderr.strip())
        return DiffResult()

    counts = _parse_numstat(numstat_r.stdout)
    if not counts:
        logger.info("No staged changes detected")
        return DiffResult()

    files = [FileChange(name=name, additions=add, deletions=del_) for name, (add, del_) in counts.items()]
    total_add = sum(f.additions for f in files)
    total_del = sum(f.deletions for f in files)

    logger.info(
        "Staged: %d file(s)  +%d -%d lines  branch=%s",
        len(files),
        total_add,
        total_del,
        get_branch(),
    )

    if len(files) >= LARGE_FILE_THRESHOLD:
        logger.info(
            "File count %d >= threshold %d — using stat-only mode",
            len(files),
            LARGE_FILE_THRESHOLD,
        )
        return DiffResult(files=files, total_additions=total_add, total_deletions=total_del, large_mode=True)

    patch_r = _git("diff", *extra)
    if patch_r.returncode != 0:
        logger.warning("git diff (patch) failed — falling back to stat-only mode")
        return DiffResult(files=files, total_additions=total_add, total_deletions=total_del, large_mode=True)

    patch = patch_r.stdout
    logger.debug("Patch size: %d characters", len(patch))

    # Single-file changes always get patch context — truncate rather than drop.
    # Large mode (stat-only) only makes sense for multi-file changesets where
    # the file list itself tells the story (e.g. bulk moves/renames).
    if len(files) == 1 and len(patch) > LARGE_DIFF_THRESHOLD:
        patch = patch[:LARGE_DIFF_THRESHOLD]
        logger.info(
            "Single file diff truncated to %d chars for context window",
            LARGE_DIFF_THRESHOLD,
        )
    elif len(patch) > LARGE_DIFF_THRESHOLD:
        logger.info(
            "Diff size %d chars > threshold %d — using stat-only mode",
            len(patch),
            LARGE_DIFF_THRESHOLD,
        )
        return DiffResult(files=files, total_additions=total_add, total_deletions=total_del, large_mode=True)

    logger.info("Using patch mode (diff: %d chars)", len(patch))
    return DiffResult(files=files, total_additions=total_add, total_deletions=total_del, patch=patch, large_mode=False)


def has_test_files(files: list[FileChange]) -> bool:
    """Return True if any changed file looks like a test or spec file."""
    return any("test" in f.name.lower() or "spec" in f.name.lower() for f in files)


def infer_scope(files: list[FileChange]) -> Optional[str]:
    """Return a scope string if every changed file shares a common subdirectory.

    Files at the repo root (no parent directory) are excluded from scope
    inference — a bare filename is never a useful scope.
    """
    if not files:
        return None
    # Only consider files that are inside at least one directory level
    tops = [Path(f.name).parts[0] for f in files if len(Path(f.name).parts) > 1]
    if not tops:
        return None
    if len(set(tops)) == 1 and tops[0] != ".":
        logger.debug("Inferred scope: %s", tops[0])
        return tops[0]
    return None


# ---------------------------------------------------------------------------
# LLM client — stdlib urllib only
# ---------------------------------------------------------------------------


class LLMClient:
    """Minimal OpenAI-compatible HTTP client using urllib."""

    def __init__(self, endpoint: str, model: Optional[str], max_tokens: int) -> None:
        """Store connection config and initialise the verified flag."""
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self._verified = False

    # -- internal HTTP helpers -----------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.endpoint}{path}"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        logger.debug("POST %s  (%d bytes)", url, len(body))
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode()
            logger.debug("HTTP %d  response: %d bytes", resp.status, len(raw))
            return json.loads(raw)

    def _get(self, path: str) -> dict:
        url = f"{self.endpoint}{path}"
        logger.debug("GET %s", url)
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # -- public interface ----------------------------------------------------

    def detect_model(self) -> str:
        """Query /v1/models and return the first advertised model ID."""
        try:
            data = self._get("/v1/models")
            model_id = data["data"][0]["id"]
            logger.info("Auto-detected model: %s", model_id)
            return model_id
        except Exception as e:
            logger.debug("Model auto-detection failed: %s", e)
            return "unknown"

    def verify(self) -> bool:
        """Return True if the LLM server responds to a models list request."""
        try:
            self._get("/v1/models")
            self._verified = True
            logger.info("LLM server reachable: %s", self.endpoint)
            return True
        except Exception as e:
            logger.error("LLM server unreachable at %s — %s", self.endpoint, e)
            return False

    def complete(self, prompt: str) -> str:
        """Send the prompt and return the model reply, retrying on transient errors."""
        model = self.model or self.detect_model()

        logger.info("Request — model=%s  max_tokens=%d", model, self.max_tokens)
        logger.debug("--- PROMPT START (%d chars) ---\n%s\n--- PROMPT END ---", len(prompt), prompt)

        if not self._verified and not self.verify():
            return _fallback_message()

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0.3,
            "enable_thinking": False,  # suppress Qwen3 reasoning tokens
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                t0 = time.monotonic()
                data = self._post("/v1/chat/completions", payload)
                elapsed = time.monotonic() - t0

                logger.debug(
                    "--- RAW JSON (attempt %d, %.2fs) ---\n%s\n--- END ---",
                    attempt, elapsed, json.dumps(data, indent=2),
                )

                message = data.get("choices", [{}])[0].get("message", {})
                # content is empty when thinking mode leaks into reasoning_content
                content = (message.get("content") or "").strip()
                reasoning = (message.get("reasoning_content") or "").strip()

                logger.debug(
                    "content: %d chars  reasoning_content: %d chars",
                    len(content),
                    len(reasoning),
                )

                if content:
                    logger.info("Response in %.2fs (%d chars)", elapsed, len(content))
                    return content

                if reasoning:
                    # The thinking chain precedes the actual answer — find where
                    # the commit message starts by looking for a conventional
                    # commit type prefix and discard everything before it.
                    match = re.search(
                        r'^(feat|fix|refactor|docs|chore|test|ci)(\(.*?\))?:',
                        reasoning, re.MULTILINE,
                    )
                    answer = reasoning[match.start():].strip() if match else reasoning.strip()
                    logger.warning(
                        "content empty — extracted answer from reasoning_content "
                        "(%d chars -> %d chars after strip)",
                        len(reasoning), len(answer),
                    )
                    logger.info("Response (reasoning) in %.2fs (%d chars)", elapsed, len(answer))
                    return answer

                logger.warning("Empty response from LLM (attempt %d/%d)", attempt, MAX_RETRIES)

            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                logger.error("HTTP %d on attempt %d/%d: %s", e.code, attempt, MAX_RETRIES, body)
                if e.code < 500:
                    break  # 4xx — retrying won't help
            except urllib.error.URLError as e:
                logger.error("Connection error on attempt %d/%d: %s", attempt, MAX_RETRIES, e.reason)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                logger.error("Parse error on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
                break
            except Exception as e:
                logger.error("Unexpected error on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
                break

            if attempt < MAX_RETRIES:
                wait = 4 * attempt
                logger.info("Retrying in %ds ...", wait)
                time.sleep(wait)

        return _fallback_message()


def _fallback_message() -> str:
    logger.warning("LLM unavailable or returned no usable content — using fallback")
    return (
        "chore: update codebase\n\n"
        "Changes:\n"
        "- Applied modifications (LLM unavailable; edit manually)\n\n"
        "Files:\n"
        "- See diff for details"
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_prompt(diff: DiffResult) -> str:
    """Build the LLM prompt from diff data, choosing patch or stat-only context."""
    scope = infer_scope(diff.files)
    scope_str = f"({scope})" if scope else ""

    file_list = "\n".join(f"  {f.name} (+{f.additions}, -{f.deletions})" for f in diff.files)

    if diff.large_mode:
        context_block = (
            f"NOTE: Large changeset — {len(diff.files)} files "
            f"(+{diff.total_additions}, -{diff.total_deletions} lines total). "
            "Full diff not provided; infer intent from file paths and line counts.\n\n"
            f"Files Modified:\n{file_list}"
        )
    else:
        context_block = f"Diff:\n{diff.patch}\n\nFiles Modified:\n{file_list}"

    testing_section = (
        "\n\nTesting:\n- [note on test coverage — test files were modified]"
        if has_test_files(diff.files) else ""
    )

    logger.debug(
        "Prompt context — mode=%s  files=%d  scope=%s  tests=%s",
        "stat-only" if diff.large_mode else "patch",
        len(diff.files),
        scope or "none",
        has_test_files(diff.files),
    )

    return f"""Generate a git commit message for the following staged changes.

Rules:
- First line: conventional commit format — type{scope_str}: short description (72 chars max)
  Valid types: feat, fix, refactor, docs, chore, test, ci
- Omit scope if it is not obvious from the file paths.
- Be concise. One short sentence per bullet. Do not pad or over-explain.
- Output ONLY the commit message. No preamble, no explanation, no markdown fences.

Format:
type{scope_str}: short description

Changes:
- [concise bullet per logical change — what and why]{testing_section}

Files:
{file_list}

---
{context_block}
"""


# ---------------------------------------------------------------------------
# Shared pipeline
# ---------------------------------------------------------------------------


def _build_message(args: argparse.Namespace) -> Optional[str]:
    if not is_git_repo():
        print("Error: not a git repository", file=sys.stderr)
        return None

    diff = get_diff(args.include_unstaged)
    if not diff.files:
        print("Error: no staged changes found", file=sys.stderr)
        return None

    endpoint = os.environ.get("LLAMA_ENDPOINT", args.endpoint)
    model = os.environ.get("LLAMA_MODEL") or None
    max_tokens = int(os.environ.get("MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))

    logger.info("Config — endpoint=%s  model=%s  max_tokens=%d", endpoint, model or "auto", max_tokens)

    client = LLMClient(endpoint, model, max_tokens)
    prompt = build_prompt(diff)
    return client.complete(prompt)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate and print a commit message without committing. Returns exit code."""
    message = _build_message(args)
    if not message:
        return 1
    print("\n" + "─" * 72)
    print(message)
    print("─" * 72 + "\n")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    """Generate a commit message and run git commit, with optional confirmation. Returns exit code."""
    message = _build_message(args)
    if not message:
        return 1

    print("\n" + "─" * 72)
    print(message)
    print("─" * 72 + "\n")

    if not args.no_prompt:
        if input("Commit with this message? (y/n): ").strip().lower() != "y":
            print("Aborted.")
            return 0

    try:
        subprocess.run(["git", "commit", "-m", message], check=True, timeout=15)
        logger.info("Committed successfully")
        print("Committed.")
    except subprocess.CalledProcessError as e:
        logger.error("git commit failed: %s", e)
        return 1
    except subprocess.TimeoutExpired:
        logger.error("git commit timed out")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse CLI arguments, configure logging, and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(
        description="Generate git commit messages via local LLM — no external dependencies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  LLAMA_ENDPOINT  LLM server URL (overrides --endpoint)
  LLAMA_MODEL     Model name (auto-detected if unset)
  MAX_TOKENS      Max tokens to generate (default: 1024)
        """,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="generate",
        choices=["generate", "commit"],
        help="Command to run (default: generate)",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        metavar="URL",
        help=f"LLM endpoint URL (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip y/n confirmation before committing",
    )
    parser.add_argument(
        "--include-unstaged",
        action="store_true",
        help="Include unstaged working tree changes in analysis",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Info-level logging: endpoint, model, file counts, timing",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug-level logging: full prompt, raw LLM response, git commands",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,  # logs to stderr; commit message prints to stdout
    )

    logger.debug("Args: %s", vars(args))

    return cmd_commit(args) if args.command == "commit" else cmd_generate(args)


if __name__ == "__main__":
    sys.exit(main())
