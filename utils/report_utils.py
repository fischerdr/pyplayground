"""Utilities for saving simple text summary reports."""

import logging
import os
from datetime import datetime
from typing import Dict, List

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


def save_volume_issue_report(
    backup_name: str,
    backup_uid: str,
    non_successful_volumes: List[Dict],
    script_name: str,
    log_dir: str = DEFAULT_LOG_DIR,
) -> None:
    """
    Saves details of non-successful volumes for a specific backup
    to a simple timestamped text file in the logs directory.

    Args:
        backup_name: The name of the backup.
        backup_uid: The UID of the backup.
        non_successful_volumes: A list of dictionaries, each containing details
                                 of a volume not in 'Successful' state.
        script_name: The base name of the script generating the report.
        log_dir: The directory to save the report in (defaults to DEFAULT_LOG_DIR).
    """
    if not non_successful_volumes:
        logger.debug(f"No non-successful volumes to report for backup {backup_name}.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize backup name for filename
    sanitized_backup_name = "".join(c if c.isalnum() else "_" for c in backup_name)
    report_filename = (
        f"{script_name}_non_successful_volumes_{sanitized_backup_name}_{timestamp}.txt"
    )
    report_filepath = os.path.join(log_dir, report_filename)

    try:
        # Ensure the log directory exists
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
                logger.debug(f"Created log directory: {log_dir}")
            except OSError as e:
                logger.error(
                    f"Could not create log directory '{log_dir}': {e}. Cannot save volume issue report."
                )
                return  # Cannot proceed without log directory

        # Format the report text
        formatted_text = "--- Non-Successful Volume Report ---\n"
        formatted_text += f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        formatted_text += f"Backup Name: {backup_name}\n"
        formatted_text += f"Backup UID: {backup_uid}\n\n"

        formatted_text += f"Found {len(non_successful_volumes)} non-successful volume(s):\n"
        for vol_detail in non_successful_volumes:
            formatted_text += (
                f"\n  Volume: {vol_detail.get('VolumeName', 'N/A')}\n"
                f"    Namespace: {vol_detail.get('Namespace', 'N/A')}\n"
                f"    PVC: {vol_detail.get('PVC', 'N/A')}\n"
                f"    Status: {vol_detail.get('Status', 'N/A')}\n"
                f"    Reason: {vol_detail.get('Reason', 'N/A')}\n"
            )

        # Write to file
        with open(report_filepath, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        logger.info(f"Non-successful volume report saved to: {report_filepath}")

    except IOError as e:
        logger.error(f"Could not write volume issue report to '{report_filepath}': {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred while saving volume issue report: {e}")


def save_inspect_backup_report(
    backup_details: Dict,
    script_name: str,
    log_dir: str = DEFAULT_LOG_DIR,
) -> None:
    """
    Saves detailed inspection information for a specific backup to a text file,
    mirroring the structure of the console output table.

    Args:
        backup_details: The dictionary containing the full backup details from the API.
        script_name: The base name of the script generating the report.
        log_dir: The directory to save the report in (defaults to DEFAULT_LOG_DIR).
    """
    metadata = backup_details.get("metadata", {})
    backup_name = metadata.get("name", "N/A")
    backup_uid = metadata.get("uid", "N/A")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize backup name for filename
    sanitized_backup_name = "".join(c if c.isalnum() else "_" for c in backup_name)
    report_filename = f"{script_name}_inspect_{sanitized_backup_name}_{timestamp}.txt"
    report_filepath = os.path.join(log_dir, report_filename)

    try:
        # Ensure the log directory exists
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
                logger.debug(f"Created log directory: {log_dir}")
            except OSError as e:
                logger.error(
                    f"Could not create log directory '{log_dir}': {e}. Cannot save inspect report."
                )
                return

        # --- Format the report text ---
        formatted_text = f"--- Backup Inspection Report: {backup_name} ---\n"
        formatted_text += f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        formatted_text += f"Backup UID: {backup_uid}\n\n"

        # Extract data (similar to the console table population)
        backup_info = backup_details.get("backup_info", {})
        cluster_ref = backup_info.get("cluster_ref", {})
        location_ref = backup_info.get("backup_location_ref", {})
        backup_type_info = backup_info.get("backup_type", {})
        status_info = backup_info.get("status", {})
        schedule_ref = backup_info.get("schedule_ref", {})
        namespaces = backup_info.get("namespaces", [])
        volumes = backup_info.get("volumes", [])

        backup_type_str = (
            backup_type_info.get("type", "N/A") if isinstance(backup_type_info, dict) else "N/A"
        )
        status_str = status_info.get("status", "N/A") if isinstance(status_info, dict) else "N/A"

        # Main Details
        details = [
            ("Name:", metadata.get("name", "N/A")),
            ("UID:", metadata.get("uid", "N/A")),
            ("Status:", status_str),
            ("Backup Type:", backup_type_str),
            ("Cluster:", cluster_ref.get("name", "N/A")),
            ("Backup Location:", location_ref.get("name", "N/A")),
            ("Namespace Count:", str(len(namespaces))),
            ("Created Time:", metadata.get("create_time", "N/A")),
            ("Start Time:", backup_info.get("start_time", "N/A")),
            ("Completion Time:", backup_info.get("completion_time", "N/A")),
        ]
        schedule_name = schedule_ref.get("name")
        if schedule_name:
            details.append(("Schedule Name:", schedule_name))

        # Format main details with padding
        max_key_len = max(len(k) for k, v in details) if details else 0
        for key, value in details:
            formatted_text += f"{key:<{max_key_len}} {value}\n"

        # Volume Status Summary
        formatted_text += "\nVolume Status Summary:\n"
        if volumes:
            from collections import Counter

            volume_statuses = Counter(
                vol.get("status", {}).get("status", "Unknown") for vol in volumes
            )
            if volume_statuses:
                for status, count in sorted(volume_statuses.items()):
                    formatted_text += f"  {status}: {count}\n"
            else:
                formatted_text += "  No volume status information available.\n"
        else:
            formatted_text += "  Volumes: 0\n"

        # --- Write to file ---
        with open(report_filepath, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        logger.info(f"Detailed inspect report saved to: {report_filepath}")

    except IOError as e:
        logger.error(f"Could not write inspect report to '{report_filepath}': {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred while saving inspect report: {e}")
