#!/usr/bin/env python3
"""llm-cache-manager — TUI for reviewing and pruning ~/.cache/llama.cpp with bidirectional SSH rsync support.

Requires: pip install textual
"""

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Log, Static

CACHE_DIR = Path.home() / ".cache" / "llama.cpp"
MODEL_EXTENSIONS = {".gguf", ".bin", ".ggml", ".q4_0", ".q8_0"}
CONFIG_FILE = Path.home() / ".config" / "llm-cache-manager" / "config"

HF_API = "https://huggingface.co/api"
HF_CDN = "https://huggingface.co"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format (B, KB, MB, GB, TB, PB).

    Args:
        size_bytes: Size in bytes to convert.

    Returns:
        Human-readable size string with appropriate unit.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def parse_flat_name(name: str) -> tuple[str, str, str]:
    """Parse llama.cpp flat cache filenames into vendor, repo, and file components.

    Handles filenames like:
      unsloth_Qwen3-Coder-30B_Qwen3-Coder-Q8_0.gguf
      -> vendor="unsloth", repo="Qwen3-Coder-30B", file="Qwen3-Coder-Q8_0.gguf"

    Falls back gracefully if the pattern doesn't match.

    Args:
        name: Filename to parse.

    Returns:
        Tuple of (vendor, repo, file) components.
    """
    # Strip known suffixes before parsing
    stem = name
    for ext in (".gguf.etag", ".etag", ".gguf", ".bin", ".ggml"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    parts = stem.split("_", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return "", stem, ""


def associated_files(base: Path, model_path: Path) -> list[Path]:
    """Return sibling files that belong to the same model.

    Returns the .etag file and any manifest=... .json files that reference
    the same repo+file.

    Args:
        base: Base cache directory.
        model_path: Path to the model file.

    Returns:
        List of associated file paths.
    """
    siblings = []
    etag = model_path.parent / (model_path.name + ".etag")
    if etag.exists():
        siblings.append(etag)
    # manifest files live at base level, named manifest=vendor=repo=quant.json
    vendor, repo, _ = parse_flat_name(model_path.name)
    if vendor and repo:
        prefix = f"manifest={vendor}={repo}="
        for f in base.iterdir():
            if f.name.startswith(prefix) and f.suffix == ".json":
                siblings.append(f)
    return siblings


def scan_models(base: Path) -> list[dict]:
    """Scan the cache directory and return a list of model information dicts.

    Recursively scans the base directory for model files matching
    MODEL_EXTENSIONS, parses their names, and collects associated files.

    Args:
        base: Base cache directory to scan.

    Returns:
        List of model info dicts with path, name, display, vendor, repo,
        quant, rel, size, total_size, mtime, and assoc fields.
    """
    models = []
    if not base.exists():
        return models
    for path in sorted(base.rglob("*")):
        name = path.name
        # Skip etag and manifest files — they're surfaced via associated_files
        if name.endswith(".etag") or (name.startswith("manifest=") and name.endswith(".json")):
            continue
        if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS:
            stat = path.stat()
            vendor, repo, quant = parse_flat_name(name)
            # Human-readable display name: repo / quant or just filename
            display = f"{repo} / {quant}" if repo and quant else name
            assoc = associated_files(base, path)
            total_size = stat.st_size + sum(f.stat().st_size for f in assoc if f.exists())
            models.append(
                {
                    "path": path,
                    "assoc": assoc,  # etag + manifest files
                    "name": name,
                    "display": display,
                    "vendor": vendor,
                    "repo": repo,
                    "quant": quant,
                    "rel": str(path.relative_to(base)),
                    "size": stat.st_size,
                    "total_size": total_size,  # model + metadata
                    "mtime": datetime.fromtimestamp(stat.st_mtime),
                }
            )
    return models


def load_config() -> dict:
    """Load configuration from the config file.

    Reads key=value pairs from the config file and returns them as a dict.
    Defaults to empty strings for 'remote' and 'hf_token' if not found.

    Returns:
        Dict with 'remote' and 'hf_token' keys.
    """
    cfg = {"remote": "", "hf_token": ""}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def save_config(cfg: dict) -> None:
    """Save configuration to the config file.

    Writes key=value pairs to the config file, creating parent directories
    if necessary.

    Args:
        cfg: Dict with configuration key-value pairs.
    """
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text("\n".join(f"{k}={v}" for k, v in cfg.items()) + "\n")


def load_remote_host() -> str:
    """Load the remote SSH host from configuration.

    Returns:
        Remote host string or empty string if not configured.
    """
    return load_config().get("remote", "")


def save_remote_host(host: str) -> None:
    """Save the remote SSH host to configuration.

    Args:
        host: Remote host string to save.
    """
    cfg = load_config()
    cfg["remote"] = host
    save_config(cfg)


def load_hf_token() -> str:
    """Load HuggingFace token from environment, config, or default location.

    Token priority:
    1. HF_TOKEN environment variable
    2. Config file ~/.config/llm-cache-manager/config
    3. ~/.cache/huggingface/token

    Returns:
        HuggingFace token string or empty string if not found.
    """
    # prefer HF_TOKEN env var, then config file, then ~/.cache/huggingface/token
    if t := os.environ.get("HF_TOKEN", ""):
        return t
    if t := load_config().get("hf_token", ""):
        return t
    hf_token_file = Path.home() / ".cache" / "huggingface" / "token"
    if hf_token_file.exists():
        return hf_token_file.read_text().strip()
    return ""


def save_hf_token(token: str) -> None:
    """Save HuggingFace token to configuration.

    Args:
        token: HuggingFace token string to save.
    """
    cfg = load_config()
    cfg["hf_token"] = token
    save_config(cfg)


def hf_headers(token: str = "") -> dict:
    """Build HTTP headers for HuggingFace API requests.

    Args:
        token: Optional HuggingFace token. If not provided, uses load_hf_token().

    Returns:
        Dict with User-Agent and optional Authorization headers.
    """
    h = {"User-Agent": "llm-cache-manager/1.0"}
    t = token or load_hf_token()
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def hf_search_models(query: str, token: str = "", limit: int = 20) -> list[dict]:
    """Search HF model hub, filter to repos that likely have GGUF files."""
    params = urllib.parse.urlencode(
        {
            "search": query,
            "filter": "gguf",
            "limit": limit,
            "sort": "downloads",
            "direction": -1,
        }
    )
    url = f"{HF_API}/models?{params}"
    req = urllib.request.Request(url, headers=hf_headers(token))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def hf_list_gguf_files(repo_id: str, token: str = "") -> list[dict]:
    """Return list of GGUF siblings in a repo."""
    url = f"{HF_API}/models/{repo_id}"
    req = urllib.request.Request(url, headers=hf_headers(token))
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    siblings = data.get("siblings", [])
    return [s for s in siblings if s.get("rfilename", "").lower().endswith(".gguf")]


# ──────────────────────────────────────────────────────────────────────────────
# Modals
# ──────────────────────────────────────────────────────────────────────────────


class ConfirmDelete(ModalScreen):
    """Delete confirmation modal for selected files."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Confirm"),
    ]

    def __init__(self, files: list[dict]):
        """Initialize the delete confirmation modal.

        Args:
            files: List of file dicts to delete.
        """
        super().__init__()
        self.files = files

    def compose(self) -> ComposeResult:
        """Compose the delete confirmation dialog UI."""
        total = sum(f.get("total_size", f["size"]) for f in self.files)
        names = "\n".join(f"  • {f['rel']}" for f in self.files)
        yield Vertical(
            Static(
                f"[bold red]Delete {len(self.files)} file(s)?[/bold red]\n\n" f"{names}\n\n" f"[yellow]Total freed: {human_size(total)}[/yellow]",
                id="confirm-text",
            ),
            Horizontal(
                Button("Cancel  [Esc]", variant="default", id="btn-cancel"),
                Button("Delete  [Enter]", variant="error", id="btn-confirm"),
                id="confirm-buttons",
            ),
            id="confirm-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press and dismiss with result.

        Args:
            event: Button press event.
        """
        self.dismiss(event.button.id == "btn-confirm")

    def action_cancel(self):
        """Cancel deletion and dismiss modal."""
        self.dismiss(False)

    def action_confirm(self):
        """Confirm deletion and dismiss modal."""
        self.dismiss(True)


class SyncScreen(ModalScreen):
    """Full-screen rsync progress view."""

    BINDINGS = [Binding("escape,q", "close", "Close")]

    def __init__(self, remote_host: str, mode: str):
        """Initialize the sync screen.

        Args:
            remote_host: SSH host string (e.g., user@hostname).
            mode: "additive" — pull then push, no --delete;
                  "prune"     — pull then push --delete (local is authority).
        """
        super().__init__()
        self.remote_host = remote_host
        self.mode = mode
        self._proc: subprocess.Popen | None = None
        self._done = False

    def compose(self) -> ComposeResult:
        """Compose the sync screen UI with progress log."""
        remote_dir = f"{self.remote_host}:{CACHE_DIR}/"
        local_dir = str(CACHE_DIR) + "/"
        mode_label = "[yellow]Additive (no deletions)[/yellow]" if self.mode == "additive" else "[red]Prune  (local is authority — remote will match local)[/red]"
        yield Vertical(
            Static(
                f"[bold]Sync — {self.remote_host}[/bold]   {mode_label}\n" f"[dim]Local : {local_dir}[/dim]\n" f"[dim]Remote: {remote_dir}[/dim]",
                id="sync-header",
            ),
            Log(id="sync-log", auto_scroll=True),
            Horizontal(
                Button("Close  [Esc]", variant="default", id="btn-close"),
                id="sync-footer",
            ),
            id="sync-dialog",
        )

    def on_mount(self) -> None:
        """Start the rsync sync process on mount."""
        self._start_sync()

    def _rsync_flags(self, delete: bool) -> list[str]:
        """Get rsync flags based on delete mode.

        Args:
            delete: Whether to include --delete flag.

        Returns:
            List of rsync flags.
        """
        flags = ["rsync", "-avzu", "--progress"]
        if delete:
            flags.append("--delete")
        return flags

    def _start_sync(self) -> None:
        remote_dir = f"{self.remote_host}:{CACHE_DIR}/"
        local_dir = str(CACHE_DIR) + "/"
        delete = self.mode == "prune"

        pull_cmd = self._rsync_flags(False) + [remote_dir, local_dir]
        push_cmd = self._rsync_flags(delete) + [local_dir, remote_dir]

        log = self.query_one("#sync-log", Log)

        def run():
            for label, cmd in [("PULL ← remote", pull_cmd), ("PUSH → remote", push_cmd)]:
                log.write_line(f"\n{'─' * 60}")
                log.write_line(f"  {label}")
                log.write_line(f"  {' '.join(cmd)}")
                log.write_line(f"{'─' * 60}\n")
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    self._proc = proc
                    for line in proc.stdout:
                        clean = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip("\r\n")
                        if clean:
                            log.write_line(clean)
                    proc.wait()
                    rc = proc.returncode
                    if rc == 0:
                        log.write_line(f"\n[✓] {label} completed successfully.")
                    else:
                        log.write_line(f"\n[✗] {label} exited with code {rc}.")
                except Exception as e:
                    log.write_line(f"\n[✗] Error: {e}")

            self._done = True
            log.write_line("\n══ Sync finished ══")

        threading.Thread(target=run, daemon=True).start()

    def action_close(self) -> None:
        """Terminate the running rsync process and dismiss the screen."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.dismiss(self._done)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button press event.
        """
        if event.button.id == "btn-close":
            self.action_close()


class SyncConfigScreen(ModalScreen):
    """Configure remote host and launch sync."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_host: str):
        """Initialize the sync config screen.

        Args:
            current_host: Current remote host string.
        """
        super().__init__()
        self.current_host = current_host

    def compose(self) -> ComposeResult:
        """Compose the sync config screen UI."""
        yield Vertical(
            Static("[bold]SSH Sync Configuration[/bold]", id="cfg-title"),
            Static(
                "Format:  [cyan]user@hostname[/cyan]  or  [cyan]hostname[/cyan]\n" "Remote cache dir mirrors local:  [dim]~/.cache/llama.cpp/[/dim]",
                id="cfg-hint",
            ),
            Input(
                value=self.current_host,
                placeholder="user@hostname",
                id="cfg-host-input",
            ),
            Static("[bold]Sync mode:[/bold]", id="cfg-mode-label"),
            Static(
                "[green]Additive[/green] — pull then push, never deletes files\n" "[yellow]Prune[/yellow]   — pull first, then push with --delete (local wins)",
                id="cfg-mode-desc",
            ),
            Horizontal(
                Button("Additive  (safe)", variant="success", id="btn-additive"),
                Button("Prune  (local wins)", variant="warning", id="btn-prune"),
                id="cfg-mode-buttons",
            ),
            Horizontal(
                Button("Cancel  [Esc]", variant="default", id="btn-cfg-cancel"),
                id="cfg-cancel-row",
            ),
            id="cfg-dialog",
        )

    def _host(self) -> str:
        """Get the configured host from the input field.

        Returns:
            Stripped host string from input.
        """
        return self.query_one("#cfg-host-input", Input).value.strip()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events for sync mode selection.

        Args:
            event: Button press event.
        """
        if event.button.id == "btn-additive":
            self.dismiss(("additive", self._host()))
        elif event.button.id == "btn-prune":
            self.dismiss(("prune", self._host()))
        else:
            self.dismiss(None)

    def action_cancel(self):
        """Cancel and dismiss the config screen."""
        self.dismiss(None)


# ──────────────────────────────────────────────────────────────────────────────
# Main App
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# HuggingFace — Search Screen
# ──────────────────────────────────────────────────────────────────────────────


class HFSearchScreen(ModalScreen):
    """Search HuggingFace for GGUF models."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "search", "Search"),
    ]

    class ModelChosen(Message):
        """Message sent when a model is chosen from search results.

        Args:
            repo_id: The selected HuggingFace repository ID.
            token: The HuggingFace token used for the search.
        """

        def __init__(self, repo_id: str, token: str):
            """Initialize the ModelChosen message.

            Args:
                repo_id: The selected HuggingFace repository ID.
                token: The HuggingFace token used for the search.
            """
            super().__init__()
            self.repo_id = repo_id
            self.token = token

    def __init__(self, token: str = ""):
        """Initialize the HF search screen.

        Args:
            token: Optional HuggingFace token for gated models.
        """
        super().__init__()
        self.token = token
        self._results: list[dict] = []

    def compose(self) -> ComposeResult:
        """Compose the HF search screen UI."""
        yield Vertical(
            Static("[bold cyan]HuggingFace Model Search[/bold cyan]", id="hf-title"),
            Static(
                "Searches for GGUF-tagged repos.  " "e.g. [cyan]mistral[/cyan]  [cyan]llama 8b[/cyan]  [cyan]qwen2.5[/cyan]",
                id="hf-hint",
            ),
            Horizontal(
                Input(placeholder="Search query…", id="hf-query"),
                Button("Search", variant="primary", id="btn-hf-search"),
                id="hf-search-row",
            ),
            Input(placeholder="HF token (optional, for gated models)", id="hf-token-input", password=True, value=self.token),
            Static("", id="hf-status"),
            DataTable(id="hf-results-table", cursor_type="row"),
            Horizontal(
                Button("Cancel  [Esc]", variant="default", id="btn-hf-cancel"),
                Button("Select Repo →", variant="success", id="btn-hf-select"),
                id="hf-action-row",
            ),
            id="hf-dialog",
        )

    def on_mount(self) -> None:
        """Initialize the HF search table columns and focus the query input."""
        t = self.query_one("#hf-results-table", DataTable)
        t.add_columns("Repository", "Downloads", "Likes", "Last Modified")
        self.query_one("#hf-query", Input).focus()

    def _set_status(self, msg: str) -> None:
        """Update the status display.

        Args:
            msg: Status message to display.
        """
        self.query_one("#hf-status", Static).update(msg)

    def action_search(self) -> None:
        """Trigger a search by pressing the search button."""
        self.query_one("#btn-hf-search", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button press event.
        """
        if event.button.id == "btn-hf-search":
            self._do_search()
        elif event.button.id == "btn-hf-select":
            self._pick_repo()
        elif event.button.id == "btn-hf-cancel":
            self.dismiss(None)

    def _do_search(self) -> None:
        """Perform a HuggingFace model search in a background thread."""
        query = self.query_one("#hf-query", Input).value.strip()
        self.token = self.query_one("#hf-token-input", Input).value.strip()
        if not query:
            self._set_status("[yellow]Enter a search query.[/yellow]")
            return
        self._set_status("[dim]Searching…[/dim]")
        table = self.query_one("#hf-results-table", DataTable)
        table.clear()
        self._results = []

        def fetch():
            try:
                results = hf_search_models(query, self.token)
                self.app.call_from_thread(self._populate, results)
            except Exception as e:
                self.app.call_from_thread(self._set_status, f"[red]Error: {e}[/red]")

        threading.Thread(target=fetch, daemon=True).start()

    def _populate(self, results: list[dict]) -> None:
        """Populate the results table with search results.

        Args:
            results: List of search result dictionaries.
        """
        self._results = results
        table = self.query_one("#hf-results-table", DataTable)
        table.clear()
        if not results:
            self._set_status("[yellow]No results found.[/yellow]")
            return
        for r in results:
            dl = r.get("downloads", 0)
            lk = r.get("likes", 0)
            lm = (r.get("lastModified") or "")[:10]
            table.add_row(r["modelId"], f"{dl:,}", str(lk), lm)
        self._set_status(f"[green]{len(results)} repos found.[/green]")

    def _pick_repo(self) -> None:
        """Pick the currently selected repository and dismiss the screen."""
        table = self.query_one("#hf-results-table", DataTable)
        idx = table.cursor_row
        if not self._results or idx >= len(self._results):
            self._set_status("[yellow]Select a repo first.[/yellow]")
            return
        repo_id = self._results[idx]["modelId"]
        self.dismiss((repo_id, self.token))

    def action_cancel(self):
        """Cancel and dismiss the search screen."""
        self.dismiss(None)

    def on_data_table_row_selected(self, _) -> None:
        """Handle row selection by picking the selected repo."""
        self._pick_repo()


# ──────────────────────────────────────────────────────────────────────────────
# HuggingFace — File Picker Screen
# ──────────────────────────────────────────────────────────────────────────────


class HFFileScreen(ModalScreen):
    """List GGUF files in a HF repo and let the user pick one."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, repo_id: str, token: str = ""):
        """Initialize the HF file picker screen.

        Args:
            repo_id: HuggingFace repository ID.
            token: Optional HuggingFace token.
        """
        super().__init__()
        self.repo_id = repo_id
        self.token = token
        self._files: list[dict] = []

    def compose(self) -> ComposeResult:
        """Compose the HF file picker screen UI."""
        yield Vertical(
            Static(
                f"[bold cyan]Select GGUF file[/bold cyan]  " f"[dim]{self.repo_id}[/dim]",
                id="hff-title",
            ),
            Static("[dim]Loading file list…[/dim]", id="hff-status"),
            DataTable(id="hff-table", cursor_type="row"),
            Horizontal(
                Button("Cancel  [Esc]", variant="default", id="btn-hff-cancel"),
                Button("Download ↓", variant="success", id="btn-hff-dl"),
                id="hff-action-row",
            ),
            id="hff-dialog",
        )

    def on_mount(self) -> None:
        """Initialize the file table and start fetching files in background."""
        t = self.query_one("#hff-table", DataTable)
        t.add_columns("Filename", "Size")
        threading.Thread(target=self._fetch_files, daemon=True).start()

    def _fetch_files(self) -> None:
        """Fetch GGUF files from HuggingFace in a background thread."""
        try:
            files = hf_list_gguf_files(self.repo_id, self.token)
            self.app.call_from_thread(self._populate, files)
        except Exception as exc:
            self.app.call_from_thread(lambda e=exc: self.query_one("#hff-status", Static).update(f"[red]Error fetching file list: {e}[/red]"))

    def _populate(self, files: list[dict]) -> None:
        """Populate the file table with fetched files.

        Args:
            files: List of file dictionaries.
        """
        self._files = files
        table = self.query_one("#hff-table", DataTable)
        if not files:
            self.query_one("#hff-status", Static).update("[yellow]No GGUF files found in this repo.[/yellow]")
            return
        for f in files:
            size_str = human_size(f["size"]) if f.get("size") else "unknown"
            table.add_row(f["rfilename"], size_str)
        self.query_one("#hff-status", Static).update(f"[green]{len(files)} GGUF file(s) available.[/green]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button press event.
        """
        if event.button.id == "btn-hff-dl":
            self._start_download()
        else:
            self.dismiss(None)

    def _start_download(self) -> None:
        """Start download of the selected file."""
        table = self.query_one("#hff-table", DataTable)
        idx = table.cursor_row
        if not self._files or idx >= len(self._files):
            return
        chosen = self._files[idx]
        self.dismiss((self.repo_id, chosen["rfilename"], self.token))

    def on_data_table_row_selected(self, _) -> None:
        """Handle row selection by starting download."""
        self._start_download()

    def action_cancel(self):
        """Cancel and dismiss the file picker screen."""
        self.dismiss(None)


# ──────────────────────────────────────────────────────────────────────────────
# HuggingFace — Download Screen
# ──────────────────────────────────────────────────────────────────────────────


class HFDownloadScreen(ModalScreen):
    """Stream download a single GGUF file from HF with progress."""

    BINDINGS = [Binding("escape,q", "close", "Close / Cancel")]

    def __init__(self, repo_id: str, filename: str, token: str = ""):
        """Initialize the HF download screen.

        Args:
            repo_id: HuggingFace repository ID.
            filename: GGUF filename to download.
            token: Optional HuggingFace token.
        """
        super().__init__()
        self.repo_id = repo_id
        self.filename = filename
        self.token = token
        self._done = False
        self._cancel = threading.Event()

    def compose(self) -> ComposeResult:
        """Compose the HF download screen UI."""
        dest = CACHE_DIR / self.repo_id.replace("/", "--") / self.filename
        yield Vertical(
            Static(
                f"[bold]Downloading from HuggingFace[/bold]\n" f"[dim]Repo :[/dim]  {self.repo_id}\n" f"[dim]File :[/dim]  {self.filename}\n" f"[dim]Dest :[/dim]  {dest}",
                id="hfdl-header",
            ),
            Log(id="hfdl-log", auto_scroll=True),
            Static("", id="hfdl-progress"),
            Horizontal(
                Button("Cancel / Close  [Esc]", variant="default", id="btn-hfdl-close"),
                id="hfdl-footer",
            ),
            id="hfdl-dialog",
        )

    def on_mount(self) -> None:
        """Start the download process on mount."""
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self) -> None:
        """Download a GGUF file from HuggingFace in a background thread.

        Supports resumable downloads via Range header.
        """
        log = self.query_one("#hfdl-log", Log)
        progress = self.query_one("#hfdl-progress", Static)

        repo_path = self.repo_id.replace("/", "--")
        dest_dir = CACHE_DIR / repo_path
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / self.filename
        url = f"{HF_CDN}/{self.repo_id}/resolve/main/{self.filename}"

        self.app.call_from_thread(log.write_line, f"URL: {url}")
        self.app.call_from_thread(log.write_line, f"Destination: {dest}\n")

        # Support resume via Range header
        existing = dest.stat().st_size if dest.exists() else 0
        headers = hf_headers(self.token)
        if existing:
            headers["Range"] = f"bytes={existing}-"
            self.app.call_from_thread(log.write_line, f"Resuming from {human_size(existing)}")

        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=30)

            total_header = resp.headers.get("Content-Length") or resp.headers.get("Content-Range", "").split("/")[-1]
            total = int(total_header) if total_header and total_header.isdigit() else 0
            if existing and total:
                total += existing

            mode = "ab" if existing else "wb"
            downloaded = existing
            chunk_size = 1024 * 1024  # 1 MB

            with open(dest, mode) as fh:
                while not self._cancel.is_set():
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                        msg = f"{bar} {pct:5.1f}%  {human_size(downloaded)} / {human_size(total)}"
                    else:
                        msg = f"Downloaded: {human_size(downloaded)}"
                    self.app.call_from_thread(progress.update, msg)

            if self._cancel.is_set():
                self.app.call_from_thread(log.write_line, "\n[yellow]Download cancelled.[/yellow]")
            else:
                self._done = True
                self.app.call_from_thread(log.write_line, f"\n[bold green]✓ Download complete:[/bold green] {dest.name}")
                self.app.call_from_thread(progress.update, f"[green]Saved to {dest}[/green]")

        except urllib.error.HTTPError as e:
            self.app.call_from_thread(log.write_line, f"\n[red]HTTP {e.code}: {e.reason}[/red]")
            if e.code == 401:
                self.app.call_from_thread(log.write_line, "[yellow]This model may be gated — provide a HF token.[/yellow]")
        except Exception as e:
            self.app.call_from_thread(log.write_line, f"\n[red]Error: {e}[/red]")

    def action_close(self) -> None:
        """Cancel the download and dismiss the screen."""
        self._cancel.set()
        self.dismiss(self._done)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button press event.
        """
        if event.button.id == "btn-hfdl-close":
            self.action_close()


class CacheManager(App):
    """Main application for managing llama.cpp cache with SSH sync support."""

    CSS = """
    Screen { background: $surface; }

    #layout { height: 1fr; }

    #table-panel {
        width: 1fr; height: 1fr;
        border: solid $primary; padding: 0 1;
    }

    #side-panel {
        width: 36; height: 1fr;
        border: solid $accent; padding: 1 2;
    }

    #remote-label  { color: $text-muted; margin-top: 1; }
    #selected-info { margin-top: 1; color: $warning; }
    #total-info    { margin-top: 1; color: $success; }

    Button { margin-top: 1; width: 100%; }

    /* ── delete confirm ── */
    #confirm-dialog {
        background: $surface; border: double $error;
        padding: 2 4; width: 64; height: auto; align: center middle;
    }
    #confirm-text    { margin-bottom: 1; }
    #confirm-buttons { height: auto; align: center middle; }
    #confirm-buttons Button { margin: 0 1; width: auto; }

    /* ── sync config ── */
    #cfg-dialog {
        background: $surface; border: double $accent;
        padding: 2 4; width: 68; height: auto; align: center middle;
    }
    #cfg-title     { margin-bottom: 1; }
    #cfg-hint      { color: $text-muted; margin-bottom: 1; }
    #cfg-mode-label { margin-top: 1; }
    #cfg-mode-desc  { color: $text-muted; margin-bottom: 1; }
    #cfg-mode-buttons { height: auto; margin-top: 1; }
    #cfg-mode-buttons Button { margin: 0 1; width: auto; }
    #cfg-cancel-row { height: auto; margin-top: 1; }
    #cfg-cancel-row Button { width: auto; }

    /* ── sync log ── */
    #sync-dialog {
        background: $surface; border: double $primary;
        padding: 1 2; width: 90%; height: 90%; align: center middle;
    }
    #sync-header { margin-bottom: 1; }
    #sync-log    { height: 1fr; border: solid $panel; }
    #sync-footer { height: auto; margin-top: 1; align: center middle; }
    #sync-footer Button { width: auto; }

    /* ── HF search ── */
    #hf-dialog {
        background: $surface; border: double $success;
        padding: 1 3; width: 90%; height: 85%; align: center middle;
    }
    #hf-title      { margin-bottom: 1; }
    #hf-hint       { color: $text-muted; margin-bottom: 1; }
    #hf-search-row { height: auto; }
    #hf-search-row Input  { width: 1fr; }
    #hf-search-row Button { width: auto; margin-top: 0; margin-left: 1; }
    #hf-status     { margin-top: 1; height: auto; }
    #hf-results-table { height: 1fr; margin-top: 1; }
    #hf-action-row { height: auto; margin-top: 1; align: center middle; }
    #hf-action-row Button { margin: 0 1; width: auto; }

    /* ── HF file picker ── */
    #hff-dialog {
        background: $surface; border: double $success;
        padding: 1 3; width: 80%; height: 70%; align: center middle;
    }
    #hff-title  { margin-bottom: 1; }
    #hff-status { height: auto; margin-bottom: 1; }
    #hff-table  { height: 1fr; }
    #hff-action-row { height: auto; margin-top: 1; align: center middle; }
    #hff-action-row Button { margin: 0 1; width: auto; }

    /* ── HF download ── */
    #hfdl-dialog {
        background: $surface; border: double $success;
        padding: 1 3; width: 90%; height: 80%; align: center middle;
    }
    #hfdl-header   { margin-bottom: 1; }
    #hfdl-log      { height: 1fr; border: solid $panel; }
    #hfdl-progress { height: auto; margin-top: 1; color: $accent; }
    #hfdl-footer   { height: auto; margin-top: 1; align: center middle; }
    #hfdl-footer Button { width: auto; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "toggle_select", "Select"),
        Binding("a", "select_all", "Select All"),
        Binding("n", "select_none", "Deselect All"),
        Binding("d", "delete_selected", "Delete"),
        Binding("s", "open_sync", "Sync"),
        Binding("h", "open_hf", "HF Download"),
        Binding("r", "refresh", "Refresh"),
    ]

    selected: reactive[set] = reactive(set)

    def __init__(self):
        super().__init__()
        self.models: list[dict] = []
        self.remote_host: str = load_remote_host()
        self.hf_token: str = load_hf_token()

    def compose(self) -> ComposeResult:
        """Compose the main application UI with table and side panel."""
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="table-panel"):
                yield DataTable(id="model-table", cursor_type="row")
            with Vertical(id="side-panel"):
                yield Label("[bold]llama.cpp cache[/bold]")
                yield Label(str(CACHE_DIR), id="status")
                yield Label("", id="remote-label")
                yield Label("", id="selected-info")
                yield Label("", id="total-info")
                yield Button("Delete Selected  [d]", variant="error", id="btn-delete")
                yield Button("HF Download  [h]", variant="success", id="btn-hf")
                yield Button("SSH Sync  [s]", variant="primary", id="btn-sync")
                yield Button("Refresh  [r]", variant="default", id="btn-refresh")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the table and load models on mount."""
        self._build_table()
        self._load_models()

    # ── table ──────────────────────────────────────────────────────────────────

    def _build_table(self) -> None:
        """Build the model table columns."""
        table = self.query_one("#model-table", DataTable)
        table.add_column("", key="sel", width=3)
        table.add_column("Vendor", key="vendor", width=12)
        table.add_column("Repo", key="repo", width=32)
        table.add_column("Quant", key="quant", width=22)
        table.add_column("Size", key="size", width=10)
        table.add_column("Modified", key="modified", width=17)

    def _load_models(self) -> None:
        """Load and display all models from the cache directory."""
        self.models = scan_models(CACHE_DIR)
        self.selected = set()
        table = self.query_one("#model-table", DataTable)
        table.clear()
        for i, m in enumerate(self.models):
            table.add_row(
                "[ ]",
                m["vendor"] or "—",
                m["repo"] or m["name"],
                m["quant"] or "—",
                human_size(m["total_size"]),
                m["mtime"].strftime("%Y-%m-%d %H:%M"),
                key=str(i),
            )
        self._update_side()

    def _update_side(self) -> None:
        """Update the side panel with model counts and sizes."""
        total_size = sum(m["total_size"] for m in self.models)
        sel_size = sum(self.models[i]["total_size"] for i in self.selected)
        remote_txt = f"[cyan]Remote: {self.remote_host}[/cyan]" if self.remote_host else "[dim]Remote: not configured[/dim]"
        self.query_one("#remote-label", Label).update(remote_txt)
        self.query_one("#total-info", Label).update(f"[green]Total: {len(self.models)} files / {human_size(total_size)}[/green]")
        self.query_one("#selected-info", Label).update(
            f"[yellow]Selected: {len(self.selected)} / {human_size(sel_size)}[/yellow]" if self.selected else "[dim]No files selected[/dim]"
        )

    def _set_row_mark(self, row_idx: int, selected: bool) -> None:
        """Set the selection mark for a table row.

        Args:
            row_idx: Row index to update.
            selected: Whether the row is selected.
        """
        mark = "[bold green]✓[/bold green]" if selected else "[ ]"
        self.query_one("#model-table", DataTable).update_cell(str(row_idx), "sel", mark)

    # ── actions ────────────────────────────────────────────────────────────────

    def action_toggle_select(self) -> None:
        """Toggle selection of the currently selected row."""
        row_idx = self.query_one("#model-table", DataTable).cursor_row
        if row_idx >= len(self.models):
            return
        if row_idx in self.selected:
            self.selected.discard(row_idx)
            self._set_row_mark(row_idx, False)
        else:
            self.selected.add(row_idx)
            self._set_row_mark(row_idx, True)
        self._update_side()

    def action_select_all(self) -> None:
        """Select all models in the table."""
        self.selected = set(range(len(self.models)))
        for i in self.selected:
            self._set_row_mark(i, True)
        self._update_side()

    def action_select_none(self) -> None:
        """Deselect all models in the table."""
        for i in self.selected:
            self._set_row_mark(i, False)
        self.selected = set()
        self._update_side()

    def action_refresh(self) -> None:
        """Refresh the model list from disk."""
        self._load_models()

    def action_delete_selected(self) -> None:
        """Delete the currently selected models."""
        if not self.selected:
            return
        files = [self.models[i] for i in sorted(self.selected)]
        self.push_screen(ConfirmDelete(files), self._do_delete)

    def _do_delete(self, confirmed: bool) -> None:
        """Delete selected files after confirmation.

        Args:
            confirmed: Whether deletion was confirmed.
        """
        if not confirmed:
            return
        errors = []
        for i in sorted(self.selected, reverse=True):
            m = self.models[i]
            to_remove = [m["path"]] + m.get("assoc", [])
            for f in to_remove:
                try:
                    if f.exists():
                        os.remove(f)
                except OSError as e:
                    errors.append(str(e))
            # clean empty subdirs
            parent = m["path"].parent
            if parent != CACHE_DIR and parent.exists() and not any(parent.iterdir()):
                shutil.rmtree(parent, ignore_errors=True)
        self._load_models()
        if errors:
            self.notify("\n".join(errors), severity="error", timeout=8)
        else:
            self.notify("Files deleted.", severity="information")

    def action_open_hf(self) -> None:
        """Open the HuggingFace model search screen."""
        self.push_screen(HFSearchScreen(self.hf_token), self._on_hf_repo_chosen)

    def _on_hf_repo_chosen(self, result) -> None:
        """Handle HuggingFace repo selection.

        Args:
            result: Tuple of (repo_id, token) or None.
        """
        if result is None:
            return
        repo_id, token = result
        if token:
            self.hf_token = token
            save_hf_token(token)
        self.push_screen(HFFileScreen(repo_id, token), self._on_hf_file_chosen)

    def _on_hf_file_chosen(self, result) -> None:
        """Handle GGUF file selection.

        Args:
            result: Tuple of (repo_id, filename, token) or None.
        """
        if result is None:
            return
        repo_id, filename, token = result
        self.push_screen(HFDownloadScreen(repo_id, filename, token), self._on_hf_download_done)

    def _on_hf_download_done(self, completed: bool) -> None:
        """Handle download completion.

        Args:
            completed: Whether the download completed successfully.
        """
        if completed:
            self._load_models()
            self.notify("Download complete — model list refreshed.", severity="information")

    def action_open_sync(self) -> None:
        """Open the SSH sync configuration screen."""
        self.push_screen(SyncConfigScreen(self.remote_host), self._on_sync_config)

    def _on_sync_config(self, result) -> None:
        """Handle sync configuration.

        Args:
            result: Tuple of (mode, host) or None.
        """
        if result is None:
            return
        mode, host = result
        if not host:
            self.notify("No remote host specified.", severity="warning")
            return
        self.remote_host = host
        save_remote_host(host)
        self._update_side()
        self.push_screen(SyncScreen(host, mode), self._on_sync_done)

    def _on_sync_done(self, completed: bool) -> None:
        """Handle sync completion.

        Args:
            completed: Whether the sync completed successfully.
        """
        if completed:
            self._load_models()
            self.notify("Sync complete — local cache refreshed.", severity="information")

    # ── button routing ─────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route button presses to appropriate action handlers.

        Args:
            event: Button press event.
        """
        dispatch = {
            "btn-delete": self.action_delete_selected,
            "btn-hf": self.action_open_hf,
            "btn-sync": self.action_open_sync,
            "btn-refresh": self.action_refresh,
        }
        if event.button.id in dispatch:
            dispatch[event.button.id]()

    def on_data_table_row_selected(self, _) -> None:
        """Handle table row selection by toggling selection."""
        self.action_toggle_select()


if __name__ == "__main__":
    app = CacheManager()
    app.run()
