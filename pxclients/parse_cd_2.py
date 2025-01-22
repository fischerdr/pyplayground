import json
import subprocess
import sys


def extract_vmdk_info(json_string):
    data = json.loads(json_string)

    vmdk_info = {}

    for vm in data["VirtualMachines"]:
        for device in vm["Config"]["Hardware"]["Device"]:
            if device is None:
                continue
            if "Backing" in device:
                if device["Backing"] is None:
                    continue

            if "FileName" in device["Backing"]:
                filename = device["Backing"]["FileName"]
                filePath = filename.split()[1]
                ds = device["Backing"]["Datastore"]["Value"]
                key = "[" + ds + "] " + filePath
                value = device["CapacityInKB"] / (1024 * 1024)
                vmdk_info[key] = value

    return vmdk_info


# Check if the filename is provided as an argument
if len(sys.argv) != 2:
    print("Usage: python parse_cd.py <filename>")
    sys.exit(1)

# Get the filename from the arguments
filename = sys.argv[1]

# Read JSON data from file
with open(filename, "r") as file:
    data = json.load(file)

print("Storage nodes only")
# Loop through each key in the JSON object
all_replaces = {}
for key, value in data.items():
    instance_id = value.get("InstanceID")
    scheduler = value.get("SchedulerNodeName")
    all_drives = ""
    if instance_id:
        # Execute the govc vm command
        result = subprocess.run(
            ["govc", "vm.info", f"-vm.uuid={instance_id}", "-json"], capture_output=True, text=True
        )
        all_drives = extract_vmdk_info(result.stdout)

    configs = value.get("Configs", {})
    expected = []
    exp_map = {}
    all_drives_map = {}
    good = True
    for key, value in all_drives.items():
        if value in all_drives_map:
            good = False
        else:
            all_drives_map[value] = key
    if configs:
        mismatch = False
        for config_key, config_value in configs.items():
            if config_key not in all_drives:
                expected.append(f"{config_key}| {config_value['Size']} GB| {config_value['Path']}")
                mismatch = True
                if good:
                    if config_value["Size"] in exp_map:
                        good = False
                    else:
                        exp_map[config_value["Size"]] = config_key
        if mismatch:
            if good:
                for key, value in exp_map.items():
                    all_replaces[value] = all_drives_map[key]
                pass
            else:
                print(f"Mismatch: Node: {scheduler}")
                print("\tExpected")
                for i in expected:
                    print(f"\t\t{i}")
                print("\tAttached on VM")
                for key, value in all_drives.items():
                    print(f"\t\t{key}: {value} GB")
        else:
            print(f"Good: Node: {scheduler}")
print("Mapping:")
for key, value in all_replaces.items():
    print(f"{key},{value}")
