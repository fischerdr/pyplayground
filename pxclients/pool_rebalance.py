import subprocess
import json
import datetime
import csv
import os
import difflib
import argparse

from datetime import datetime

#PX_NAMESPACE="kube-system"
PX_NAMESPACE="portworx"
GOVC="govc"
shortNameMap={}

# Declare an associative array
dsFullPath={}

# Add key-value pairs to the map
dsFullPath["HK-TKO102-CL15-PX-535-244-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-244-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-535-245-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-245-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-535-249-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-249-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-535-250-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-250-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-535-251-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-251-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-535-252-IKP-PURE"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-535-252-IKP-PURE"
dsFullPath["HK-TKO102-CL15-PX-NEW-1"]="/HK-TKO102/datastore/Portworx/HK-TKO102-CL15-PX-NEW-1"
dsFullPath["HK-TKO103-CL15-PX-NEW-2"]="/HK-TKO102/datastore/Portworx/HK-TKO103-CL15-PX-NEW-2"


####################--------START-------######################
# Copy paste dsShortName output below


####################--------END--------######################

dsFullPath["js500-9-HSBC-nrevanna-01"]="/CNBU/datastore/js500-9-HSBC-nrevanna-01"
dsFullPath["js500-9-HSBC-nrevanna-02"]="/CNBU/datastore/js500-9-HSBC-nrevanna-02"
dsFullPath["js500-9-HSBC-nrevanna-03"]="/CNBU/datastore/js500-9-HSBC-nrevanna-03"
dsFullPath["js500-9-HSBC-nrevanna-04"]="/CNBU/datastore/js500-9-HSBC-nrevanna-04"
dsFullPath["js500-9-HSBC-nrevanna-05"]="/CNBU/datastore/js500-9-HSBC-nrevanna-05"
dsFullPath["js500-9-HSBC-nrevanna-06"]="/CNBU/datastore/js500-9-HSBC-nrevanna-06"
dsFullPath["js500-9-HSBC-nrevanna-07"]="/CNBU/datastore/js500-9-HSBC-nrevanna-07"
dsFullPath["js500-9-DS2"]="/CNBU/datastore/js500-9-DS2"

dsFullPath["Dev-Sandbox-N5-guava-ds01"]="/slc5-n5-CNBU/datastore/Dev-Sandbox-N5-DS/Dev-Sandbox-N5-guava-ds01"
dsFullPath["Dev-Sandbox-N5-plum-ds01"]="/slc5-n5-CNBU/datastore/Dev-Sandbox-N5-DS/Dev-Sandbox-N5-plum-ds01"
dsFullPath["cds-1"]="/Lehi/datastore/cds-1"
dsFullPath["cds-2"]="/Lehi/datastore/cds-2"
dsFullPath["cds-3"]="/Lehi/datastore/cds-3"

def px_exec_some_pod(cmd):
    px_label_selector = "name=portworx"
    px_cmd = f"kubectl get pods -l {px_label_selector} -n {PX_NAMESPACE} --no-headers"
    output = subprocess.check_output(px_cmd.split()).decode("utf-8")
    lines = output.strip().split("\n")
    for line in lines:
        if "2/2" in line:
            some_pod = line.split()[0]
            return px_exec(some_pod, cmd)
            break

def px_exec(pod_name, cmd):
    px_container = "portworx"
    nsenter_cmd = "nsenter --mount=/host_proc/1/ns/mnt bash -c"
    full_cmd = f"kubectl exec -it {pod_name} -n {PX_NAMESPACE} -c {px_container} -- {nsenter_cmd} \"{cmd}\""
    return subprocess.check_output(full_cmd, shell=True).decode()

def get_scheduler_name(node_id):
    cmd = f"pxctl status | grep -v 'Node ID' | grep {node_id}"
    output = px_exec_some_pod(cmd)
    return output.split()[2]

def shell_exec(verbose, cmd):
    if verbose:
        print("Running: " + cmd)
    return subprocess.check_output(cmd, shell=True).decode().strip()

def get_pod_name(node_id):
    sched_name = get_scheduler_name(node_id)
    cmd = f"kubectl get pods -l name=portworx -n {PX_NAMESPACE} --no-headers -owide | grep {sched_name}"
    output = shell_exec(False,cmd)
    return output.split()[0]

def convert_uuid_format(uuid):
    uuid_without_dashes = uuid.replace("-", "")
    converted_uuid = f"{uuid_without_dashes[:8]}-{uuid_without_dashes[8:12]}-{uuid_without_dashes[12:16]}-{uuid_without_dashes[16:20]}-{uuid_without_dashes[20:]}"
    return converted_uuid


def get_vm_uuid(node_id):
    pod_name = get_pod_name(node_id)
    cmd = "cat /sys/class/dmi/id/product_serial"
    output = px_exec(pod_name, cmd)
    vm_uuid = output.replace('VMware-', '').replace('-', ' ').lower().split()
    vm_uuid = '-'.join(vm_uuid)
    return convert_uuid_format(vm_uuid)


def get_cm_cloud_drive():
    cm_cloud_drive = shell_exec(False,"kubectl get cm -n kube-system | grep px-cloud-drive").split()[0]
    cmd = f"kubectl get cm {cm_cloud_drive} -n kube-system -ojson"
    cm_json = shell_exec(False,cmd)
    cm_data = json.loads(cm_json)
    del cm_data['metadata']['resourceVersion']
    del cm_data['metadata']['uid']
    if "annotations" in cm_data['metadata'] and 'kubectl.kubernetes.io/last-applied-configuration' in cm_data['metadata']['annotations']['kubectl.kubernetes.io/last-applied-configuration']:
        del cm_data['metadata']['annotations']['kubectl.kubernetes.io/last-applied-configuration']
    return cm_data

def setup_config_map_files():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    before_config_map = f"before_configmap_{timestamp}.json"
    after_config_map = f"after_configmap_{timestamp}.json"

    before_data = get_cm_cloud_drive()
    with open(before_config_map, 'w') as f:
        json.dump(before_data, f)
    with open(after_config_map, 'w') as f:
        json.dump(before_data, f)

    return after_config_map

'''
The old and new vmdk paths given here must have the datastore name in the format we need in configmap. i.e short name
'''
def update_vmdk_path_helper(json_file_to_modify, new_datastore_full_name, destination_file, old_vmdk_path, new_vmdk_path):
    try:
        # Open the JSON file for reading
        with open(json_file_to_modify, 'r') as json_file:
            data = json.load(json_file)

        # Check if the "data" key exists
        if "data" in data:
            # Check if "cloud-drive" key exists within the "data" dictionary
            if "cloud-drive" in data["data"]:
                # Parse the JSON string within the "cloud-drive" key
                cloud_drive_data = json.loads(data["data"]["cloud-drive"])
                #print(len(cloud_drive_data))
                # Check if the old_vmdk_path exists within the parsed JSON
                found = False
                for node_id, configs in cloud_drive_data.items():
                    #print(configs)
                    if old_vmdk_path in configs["Configs"]:
                        #print("Found")
                        found = True
                        drive_content = configs["Configs"].pop(old_vmdk_path)
                        drive_content["ID"] =new_vmdk_path
                        drive_content["labels"]["datastore"] = new_datastore_full_name
                        
                        cloud_drive_data[node_id]["Configs"][new_vmdk_path] = drive_content

                        # Convert the updated JSON back to a string
                        updated_cloud_drive_json = json.dumps(cloud_drive_data)

                        # Update the "cloud-drive" key in the original JSON
                        data["data"]["cloud-drive"] = updated_cloud_drive_json

                        # Write the modified data back to the JSON file
                        with open(destination_file, 'w') as json_file:
                            json.dump(data, json_file, indent=4)

                        print(f"Modified JSON and saved to {destination_file}")
                        break
                if found is False:
                    print("Unable to find {old_vmdk_path} in the input file")
            else:
                print("No 'cloud-drive' key found in the 'data' dictionary.")
        else:
            print("No 'data' key found in the JSON file.")

    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
    except IOError as e:
        print(f"Error reading/writing JSON file: {e}")

def update_config_map_with_new_paths(src, dst, vmdk_path, filename):
    src_short = get_short_name(src)
    dst_short = get_short_name(dst)

    src_ds = f"[{src_short}] {vmdk_path}"
    dst_ds = f"[{dst_short}] {vmdk_path}"

    update_vmdk_path_helper(filename, dst, filename, src_ds, dst_ds)

def wait_for_key_press():
    user_input = input("Proceed [Y/N]: ").lower()

    if user_input == "y":
        print("Continuing...")
        # Perform further actions here

    elif user_input == "n":
        print("Exiting...")
        exit(0)

    else:
        print("Invalid input. Please enter Y or N.")
        # Ask again if the input is invalid
        wait_for_key_press()

def pretty_format_cd(filename):
    with open(filename, 'r') as f:
        config_map_data = f.read()

    try:
        parsed_json = json.loads(config_map_data)
        parsed_json = parsed_json['data']['cloud-drive'].replace('\\\"','"')
        formatted_json = json.dumps(json.loads(parsed_json), indent=4)
        return formatted_json
    except json.JSONDecodeError:
        print("Error: Invalid JSON format")
    return ""

def move_datastores(dry_run, node_id, config_map_file, input_file):
    # Check if nodeID is missing
    if not node_id:
        print("Error: Missing nodeID for moveDatastores function")
        return 1
    with open(input_file, 'r') as file:
        #/print("Debug: Entering datastore movement")
        reader = csv.reader(file)
        for columns in reader:
            if len(columns) == 0:
                continue
            # Assign variable names to columns
            node = columns[0]
            if node != node_id:
                continue
            src = columns[1]
            dst = columns[2]
            vmdk = columns[3]
            #print("Debug: Entering datastore movement values - " + src + "," + dst + "," +vmdk )
            directory = os.path.dirname(vmdk)
            fullPathDst = dsFullPath[dst]
            fullPathSrc = dsFullPath[src]

            cmd=f"{GOVC} datastore.mkdir -p -ds={fullPathDst} {directory}"
            if dry_run:
                print("Running: "+ cmd)
            else:
                shell_exec(True,cmd)

            cmd=f"{GOVC} datastore.mv -ds={fullPathSrc} -ds-target={fullPathDst} {vmdk} {vmdk}"
            if dry_run:
                print("Running: "+ cmd)
            else:
                shell_exec(True,cmd)

            msg = f'Updating configmap paths.. ({src},{dst}, {vmdk}, {config_map_file})'
            if dry_run:
                print("Dry run:" + msg)
            else:
                print(msg)
                update_config_map_with_new_paths(src, dst, vmdk, config_map_file)

def get_disks_to_detach(node_id):
    vm_uuid = get_vm_uuid(node_id)
    vmdk_list = px_exec_some_pod(f'pxctl cd list-drives| grep \.vmdk | grep {node_id}').splitlines()
    #print(f"The following are the PX VMDKS attached on node {node_id}")
    allvmdks ={}
    for vmdk in vmdk_list:
        vmdkName = vmdk.split()[1]
        #print("\t" + vmdkName)
        allvmdks[vmdkName] = 0

    print("VM UUID: " + vm_uuid)

    # Get all virtual disks on the VM
    cmd = f'{GOVC} device.ls -vm.uuid="{vm_uuid}" -json | tr \'[:upper:]\' \'[:lower:]\' | jq \'.devices[] | select(.type | contains("virtualdisk")) | .name\''
    all_vm_vdisks = shell_exec(False,cmd)
    ret_px_vdisks = []

    print("Mapping of PX vmdks and VM disk names and their UUIDs")
    for vdisk in all_vm_vdisks.split("\n"):
        d = vdisk.replace('"','')
        cmd = f'govc device.info -vm.uuid="{vm_uuid}" -json {d} |  tr \'[:upper:]\' \'[:lower:]\' | jq \'.devices | .[] | .name + " " + .backing.filename + " " + .backing.uuid\''
        output = shell_exec(False,cmd)
        vmdk = output.split()[2]
        vdisk = output.split()[0].replace('"','')
        if vmdk not in allvmdks:
            continue
        print(output)
        ret_px_vdisks.append(vdisk)

    vmdk_count = len(allvmdks)
    vdisk_count = len(ret_px_vdisks)

    if vmdk_count != vdisk_count:
        print(f"Mismatch in VMDK count({vmdk_count}) and actual vDisks on the VM ({vdisk_count}). Node ID {node_id}. Exiting. Rerun")
        exit(0)
    return ret_px_vdisks

def detach_px_vmdks(dry_run, node_id):
    vm_uuid = get_vm_uuid(node_id)

    ret_px_vdisks = get_disks_to_detach(node_id)
    sched_name = get_scheduler_name(node_id)

    print(f"Proceed with disk detach for nodeID {node_id} ({sched_name})?")
    wait_for_key_press()

    print(f"Stopping px on {node_id} ({sched_name})")
    subprocess.run(['kubectl', '-n', PX_NAMESPACE, 'label', 'node', sched_name, 'px/service=stop', '--overwrite'])

    print("Wait for pod to go down")
    wait_for_key_press()


    print(f"The following will be detached from VM {vm_uuid}")
    print(ret_px_vdisks)

    for vdisk in ret_px_vdisks:
        cmd = f'govc device.remove -vm.uuid={vm_uuid} -keep {vdisk}'
        if not dry_run:
            shell_exec(True, cmd)
        else:
            print("Dry run: " + cmd)

    print(f"Detached from {node_id}")


def compare_json_strings(json_str1, json_str2):
    json_obj1 = json.loads(json_str1)
    json_obj2 = json.loads(json_str2)
    diff = difflib.unified_diff(
        json.dumps(json_obj1, indent=2).splitlines(),
        json.dumps(json_obj2, indent=2).splitlines(),
        lineterm=''
    )
    return '\n'.join(diff)

def update_one_node(dry_run, node_id, input_file):
    pod_name = get_pod_name(node_id)

    ###################------------STEP 1----------------------#####################
    print("----- STEP 1: Detaching VMDKs and stopping PX on node " + node_id)
    detach_px_vmdks(dry_run, node_id)
    config_map_file = setup_config_map_files()
    before_file = config_map_file.replace("after", "before")

    ###################------------STEP 2----------------------#####################
    print("----- STEP 2: Move VMDKs belonging to node " + node_id + " and have the new configmap at " + config_map_file)
    #print("Debug: Calling move_datastores" + "," + node_id + "," + config_map_file + "," + input_file )
    move_datastores(dry_run, node_id, config_map_file, input_file)

    print("This is the diff between the old and new config... Proceed?")
    print(compare_json_strings(pretty_format_cd(before_file), pretty_format_cd(config_map_file)))
    wait_for_key_press()

    ###################------------STEP 3----------------------#####################
    print("----- STEP 3: Apply the new configmap")
    cm_cloud_drive = subprocess.check_output("kubectl get cm -n kube-system | grep px-cloud-drive | awk '{print $1}'", shell=True).decode().strip()
    # Check if the string is empty
    if not cm_cloud_drive:
        print("Could not find cloud drive configmap")
        exit(1)
    subprocess.run(["kubectl", "delete", "cm", cm_cloud_drive, "-n", "kube-system"])
    subprocess.run(["kubectl", "apply", "-f", config_map_file])

    ###################------------STEP 4----------------------#####################
    print("----- STEP 4: Restart PX on " + node_id)
    schedName = get_scheduler_name(node_id)
    print("Restarting px on " + node_id + " (" + schedName + ")")
    subprocess.run(["kubectl", "label", "node", schedName, "px/service=restart", "--overwrite"])

    print("\nWait for PX to come up on " + node_id + " (" + schedName + ") before proceeding to the next node")
    print("Check for the below output to be 2/2")
    print(f'kubectl get pods {pod_name} -n {PX_NAMESPACE}')


def get_short_name(ds_name):
    if ds_name not in shortNameMap:
        full_path = dsFullPath[ds_name]
        short_name = subprocess.check_output([GOVC, "datastore.info", "-json", full_path]).decode()
        short_name = subprocess.check_output(['jq', '.datastores[].summary.datastore.value'], input=short_name.encode()).decode().strip()
        print("dsShortName[\"{0}\"]={1}".format(ds_name, short_name))
        shortNameMap[ds_name] = short_name.replace('"','')
    return shortNameMap[ds_name]

def backup_configmap(output_type, backup_filename):
    cm_cloud_drive = shell_exec(False,"kubectl get cm -n kube-system | grep px-cloud-drive").split()[0]
    cmd = f"kubectl get cm {cm_cloud_drive} -n kube-system -o" + output_type
    cm_yaml = shell_exec(False,cmd)
    with open(backup_filename, 'w') as f:
        f.write(cm_yaml)

def pre_reqs(input_file):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename=f'Primary_backup_{timestamp}.yaml'
    print("\n#-- Taking a backup of the configmap at {}".format(filename))
    backup_configmap("yaml", filename)

    filename=f'Primary_backup_{timestamp}.yaml'
    print("\n#-- Taking a second backup of the configmap at {}".format(filename.replace(".yaml",".json")))
    backup_configmap("json", filename)

    node_ids = subprocess.check_output("awk -F ',' '{print $1}' " + input_file + " | sort -u", shell=True).decode().strip()
    print("\n#######------Run the following commands-----------##############")
    for node_id in node_ids.split():
        print(f"python3.6 pool_rebalance.py rebalance start --node-id {node_id} --input-file {input_file}")

'''
This function will take in a csv file of datastore short name, datastore full name
and return two dictionaries - one keyed on short name another keyed on full name
'''
def create_dict_from_file(input_file):
    # Initialize an empty dictionary to store the data
    shortname_key_dict = {}
    fullname_key_dict = {}

    # Open the file for reading
    with open(input_file, "r") as file:
        # Read each line in the file
        for line in file:
            # Split the line using a comma as the delimiter
            parts = line.strip().split(",")

            # Ensure there are two parts (short name and long name)
            if len(parts) == 2:
                short_name, long_name = parts
                # Store the data in the dictionary
                shortname_key_dict[short_name.strip()] = long_name.strip()
                fullname_key_dict[long_name.strip()] = short_name.strip()

    # Return the resulting dictionary
    return shortname_key_dict, fullname_key_dict

def update_vmdk_paths(json_file_to_modify, ds_mapping_file, destination_file, old_vmdk_path, new_vmdk_path):
    try:
        new_ds_name_input = new_vmdk_path.split()[0].replace("[","").replace("]","")

        # Call the function to create the dictionary
        shortname_dict, fullname_dict = create_dict_from_file(ds_mapping_file)

        if new_ds_name_input not in shortname_dict and new_ds_name_input not in fullname_dict:
            print(f"Can't find the datastore {new_ds_name_input} in the input file of datastore mappings")

        new_datastore_full_name = new_ds_name_input
        if new_ds_name_input in shortname_dict:
            new_datastore_full_name = shortname_dict[new_ds_name_input]

        # user input has the full datastore name. Need to change that to short name
        if new_ds_name_input in fullname_dict:
            #print(f"Found: {new_ds_name_input}, {fullname_dict[new_ds_name_input]}")
            new_vmdk_path = new_vmdk_path.replace(new_ds_name_input, fullname_dict[new_ds_name_input])

        update_vmdk_path_helper(json_file_to_modify, new_datastore_full_name, destination_file, old_vmdk_path, new_vmdk_path)
        #print(new_vmdk_path)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
    except IOError as e:
        print(f"Error reading/writing JSON file: {e}")
    print("Diff of the two files")
    print(compare_json_strings(pretty_format_cd(json_file_to_modify), pretty_format_cd(destination_file)))

def rebalance_start(node_id, input_file):
 # Implement the logic for the "rebalance start" subcommand here
 print(f"Starting rebalance with Node ID: {node_id} and Input File: {input_file}")
 update_one_node(False, node_id, input_file)

def rebalance_pre_req(input_file):
 # Implement the logic for the "rebalance pre-req" subcommand here
 print(f"Checking prerequisites for rebalance with Input File: {input_file}")
 pre_reqs(input_file)

def main():
 parser = argparse.ArgumentParser(description="My CLI Tool")

 # Create subparsers for subcommands
 subparsers = parser.add_subparsers(title="Subcommands", dest="subcommand")

 # Subcommand: update-vmdk-paths
 parser_update = subparsers.add_parser("update-vmdk-paths", help="Update VMDK paths")

 # Optional arguments for update-vmdk-paths
 parser_update.add_argument("--input-json-file", required=True, help="output of `kubectl get cm <px-cloud-drive-cofigmap> -ojson -n kube-system")
 parser_update.add_argument("--ds-mapping-file", required=True, help="A csv file in which each line looks something like this `datastore-2334, SOME-DATASTORE-NAME`")
 parser_update.add_argument("--old-vmdk-path", required=True, help="Full path of VMDK to replace. [datastore_name] fcd/xxx/xxxxxxxxxxxxxx.vmdk")
 parser_update.add_argument("--new-vmdk-path", required=True, help="Full path of VMDK to replace with.")

 # Subcommand: rebalance
 parser_rebalance = subparsers.add_parser("rebalance", help="Rebalance")

 # Sub-subcommand: rebalance start
 parser_start = parser_rebalance.add_subparsers(title="Rebalance Start", dest="rebalance_subcommand")

 parser_start_start = parser_start.add_parser("start", help="Start rebalance")

 # Mandatory arguments for rebalance start
 parser_start_start.add_argument("--node-id", required=True, help="Node ID for rebalance")
 parser_start_start.add_argument("--input-file", required=True, help="csv file containing src-dst mapping of VMDKs - vmdk_src_dst_mappikngs.csv")

 # Sub-subcommand: rebalance pre-req
 parser_start_pre_req = parser_start.add_parser("pre-req", help="Check prerequisites")

 # Mandatory arguments for rebalance pre-req
 parser_start_pre_req.add_argument("--input-file", required=True, help="Input file for prerequisites")

 # Parse command-line arguments
 args = parser.parse_args()

 if args.subcommand == "update-vmdk-paths":
     update_vmdk_paths(args.input_json_file, args.ds_mapping_file, args.input_json_file + "-modified.json", args.old_vmdk_path, args.new_vmdk_path)
 elif args.subcommand == "rebalance":
     if args.rebalance_subcommand == "start":
         rebalance_start(args.node_id, args.input_file)
     elif args.rebalance_subcommand == "pre-req":
         rebalance_pre_req(args.input_file)
 else:
     print("Invalid subcommand. Use 'update-vmdk-paths' or 'rebalance'.")

if __name__ == "__main__":
 main()