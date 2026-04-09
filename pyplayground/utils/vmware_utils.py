#!/usr/bin/env python3
"""VMDK Utility Functions.

This module provides utility functions for VMDK operations
These functions are shared across the vmdk_manager and related scripts.

"""

import atexit
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

import pyVmomi
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim, vmodl

from pyplayground.utils.logging_utils import get_logger

logger = get_logger(__name__)
# setup_logging() # Remove: Logging should be configured by the calling script's entry point


@dataclass
class VSphereConnectionParams:
    """Dataclass to hold vSphere connection parameters."""

    host: str
    user: str
    password: str
    port: int = 443
    disable_ssl_verification: bool = False
    effective_cert_path: Optional[str] = None


def print_vm_info(vm, depth=1, max_depth=10):
    """Print information for a particular virtual machine or recurse into a folder with depth protection."""
    # if this is a group it will have children. if it does, recurse into them
    # and then return
    if hasattr(vm, "childEntity"):
        if depth > max_depth:
            return
        vm_list = vm.childEntity
        for child_vm in vm_list:
            print_vm_info(child_vm, depth + 1)
        return

    summary = vm.summary
    print("Name       :", summary.config.name)
    print("Path       :", summary.config.vmPathName)
    print("Guest      :", summary.config.guestFullName)
    annotation = summary.config.annotation
    if annotation:
        print("Annotation :", annotation)
    print("State      :", summary.runtime.powerState)
    if summary.guest is not None:
        ip = summary.guest.ipAddress
        if ip:
            print("IP         :", ip)
    if summary.runtime.question is not None:
        print("Question  :", summary.runtime.question.text)
    print("")


# TODO: Refactor wait_for_tasks to reduce complexity (currently McCabe complexity 11)
def wait_for_tasks(si, tasks):  # noqa: C901
    """Given the service instance and tasks, it returns after all the tasks are complete."""
    property_collector = si.content.propertyCollector
    task_list = [str(task) for task in tasks]
    # Create filter
    obj_specs = [vmodl.query.PropertyCollector.ObjectSpec(obj=task) for task in tasks]
    property_spec = vmodl.query.PropertyCollector.PropertySpec(type=vim.Task, pathSet=[], all=True)
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = obj_specs
    filter_spec.propSet = [property_spec]
    pcfilter = property_collector.CreateFilter(filter_spec, True)
    try:
        version, state = None, None
        # Loop looking for updates till the state moves to a completed state.
        while task_list:
            update = property_collector.WaitForUpdates(version)
            for filter_set in update.filterSet:
                for obj_set in filter_set.objectSet:
                    task = obj_set.obj
                    for change in obj_set.changeSet:
                        if change.name == "info":
                            state = change.val.state
                        elif change.name == "info.state":
                            state = change.val
                        else:
                            continue

                        if str(task) not in task_list:
                            continue

                        if state == vim.TaskInfo.State.success:
                            # Remove task from taskList
                            task_list.remove(str(task))
                        elif state == vim.TaskInfo.State.error:
                            raise task.info.error
            # Move to next version
            version = update.version
    finally:
        if pcfilter:
            pcfilter.Destroy()


def connect(args) -> Optional[vim.ServiceInstance]:
    """Connect to vSphere using SmartConnect and return the ServiceInstance.

    Args:
        args: An object with attributes: host, user, password, port, disable_ssl_verification.

    Returns:
        vim.ServiceInstance object upon successful connection, None otherwise.
    """
    service_instance = None
    try:
        if args.disable_ssl_verification:
            logger.debug(
                "Calling SmartConnect: host=%s, user=%s, port=%d, sslContext=Unverified",
                args.host,
                args.user,
                args.port,
            )
            service_instance = SmartConnect(
                host=args.host,
                user=args.user,
                pwd=args.password,
                port=args.port,
                disableSslCertValidation=True,
            )
        else:
            # Connect with default SSL verification
            logger.debug(
                "Calling SmartConnect: host=%s, user=%s, port=%d, sslContext=Default",
                args.host,
                args.user,
                args.port,
            )
            service_instance = SmartConnect(host=args.host, user=args.user, pwd=args.password, port=args.port)

        # Ensure connection was successful before registering disconnect
        if service_instance:
            atexit.register(Disconnect, service_instance)
            logger.info("Successfully connected to vSphere host: %s", args.host)
            return service_instance  # Return on success
        else:
            # This case might occur if SmartConnect returns None without raising an exception
            logger.error(
                "SmartConnect returned None without raising an exception for host %s",
                args.host,
            )
            return None

    except vim.fault.InvalidLogin as e:
        logger.error("vSphere login failed for host %s: %s", args.host, e.msg)
        return None
    except IOError as e:  # Catches socket errors, connection refused etc.
        logger.error("vSphere connection error for host %s: %s", args.host, str(e))
        return None
    except Exception as e:  # Catch other potential exceptions during connect
        logger.error(
            "Unexpected error connecting to vSphere host %s: %s",
            args.host,
            str(e),
            exc_info=True,
        )
        return None

    # This part should ideally not be reached if logic above is correct
    # if not service_instance:
    #     logger.error("Unable to connect to host %s with supplied credentials.", args.host)
    #     # raise SystemExit("Unable to connect to host with supplied credentials.")
    #     return None
    # return service_instance # Already returned or None returned in except blocks


def extract_path_from_datastore_path(datastore_path: str) -> str:
    """Extract the file path portion from a datastore path.

    Args:
        datastore_path: Full datastore path (e.g., "[datastore] path/to/file.vmdk")

    Returns:
        File path portion without datastore prefix
    """
    return datastore_path.split("] ", 1)[1] if "] " in datastore_path else datastore_path


def collect_properties(si, view_ref, obj_type, path_set=None, include_mors=False):
    """Collect properties for managed objects from a view ref.

    Check the vSphere API documentation for example on retrieving
    object properties:

        - http://goo.gl/erbFDz

    Args:
        si          (ServiceInstance): ServiceInstance connection
        view_ref (pyVmomi.vim.view.*): Starting point of inventory navigation
        obj_type      (pyVmomi.vim.*): Type of managed object
        path_set               (list): List of properties to retrieve
        include_mors           (bool): If True include the managed objects
                                        refs in the result

    Returns:
        A list of properties for the managed objects

    """
    collector = si.content.propertyCollector

    # Create object specification to define the starting point of
    # inventory navigation
    obj_spec = pyVmomi.vmodl.query.PropertyCollector.ObjectSpec()
    obj_spec.obj = view_ref
    obj_spec.skip = True

    # Create a traversal specification to identify the path for collection
    traversal_spec = pyVmomi.vmodl.query.PropertyCollector.TraversalSpec()
    traversal_spec.name = "traverseEntities"
    traversal_spec.path = "view"
    traversal_spec.skip = False
    traversal_spec.type = view_ref.__class__
    obj_spec.selectSet = [traversal_spec]

    # Identify the properties to the retrieved
    property_spec = pyVmomi.vmodl.query.PropertyCollector.PropertySpec()
    property_spec.type = obj_type

    if not path_set:
        property_spec.all = True
    else:
        property_spec.pathSet = path_set

    # Add the object and property specification to the
    # property filter specification
    filter_spec = pyVmomi.vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [property_spec]

    # Retrieve properties with pagination for large inventories
    options = pyVmomi.vmodl.query.PropertyCollector.RetrieveOptions()
    options.maxObjects = 200

    result = collector.RetrievePropertiesEx([filter_spec], options)

    data = []
    while result:
        for obj in result.objects:
            props_dict = {}
            for prop in obj.propSet:
                props_dict[prop.name] = prop.val

            if include_mors:
                props_dict["obj"] = obj.obj

            data.append(props_dict)

        if not result.token:
            break
        result = collector.ContinueRetrievePropertiesEx(result.token)

    return data


def get_container_view(si, obj_type, container=None):
    """Get a vSphere Container View reference to all objects of type 'obj_type'.

    It is up to the caller to take care of destroying the View when no longer needed.

    Args:
        obj_type (list): A list of managed object types

    Returns:
        A container view ref to the discovered managed objects
    """
    if not container:
        container = si.content.rootFolder

    view_ref = si.content.viewManager.CreateContainerView(container=container, type=obj_type, recursive=True)
    return view_ref


def search_for_obj(content, vim_type, name, folder=None, recurse=True):
    """Search the managed object for the name and type specified.

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    if folder is None:
        folder = content.rootFolder

    obj = None
    container = content.viewManager.CreateContainerView(folder, vim_type, recurse)

    for managed_object_ref in container.view:
        if managed_object_ref.name == name:
            obj = managed_object_ref
            break
    container.Destroy()
    return obj


def get_all_obj(content, vim_type, folder=None, recurse=True):
    """Search the managed object for the name and type specified.

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    if not folder:
        folder = content.rootFolder

    obj = {}
    container = content.viewManager.CreateContainerView(folder, vim_type, recurse)

    for managed_object_ref in container.view:
        obj[managed_object_ref] = managed_object_ref.name

    container.Destroy()
    return obj


def get_obj(content, vim_type, name, folder=None, recurse=True):
    """Retrieves the managed object for the name and type specified.

    Throws an exception if the managed object is not found.

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    obj = search_for_obj(content, vim_type, name, folder, recurse)
    if not obj:
        raise RuntimeError("Managed Object " + name + " not found.")
    return obj


def get_datastore_info(datastore_mor: vim.Datastore) -> Dict[str, Any]:
    """Get datastore capacity, free space, and type information.

    Args:
        datastore_mor: The managed object reference for the datastore.

    Returns:
        Dictionary containing datastore information (capacity, free space, type).
    """
    datastore_host_mounts: Dict[str, Any] = {}

    try:
        for host_mount in datastore_mor.host:
            host_key = host_mount.key._moId if hasattr(host_mount.key, "_moId") else host_mount.key
            if host_key not in datastore_host_mounts:
                try:
                    mount_info = host_mount.mountInfo
                    datastore_host_mounts[host_key] = {
                        "host_name": host_mount.key.name,
                        "mount": mount_info,
                    }
                except vmodl.fault.NotFound:
                    pass
    except Exception as e:
        logger.debug("Error getting datastore host mounts: %s", str(e))

    try:
        capacity = datastore_mor.summary.capacity
        free_space = datastore_mor.summary.freeSpace
        datastore_info: Dict[str, Any] = {
            "name": datastore_mor.name,
            "type": datastore_mor.summary.type,
            "capacity_gb": capacity / (1024**3) if capacity else None,
            "free_space_gb": free_space / (1024**3) if free_space else None,
            "used_space_gb": (capacity - free_space) / (1024**3) if capacity and free_space else None,
            "host_mounts": datastore_host_mounts,
        }
        return datastore_info
    except Exception as e:
        logger.warning("Error getting datastore summary for %s: %s", datastore_mor.name, str(e))
        return {
            "name": datastore_mor.name,
            "type": "unknown",
            "capacity_gb": None,
            "free_space_gb": None,
            "used_space_gb": None,
            "host_mounts": datastore_host_mounts,
        }


def get_vm_cluster_info(vm: vim.VirtualMachine) -> Dict[str, Any]:
    """Get VM's cluster information from vCenter inventory.

    Args:
        vm: The vim.VirtualMachine object.

    Returns:
        Dictionary containing cluster information and current host details.
    """
    cluster_info: Dict[str, Any] = {
        "cluster_name": None,
        "cluster_path": None,
        "current_host_name": None,
        "current_host_system": None,
    }

    try:
        host_system = vm.runtime.host
        if host_system:
            cluster_info["current_host_name"] = host_system.name
            cluster_info["current_host_system"] = host_system._moId

            parent = host_system.parent
            if parent:
                if isinstance(parent, vim.ClusterComputeResource):
                    cluster_info["cluster_name"] = parent.name
                    cluster_info["cluster_path"] = parent.name
                elif isinstance(parent, vim.ComputeResource):
                    cluster_info["cluster_name"] = parent.name
                    cluster_info["cluster_path"] = parent.name
                elif hasattr(parent, "parent") and parent.parent:
                    grandparent = parent.parent
                    if isinstance(grandparent, vim.ClusterComputeResource):
                        cluster_info["cluster_name"] = grandparent.name
                        cluster_info["cluster_path"] = grandparent.name

    except Exception as e:
        logger.warning("Error getting cluster info for VM %s: %s", vm.name, str(e))

    return cluster_info


def get_vm_datastores(vm: vim.VirtualMachine) -> List[Dict[str, Any]]:
    """Get unique datastores used by VM's disks.

    Args:
        vm: The vim.VirtualMachine object.

    Returns:
        List of unique datastore information dictionaries.
    """
    datastores: List[Dict[str, Any]] = []
    seen_datastores: Set[str] = set()

    try:
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                backing = device.backing
                if backing and hasattr(backing, "datastore"):
                    datastore_mor = backing.datastore
                    if datastore_mor and datastore_mor._moId not in seen_datastores:
                        seen_datastores.add(datastore_mor._moId)
                        datastores.append(
                            {
                                "datastore_mor": datastore_mor,
                                "datastore_name": datastore_mor.name,
                            }
                        )
    except Exception as e:
        logger.warning("Error getting VM datastores for %s: %s", vm.name, str(e))

    return datastores


def get_cluster_vms(si: vim.ServiceInstance, cluster_name: str) -> Dict[str, vim.VirtualMachine]:
    """Get VMs filtered by cluster name prefix using PropertyCollector with pagination.

    This function uses PropertyCollector with RetrievePropertiesEx to:
    1. Fetch only required VM properties (not full objects) from vCenter
    2. Use pagination (maxObjects=200) to keep memory usage flat
    3. Filter VMs by name prefix client-side (vSphere has no server-side LIKE query)

    With 1000+ VMs, this approach:
    - Avoids loading full VM objects into memory
    - Only transfers the properties we actually need
    - Uses pagination to handle large inventories efficiently
    - Filters locally since vSphere PropertyCollector has no server-side name filtering

    Args:
        si: The vCenter ServiceInstance connection.
        cluster_name: The cluster name prefix to filter VMs by.

    Returns:
        Dictionary mapping VM names to vim.VirtualMachine objects for VMs
        matching the cluster name prefix.

    Example:
        >>> cluster_vms = get_cluster_vms(si, "mycluster")
        >>> print(f"Found {len(cluster_vms)} VMs for cluster 'mycluster'")
    """
    vm_cache: Dict[str, vim.VirtualMachine] = {}
    content = si.RetrieveContent()
    prefix_lower = cluster_name.lower()

    try:
        vms_data = _collect_vm_properties_paginated(content, cluster_name)

        for vm_data in vms_data:
            vm_mor = vm_data.get("_moref")
            if vm_mor and vm_data.get("name", "").lower().startswith(prefix_lower):
                vm_cache[vm_data["name"]] = vm_mor

        logger.info(
            "Cached %d VMs matching cluster name prefix '%s' using PropertyCollector",
            len(vm_cache),
            cluster_name,
        )

    except Exception as e:
        logger.warning(
            "PropertyCollector lookup failed for '%s', falling back to ContainerView: %s",
            cluster_name,
            str(e),
        )
        vm_cache = _get_cluster_vms_fallback(si, cluster_name)

    return vm_cache


def _collect_vm_properties_paginated(content: vim.ServiceInstance.content, cluster_name: str) -> List[Dict[str, Any]]:
    """Collect VM properties using PropertyCollector with pagination.

    Args:
        content: vCenter ServiceInstance content object.
        cluster_name: Cluster name for logging purposes.

    Returns:
        List of dictionaries containing VM properties and managed object refs.
    """
    properties = [
        "name",
        "config.uuid",
        "runtime.host",
        "summary.config.vmPathName",
    ]

    # Build correct folder hierarchy traversal: rootFolder -> Datacenter -> VM folder -> VMs
    # Also include HostSystem.vm traversal for VMs on standalone hosts
    folder_traversal = vmodl.query.PropertyCollector.TraversalSpec(
        name="folderTraversal",
        type=vim.Folder,
        path="childEntity",
        skip=False,
        selectSet=[
            vmodl.query.PropertyCollector.SelectionSpec(name="folderTraversal"),
            # Datacenter -> vmFolder
            vmodl.query.PropertyCollector.TraversalSpec(
                name="datacenterTraversal",
                type=vim.Datacenter,
                path="vmFolder",
                skip=False,
                selectSet=[vmodl.query.PropertyCollector.SelectionSpec(name="folderTraversal")],
            ),
            # HostSystem -> vm (for standalone hosts)
            vmodl.query.PropertyCollector.TraversalSpec(
                name="hostTraversal",
                type=vim.HostSystem,
                path="vm",
                skip=False,
            ),
        ],
    )

    obj_spec = vmodl.query.PropertyCollector.ObjectSpec()
    obj_spec.obj = content.rootFolder
    obj_spec.skip = True
    obj_spec.selectSet = [folder_traversal]

    prop_spec = vmodl.query.PropertyCollector.PropertySpec()
    prop_spec.type = vim.VirtualMachine
    prop_spec.all = False
    prop_spec.pathSet = properties

    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [prop_spec]

    options = vmodl.query.PropertyCollector.RetrieveOptions()
    options.maxObjects = 200

    result = content.propertyCollector.RetrievePropertiesEx([filter_spec], options)

    all_objects: List[Dict[str, Any]] = []
    while result:
        for obj in result.objects:
            vm_data: Dict[str, Any] = {"_moref": obj.obj}
            for prop in obj.propSet:
                vm_data[prop.name] = prop.val
            all_objects.append(vm_data)

        if not result.token:
            break
        result = content.propertyCollector.ContinueRetrievePropertiesEx(result.token)

    return all_objects


def _get_cluster_vms_fallback(si: vim.ServiceInstance, cluster_name: str) -> Dict[str, vim.VirtualMachine]:
    """Fallback method using ContainerView when PropertyCollector fails.

    Args:
        si: The vCenter ServiceInstance connection.
        cluster_name: The cluster name prefix to filter VMs by.

    Returns:
        Dictionary mapping VM names to vim.VirtualMachine objects.
    """
    vm_cache: Dict[str, vim.VirtualMachine] = {}
    content = si.RetrieveContent()
    container = None

    try:
        container = content.viewManager.CreateContainerView(  # type: ignore[attr-defined]
            content.rootFolder,  # type: ignore[attr-defined]
            [vim.VirtualMachine],
            True,
        )

        prefix_lower = cluster_name.lower()
        matching_count = 0

        for vm in container.view:
            if vm.name.lower().startswith(prefix_lower):
                vm_cache[vm.name] = vm
                matching_count += 1

        logger.info(
            "Cached %d VMs matching cluster name prefix '%s' via fallback",
            matching_count,
            cluster_name,
        )

    finally:
        if container is not None:
            container.Destroy()

    return vm_cache
