import json
import subprocess
import sys

"""
Instructions to use it:
gov is required
export PX_NS=<px-namespace>
export GOVC_USERNAME=$(kubectl get secrets px-vsphere-secret -ojson -n $PX_NS| jq -r '.data.VSPHERE_USER'| base64 -d)
export GOVC_PASSWORD=$(kubectl get secrets px-vsphere-secret -ojson -n $PX_NS| jq -r '.data.VSPHERE_PASSWORD'| base64 -d)
export GOVC_URL=$(kubectl get stc -n $PX_NS -ojson | jq -r '.items[0].spec.env[] | select(.name=="VSPHERE_VCENTER") | .value')/sdk
export GOVC_INSECURE=true
export GOVC_DATACENTER= # if multiple Datacenters are there

Create a cd.json from the configmap
kubectl get cm <cluster-name> -ojson -n kube-system | jq -r '.data."cloud-drive"'| jq . > cd.json

python parse_cd.py cd.json  
"""
def extract_vmdk_info(json_string):
    data = json.loads(json_string)

    vmdk_info = {}

    for vm in data['VirtualMachines']:
        for device in vm['Config']['Hardware']['Device']:
            if device is None:
                continue
            if 'Backing' in device:
                if device['Backing'] is None:
                    continue

            if 'FileName' in device['Backing']:
                filename=device['Backing']['FileName']
                filePath=filename.split()[1]
                ds=device['Backing']['Datastore']['Value']
                key="["+ds + "] " + filePath
                value= device['CapacityInKB'] / (1024 * 1024)
                vmdk_info[key]=value

    return vmdk_info

# Check if the filename is provided as an argument
if len(sys.argv) != 2:
    print("Usage: python parse_cd.py <filename>")
    sys.exit(1)

# Get the filename from the arguments
filename = sys.argv[1]

# Read JSON data from file
with open(filename, 'r') as file:
    data = json.load(file)

print("Storage nodes only")
# Loop through each key in the JSON object
for key, value in data.items():
    instance_id = value.get('InstanceID')
    scheduler = value.get('SchedulerNodeName')
    all_drives = ""
    if instance_id:

        # Execute the govc vm command
        result = subprocess.run(['govc', 'vm.info', f'-vm.uuid={instance_id}', '-json'], capture_output=True, text=True)
        all_drives=extract_vmdk_info(result.stdout)

    configs = value.get('Configs', {})
    if configs:
        found = False
        for config_key, config_value in configs.items():
            if config_key not in all_drives:
                print(f"Expected: {config_key}|{config_value['Size']}| {config_value['Path']}")
                found = True
        if found:
            print(f"Mismatch: Node: {scheduler}")
            for key, value in all_drives.items():
                print(f"{key}: {value} GB")
        else:
            print(f"Good: Node: {scheduler}")


