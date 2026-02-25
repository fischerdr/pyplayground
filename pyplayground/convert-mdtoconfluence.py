#!/usr/bin/env python3
# Convert Markdown to Confluence Storage Format
# Author: dfischer
# Date: 2025-03-10
"""This script converts markdown content to Confluence storage format and uploads it to a Confluence page.

Example Usage:
    python convert-mdtoconfluence.py --markdown-file="path/to/markdown/file.md" \
        --confluence-url="https://your-confluence-instance.com" \
        --username="your-username" \
        --api-token="your-api-token" \
        --space-key="your-space-key" \
        --parent-id="your-parent-id"
"""

import logging
import os
from typing import Any, Dict, Optional

import markdown
import requests
import typer

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer()


def convert_markdown_to_storage_format(markdown_content: str) -> str:
    """Convert markdown content to Confluence storage format.

    This function takes in markdown content and converts it to the Confluence storage
    format. The Confluence storage format is a subset of XML that is used to store
    content in Confluence. The function uses the markdown library to convert the
    markdown to HTML and then wraps the HTML in CDATA tags to make it conform to the
    Confluence storage format.

    Args:
        markdown_content: The markdown content to convert

    Returns:
        The content in Confluence storage format
    """
    # Convert markdown to HTML
    html = markdown.markdown(markdown_content, extensions=["tables", "fenced_code"])

    # Wrap the HTML in CDATA for Confluence storage format
    storage_format = f'<ac:structured-macro ac:name="html"><ac:plain-text-body><![CDATA[{html}]]></ac:plain-text-body></ac:structured-macro>'

    return storage_format


def update_confluence_page(
    base_url: str,
    auth: tuple,
    space_key: str,
    title: str,
    content: str,
    parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a Confluence page.

    Args:
        base_url: The base URL of your Confluence instance
        auth: Tuple containing (username, api_token)
        space_key: The Confluence space key
        title: The title of the page
        content: The content in Confluence storage format
        parent_id: Optional parent page ID

    Returns:
        Response from the Confluence API
    """
    # Check if page exists
    search_url = f"{base_url}/rest/api/content"
    search_params = {"title": title, "spaceKey": space_key, "expand": "version"}

    response = requests.get(search_url, params=search_params, auth=auth)
    response.raise_for_status()

    results = response.json().get("results", [])

    if results:
        # Update existing page
        page_id = results[0]["id"]
        version = results[0]["version"]["number"]

        update_url = f"{base_url}/rest/api/content/{page_id}"

        data = {
            "id": page_id,
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": content, "representation": "storage"}},
            "version": {"number": version + 1},
        }

        response = requests.put(update_url, json=data, auth=auth, headers={"Content-Type": "application/json"})

        logger.info(f"Updated page: {title}")
    else:
        # Create new page
        create_url = f"{base_url}/rest/api/content"

        data = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": content, "representation": "storage"}},
        }

        if parent_id:
            data["ancestors"] = [{"id": parent_id}]

        response = requests.post(create_url, json=data, auth=auth, headers={"Content-Type": "application/json"})

        logger.info(f"Created page: {title}")

    response.raise_for_status()
    return response.json()


@app.command()
def upload_markdown(
    markdown_file: str = typer.Argument(..., help="Path to markdown file"),
    confluence_url: str = typer.Option(..., envvar="CONFLUENCE_URL", help="Confluence base URL"),
    username: str = typer.Option(..., envvar="CONFLUENCE_USERNAME", help="Confluence username"),
    api_token: str = typer.Option(..., envvar="CONFLUENCE_API_TOKEN", help="Confluence API token"),
    space_key: str = typer.Option(..., help="Confluence space key"),
    parent_id: Optional[str] = typer.Option(None, help="Parent page ID"),
):
    """Upload a markdown file to Confluence.

    This command reads a markdown file, converts it to Confluence storage format,
    and uploads it to a specified Confluence space. The Confluence credentials
    and other parameters can be provided as command-line options or environment variables.

    Args:
        markdown_file: The path to the markdown file to be uploaded.
        confluence_url: The base URL of the Confluence instance.
        username: The username for Confluence authentication.
        api_token: The API token for Confluence authentication.
        space_key: The Confluence space key where the page will be uploaded.
        parent_id: The optional parent page ID under which the new page will be created.
    """
    try:
        # Read markdown file
        with open(markdown_file, "r") as f:
            markdown_content = f.read()

        # Get title from filename or first heading
        title = os.path.splitext(os.path.basename(markdown_file))[0]

        # Convert to Confluence storage format
        storage_format = convert_markdown_to_storage_format(markdown_content)

        # Update Confluence
        auth = (username, api_token)
        result = update_confluence_page(confluence_url, auth, space_key, title, storage_format, parent_id)

        logger.info(f"Successfully uploaded to Confluence: {confluence_url}/pages/viewpage.action?pageId={result['id']}")

    except Exception as e:
        logger.error(f"Error uploading markdown to Confluence: {str(e)}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
