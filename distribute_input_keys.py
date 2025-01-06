import random


def distribute_input_keys(input_dict):
    """
    Evenly distribute keys from the input dictionary into six groups based on their 'count' values.

    Args:
        input_dict (dict): A dictionary where each key contains a nested dictionary with a 'count' key.

    Returns:
        dict: A dictionary with specified keys ('4am', '8am', '12pm', '4pm', '8pm', '12am') 
              containing evenly distributed input keys and their totals.
        int: The total count of all 'count' values from the input dictionary.
    """
    # Ensure all keys in the input dictionary have a 'count' key
    for key, value in input_dict.items():
        if not isinstance(value, dict) or 'count' not in value:
            raise ValueError(f"Each key in the input dictionary must contain a nested 'count' key. Problem with key: {key}")
    
    # Calculate the total count across all input counts
    total_count = sum(value['count'] for value in input_dict.values())

    # Sort the input dictionary by the 'count' values (descending order)
    sorted_items = sorted(input_dict.items(), key=lambda x: x[1]['count'], reverse=True)
    
    # Initialize the six groups with custom keys
    group_labels = ["4am", "8am", "12pm", "4pm", "8pm", "12am"]
    groups = {label: {'keys': [], 'total_count': 0} for label in group_labels}

    # Distribute keys into groups to balance the total count
    for key, value in sorted_items:
        # Find the group with the smallest current count
        smallest_group = min(groups.values(), key=lambda x: x['total_count'])
        # Add the key to that group
        for group_label, group_data in groups.items():
            if group_data == smallest_group:
                group_data['keys'].append(key)
                group_data['total_count'] += value['count']
                break

    # Prepare the output dictionary
    output_dict = {
        label: {'keys': data['keys'], 'total_count': data['total_count']}
        for label, data in groups.items()
    }
    return output_dict, total_count

# Generate an input dictionary with 100 keys and random counts between 1 and 1000
input_data = {
    f'key{i}': {'count': random.randint(1, 86)} for i in range(1, 101)
}
output_dict, total = distribute_input_keys(input_data)
# Display the results
print("Distributed Dictionary:")
for group, data in output_dict.items():
    print(f"{group}: Total Count = {data['total_count']}, Keys = {data['keys']}")
print(f"Overall Total Count: {total}")