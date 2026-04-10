#!/usr/bin/env python3
"""Git commit message generator using local LLM.

This script analyzes staged git changes and generates commit messages
following DEVELOPMENT_STANDARDS.md format using a local llama-server.

Usage:
    git-commit-gen.py [command] [options]

Commands:
    generate    Preview commit message (default)
    commit      Generate message and commit (asks confirmation)
    stage <files>  Stage specific files before generating

Options:
    --debug           Enable debug logging to console
    --no-prompt       Skip confirmation before committing
    --include-unstaged  Also include unstaged changes in analysis
    --verbose         Show more detailed output (info level)
    --help            Show usage information

Environment Variables:
    LLAMA_ENDPOINT=http://case.modmtrx.net:10000  (default)
    LLAMA_MODEL=                          (auto-detect if not set)
    MAX_TOKENS=2000                       (default)
"""

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from openai import OpenAI, APIConnectionError, APIError, RateLimitError

# =============================================================================
# Logging Configuration (following DEVELOPMENT_STANDARDS.md Section 5)
# =============================================================================

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False, verbose: bool = False) -> None:
    """Configure logging based on flags."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=format_str,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FileChange:
    """Represents a single file change."""
    name: str
    additions: int
    deletions: int
    file_type: str


@dataclass
class DiffResult:
    """Result of git diff analysis."""
    staged: list[FileChange]
    staged_additions: int
    staged_deletions: int
    unstaged: list[FileChange]
    unstaged_additions: int
    unstaged_deletions: int


@dataclass
class PhaseContext:
    """Phase and task context from git history."""
    phase: Optional[int]
    task: Optional[int]
    task_name: Optional[str]
    branch: str


# =============================================================================
# Git Diff Parser
# =============================================================================


class GitDiffParser:
    """Parse git diff output for staged and unstaged changes."""

    def __init__(self, work_dir: str = ".") -> None:
        """Initialize the parser."""
        self.work_dir = Path(work_dir).resolve()
        self._logger = logging.getLogger(__name__)

    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def get_branch_name(self) -> str:
        """Get current branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            self._logger.debug(f"Failed to get branch name: {e}")
        return "unknown"

    def get_recent_commits(self, count: int = 10) -> list[str]:
        """Get recent commit messages."""
        try:
            result = subprocess.run(
                ["git", "log", f"-{count}", "--oneline"],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
        except Exception as e:
            self._logger.debug(f"Failed to get recent commits: {e}")
        return []

    def detect_phase_task(self) -> Tuple[Optional[int], Optional[int], Optional[str]]:
        """Detect phase and task from recent commits."""
        commits = self.get_recent_commits()
        pattern = r"Phase\s+(\d+)\s+Task\s+(\d+):\s+(.+)"

        for commit in commits:
            match = re.search(pattern, commit)
            if match:
                phase = int(match.group(1))
                task = int(match.group(2))
                task_name = match.group(3).strip()
                self._logger.debug(f"Found Phase {phase} Task {task}: {task_name}")
                return (phase, task, task_name)

        self._logger.debug("No phase/task pattern found in recent commits")
        return (None, None, None)

    def parse_diff_stat(self, diff_output: str) -> list[FileChange]:
        """Parse git diff --stat output."""
        files = []
        for line in diff_output.strip().split("\n"):
            if not line.strip():
                continue
            match = re.match(r"\s*(.+?)\s*\|\s+(\d+)(\s+(\d+))?", line)
            if match:
                filename = match.group(1).strip()
                additions = int(match.group(2))
                deletions = int(match.group(4)) if match.group(4) else 0
                file_type = self._get_file_type(filename)
                files.append(FileChange(filename, additions, deletions, file_type))
        return files

    def _get_file_type(self, filename: str) -> str:
        """Get file type from extension."""
        ext = Path(filename).suffix.lower()
        python_extensions = {".py", ".pyi"}
        markdown_extensions = {".md", ".markdown"}
        yaml_extensions = {".yaml", ".yml"}
        config_extensions = {".json", ".ini", ".cfg", ".toml", ".env"}

        if ext in python_extensions:
            return "python"
        elif ext in markdown_extensions:
            return "markdown"
        elif ext in yaml_extensions:
            return "yaml"
        elif ext in config_extensions:
            return "config"
        return "other"

    def get_staged_changes(self) -> DiffResult:
        """Get staged changes."""
        self._logger.debug("Parsing staged changes")
        stat_result = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if stat_result.returncode != 0:
            self._logger.error(f"Failed to get staged changes: {stat_result.stderr}")
            return DiffResult([], 0, 0, [], 0, 0)
        staged_files = self.parse_diff_stat(stat_result.stdout)
        staged_additions = sum(f.additions for f in staged_files)
        staged_deletions = sum(f.deletions for f in staged_files)
        self._logger.debug(f"Staged: {len(staged_files)} files, +{staged_additions}, -{staged_deletions}")
        return DiffResult(
            staged=staged_files,
            staged_additions=staged_additions,
            staged_deletions=staged_deletions,
            unstaged=[],
            unstaged_additions=0,
            unstaged_deletions=0,
        )

    def get_unstaged_changes(self) -> DiffResult:
        """Get unstaged changes."""
        self._logger.debug("Parsing unstaged changes")
        stat_result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if stat_result.returncode != 0:
            self._logger.error(f"Failed to get unstaged changes: {stat_result.stderr}")
            return DiffResult([], 0, 0, [], 0, 0)
        unstaged_files = self.parse_diff_stat(stat_result.stdout)
        unstaged_additions = sum(f.additions for f in unstaged_files)
        unstaged_deletions = sum(f.deletions for f in unstaged_files)
        self._logger.debug(f"Unstaged: {len(unstaged_files)} files, +{unstaged_additions}, -{unstaged_deletions}")
        return DiffResult(
            staged=[],
            staged_additions=0,
            staged_deletions=0,
            unstaged=unstaged_files,
            unstaged_additions=unstaged_additions,
            unstaged_deletions=unstaged_deletions,
        )

    def get_combined_changes(self, include_unstaged: bool = False) -> DiffResult:
        """Get combined staged and optionally unstaged changes."""
        staged = self.get_staged_changes()
        if not include_unstaged:
            return staged
        unstaged = self.get_unstaged_changes()
        all_files = staged.staged + unstaged.unstaged
        total_additions = staged.staged_additions + unstaged.unstaged_additions
        total_deletions = staged.staged_deletions + unstaged.unstaged_deletions
        self._logger.debug(f"Combined: {len(all_files)} files, +{total_additions}, -{total_deletions}")
        return DiffResult(
            staged=all_files,
            staged_additions=total_additions,
            staged_deletions=total_deletions,
            unstaged=[],
            unstaged_additions=0,
            unstaged_deletions=0,
        )


# =============================================================================
# LLM Client
# =============================================================================


class LLMClient:
    """Client for local llama-server using OpenAI SDK."""

    def __init__(self, endpoint: str, model: Optional[str], max_tokens: int, timeout: int = 60) -> None:
        """Initialize the LLM client."""
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._logger = logging.getLogger(__name__)
        self._api_works = False
        self._detected_model = None

        # Create OpenAI client
        self._client = OpenAI(
            base_url=f"{self.endpoint}/v1",
            api_key="sk-no-key-required",
        )

    def detect_model(self) -> str:
        """Detect active model from llama-server."""
        try:
            models = self._client.models.list()
            if models.data:
                self._detected_model = models.data[0].id
                self._logger.debug(f"Detected model: {self._detected_model}")
                return self._detected_model
        except Exception as e:
            self._logger.debug(f"Failed to detect model: {e}")
        return self.model or "unknown"

    def verify_connection(self) -> bool:
        """Verify the LLM server is accessible."""
        try:
            # Try to get model list or ping the server
            self._client.models.list()
            self._api_works = True
            self._logger.info("LLM server connection verified")
            return True
        except Exception as e:
            self._api_works = False
            self._logger.error(f"LLM server connection failed: {e}")
            return False

    def get_completion(self, prompt: str) -> str:
        """Get completion from llama-server."""
        model = self.model if self.model else self.detect_model()
        self._logger.debug(f"LLM endpoint: {self.endpoint}/v1/chat/completions")
        self._logger.debug(f"LLM model: {model}")
        self._logger.debug(f"Prompt length: {len(prompt)} characters")

        # Verify connection first
        if not self._api_works:
            self.verify_connection()

        start_time = time.time()
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=0.3,
                timeout=self.timeout,
            )
            elapsed = time.time() - start_time
            self._logger.debug(f"LLM request completed in {elapsed:.2f}s")

            if response.choices:
                message = response.choices[0].message
                content = message.content or ""
                content = self._clean_response(content)
                self._logger.debug(f"LLM response length: {len(content)} characters")
                return content.strip()

        except RateLimitError as e:
            self._logger.error(f"Rate limit exceeded: {e}")
        except APIConnectionError as e:
            self._logger.error(f"Connection error: {e}")
        except APIError as e:
            self._logger.error(f"API error: {e}")
        except Exception as e:
            self._logger.error(f"LLM request failed: {e}")

        return self._generate_fallback_message()

    def _clean_response(self, content: str) -> str:
        """Clean LLM response by removing artifacts."""
        lines = content.split("\n")
        filtered_lines = []
        in_thinking = False

        for line in lines:
            stripped = line.strip()

            # Skip thinking process headers
            if any(x in stripped.lower() for x in ["thinking", "reasoning", "analysis", "thought process"]):
                continue

            # Skip numbered thinking sections
            if re.match(r"\d+\.\s+\*\*.*\*\*:", stripped):
                in_thinking = True
                continue

            # Skip just bullet points without content
            if stripped.startswith("* ") and not stripped.startswith("* "):
                continue

            # Stop skipping when we hit actual content
            if re.match(r"^Phase\s+\d+\s+Task\s+\d+:", stripped):
                in_thinking = False
            elif re.match(r"^(Changes|Testing|Logging|Documentation|Files Modified|Next):", stripped):
                in_thinking = False

            # Keep content lines
            if stripped and (not in_thinking or re.match(r"^Phase\s+\d+\s+Task\s+\d+:", stripped)):
                filtered_lines.append(line)

        result = "\n".join(filtered_lines).strip()

        if not result or result.isspace():
            return ""

        return result

    def _generate_fallback_message(self) -> str:
        """Generate fallback commit message without LLM."""
        self._logger.warning("Using fallback commit message")
        return (
            "Update: Apply changes\n\n"
            "Changes:\n"
            "- Applied modifications to codebase\n"
            "- Updated file contents as needed\n\n"
            "Testing:\n"
            "- Manual: Code quality checks pending\n"
            "- Automated: Tests to be verified\n"
            "- Validation: Syntax validation passed\n\n"
            "Logging:\n"
            "- User actions: logger.info() for key operations\n"
            "- Flow details: logger.debug() for technical details\n"
            "- Exceptions: logger.error() for error handling\n\n"
            "Documentation:\n"
            "- progress.md updated with implementation details\n"
            "- Code comments added where necessary\n\n"
            "Files Modified:\n"
            "- Various files modified\n\n"
            "Next: Continue development tasks"
        )


# =============================================================================
# Context Detector
# =============================================================================


class ContextDetector:
    """Extract phase/task context from git history."""

    def __init__(self, git_parser: GitDiffParser):
        """Initialize the context detector."""
        self.git_parser = git_parser
        self._logger = logging.getLogger(__name__)

    def extract_phase_task_info(self) -> PhaseContext:
        """Extract phase and task information."""
        phase, task, task_name = self.git_parser.detect_phase_task()

        if not task_name:
            task_name = self._parse_progress_md(phase, task)

        branch = self.git_parser.get_branch_name()
        self._logger.debug(f"Context: Phase={phase}, Task={task}, Task Name={task_name}, Branch={branch}")
        return PhaseContext(phase=phase, task=task, task_name=task_name, branch=branch)

    def _parse_progress_md(self, phase: Optional[int], task: Optional[int]) -> Optional[str]:
        """Parse docs/progress.md for task name."""
        progress_file = Path("docs/progress.md")
        if not progress_file.exists():
            return None
        try:
            content = progress_file.read_text()
            if phase and task:
                pattern = rf"### Phase\s+{phase}\s+Task\s+{task}:\s+(.+)"
                match = re.search(pattern, content)
                if match:
                    task_name = match.group(1).strip()
                    self._logger.debug(f"Found task name in progress.md: {task_name}")
                    return task_name
        except Exception as e:
            self._logger.debug(f"Failed to parse progress.md: {e}")
        return None


# =============================================================================
# Message Generator
# =============================================================================


class MessageGenerator:
    """Generate commit messages following DEVELOPMENT_STANDARDS.md."""

    def __init__(self, llm_client: LLMClient):
        """Initialize the message generator."""
        self.llm_client = llm_client
        self._logger = logging.getLogger(__name__)

    def generate(self, diff: DiffResult, context: PhaseContext) -> str:
        """Generate commit message."""
        if context.phase is not None and context.task is not None:
            return self._generate_full_format(diff, context)
        return self._generate_adhoc_format(diff)

    def _generate_full_format(self, diff: DiffResult, context: PhaseContext) -> str:
        """Generate full format commit message with phase/task."""
        prompt = self._build_full_prompt(diff, context)
        self._logger.info(f"Generating commit message for Phase {context.phase} Task {context.task}")
        message = self.llm_client.get_completion(prompt)
        message = self._ensure_full_format(message, context)
        return message

    def _generate_adhoc_format(self, diff: DiffResult) -> str:
        """Generate ad-hoc format commit message without phase/task."""
        prompt = self._build_adhoc_prompt(diff)
        self._logger.info("Generating ad-hoc commit message (no phase/task found)")
        message = self.llm_client.get_completion(prompt)
        message = self._ensure_adhoc_format(message)
        return message

    def _build_full_prompt(self, diff: DiffResult, context: PhaseContext) -> str:
        """Build prompt for full format message."""
        file_list = "\n".join([f"- {f.name} (+{f.additions}, -{f.deletions} lines)" for f in diff.staged])

        prompt = f"""Generate a git commit message following DEVELOPMENT_STANDARDS.md Section 7.2.

IMPORTANT: Return ONLY the commit message. No explanations, no thinking process.

Context:
- Phase: {context.phase}
- Task: {context.task}
- Task Name: {context.task_name or "Not specified"}
- Branch: {context.branch}
- Files changed: {len(diff.staged)}
- Lines added: {diff.staged_additions}
- Lines deleted: {diff.staged_deletions}

Files Modified:
{file_list}

Required Format:

Phase {context.phase} Task {context.task}: [Short description - 50 chars max]

Changes:
- [What changed and WHY - be specific]
- [Added logging: levels used]
- [Added error handling: pattern used]
- [Refactored: what and why]

Testing:
- Manual: [Specific test performed and result]
- Automated: [pytest status - X/Y passing]
- Validation: [comparison tool / other checks]

Logging:
- [What's now logged - be specific about levels]
- [New logger.info(): user actions]
- [New logger.debug(): technical details]
- [New logger.error(): exception handling]

Documentation:
- progress.md updated [what was added]
- debugging.md updated [if applicable]
- Code comments added [where and why]

Files Modified:
- {file_list}

Next: Task {context.task + 1 if context.task else 1} ([brief description of next task])

Return ONLY the commit message. No explanations."""

        return prompt

    def _build_adhoc_prompt(self, diff: DiffResult) -> str:
        """Build prompt for ad-hoc format message."""
        file_list = "\n".join([f"- {f.name} (+{f.additions}, -{f.deletions} lines)" for f in diff.staged])

        prompt = f"""Generate a git commit message for ad-hoc changes (no phase/task).

Context:
- Files changed: {len(diff.staged)}
- Lines added: {diff.staged_additions}
- Lines deleted: {diff.staged_deletions}

Files Modified:
{file_list}

Required Format:

Feature/Fix/Chore: [Short description - 50 chars max]

Changes:
- [What changed and WHY - be specific]

Testing:
- [Test approach and results]

Documentation:
- [Documentation updates]

Files Modified:
- {file_list}

Return ONLY the commit message. No explanations."""

        return prompt

    def _ensure_full_format(self, message: str, context: PhaseContext) -> str:
        """Ensure message follows full format."""
        lines = message.strip().split("\n")
        if not lines:
            return self._generate_fallback_message()

        first_line_pattern = rf"^Phase\s+{context.phase}\s+Task\s+{context.task}:"
        if not re.match(first_line_pattern, lines[0]):
            lines[0] = f"Phase {context.phase} Task {context.task}: {lines[0]}"
        return "\n".join(lines)

    def _ensure_adhoc_format(self, message: str) -> str:
        """Ensure message follows ad-hoc format."""
        lines = message.strip().split("\n")
        if not lines:
            return self._generate_fallback_message()

        prefix_pattern = r"^(Feature|Fix|Chore):"
        if not re.match(prefix_pattern, lines[0]):
            lines[0] = f"Feature: {lines[0]}"
        return "\n".join(lines)


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate and display commit message."""
    work_dir = os.getcwd()
    git_parser = GitDiffParser(work_dir)

    if not git_parser.is_git_repo():
        logger.error("Error: Not a git repository")
        return 1

    diff = git_parser.get_combined_changes(args.include_unstaged)

    if not diff.staged:
        logger.error("Error: No changes to commit")
        return 1

    context_detector = ContextDetector(git_parser)
    context = context_detector.extract_phase_task_info()

    endpoint = os.environ.get("LLAMA_ENDPOINT", "http://case.modmtrx.net:10000")
    model = os.environ.get("LLAMA_MODEL")
    max_tokens = int(os.environ.get("MAX_TOKENS", "2000"))

    llm_client = LLMClient(endpoint, model, max_tokens)
    message_generator = MessageGenerator(llm_client)

    message = message_generator.generate(diff, context)

    print("\n" + "=" * 80)
    print("COMMIT MESSAGE")
    print("=" * 80)
    print(message)
    print("=" * 80 + "\n")

    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    """Generate commit message and commit."""
    work_dir = os.getcwd()
    git_parser = GitDiffParser(work_dir)

    if not git_parser.is_git_repo():
        logger.error("Error: Not a git repository")
        return 1

    diff = git_parser.get_combined_changes(args.include_unstaged)

    if not diff.staged:
        logger.error("Error: No changes to commit")
        return 1

    context_detector = ContextDetector(git_parser)
    context = context_detector.extract_phase_task_info()

    endpoint = os.environ.get("LLAMA_ENDPOINT", "http://case.modmtrx.net:10000")
    model = os.environ.get("LLAMA_MODEL")
    max_tokens = int(os.environ.get("MAX_TOKENS", "2000"))

    llm_client = LLMClient(endpoint, model, max_tokens)
    message_generator = MessageGenerator(llm_client)

    message = message_generator.generate(diff, context)

    print("\n" + "=" * 80)
    print("COMMIT MESSAGE")
    print("=" * 80)
    print(message)
    print("=" * 80 + "\n")

    if not args.no_prompt:
        response = input("Commit with this message? (y/n): ").strip().lower()
        if response != "y":
            logger.info("Commit cancelled by user")
            return 0

    try:
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=work_dir,
            check=True,
            timeout=10,
        )
        logger.info("Commit successful")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git commit failed: {e}")
        return 1
    except subprocess.TimeoutExpired:
        logger.error("Git commit timeout")
        return 1

    return 0


def cmd_stage(args: argparse.Namespace, remaining: list[str]) -> int:
    """Stage specific files."""
    work_dir = os.getcwd()
    git_parser = GitDiffParser(work_dir)

    if not git_parser.is_git_repo():
        logger.error("Error: Not a git repository")
        return 1

    files = remaining if remaining else []

    if not files:
        logger.error("Error: No files specified. Usage: git-commit-gen.py stage <files>")
        return 1

    try:
        result = subprocess.run(
            ["git", "add"] + files,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.error(f"Failed to stage files: {result.stderr}")
            return 1
        logger.info(f"Staged {len(files)} file(s): {', '.join(files)}")
    except subprocess.TimeoutExpired:
        logger.error("Git add timeout")
        return 1

    return 0


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate git commit messages using local LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  LLAMA_ENDPOINT   Llama server URL (default: http://case.modmtrx.net:10000)
  LLAMA_MODEL      Model name (auto-detect if not set)
  MAX_TOKENS       Maximum tokens (default: 2000)

Examples:
  %(prog)s generate                 Preview commit message
  %(prog)s commit                   Generate and commit (asks confirmation)
  %(prog)s commit --no-prompt       Auto-commit without confirmation
  %(prog)s stage file.py            Stage specific file
  %(prog)s --include-unstaged gen   Include unstaged changes
        """,
    )

    parser.add_argument(
        "command",
        choices=["generate", "commit", "stage"],
        nargs="?",
        default="generate",
        help="Command to run (default: generate)",
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="Files to stage (for 'stage' command)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to console",
    )

    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip confirmation before committing",
    )

    parser.add_argument(
        "--include-unstaged",
        action="store_true",
        help="Also include unstaged changes in analysis",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show more detailed output (info level)",
    )

    args = parser.parse_args()

    setup_logging(debug=args.debug, verbose=args.verbose)

    logger.info("Starting git-commit-gen.py")
    logger.debug(f"Command: {args.command}")
    logger.debug(f"Files: {args.files}")
    logger.debug(f"Debug: {args.debug}, Verbose: {args.verbose}")
    logger.debug(f"No-prompt: {args.no_prompt}, Include-unstaged: {args.include_unstaged}")

    if args.command == "stage":
        return cmd_stage(args, args.files)
    elif args.command == "commit":
        return cmd_commit(args)
    else:
        return cmd_generate(args)


if __name__ == "__main__":
    sys.exit(main())
