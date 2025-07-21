#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A Python script to manage and test Ollama models.

This script replicates the functionality of the original bash script
`ollama_test_switch.sh`, providing features to pull, preload, and test
multiple Ollama models. It uses the `rich` library for enhanced terminal output.
"""

import json
import logging
import sys
from typing import List

import click
import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from pyplayground.utils.logging_utils import setup_logging

# --- Configuration ---
MODELS: List[str] = ["llama3.1:8b", "mistral:7b", "codellama:7b"]
DEFAULT_OLLAMA_HOST: str = "192.168.100.10"
KEEP_ALIVE: str = "2h"

# --- Setup ---
logger = logging.getLogger(__name__)


def get_ollama_url(host: str) -> str:
    """Construct the base URL for the Ollama API."""
    return f"http://{host}:11434/api"


def pull_model_with_progress(model_name: str, ollama_url: str, console: Console) -> bool:
    """Pull a model from Ollama with a progress bar.

    Args:
        model_name: The name of the model to pull.
        ollama_url: The base URL of the Ollama API.
        console: The Rich console instance for output.

    Returns:
        True if the pull was successful, False otherwise.
    """
    console.print(f"Pulling [bold cyan]{model_name}[/]...")

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    )

    try:
        with progress:
            task = progress.add_task(f"Downloading {model_name}", total=None)
            response = requests.post(
                f"{ollama_url}/pull",
                json={"name": model_name, "stream": True},
                stream=True,
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if "total" in data and "completed" in data:
                            if progress.tasks[task].total is None:
                                progress.update(task, total=data["total"])
                            progress.update(
                                task,
                                completed=data["completed"],
                                description=status.capitalize(),
                            )
                        else:
                            progress.update(task, description=status.capitalize())
                    except json.JSONDecodeError:
                        logger.warning(f"Could not decode JSON line: {line}")

        console.print(f"[bold green]✓[/] Successfully pulled [bold cyan]{model_name}[/].\n")
        return True
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]✗[/] Failed to pull {model_name}: {e}\n")
        return False


def preload_model(model_name: str, ollama_url: str, console: Console) -> bool:
    """Preload a model into memory.

    Args:
        model_name: The name of the model to preload.
        ollama_url: The base URL of the Ollama API.
        console: The Rich console instance for output.

    Returns:
        True if preloading was successful, False otherwise.
    """
    console.print(f"Loading [bold cyan]{model_name}[/] into memory...")
    try:
        requests.post(
            f"{ollama_url}/generate",
            json={
                "model": model_name,
                "prompt": "",
                "stream": False,
                "keep_alive": KEEP_ALIVE,
            },
            timeout=60,
        )
        console.print(f"[bold green]✓[/] [bold cyan]{model_name}[/] loaded and ready.")
        return True
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]✗[/] Failed to load {model_name}: {e}")
        return False


def check_loaded_models(ollama_url: str, console: Console):
    """Check and display the currently loaded models.

    Args:
        ollama_url: The base URL of the Ollama API.
        console: The Rich console instance for output.
    """
    try:
        response = requests.get(f"{ollama_url}/ps", timeout=10)
        response.raise_for_status()
        console.print("\n[bold]Loaded Models:[/]")
        console.print(response.json())
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]✗[/] Failed to get loaded models: {e}")


def test_model_switching(model_name: str, ollama_url: str, console: Console):
    """Send a test prompt to a model to check if it's responsive.

    Args:
        model_name: The name of the model to test.
        ollama_url: The base URL of the Ollama API.
        console: The Rich console instance for output.
    """
    console.print(f"  Testing [bold cyan]{model_name}[/]...")
    try:
        response = requests.post(
            f"{ollama_url}/generate",
            json={
                "model": model_name,
                "prompt": "Say hello in one word",
                "stream": False,
                "keep_alive": KEEP_ALIVE,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        response_text = data.get("response", "").strip()
        console.print(f"    Response: [bold green]{response_text}[/]")
    except requests.exceptions.RequestException as e:
        console.print(f"    [bold red]✗[/] Failed to get response from {model_name}: {e}")


@click.command()
@click.option(
    "--host",
    default=DEFAULT_OLLAMA_HOST,
    help=f"Ollama host address (default: {DEFAULT_OLLAMA_HOST})",
    show_default=True,
)
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(host: str, debug: bool):
    """Run the main function to execute the model testing script."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(log_level, "ollama_model_switcher")

    console = Console()
    ollama_url = get_ollama_url(host)

    console.print(Panel("[bold yellow]Ollama Model Switcher[/]", expand=False))

    # --- 1. Pull Models ---
    console.print("\n" + "=" * 15 + " [bold]Pulling Models[/] " + "=" * 15 + "\n")
    for model in MODELS:
        if not pull_model_with_progress(model, ollama_url, console):
            sys.exit(1)

    # --- 2. Pre-load Models ---
    console.print("\n" + "=" * 15 + " [bold]Pre-loading Models[/] " + "=" * 15 + "\n")
    for model in MODELS:
        preload_model(model, ollama_url, console)

    # --- 3. Check Loaded Models ---
    check_loaded_models(ollama_url, console)

    # --- 4. Test Model Switching ---
    console.print("\n" + "=" * 15 + " [bold]Testing Model Switching[/] " + "=" * 15 + "\n")
    for i in range(1, 4):
        console.print(f"[bold]Test round {i}:[/]")
        for model in MODELS:
            test_model_switching(model, ollama_url, console)
        console.print("")

    # --- 5. Final Status Check ---
    console.print("\n" + "=" * 15 + " [bold]Final Status[/] " + "=" * 15 + "\n")
    check_loaded_models(ollama_url, console)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScript interrupted by user. Exiting.")
        sys.exit(0)
