import os
import re
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

# --- Configuration ---
CACHE_DIR = Path(os.path.expanduser("~/.cache/llama.cpp"))
CONFIG_DIR = Path.home() / ".config" / "llm-cache-manager"
CONFIG_FILE = CONFIG_DIR / "config"
HF_CACHE_TOKEN = Path.home() / ".cache" / "huggingface" / "token"


# --- Token Resolution Logic ---
def get_hf_token():
    """Resolve HuggingFace token from environment, config file, or cache.

    Token priority:
    1. HF_TOKEN env var
    2. Config file ~/.config/llm-cache-manager/config
    3. ~/.cache/huggingface/token

    Returns:
        str | None: The resolved token or None if not found.
    """
    # 1. Environment Variable
    if token := os.environ.get("HF_TOKEN"):
        return token.strip()

    # 2. Config File
    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text().strip()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("HF_TOKEN="):
                    # Handle potential quotes
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return val
        except Exception:
            pass

    # 3. HuggingFace Default Cache
    if HF_CACHE_TOKEN.exists():
        try:
            return HF_CACHE_TOKEN.read_text().strip()
        except Exception:
            pass

    return None


class PullModelScreen(ModalScreen[None]):
    """Modal screen for pulling models from HuggingFace.

    Args:
        callback: Callback function to handle the selected repo ID.
    """

    def __init__(self, callback):
        """Initialize the PullModelScreen.

        Args:
            callback: Callback function to handle the selected repo ID.
        """
        super().__init__()
        self.callback = callback
        self.repo_id = ""

    def compose(self) -> ComposeResult:
        """Compose the UI elements for the pull model screen.

        Yields:
            UI elements: Static title, Input for repo ID, Download and Cancel buttons.
        """
        yield Static("Pull Model from HuggingFace", classes="modal-title")
        yield Input(placeholder="e.g., unsloth/Qwen3.5-35B-GGUF", id="repo_input")
        yield Button("Download", id="btn_download", variant="primary")
        yield Button("Cancel", id="btn_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event containing the button ID.
        """
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_download":
            self.repo_id = self.query_one("#repo_input", Input).value
            if self.repo_id:
                self.dismiss(self.repo_id)
            else:
                self.notify("Please enter a repo ID", severity="error")


class SyncScreen(ModalScreen[None]):
    """Modal screen for syncing models via SSH (rsync).

    Args:
        callback: Callback function to handle the sync action.
    """

    def __init__(self, callback):
        """Initialize the SyncScreen.

        Args:
            callback: Callback function to handle the sync action.
        """
        super().__init__()
        self.callback = callback
        self.host = "user@remote-host"

    def compose(self) -> ComposeResult:
        """Compose the UI elements for the sync screen.

        Yields:
            UI elements: Static title, Input for host, Push/Pull/Cancel buttons.
        """
        yield Static("Sync via SSH (rsync)", classes="modal-title")
        yield Input(placeholder="e.g., user@192.168.1.5", id="host_input", value=self.host)
        yield Button("Push (Local -> Remote)", id="btn_push", variant="primary")
        yield Button("Pull (Remote -> Local)", id="btn_pull", variant="warning")
        yield Button("Cancel", id="btn_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event containing the button ID.
        """
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        else:
            self.host = self.query_one("#host_input", Input).value
            self.dismiss(event.button.id)


class ConfirmScreen(ModalScreen[None]):
    """Modal screen for confirming deletion actions.

    Args:
        callback: Callback function to execute on confirmation.
    """

    def __init__(self, callback):
        """Initialize the ConfirmScreen.

        Args:
            callback: Callback function to execute on confirmation.
        """
        super().__init__()
        self.callback = callback

    def compose(self) -> ComposeResult:
        """Compose the UI elements for the confirmation screen.

        Yields:
            UI elements: Static title, warning message, Delete and Cancel buttons.
        """
        yield Static("Confirm Deletion", classes="modal-title")
        yield Static("This action cannot be undone.", classes="danger-text")
        yield Button("Yes, Delete", id="btn_delete_confirm", variant="error")
        yield Button("Cancel", id="btn_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event containing the button ID.
        """
        if event.button.id == "btn_delete_confirm":
            self.callback()
            self.dismiss()
        elif event.button.id == "btn_cancel":
            self.dismiss()


class LlamaManagerApp(App[None]):
    """Textual TUI application for managing Llama model caches.

    Provides a terminal-based interface for viewing, deleting,
    pulling from HuggingFace, and syncing model caches.
    """

    CSS = """
    Screen {
        background: $surface;
    }
    #main-container {
        height: 100%;
        layout: vertical;
    }
    #header {
        background: $primary;
        color: $text;
        padding: 1;
        text-align: center;
    }
    #status-bar {
        height: 1;
        background: $surface;
        border: solid $text;
        padding: 0 1;
    }
    .modal-title {
        text-align: center;
        height: 1;
        color: $text;
    }
    .danger-text {
        color: red;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "delete", "Delete"),
        Binding("p", "pull", "Pull HF"),
        Binding("s", "sync", "Sync SSH"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        """Initialize the LlamaManager application."""
        super().__init__()
        self.models: list[dict] = []
        self.selected_index: int = -1
        self.token_status: str = "Unknown"

    def compose(self) -> ComposeResult:
        """Compose the application UI.

        Yields:
            Header: Application header widget
            Container: Main container with header and model table
            Footer: Application footer widget
        """
        yield Header()
        with Container(id="main-container"):
            with Horizontal(id="header"):
                yield Static(f"Cache: {CACHE_DIR}", id="path-display")
                yield Static(f"HF Token: {self.token_status}", id="token-display")

            yield DataTable(id="model-table")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application on mount.

        Sets the token status and refreshes the model list.
        """
        self.token_status = "Not Found" if not get_hf_token() else "Found"
        self.refresh_models()
        self.query_one("#token-display", Static).update(f"HF Token: {self.token_status}")

    def refresh_models(self) -> None:
        """Refresh the model list from the cache directory.

        Scans CACHE_DIR for model files, groups them by base name,
        and populates the model table with name, size, and file count.
        """
        if not CACHE_DIR.exists():
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

        table = self.query_one("#model-table", DataTable)
        table.clear()

        # Define columns
        table.add_columns("Name", "Size", "Files")
        table.cursor_type = "row"

        self.models = []
        files = list(CACHE_DIR.glob("*"))
        model_groups: dict[str, list[Path]] = {}

        # Regex to extract base name from filenames
        # Handles: unsloth_{Name}_{Quant}.gguf and manifest=unsloth={Name}={Quant}.json
        pattern = re.compile(r"unsloth_([^-]+(?:-[^-]+)+)", re.IGNORECASE)

        for f in files:
            if f.suffix == ".gguf":
                match = pattern.search(f.name)
                if match:
                    base_name = match.group(1)
                    if base_name not in model_groups:
                        model_groups[base_name] = []
                    model_groups[base_name].append(f)
            elif f.name.startswith("manifest=") and f.suffix == ".json":
                manifest_match = re.search(r"manifest=unsloth=([^=]+)", f.name)
                if manifest_match:
                    base_name = manifest_match.group(1)
                    if base_name not in model_groups:
                        model_groups[base_name] = []
                    model_groups[base_name].append(f)

        # Populate Data
        for name, file_list in model_groups.items():
            total_size = sum(f.stat().st_size for f in file_list)
            size_str = self.format_size(total_size)
            self.models.append({"name": name, "files": file_list, "size": total_size})
            table.add_row(name, size_str, str(len(file_list)))

        self.notify(f"Loaded {len(self.models)} models", severity="info")

    def format_size(self, size: int) -> str:
        """Format a size in bytes to a human-readable string.

        Args:
            size: Size in bytes to format.

        Returns:
            Human-readable size string (e.g., "1.5 GB").
        """
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the model table.

        Args:
            event: The row selection event containing the selected row index.
        """
        self.selected_index = event.row

    def action_delete(self) -> None:
        """Handle the delete action triggered by keyboard binding.

        Prompts for confirmation before deleting the selected model.
        """
        if self.selected_index == -1:
            self.notify("Select a model to delete", severity="warning")
            return

        model = self.models[self.selected_index]
        self.push_screen(ConfirmScreen(lambda: self.delete_selected(model)))

    def delete_selected(self, model: dict) -> None:
        """Delete the selected model files.

        Args:
            model: Dictionary containing model name, files list, and size.
        """
        self.notify(f"Deleting {model['name']}...", severity="info")
        try:
            for f in model["files"]:
                f.unlink()
            self.models.pop(self.selected_index)
            self.refresh_models()
            self.selected_index = -1
            self.notify("Deleted successfully", severity="success")
        except PermissionError:
            self.notify("Permission denied", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_pull(self) -> None:
        """Handle the pull action triggered by keyboard binding.

        Opens a modal screen to prompt for a HuggingFace repository ID.
        """
        self.push_screen(PullModelScreen(self.handle_pull))

    def handle_pull(self, repo_id: str) -> None:
        """Handle pulling a model from HuggingFace.

        Args:
            repo_id: The HuggingFace repository ID to download.
        """
        if not repo_id:
            return
        self.notify(f"Pulling {repo_id}...", severity="info")
        token = get_hf_token()

        if not token:
            self.notify("HuggingFace Token not found!", severity="error")
            return

        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=repo_id, local_dir=CACHE_DIR, repo_type="model", token=token)
            self.notify("Download complete. Refreshing...", severity="success")
            self.refresh_models()
        except Exception as e:
            self.notify(f"Pull failed: {e}", severity="error")

    def action_sync(self) -> None:
        """Handle the sync action triggered by keyboard binding.

        Opens a modal screen to prompt for SSH host and sync direction.
        """
        self.push_screen(SyncScreen(self.handle_sync))

    def handle_sync(self, action: str) -> None:
        """Handle SSH sync operation (push or pull).

        Args:
            action: Either "btn_push" or "btn_pull" to specify sync direction.
        """
        host = self.query_one("#host_input", Input).value
        if not host or "@" not in host:
            self.notify("Invalid host format", severity="error")
            return

        cmd: list[str] = []
        if action == "btn_push":
            cmd = ["rsync", "-avz", "--delete", f"{CACHE_DIR}/", f"{host}:{CACHE_DIR}/"]
        elif action == "btn_pull":
            cmd = ["rsync", "-avz", f"{host}:{CACHE_DIR}/", f"{CACHE_DIR}/"]

        self.notify(f"Running: {' '.join(cmd)}", severity="info")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.notify("Sync complete", severity="success")
            self.refresh_models()
        except subprocess.CalledProcessError as e:
            self.notify(f"SSH/Rsync Error: {e.stderr}", severity="error")
        except FileNotFoundError:
            self.notify("rsync not found", severity="error")

    def action_refresh(self) -> None:
        """Handle the refresh action triggered by keyboard binding.

        Refreshes the model list from the cache directory.
        """
        self.refresh_models()


if __name__ == "__main__":
    app = LlamaManagerApp()
    app.run()
