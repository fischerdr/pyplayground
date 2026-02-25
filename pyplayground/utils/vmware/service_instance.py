"""This module implements simple helper functions for managing service instance objects."""

__author__ = "VMware, Inc."

import atexit

from pyVim.connect import Disconnect, SmartConnect


def connect(args):
    """Connects to a vSphere service instance (vCenter or ESXi).

    Determines the most preferred API version supported by the server,
    connects using that version, logs in using credentials from command-line
    arguments, and returns the service instance object. Handles SSL verification
    based on arguments.

    Args:
        args (argparse.Namespace): Parsed command-line arguments containing
            host, port, user, password, and disable_ssl_verification flags.

    Returns:
        Optional[vim.ServiceInstance]: The connected ServiceInstance object upon
            successful connection, or None if connection fails.
    """
    service_instance = None

    # form a connection...
    try:
        if args.disable_ssl_verification:
            service_instance = SmartConnect(
                host=args.host,
                user=args.user,
                pwd=args.password,
                port=args.port,
                disableSslCertValidation=True,
            )
        else:
            service_instance = SmartConnect(host=args.host, user=args.user, pwd=args.password, port=args.port)

        # doing this means you don't need to remember to disconnect your script/objects
        atexit.register(Disconnect, service_instance)
    except IOError as io_error:
        print(io_error)

    if not service_instance:
        raise SystemExit("Unable to connect to host with supplied credentials.")

    return service_instance
