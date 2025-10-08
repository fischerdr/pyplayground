"""A script to benchmark different Ollama models.

This script runs inference on a list of specified models with and without "thinking"
(higher temperature and top_k) and measures the performance.
"""

import logging
import time

import requests

# Configure
OLLAMA_HOST = "http://your-remote-ollama-host:11434"
TEST_PROMPT = "Explain the theory of relativity in simple terms."
MODEL_LIST = ["llama3", "mistral", "codellama"]
WAIT_TIME = 300  # 5 minutes in seconds if unload fails
HEADERS = {"Content-Type": "application/json"}

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def generate_payload(prompt: str, thinking: bool):
    """Generate the payload for the Ollama API request.

    Args:
        prompt: The prompt to send to the model.
        thinking: Whether to use "thinking" settings (higher temperature/top_k).

    Returns:
        A dictionary representing the request payload.
    """
    return {
        "prompt": prompt,
        "options": {
            "temperature": 0.8 if thinking else 0.0,
            "top_k": 100 if thinking else 0,
            "max_tokens": 256,
        },
        "stream": False,
    }


def run_inference(model: str, thinking: bool):
    """Run inference on a given model and return performance metrics.

    Args:
        model: The name of the model to run inference on.
        thinking: Whether to use "thinking" settings.

    Returns:
        A dictionary containing the performance results.
    """
    label = "thinking" if thinking else "no-thinking"
    logging.info(f"⏳ Running inference on model: {model} [{label}]")
    start = time.time()
    try:
        res = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={**generate_payload(TEST_PROMPT, thinking), "model": model},
            headers=HEADERS,
            timeout=300,
        )
        duration = time.time() - start
        res.raise_for_status()
        result = res.json()
        output_text = result.get("response", "").strip()
        logging.info(f"✅ Completed in {duration:.2f}s — {len(output_text.split())} words")
        return {
            "model": model,
            "thinking": thinking,
            "duration": duration,
            "tokens": result.get("eval_count", 0),
            "words": len(output_text.split()),
        }
    except Exception as e:
        logging.error(f"❌ Error during inference on {model}: {e}")
        return {"model": model, "thinking": thinking, "duration": -1, "tokens": 0, "error": str(e)}


def unload_model(model: str):
    """Unload a model from Ollama to free up resources.

    Args:
        model: The name of the model to unload.

    Returns:
        True if the model was unloaded successfully, False otherwise.
    """
    try:
        res = requests.delete(f"{OLLAMA_HOST}/api/models/{model}", timeout=30)
        if res.status_code == 200:
            logging.info(f"🧹 Unloaded model: {model}")
            return True
        else:
            logging.warning(f"⚠️ Could not unload {model}: {res.text}")
            return False
    except Exception as e:
        logging.error(f"⚠️ Exception during unload: {e}")
        return False


def main():
    """Run the main benchmark loop and print the results."""
    results = []
    for model in MODEL_LIST:
        for thinking in [True, False]:
            result = run_inference(model, thinking)
            results.append(result)
            # Try to unload or wait
            if not unload_model(model):
                logging.info(f"⏳ Waiting {WAIT_TIME // 60} minutes to let model be ejected...")
                time.sleep(WAIT_TIME)

    # Output results summary
    print("\n=== Benchmark Results ===")
    for r in results:
        print(
            f"{r['model']:10} | {'thinking' if r['thinking'] else 'no-think':10} | "
            f"Time: {r['duration']:.2f}s | Tokens: {r.get('tokens', 'n/a')} | "
            f"Words: {r.get('words', 'n/a')}"
        )


if __name__ == "__main__":
    main()
