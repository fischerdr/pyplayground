#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Path replacement utility for cloud drive configurations.

This module provides functionality to replace paths in cloud drive configuration
JSON files using mappings from CSV files.

Usage:
    Run the other script and come up with a mapping of old_path,new_path in a file (mapping.csv)
    $K8S_CMD get cm <cluster-name> -ojson -n kube-system >./clouddrive.cm.json
    python path_replace.py --mapping ./mapping.csv --cd_config ./clouddrive.cm.json
    Verify that the modifications have happened
    cat ./clouddrive.cm_modified.json | jq -r '.data."cloud-drive"'| jq . > /tmp/1.json
    cat ./clouddrive.cm.json | jq -r '.data."cloud-drive"'| jq . > /tmp/2.json
    diff /tmp/1.json /tmp/2.json
    kubectl apply -f clouddrive.cm_modified.json
"""

import argparse
import csv
import json
import os


def read_csv(file_path):
    """Read CSV file and return path mappings.

    Args:
        file_path (str): Path to the CSV file containing old_path,new_path mappings.

    Returns:
        List[Tuple[str, str]]: List of (old_path, new_path) tuples.
    """
    path_mappings = []
    with open(file_path, mode="r") as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            if len(row) == 2:
                old_path, new_path = row
                path_mappings.append((old_path, new_path))
    return path_mappings


def replace_paths_in_json(json_content, path_mappings):
    """Replace paths in JSON content using provided mappings.

    Args:
        json_content (dict): The JSON content to modify.
        path_mappings (List[Tuple[str, str]]): List of (old_path, new_path) tuples.

    Returns:
        dict: Modified JSON content with paths replaced.
    """
    json_str = json.dumps(json_content)
    # print(json_str)
    for old_path, new_path in path_mappings:
        old_path = old_path.split()[1]
        new_path = new_path.split()[1]
        # print(f"{old_path} {new_path}")
        json_str = json_str.replace(old_path, new_path)
    # print(json_str)
    return json.loads(json_str)


def main(csv_file_path, json_file_path):
    """Main function to process path replacements.

    Args:
        csv_file_path (str): Path to the CSV file with mappings.
        json_file_path (str): Path to the JSON file to modify.
    """
    # Read the CSV file
    path_mappings = read_csv(csv_file_path)

    # Read the JSON file
    with open(json_file_path, "r") as json_file:
        json_content = json.load(json_file)

    # Replace old paths with new paths
    updated_json_content = replace_paths_in_json(json_content, path_mappings)

    # Derive the output file path
    base, ext = os.path.splitext(json_file_path)
    output_file_path = f"{base}_modified{ext}"

    # Write the updated JSON content to the new file
    with open(output_file_path, "w") as output_file:
        json.dump(updated_json_content, output_file, indent=4)

    print(f"Updated JSON content has been saved to {output_file_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replace paths in a JSON file based on a CSV mapping file."
    )
    parser.add_argument("--mapping", required=True, help="Path to the CSV mapping file.")
    parser.add_argument("--cd_config", required=True, help="Path to the JSON configuration file.")

    args = parser.parse_args()

    print("This script assumes that the source and destination paths are in the same datastore")
    main(args.mapping, args.cd_config)
