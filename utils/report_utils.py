"""Utilities for saving simple text summary reports."""

import logging
import os
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

# Get the project root directory (assuming utils is one level down)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "logs")


def save_summary_report(
    summary_data: Dict,
    report_title: str,
    script_name: str,
    log_dir: str = DEFAULT_LOG_DIR,
) -> None:
    """
    Saves provided data to a simple timestamped text file in the logs directory.

    Args:
        summary_data: A dictionary (for inspect) or list of dictionaries (for list)
                      containing the data to report.
        report_title: The title to put at the top of the report.
        script_name: The base name of the script generating the report.
        log_dir: The directory to save the report in (defaults to DEFAULT_LOG_DIR).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"{script_name}_summary_{timestamp}.txt"
    report_filepath = os.path.join(log_dir, report_filename)

    try:
        # Ensure the log directory exists
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
                logger.debug(f"Created log directory: {log_dir}")
            except OSError as e:
                logger.error(
                    f"Could not create log directory '{log_dir}': {e}. Cannot save summary."
                )
                return  # Cannot proceed without log directory

        formatted_text = f"--- {report_title} ---\
Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\
\
"

        if isinstance(summary_data, dict):
            # Format dictionary as Key: Value pairs
            max_key_len = max(len(str(k)) for k in summary_data.keys()) if summary_data else 0
            for key, value in summary_data.items():
                formatted_text += f"{str(key):<{max_key_len}}: {value}\n"

        # --- Write to file ---
        with open(report_filepath, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        logger.info(f"Summary report saved to: {report_filepath}")

    except IOError as e:
        logger.error(f"Could not write summary report to '{report_filepath}': {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred while saving summary report: {e}")
