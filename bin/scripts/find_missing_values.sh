#!/bin/bash

# Script to find missing values between two files
# Usage: ./find_missing_values.sh <src1> <src2> <output_file>

# Check if all arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <src1> <src2> <output_file>"
    echo "Example: $0 file1.txt file2.txt missing.txt"
    exit 1
fi

src1="$1"
src2="$2"
output_file="$3"

# Check if source files exist
if [ ! -f "$src1" ]; then
    echo "Error: Source file '$src1' does not exist"
    exit 1
fi

if [ ! -f "$src2" ]; then
    echo "Error: Source file '$src2' does not exist"
    exit 1
fi

# Find values in src1 that are not in src2
# Sort and uniq to remove duplicates
# comm -23 <(sort -u "$src1") <(sort -u "$src2") > "$output_file"

# Find values in src1 that are not in src2
# Sort and uniq to remove duplicates
comm -23 <(sort -u "$src1") <(sort -u "$src2") | xargs -n 5 > "$output_file"

echo "Missing values from $src1 (not in $src2) saved to $output_file"
