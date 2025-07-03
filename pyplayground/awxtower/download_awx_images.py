#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Download AWX container images for air-gapped installation.

This script downloads all required images and saves them as tar files.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("awx-image-downloader")

# Initialize Typer app
app = typer.Typer(help="Download AWX container images for air-gapped installation")

# Define required images and their versions
REQUIRED_IMAGES = {
    # Mandatory Images
    "awx-operator": "quay.io/ansible/awx-operator:latest",
    "awx": "quay.io/ansible/awx:latest",
    "postgres": "postgres:13",
    "redis": "redis:latest",
    # Execution Environments
    "awx-ee": "quay.io/ansible/awx-ee:latest",
    "awx-ee-control-plane": "quay.io/ansible/awx-ee-control-plane:latest",
    # Initialization Containers
    "init-container": "quay.io/ansible/awx-operator-init-container:latest",
    "init-projects": "quay.io/ansible/awx-operator-init-projects:latest",
}


def run_command(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True,
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(cmd)}")
        logger.error(f"Error: {e.stderr}")
        raise


def pull_image(image: str) -> None:
    """Pull a container image."""
    logger.info(f"Pulling image: {image}")
    run_command(["podman", "pull", image])


def save_image(image: str, output_dir: Path) -> None:
    """Save a container image as a tar file."""
    # Extract image name without registry and tag
    image_name = image.split("/")[-1].split(":")[0]
    output_file = output_dir / f"{image_name}.tar"

    logger.info(f"Saving image {image} to {output_file}")
    run_command(["podman", "save", "-o", str(output_file), image])


def load_custom_images(custom_images_file: Optional[Path]) -> Dict[str, str]:
    """Load custom images from a YAML file."""
    if not custom_images_file:
        return {}

    try:
        import yaml

        with open(custom_images_file) as f:
            data = yaml.safe_load(f)
            return data.get("images", {})
    except Exception as e:
        logger.error(f"Failed to load custom images: {str(e)}")
        return {}


@app.command()
def download_images(
    output_dir: Path = typer.Option(
        Path("awx-images"),
        help="Directory to save the downloaded images",
        exists=False,
    ),
    registry: Optional[str] = typer.Option(
        None,
        help="Target registry for the images (e.g., registry.example.com)",
    ),
    custom_images: Optional[Path] = typer.Option(
        None,
        help="Path to YAML file containing custom images to download",
        exists=True,
    ),
    skip_ee: bool = typer.Option(
        False,
        help="Skip downloading execution environment images",
    ),
) -> None:
    """Download all required AWX container images and save them as tar files.

    Optionally tag them for a target registry and include custom images.
    """
    console = Console()

    try:
        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {output_dir}")

        # Load custom images if specified
        custom_images_dict = load_custom_images(custom_images)
        if custom_images_dict:
            logger.info(f"Loaded {len(custom_images_dict)} custom images")
            REQUIRED_IMAGES.update(custom_images_dict)

        # Filter out EE images if requested
        images_to_download = {
            k: v for k, v in REQUIRED_IMAGES.items() if not (skip_ee and k.startswith("awx-ee"))
        }

        # Pull and save each image
        for name, image in images_to_download.items():
            with console.status(f"Processing {name}..."):
                try:
                    # Pull the image
                    pull_image(image)

                    # If registry is specified, tag the image
                    if registry:
                        new_tag = f"{registry}/{image.split('/')[-1]}"
                        run_command(["podman", "tag", image, new_tag])
                        image = new_tag

                    # Save the image
                    save_image(image, output_dir)

                except Exception as e:
                    logger.error(f"Failed to process {name}: {str(e)}")
                    raise

        logger.info("All images downloaded successfully!")

    except Exception as e:
        logger.error(f"Failed to download images: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    app()
