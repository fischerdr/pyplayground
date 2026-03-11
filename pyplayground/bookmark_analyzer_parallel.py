import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import click

# External Libraries
import requests
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
DEFAULT_MODEL = "GLM-4.7-Flash"
DEFAULT_URL = "http://flyyn.modmtrx.net:10000/v1/chat/completions"
TIMEOUT = 10
MAX_WORKERS = 5
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def setup_logging(debug):
    """Configures logging to file and console."""
    # Create tmp directory if it doesn't exist
    os.makedirs("tmp", exist_ok=True)

    log_filename = os.path.join("tmp", "bookmark_analyzer.log")

    # Set logging level based on debug flag
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(log_filename), logging.StreamHandler()])


def scrape_and_tag(url):
    """Scrapes page and tags it."""
    logging.info(f"Scraping: {url}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return ["Error: Page unavailable"]

        soup = BeautifulSoup(response.text, "html.parser")
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()

        text_content = soup.get_text(separator=" ", strip=True)
        text_to_analyze = text_content[:2000]

        # prompt = f"""
        # Analyze the following text. Extract 5-7 relevant tags.
        # Return ONLY a comma-separated list. No quotes.
        # Text: {text_to_analyze}
        # Tags:
        # """
        prompt = f"""
        You are analyzing a summarized text extracted from a webpage.
        Based on this summary, generate 5-7 descriptive tags.
        Focus on the main topic, subject matter, or content category (e.g., 'programming', 'tutorial', 'news', 'documentation').
        Return ONLY a comma-separated list. No quotes or extra text.
        Summary: {text_to_analyze}
        Tags:
        """
        llm_payload = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "system", "content": "Return only a comma-separated list of tags."}, {"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 100,
        }

        llm_response = requests.post(DEFAULT_URL, json=llm_payload, timeout=30)
        if llm_response.status_code == 200:
            tags = llm_response.json()["choices"][0]["message"]["content"]
            # Convert to set to remove duplicates, then back to list
            return list(set([t.strip() for t in tags.split(",") if t.strip()]))
        else:
            return [f"LLM Error: {llm_response.status_code}"]

    except Exception as e:
        logging.error(f"Scraping error for {url}: {e}")
        return ["Scraping Error"]


def validate_and_process_link(link_data):
    """Validates link, scrapes, and tags."""
    url = link_data["url"]
    title = link_data["title"]
    desc = link_data.get("description", "")
    logging.debug(f"Processing: {title} ({url})")

    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        response = session.head(url, allow_redirects=True, timeout=TIMEOUT)

        is_valid = 200 <= response.status_code < 400
        link_data["valid"] = is_valid

        if not is_valid:
            link_data["tags"] = ["Broken Link"]
            return link_data

        tags = scrape_and_tag(url)
        link_data["tags"] = tags
        logging.info(f"Successfully tagged: {title}")

    except Exception as e:
        logging.error(f"Error processing {url}: {e}")
        link_data["valid"] = False
        link_data["tags"] = ["Network Error"]

    return link_data


def parse_firefox_bookmarks(file_path):
    """Parses HTML and extracts URL, Title, and Description."""
    links = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

            for link_tag in soup.find_all("a", href=True):
                link_data = {"url": link_tag["href"], "title": link_tag.get_text(strip=True), "description": ""}

                # Check for description attribute
                if link_tag.get("description"):
                    link_data["description"] = link_tag.get("description")

                # If no attribute, check for the <dd> sibling
                if not link_data["description"]:
                    next_dd = link_tag.find_next_sibling("dd")
                    if next_dd:
                        link_data["description"] = next_dd.get_text(strip=True)

                links.append(link_data)

    except FileNotFoundError:
        logging.error(f"The file '{file_path}' was not found.")
        return []

    return links


@click.command()
@click.option('--api-url', default='http://flyyn.modmtrx.net:10000/v1/chat/completions', help='Custom API Endpoint URL')
@click.option('--file', default='bookmarks.html', help='Path to the bookmark HTML file')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def cli(file, debug, api_url):
    """Tool to validate bookmarks, scrape content, and generate tags using LLM."""
    setup_logging(debug)
    logging.info("Starting Bookmark Analyzer...")
    # Update the global URL configuration to use the passed option
    global DEFAULT_URL
    DEFAULT_URL = api_url

    bookmarks = parse_firefox_bookmarks(file)

    if not bookmarks:
        logging.error("No bookmarks found or file error.")
        return

    logging.info(f"Found {len(bookmarks)} bookmarks. Starting parallel processing...")

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(validate_and_process_link, bookmarks))

    # Save Output
    output_file = "bookmarks_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    logging.info("--- Complete ---")
    logging.info(f"Results saved to {output_file}")


if __name__ == "__main__":
    cli()
