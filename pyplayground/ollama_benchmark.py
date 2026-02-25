#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""A Python script to benchmark Ollama models using direct HTTP requests.

This script discovers local models via the Ollama API, checks their capabilities,
and then runs a benchmark against them. It uses a session with retry logic for
resilience, calculates performance metrics including throughput, and saves the
final results to a JSON file.

It can be configured via command-line arguments for model selection, custom
prompts, and model unloading behavior.
"""

import argparse
import json
import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.table import Table
from urllib3.util import Retry

from pyplayground.utils.logging_utils import setup_logging

# --- Configuration ---
# OLLAMA_HOST_URL will be set in main() based on env/args, defaulting to localhost.
OLLAMA_HOST_URL = ""
WAIT_TIME = 120  # 2 minutes to wait between model tests
HEADERS = {"Content-Type": "application/json"}
BASE_PROMPT = """
Create a Python program that analyzes a text file containing student grades. Your program should:

### Requirements:
1. **Read a CSV file** with columns: student_name, subject, grade (0-100)
2. **Calculate statistics** for each student: average grade, highest grade, lowest grade
3. **Find the top 3 students** by average grade
4. **Generate a report** showing:
   - Each student's statistics
   - Class average
   - Subject with highest average grade
   - Number of students failing (average < 60)

### Input Format:
```
student_name,subject,grade
Alice,Math,85
Alice,Science,92
Alice,English,78
Bob,Math,76
Bob,Science,88
Bob,English,82
Charlie,Math,45
Charlie,Science,52
Charlie,English,68
```

### Expected Output:
```
=== STUDENT GRADE ANALYSIS ===

Student Statistics:
Alice: Avg=85.0, High=92, Low=78
Bob: Avg=82.0, High=88, Low=76
Charlie: Avg=55.0, High=68, Low=45

Top 3 Students:
1. Alice (85.0)
2. Bob (82.0)
3. Charlie (55.0)

Class Average: 74.0
Best Subject: Science (77.3)
Students Failing: 1
```

**Include error handling for missing files and invalid data. Write clean, commented code.**
"""
THINKING_PROMPT_ADDITION = "\nPlease provide a verbose, step-by-step thought process on how you would " "approach creating the solution before writing the code."

# --- Functions ---


def create_session_with_retry() -> requests.Session:
    """Creates a requests.Session with a retry policy."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def read_prompt_from_file(filepath: str) -> str | None:
    """Reads a prompt from a file, returning None if an error occurs."""
    logging.info(f"Reading custom prompt from {filepath}...")
    if not os.path.exists(filepath):
        logging.error(f"Prompt file not found: {filepath}")
        return None
    try:
        with open(filepath, "r") as f:
            return f.read()
    except IOError as e:
        logging.error(f"Error reading prompt file {filepath}: {e}")
        return None


def get_local_models(session: requests.Session) -> list:
    """Fetches the list of locally available models from the Ollama API."""
    logging.info("Fetching list of local models...")
    try:
        response = session.get(f"{OLLAMA_HOST_URL}/api/tags", headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
        model_names = [model["name"] for model in data.get("models", [])]
        logging.info(f"Found {len(model_names)} local models.")
        return model_names
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch local models: {e}")
        return []


def check_model_thinking_capability(session: requests.Session, model_name: str) -> bool:
    """Checks if a model is instruction-tuned by inspecting its template."""
    logging.info(f"Checking capabilities for model: {model_name}...")
    try:
        response = session.post(
            f"{OLLAMA_HOST_URL}/api/show",
            json={"model": model_name},
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        template = data.get("template", "")

        if "{{." in template and "}}" in template:
            logging.info(f" -> Model {model_name} has a chat template and is thinking-capable.")
            return True
        else:
            logging.info(f" -> Model {model_name} does not have a complex template. Data: {data}")
            return False

    except requests.exceptions.RequestException as e:
        logging.error(f"Could not retrieve details for model {model_name}: {e}")
        return False


def get_prompt(is_thinking: bool) -> str:
    """Constructs the prompt based on the 'thinking' flag."""
    if is_thinking:
        return BASE_PROMPT + THINKING_PROMPT_ADDITION
    return BASE_PROMPT


def load_model(session: requests.Session, model: str) -> bool:
    """Explicitly loads a model into memory."""
    logging.info(f"Loading model: {model}...")
    payload = {"model": model, "messages": []}
    try:
        response = session.post(f"{OLLAMA_HOST_URL}/api/chat", json=payload, headers=HEADERS, timeout=300)
        response.raise_for_status()
        data = response.json()
        if data.get("done_reason") == "load" and data.get("done"):
            logging.info(f"Model {model} loaded successfully.")
            return True
        else:
            logging.error(f"Failed to load model {model}. Unexpected response: {data}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to load model {model}: {e}")
        return False


def unload_model(session: requests.Session, model: str) -> bool:
    """Explicitly unloads a model from memory."""
    logging.info(f"Unloading model: {model}...")
    payload = {"model": model, "messages": [], "keep_alive": 0}
    try:
        response = session.post(f"{OLLAMA_HOST_URL}/api/chat", json=payload, headers=HEADERS, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("done_reason") == "unload" and data.get("done"):
            logging.info(f"Model {model} unloaded successfully.")
            return True
        else:
            logging.error(f"Failed to unload model {model}. Unexpected response: {data}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to unload model {model}: {e}")
        return False


def pull_model(session: requests.Session, model_name: str) -> bool:
    """Pulls a model from the Ollama registry."""
    logging.info(f"Attempting to pull model: {model_name}...")
    payload = {"name": model_name, "stream": True}
    try:
        with session.post(f"{OLLAMA_HOST_URL}/api/pull", json=payload, stream=True, headers=HEADERS, timeout=1800) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue

                chunk = json.loads(line)
                if "error" in chunk:
                    logging.error(f"  API Error during pull: {chunk['error']}")
                    return False

                status = chunk.get("status", "")
                logging.info(f"  [PULL] {status}")

                if status == "success":
                    logging.info(f"Model '{model_name}' pulled successfully.")
                    return True

            # If the loop completes without a "success" status
            logging.error(f"Pull stream for '{model_name}' ended unexpectedly.")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to pull model '{model_name}': {e}")
        return False


def _process_inference_stream(response: requests.Response) -> tuple[str | None, dict | None]:
    """Helper to process the streaming response from the API."""
    api_error = None
    final_chunk = None
    debug_stream_buffer = ""
    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if "error" in chunk:
            api_error = chunk["error"]
            logging.error(f"  API Error: {api_error}")
            break
        if token := chunk.get("message", {}).get("content"):
            debug_stream_buffer += token
            while "\\n" in debug_stream_buffer:
                sentence, _, debug_stream_buffer = debug_stream_buffer.partition("\\n")
                if sentence.strip():
                    logging.debug(f"  [STREAM] {sentence.strip()}")
        if chunk.get("done"):
            if debug_stream_buffer.strip():
                logging.debug(f"  [STREAM] {debug_stream_buffer.strip()}")
            final_chunk = chunk
            break
    return api_error, final_chunk


def _calculate_metrics_from_chunk(final_chunk: dict | None) -> tuple[float, float, int, str | None]:
    """Helper to calculate performance metrics from the final response chunk."""
    if not final_chunk:
        return 0.0, 0.0, 0, "Final stats chunk not received"

    total_duration_ns = final_chunk.get("total_duration", 0)
    eval_duration_ns = final_chunk.get("eval_duration", 0)
    prompt_eval_count = final_chunk.get("prompt_eval_count", 0)
    eval_count = final_chunk.get("eval_count", 0)

    total_tokens = prompt_eval_count + eval_count
    duration = total_duration_ns / 1_000_000_000
    eval_duration_s = eval_duration_ns / 1_000_000_000
    throughput = total_tokens / eval_duration_s if eval_duration_s > 0 else 0

    logging.info("  Inference complete. Server-reported stats:")
    logging.info(f"    - Total Duration: {duration:.2f}s")
    logging.info(f"    - Eval Duration: {eval_duration_s:.2f}s")
    logging.info(f"    - Total Tokens: {total_tokens}")
    logging.info(f"    - Throughput: {throughput:.2f} tokens/sec")
    return duration, throughput, total_tokens, None


def run_inference(session: requests.Session, model: str, prompt: str, is_thinking: bool) -> tuple:
    """Runs inference on a model and returns stats."""
    label = "Thinking Request" if is_thinking else "Standard Request"
    logging.info(f"Running inference on model: {model} [{label}]")
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}

    try:
        with session.post(f"{OLLAMA_HOST_URL}/api/chat", json=payload, stream=True, headers=HEADERS, timeout=600) as response:
            response.raise_for_status()
            api_error, final_chunk = _process_inference_stream(response)
    except requests.exceptions.RequestException as e:
        logging.error(f"  HTTP Request failed: {e}")
        return str(e), 0.0, 0.0, 0

    duration, throughput, total_tokens, calc_error = _calculate_metrics_from_chunk(final_chunk)
    error = api_error or calc_error
    return error, duration, throughput, total_tokens


def run_benchmark(session: requests.Session, models_to_test: list, no_unload: bool) -> list:
    """Runs the full benchmark against the provided models."""
    if not models_to_test:
        logging.info("No models to test.")
        return []
    logging.info("Starting benchmark...")
    results = []
    for i, (model, is_thinking) in enumerate(models_to_test):
        result_error, result_duration, result_throughput, result_tokens = (None, 0.0, 0.0, 0)
        if not load_model(session, model):
            result_error = "Model failed to load"
        else:
            try:
                error, duration, throughput, tokens = run_inference(session, model, get_prompt(is_thinking), is_thinking)
                result_duration, result_throughput, result_tokens, result_error = (
                    duration,
                    throughput,
                    tokens,
                    error,
                )
            finally:
                if not no_unload and not unload_model(session, model):
                    unload_error = "Model failed to unload"
                    logging.error(unload_error)
                    if not result_error:
                        result_error = unload_error
        results.append(
            {
                "model": model,
                "thinking": is_thinking,
                "duration": result_duration,
                "tokens": result_tokens,
                "throughput": result_throughput,
                "error": result_error,
            }
        )
        if i < len(models_to_test) - 1:
            logging.info(f"Pausing for {WAIT_TIME // 60} minutes before next test...")
            time.sleep(WAIT_TIME)
    return results


def print_summary(results: list):
    """Prints a summary of the benchmark results using a rich Table."""
    console = Console()
    table = Table(title="Benchmark Summary", show_header=True, header_style="bold magenta")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Request Type")
    table.add_column("Duration (s)", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Throughput (t/s)", justify="right")
    table.add_column("Status", justify="center")

    for r in results:
        status = "[bold green]OK[/]" if not r["error"] else "[bold red]FAIL[/]"
        thinking_label = "Thinking" if r["thinking"] else "Standard"
        error_details = f"\n[dim]└─ {r['error']}[/dim]" if r["error"] else ""
        table.add_row(
            r["model"],
            thinking_label,
            f"{r['duration']:.2f}",
            str(r["tokens"]),
            f"{r.get('throughput', 0):.2f}",
            status + error_details,
        )

    console.print(table)


def save_results_to_json(results: list, filepath: str = "benchmark_results.json"):
    """Saves the benchmark results to a JSON file."""
    logging.info(f"Saving results to {filepath}...")
    try:
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2)
        logging.info("Results saved successfully.")
    except IOError as e:
        logging.error(f"Failed to save results to {filepath}: {e}")


def parse_args():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="Benchmark Ollama models.")
    parser.add_argument(
        "--host",
        help="Ollama host URL (e.g., http://localhost:11434). Overrides OLLAMA_HOST env var.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Specific models to benchmark. If not provided, all local models are used.",
    )
    parser.add_argument("--prompt-file", help="Path to a file containing a custom prompt.")
    parser.add_argument("--no-unload", action="store_true", help="Do not unload models after each test.")
    parser.add_argument("--list-models", action="store_true", help="List locally available models and exit.")
    parser.add_argument(
        "--pull-models",
        nargs="+",
        help="Pull one or more models from the Ollama registry and exit.",
    )
    return parser.parse_args()


def configure_globals(args: argparse.Namespace):
    """Configures global settings like host URL and base prompt from args."""
    global OLLAMA_HOST_URL, BASE_PROMPT

    host_url = args.host or os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    if not host_url.startswith(("http://", "https://")):
        host_url = f"http://{host_url}"
    OLLAMA_HOST_URL = host_url
    logging.info(f"Using Ollama host: {OLLAMA_HOST_URL}")

    if args.prompt_file:
        custom_prompt = read_prompt_from_file(args.prompt_file)
        if custom_prompt:
            BASE_PROMPT = custom_prompt
        else:
            logging.error("Exiting due to failed prompt file read.")
            exit(1)


def handle_list_models(session: requests.Session):
    """Handles the --list-models command."""
    console = Console()
    console.print("[bold green]Discovering local models...[/bold green]")
    local_models = get_local_models(session)
    if local_models:
        console.print("[bold blue]Available Local Models:[/bold blue]")
        for model in sorted(local_models):
            console.print(f" • {model}")
    else:
        console.print("[yellow]No local models found.[/yellow]")


def handle_pull_models(session: requests.Session, models_to_pull: list[str]):
    """Handles the --pull-models command."""
    for model_name in models_to_pull:
        pull_model(session, model_name)


def run_full_benchmark(session: requests.Session, args: argparse.Namespace):
    """Runs the main benchmark workflow."""
    all_local_models = get_local_models(session)
    if not all_local_models:
        return

    target_models = args.models if args.models else all_local_models
    models_to_run = [m for m in target_models if m in all_local_models]

    missing = set(target_models) - set(all_local_models)
    if missing:
        logging.warning(f"Models not found and will be skipped: {', '.join(missing)}")
    if not models_to_run:
        logging.error("No valid models selected for benchmarking.")
        return

    models_to_test = []
    for model_name in models_to_run:
        models_to_test.append((model_name, False))
        if check_model_thinking_capability(session, model_name):
            models_to_test.append((model_name, True))

    results = run_benchmark(session, models_to_test, args.no_unload)
    print_summary(results)
    save_results_to_json(results)


def main():
    """Main function to orchestrate the benchmark."""
    setup_logging(level="DEBUG", script_name="ollama_benchmark")
    args = parse_args()
    configure_globals(args)

    session = create_session_with_retry()

    if args.list_models:
        handle_list_models(session)
    elif args.pull_models:
        handle_pull_models(session, args.pull_models)
    else:
        run_full_benchmark(session, args)


if __name__ == "__main__":
    main()
