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
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from openai import OpenAI, APIConnectionError, APIError, APITimeoutError

logger = logging.getLogger(__name__)

# TRACE level sits below DEBUG — used for per-token stream logging.
# Enabled only with --trace; --debug does not activate it.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")
trace_logger = logging.getLogger(f"{__name__}.trace")

DEFAULT_ENDPOINT = "http://case.modmtrx.net:10001"
LARGE_FILE_THRESHOLD = 20    # files — above this, switch to stat-only mode
LARGE_DIFF_THRESHOLD = 6000  # characters — above this, switch to stat-only mode
DEFAULT_MAX_TOKENS = 16384   # match Kilo output limit — thinking models need room
CONNECT_TIMEOUT = 10         # seconds to establish connection
READ_TIMEOUT = 300           # seconds to wait for streaming to complete
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
# LLM client — openai library with streaming
# ---------------------------------------------------------------------------


class LLMClient:
    """OpenAI-compatible streaming client for llama-server."""

    def __init__(self, endpoint: str, model: Optional[str], max_tokens: int) -> None:
        """Initialise the OpenAI client pointed at the local llama-server."""
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self._client = OpenAI(
            base_url=f"{self.endpoint}/v1",
            api_key="sk-no-key-required",
            timeout=CONNECT_TIMEOUT,
            max_retries=0,  # we handle retries ourselves
        )

    def detect_model(self) -> str:
        """Query /v1/models and return the first advertised model ID."""
        try:
            models = self._client.models.list()
            if models.data:
                model_id = models.data[0].id
                logger.info("Auto-detected model: %s", model_id)
                return model_id
        except Exception as e:
            logger.debug("Model auto-detection failed: %s", e)
        return "unknown"

    def complete(self, system: str, user: str) -> str:
        """Stream a chat completion and return the assembled content string.

        Uses a system prompt + user message split so the model receives
        instructions and diff content separately. Streams tokens to avoid
        timeout issues with thinking models that generate long reasoning chains
        before producing output. Reasoning tokens (reasoning_content deltas)
        are discarded; only content deltas are collected.

        Falls back to extracting the commit message from reasoning_content if
        the content stream is empty (thinking forced on server-side).
        """
        model = self.model or self.detect_model()

        logger.info("Request — endpoint=%s  model=%s  max_tokens=%d",
                    self.endpoint, model, self.max_tokens)
        logger.debug("--- SYSTEM PROMPT ---\n%s\n--- END ---", system)
        logger.debug("--- USER PROMPT (%d chars) ---\n%s\n--- END ---", len(user), user)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                content_chunks: list[str] = []
                reasoning_chunks: list[str] = []
                token_count = 0

                logger.debug("Opening stream (attempt %d/%d)", attempt, MAX_RETRIES)

                with self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                    stream=True,
                    timeout=READ_TIMEOUT,
                ) as stream:
                    for chunk in stream:
                        delta = chunk.choices[0].delta if chunk.choices else None
                        if delta is None:
                            continue

                        # Standard content token
                        if delta.content:
                            content_chunks.append(delta.content)
                            token_count += 1
                            trace_logger.log(TRACE, "content token: %r", delta.content)

                        # Reasoning token — collect separately, don't output
                        reasoning = getattr(delta, "reasoning_content", None)
                        if reasoning:
                            reasoning_chunks.append(reasoning)
                            trace_logger.log(TRACE, "reasoning token: %r", reasoning)

                content = "".join(content_chunks).strip()
                reasoning = "".join(reasoning_chunks).strip()

                logger.debug(
                    "Stream complete — content: %d chars  reasoning: %d chars  tokens: %d",
                    len(content), len(reasoning), token_count,
                )

                if content:
                    answer = _strip_thinking(content)
                    logger.info("Response complete (%d chars -> %d chars after strip)",
                                len(content), len(answer))
                    return answer

                # content empty — thinking was forced on server-side
                # extract the commit message from the reasoning stream
                if reasoning:
                    answer = _strip_thinking(reasoning)
                    logger.warning(
                        "content stream empty — extracted answer from reasoning "
                        "(%d chars -> %d chars); thinking is forced on at the server",
                        len(reasoning), len(answer),
                    )
                    return answer

                logger.warning("Empty response from LLM (attempt %d/%d)", attempt, MAX_RETRIES)

            except APIConnectionError as e:
                logger.error("Connection error on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
            except APITimeoutError as e:
                logger.error("Timeout on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
            except APIError as e:
                logger.error("API error on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
                if hasattr(e, "status_code") and e.status_code and e.status_code < 500:
                    break  # 4xx — retrying won't help
            except Exception as e:
                logger.error("Unexpected error on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
                break

            if attempt < MAX_RETRIES:
                logger.info("Retrying in 4s ...")
                time.sleep(4)

        return _fallback_message()


def _strip_thinking(text: str) -> str:
    """Strip thinking preamble from model output.

    Some models emit a reasoning chain before the actual answer regardless
    of whether thinking mode is enabled. We find the first line that looks
    like a conventional commit subject and return everything from there.
    If no match is found the full text is returned unchanged.
    """
    match = re.search(
        r'^(feat|fix|refactor|docs|chore|test|ci)(\(.*?\))?:',
        text, re.MULTILINE,
    )
    if match:
        stripped = text[match.start():].strip()
        logger.debug("Stripped %d chars of thinking preamble", match.start())
        return stripped
    return text.strip()


def _fallback_message() -> str:
    """Return a minimal valid commit message when the LLM is unavailable."""
    logger.warning("LLM unavailable or returned no content — using fallback")
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


def build_prompt(diff: DiffResult) -> tuple[str, str]:
    """Build system and user prompts from diff data.

    Returns a (system, user) tuple. The system prompt carries the format
    rules; the user message carries the diff content. Splitting them gives
    the model clearer role separation and tends to produce cleaner output.
    """
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

    system = f"""You are a git commit message generator.
Output ONLY the commit message — no preamble, no explanation, no markdown fences.

Format rules:
- First line: conventional commit — type{scope_str}: short description (72 chars max)
  Valid types: feat, fix, refactor, docs, chore, test, ci
- Omit scope if it is not obvious from the file paths.
- Be concise. One short sentence per bullet. Do not pad or over-explain.

Message format:
type{scope_str}: short description

Changes:
- [concise bullet per logical change — what and why]{testing_section}

Files:
{file_list}"""

    user = context_block

    return system, user


# ---------------------------------------------------------------------------
# Shared pipeline
# ---------------------------------------------------------------------------


def _build_message(args: argparse.Namespace) -> Optional[str]:
    """Run the full pipeline: diff -> prompt -> LLM -> commit message string."""
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
    system, user = build_prompt(diff)
    return client.complete(system, user)


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
        help="Debug-level logging: full prompt, system prompt, git commands, stream summary",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Trace-level logging: every individual stream token (implies --debug)",
    )

    args = parser.parse_args()

    if args.trace:
        level = TRACE
    elif args.debug:
        level = logging.DEBUG
    elif args.verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,  # logs to stderr; commit message prints to stdout
    )
    # trace_logger inherits root level; no extra config needed

    logger.debug("Args: %s", vars(args))

    return cmd_commit(args) if args.command == "commit" else cmd_generate(args)


if __name__ == "__main__":
    sys.exit(main())
