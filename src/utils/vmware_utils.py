#!/usr/bin/env python3
"""VMDK Utility Functions.

This module provides utility functions for VMDK operations
These functions are shared across the vmdk_manager and related scripts.

"""

import atexit
from dataclasses import dataclass
from typing import Optional

import pyVmomi
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim, vmodl

from utils.logging_utils import get_logger

logger = get_logger(__name__)
# setup_logging() # Remove: Logging should be configured by the calling script's entry point


@dataclass
class VSphereConnectionParams:
    """Dataclass to hold vSphere connection parameters."""

    host: str
    user: str
    password: str
    disable_ssl: bool
    effective_cert_path: Optional[str]


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
        # ssl_context = None # Removed as context is used directly
        if args.disable_ssl_verification:
            # Attempt to import ssl module for context creation
            context = None  # Initialize context
            try:
                import ssl

                context = ssl._create_unverified_context()
            except ImportError:
                logger.warning(
                    "Could not import ssl module. Proceeding without specific SSL context."
                )
                # context remains None
            except AttributeError:
                logger.warning(
                    "ssl._create_unverified_context not available. Proceeding without specific SSL context."
                )
                # context remains None

            logger.debug(
                "Calling SmartConnect: host=%s, user=%s, port=%d, sslContext=%s",
                args.host,
                args.user,
                args.port,
                "Unverified" if context else "Default",
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
            service_instance = SmartConnect(
                host=args.host, user=args.user, pwd=args.password, port=args.port
            )

        # Ensure connection was successful before registering disconnect
        if service_instance:
            atexit.register(Disconnect, service_instance)
            logger.info("Successfully connected to vSphere host: %s", args.host)
            return service_instance  # Return on success
        else:
            # This case might occur if SmartConnect returns None without raising an exception
            logger.error(
                "SmartConnect returned None without raising an exception for host %s", args.host
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
            "Unexpected error connecting to vSphere host %s: %s", args.host, str(e), exc_info=True
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

    property_spec.pathSet = path_set

    # Add the object and property specification to the
    # property filter specification
    filter_spec = pyVmomi.vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [property_spec]

    # Retrieve properties
    props = collector.RetrieveContents([filter_spec])

    data = []
    for obj in props:
        properties = {}
        for prop in obj.propSet:
            properties[prop.name] = prop.val

        if include_mors:
            properties["obj"] = obj.obj

        data.append(properties)
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

    view_ref = si.content.viewManager.CreateContainerView(
        container=container, type=obj_type, recursive=True
    )
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
