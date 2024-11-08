import argparse
import time
from kubernetes import client, config
import json
from kubernetes.client import ApiException


class PortworxNodeManager:
    def __init__(self, fallback_zone=None, dry_run=True, debug_cm=False, v1_client=None, crd_client=None):
        self.v1 = v1_client
        self.crd = crd_client
        self.fallback_zone = fallback_zone
        self.dry_run = dry_run
        self.debug_cm = debug_cm

    def get_nodes_from_machineset(self):
        """
        Query Kubernetes for nodes associated with MachineSets and their zones.
        Return a dictionary mapping node names to their respective zones.
        """
        print("Attempting to retrieve nodes and zones from MachineSets...")
        try:
            machinesets = self.crd.list_cluster_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                plural="machinesets"
            )

            node_zone_map = {}

            for ms in machinesets['items']:
                ms_name = ms['metadata']['name']
                print(f"Processing MachineSet: {ms_name}")
                # Extract zone information from the MachineSet labels
                zone = ms.get('metadata', {}).get('labels', {}).get('topology.portworx.io/zone', None)

                if zone:
                    print(f"MachineSet {ms_name} is in zone {zone}")
                else:
                    print(f"No zone found for MachineSet {ms_name}. Skipping zone labeling.")

                # Find associated machines for the MachineSet
                machines = self.crd.list_cluster_custom_object(
                    group="machine.openshift.io",
                    version="v1beta1",
                    plural="machines"
                )

                for machine in machines['items']:
                    # Check if the machine is part of the current MachineSet
                    if ms_name in machine['metadata']['name'] and 'status' in machine:
                        node_name = machine['status'].get('nodeRef', {}).get('name', None)
                        if node_name:
                            # Map the node to its zone (if zone is available)
                            node_zone_map[node_name] = zone if zone else 'unknown'
                            print(f"Associated node {node_name} with zone {zone}")

            if node_zone_map:
                print(f"Found {len(node_zone_map)} node(s) associated with MachineSets and zones.")
                return node_zone_map
            else:
                print("No nodes found in MachineSets. Falling back to other options.")
                return {}

        except Exception as e:
            print(f"Error retrieving nodes from MachineSets: {e}")
            return {}

    def get_nodes_from_machineset_specific(self, machineset_name):
        """
        Query Kubernetes for nodes associated with a specific MachineSet and its zone.
        Return a dictionary mapping node names to their respective zones.
        """
        print(f"Attempting to retrieve nodes and zones from MachineSet: {machineset_name}...")
        try:
            # Get all MachineSets (MachineSets are namespaced resources)
            machinesets = self.crd.list_namespaced_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                namespace="openshift-machine-api",  # MachineSets typically reside in this namespace
                plural="machinesets"
            )

            # Find the specific MachineSet object by name
            machineset = next((ms for ms in machinesets['items'] if ms['metadata']['name'] == machineset_name), None)

            if not machineset:
                print(f"MachineSet {machineset_name} not found.")
                return {}

            node_zone_map = {}

            # Extract zone information from the MachineSet labels
            zone = machineset.get('metadata', {}).get('labels', {}).get('topology.portworx.io/zone', None)

            if zone:
                print(f"MachineSet {machineset_name} is in zone {zone}")
            else:
                print(f"No zone found for MachineSet {machineset_name}. Skipping zone labeling.")

            # Find associated machines for the MachineSet
            machines = self.crd.list_namespaced_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                namespace="openshift-machine-api",  # Machines also reside in the same namespace
                plural="machines"
            )

            for machine in machines['items']:
                # Check if the machine is part of the specified MachineSet
                if machineset_name in machine['metadata']['name'] and 'status' in machine:
                    node_name = machine['status'].get('nodeRef', {}).get('name', None)
                    if node_name:
                        # Map the node to its zone (if zone is available)
                        node_zone_map[node_name] = zone if zone else 'unknown'
                        print(f"Associated node {node_name} with zone {zone}")

            if node_zone_map:
                print(f"Found {len(node_zone_map)} node(s) associated with MachineSet {machineset_name}.")
                return node_zone_map
            else:
                print(f"No nodes found in MachineSet {machineset_name}.")
                return {}

        except ApiException as e:
            print(f"Error retrieving nodes from MachineSet {machineset_name}: {e}")
            return {}

    def get_machine_for_node(self, node_name):
        """
        Query Kubernetes for the Machine object associated with the Node.
        """
        print(f"Fetching Machine object for node {node_name}...")
        try:
            machines = self.crd.list_cluster_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                plural="machines"
            )

            for machine in machines['items']:
                if machine['status']['nodeRef']['name'] == node_name:
                    print(f"Found Machine {machine['metadata']['name']} for Node {node_name}")
                    return machine
            print(f"No Machine found for Node {node_name}. This might be UPI.")
            return None
        except Exception as e:
            print(f"Error fetching Machine for Node {node_name}: {e}")
            return None

    def get_machineset_for_machine(self, machine):
        """
        Query Kubernetes for the MachineSet associated with the Machine.
        """
        print(f"Fetching MachineSet for Machine {machine['metadata']['name']}...")
        try:
            machinesets = self.crd.list_cluster_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                plural="machinesets"
            )

            for ms in machinesets['items']:
                if ms['metadata']['name'] in machine['metadata']['name']:
                    print(f"Found MachineSet {ms['metadata']['name']} for Machine {machine['metadata']['name']}")
                    return ms
            print(f"No MachineSet found for Machine {machine['metadata']['name']}.")
            return None
        except Exception as e:
            print(f"Error fetching MachineSet: {e}")
            return None

    def get_zone_for_node(self, node_name):
        """
        Fetch the zone for a node by checking its Machine and MachineSet.
        Preference is given to the MachineSet's zone. If no zone is found:
        - Fallback to provided `--zone` argument if given.
        - Ask the user for manual input as the last resort.
        """
        machine = self.get_machine_for_node(node_name)
        if machine:
            machineset = self.get_machineset_for_machine(machine)
            if machineset:
                # Check if 'metadata' and 'labels' exist in the nested structure
                labels = machineset.get('metadata', {}).get('labels', None)
                if labels:
                    zone = labels.get("topology.portworx.io/zone", None)
                    if zone:
                        print(f"Zone {zone} found in MachineSet {machineset['metadata']['name']}")
                        return zone
                else:
                    print(f"No labels found in MachineSet {machineset['metadata']['name']}")

        # Fallback to provided `--zone` argument if no zone found in MachineSet
        if self.fallback_zone:
            print(f"No zone found in MachineSet, using provided fallback zone: {self.fallback_zone}")
            return self.fallback_zone

        # Ask for manual input as the last resort
        zone = input(f"No zone found for node {node_name}. Please provide the zone manually: ")
        return zone

    def label_node(self, node_name, labels):
        # Apply the label only if it's not a dry run
        if not self.dry_run:
            body = {"metadata": {"labels": labels}}
            self.v1.patch_node(node_name, body)
            print(f"Node {node_name} labeled successfully with {labels}.")

    def label_machine(self, machine_name, labels):
        print(f"Dry-run: {self.dry_run} - Adding labels {labels} to machine {machine_name}...")
        if not self.dry_run:
            body = {"metadata": {"labels": labels}}
            self.crd.patch_namespaced_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                namespace="openshift-machine-api",
                plural="machines",
                name=machine_name,
                body=body
            )
            print(f"Machine {machine_name} labeled successfully with {labels}.")

    def update_cm(self, node_name, zone):
        print(f"Fetching ConfigMap for node {node_name}...")
        config_maps = self.v1.list_namespaced_config_map(namespace="kube-system")
        for cm in config_maps.items:
            if cm.metadata.name.startswith("px-cloud-drive-"):
                data = json.loads(cm.data['cloud-drive'])
                configmap_modified = False

                for node_id, node_config in data.items():
                    if node_config['SchedulerNodeName'] == node_name:
                        print(f"Found SchedulerNodeName {node_name} in ConfigMap {cm.metadata.name}.")
                        print(f"Current zone for {node_name}: {node_config.get('Zone', 'not set')}")
                        print(f"Updating zone to: {zone}")

                        node_config['Zone'] = zone
                        configmap_modified = True

                if configmap_modified:
                    new_configmap = json.dumps(data, separators=(',', ':'))

                    if self.dry_run:
                        if self.debug_cm:
                            print(f"\nDry-run: New intended ConfigMap content for {cm.metadata.name}:\n{new_configmap}\n")
                        print(f"Dry-run: Would save a backup of the current ConfigMap to cm_backup_{cm.metadata.name}.json")
                    else:
                        backup_filename = f"cm_backup_{cm.metadata.name}.json"
                        with open(backup_filename, 'w') as backup_file:
                            json.dump(data, backup_file, separators=(',', ':'))
                        print(f"Backup of ConfigMap saved as {backup_filename}.")

                        body = {"data": {"cloud-drive": new_configmap}}
                        self.v1.patch_namespaced_config_map(cm.metadata.name, 'kube-system', body)
                        print(f"ConfigMap {cm.metadata.name} updated successfully with changes for {node_name}.")
                else:
                    print(f"No changes made to ConfigMap {cm.metadata.name} for {node_name}.")

    def get_px_nodes(self):
        print("Fetching all nodes where Portworx pods are running...")
        pods = self.v1.list_namespaced_pod(namespace='portworx', label_selector='name=portworx')
        px_nodes = set()
        for pod in pods.items:
            node_name = pod.spec.node_name
            if node_name:
                px_nodes.add(node_name)

        print(f"Found {len(px_nodes)} node(s) running Portworx pods.")
        node_list = []
        for node_name in px_nodes:
            node = self.v1.read_node(node_name)
            node_list.append(node)

        return node_list

    def get_portworx_pod_for_node(self, node_name):
        """
        Get the Portworx pod running on a specific node by filtering with label 'name=portworx'
        and checking the node name.
        """
        try:
            pods = self.v1.list_namespaced_pod(namespace='portworx', label_selector='name=portworx')
            for pod in pods.items:
                if pod.spec.node_name == node_name:
                    return pod
            return None
        except ApiException as e:
            print(f"Error fetching pod for node {node_name}: {e}")
            return None

    def wait_for_pod_readiness(self, pod_name, namespace, timeout=420):
        """
        Wait for a pod to be ready (1/1) with a timeout (default 7 minutes).
        If the pod does not become ready within the timeout, raise an exception.
        """
        interval = 15
        elapsed_time = 0

        while elapsed_time < timeout:
            try:
                pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                pod_status = pod.status.container_statuses[0].ready
                if pod_status:
                    print(f"Pod {pod_name} is ready (1/1).")
                    return True
            except ApiException as e:
                print(f"Error reading pod {pod_name} status: {e}")
                return False

            elapsed_time += interval
            print(f"Waiting for pod {pod_name} to be ready... ({elapsed_time}/{timeout} seconds elapsed)")
            time.sleep(interval)

        print(f"Timeout reached: Pod {pod_name} is not ready after {timeout} seconds.")
        return False

    def label_px_nodes(self, node_names):
        nodes = self.get_px_nodes()
        node_dict = {node.metadata.name: node for node in nodes}
        label_changed = False

        for node_name in node_names:
            node = node_dict.get(node_name)
            if not node:
                print(f"Node {node_name} not found with PX installed, skipping...")
                continue

            node_type = node.metadata.labels.get("portworx.io/node-type")
            print(f"\nProcessing node: {node_name}, type: {node_type}")

            zone = self.get_zone_for_node(node_name)
            print(f"Labeled {node_name} with topology.portworx.io/zone={zone}")

            # Track whether the label was changed
            current_label_value = node.metadata.labels.get("topology.portworx.io/zone")

            if current_label_value != zone:
                print(f"Desired {zone} for node {node_name} is not the same as current zone found {current_label_value}, updating it...")
                label_changed = True

            # If no label change, skip the restart and config map update
            if not label_changed:
                print(f"Skipping PX restart and config map update for {node_name} as no label changes were made.")
                continue

            if label_changed:
                machine = self.get_machine_for_node(node_name)
                if machine:
                    self.label_machine(machine['metadata']['name'], {"topology.portworx.io/zone": zone})

                # Apply the new zone to the node
                self.label_node(node_name, {"topology.portworx.io/zone": zone})

                # Get the Portworx pod for this node
                pod = self.get_portworx_pod_for_node(node_name)
                if not pod:
                    print(f"No Portworx pod found for node {node_name}. Skipping readiness check.")
                    continue

                # Storage node case
                if node_type == "storage":
                    print(f"{node_name} is a storage node. Proceeding with special handling...")
                    self.label_node(node_name, {"px/service": "stop"})

                    if not self.dry_run:
                        print(f"Waiting for 1 minute after labeling {node_name} with px/service=stop...")
                        time.sleep(60)

                    self.update_cm(node_name, zone)

                    if not self.dry_run:
                        print("Restarting PX on the storage node...")
                        self.label_node(node_name, {"px/service": "restart"})

                # Storage-less node case
                else:
                    print(f"{node_name} is a storageless node. Proceeding to restart...")
                    if not self.dry_run:
                        print(f"Labeled {node_name} with px/service=restart")
                        self.label_node(node_name, {"px/service": "restart"})

                # Wait for PX Pod readiness on any case
                if not self.dry_run:
                    print(f"Waiting for Portworx pod {pod.metadata.name} on node {node_name} to be ready...")
                    pod_ready = self.wait_for_pod_readiness(pod_name=pod.metadata.name, namespace='portworx')
                    if not pod_ready:
                        print(f"Error: Pod {pod.metadata.name} did not become ready within the timeout.")
                        raise Exception(f"Portworx pod on node {node_name} failed to become ready. Exiting.")

def load_nodes_from_file(file_path):
    try:
        with open(file_path, 'r') as f:
            nodes = [line.strip() for line in f.readlines() if line.strip()]
        print(f"Loaded {len(nodes)} nodes from file {file_path}")
        return nodes
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        return []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Label Portworx nodes and update ConfigMaps")
    parser.add_argument("--zone", help="Zone value to set for nodes (used as fallback)")
    parser.add_argument("--real-run", action="store_true", help="If set, run for real (not a dry-run)")
    parser.add_argument("--kubeconfig", help="Path to the kubeconfig file")
    parser.add_argument("--node-file", help="Path to a file with node names, one per line")
    parser.add_argument("--debug-cm", action="store_true", help="Enable debug Config Map")
    parser.add_argument("--fully-unattended", action="store_true", help="Run unattended and iterate over all MachineSets")
    parser.add_argument("--machine-set", help="Specify a MachineSet to load nodes from")

    args = parser.parse_args()
    dry_run = not args.real_run
    debug_cm = args.debug_cm

    # Load Kubernetes config
    if args.kubeconfig:
        config.load_kube_config(config_file=args.kubeconfig)
    else:
        config.load_kube_config()

    v1_client = client.CoreV1Api()
    crd_client = client.CustomObjectsApi()

    manager = PortworxNodeManager(fallback_zone=args.zone, dry_run=dry_run, v1_client=v1_client, crd_client=crd_client, debug_cm=debug_cm)

    node_zone_map = {}

    if args.fully_unattended:
        # Iterate over all machineSets
        node_zone_map = manager.get_nodes_from_machineset()
    elif args.machine_set:
        # Use the provided MachineSet
        print(f"Using MachineSet: {args.machine_set}")
        node_zone_map = manager.get_nodes_from_machineset_specific(args.machine_set)
    else:
        # Ask for a MachineSet as a fallback
        selected_machineset = input("Please provide a MachineSet: ")
        if selected_machineset:
            node_zone_map = manager.get_nodes_from_machineset_specific(selected_machineset)
        else:
            print("No MachineSet provided. Exiting.")
            exit(1)

    # Fallback to node file or manual input if no nodes from MachineSets
    if not node_zone_map:
        if args.node_file:
            node_names = load_nodes_from_file(args.node_file)
            node_zone_map = {node_name: args.zone for node_name in node_names}
        else:
            node_names = input("Enter the comma-separated list of node names: ").split(',')
            node_zone_map = {node_name.strip(): args.zone for node_name in node_names}

    if node_zone_map:
        for node_name, zone in node_zone_map.items():
            manager.label_px_nodes([node_name.strip()])
    else:
        print("No nodes provided. Exiting.")