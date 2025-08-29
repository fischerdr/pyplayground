#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Cloud drive JSON cleanup utility.

This module provides functionality to clean cloud drive configuration JSON files
by removing entries where 'Configs' is null.
"""

import json


def clean_cloud_drive_json(input_file, output_file):
    """Read a JSON file and remove entries in 'cloud-drive' data where 'Configs' is null.

    Args:
        input_file (str): The path to the input JSON file.
        output_file (str): The path to where the cleaned file should be saved.

    Returns:
        None
    """
    with open(input_file, "r") as file:
        main_json = json.load(file)

    # Extract the embedded JSON from 'cloud-drive'
    embedded_json_str = main_json["data"]["cloud-drive"]

    # Convert the string into a Python dictionary
    embedded_json = json.loads(embedded_json_str)

    # Remove entries where 'Configs' is null
    cleaned_data = {
        key: value for key, value in embedded_json.items() if value.get("Configs") is not None
    }

    # Update the main JSON with the cleaned data, removing newlines and extra spaces for the cleaned_data only
    main_json["data"]["cloud-drive"] = json.dumps(cleaned_data, separators=(",", ":"))

    # Save the modified JSON back to a file with normal formatting for the main JSON
    with open(output_file, "w") as outfile:
        json.dump(main_json, outfile, indent=4)

    print(f"Cleaned file saved to {output_file}")


# Usage:
input_file = "path_to_your_input_file.json"
output_file = "path_to_save_cleaned_file.json"
clean_cloud_drive_json(input_file, output_file)
