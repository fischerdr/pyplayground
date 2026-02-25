"""This module provides a simple CLI tool to power on and off VMs in vSphere."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pyVim.connect import Disconnect
from pyVmomi import vim
from rich.console import Console
from rich.prompt import Confirm, Prompt

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vmware import cli, pchelper, service_instance

# Initialize Rich Console for user output
console = Console()

# Initialize Logger using the utility function
logger = get_logger(__name__)


def check_vm_power_state(vm: vim.VirtualMachine) -> str:
    """Check the power state of a VM."""
    return vm.runtime.powerState


def power_on_vm(vm: vim.VirtualMachine):
    """Power on a VM."""
    if check_vm_power_state(vm) != vim.VirtualMachine.PowerState.poweredOn:
        task = vm.PowerOn()
        console.print(f"Powering on VM '[bold cyan]{vm.name}[/bold cyan]'...")
        task.Wait()  # pyVmomi tasks are synchronous by default in recent versions
        console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' powered on successfully.", style="green")
    else:
        console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' is already powered on.", style="yellow")


def power_off_vm(vm: vim.VirtualMachine):
    """Power off a VM."""
    if check_vm_power_state(vm) != vim.VirtualMachine.PowerState.poweredOff:
        task = vm.PowerOff()
        console.print(f"Powering off VM '[bold cyan]{vm.name}[/bold cyan]'...")
        task.Wait()
        console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' powered off successfully.", style="green")
    else:
        console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' is already powered off.", style="yellow")


def reboot_vm(vm: vim.VirtualMachine):
    """Reboot a VM."""
    if check_vm_power_state(vm) == vim.VirtualMachine.PowerState.poweredOn:
        if vm.guest.toolsStatus == vim.vm.GuestInfo.ToolsStatus.toolsOk:
            console.print(f"Rebooting guest OS for VM '[bold cyan]{vm.name}[/bold cyan]'...")
            vm.RebootGuest()
            console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' guest OS reboot initiated.", style="green")
        else:
            console.print(
                f"VMware Tools not available for '[bold cyan]{vm.name}[/bold cyan]'; performing a hard reset...",
                style="yellow",
            )
            task = vm.ResetVM_Task()
            task.Wait()
            console.print(f"VM '[bold cyan]{vm.name}[/bold cyan]' hard reset successfully.", style="green")
    else:
        console.print(
            f"VM '[bold cyan]{vm.name}[/bold cyan]' is powered off and cannot be rebooted.",
            style="yellow",
        )


def find_vm(si: vim.ServiceInstance, args: argparse.Namespace) -> Optional[vim.VirtualMachine]:
    """Find the virtual machine based on the provided arguments."""
    vm = None
    content = si.RetrieveContent()
    search_method = ""
    search_value = ""

    try:
        if args.uuid:
            search_method, search_value = "UUID", args.uuid
            logger.debug(f"Searching for VM by {search_method}: {search_value}")
            vm = content.searchIndex.FindByUuid(None, args.uuid, True, True)
        elif args.dns_name:
            search_method, search_value = "DNS Name", args.dns_name
            logger.debug(f"Searching for VM by {search_method}: {search_value}")
            vm = content.searchIndex.FindByDnsName(None, args.dns_name, True)
        elif args.vm_ip:
            search_method, search_value = "IP Address", args.vm_ip
            logger.debug(f"Searching for VM by {search_method}: {search_value}")
            vm = content.searchIndex.FindByIp(None, args.vm_ip, True)
        elif args.vm_name:
            search_method, search_value = "Name", args.vm_name
            logger.debug(f"Searching for VM by {search_method}: {search_value}")
            vm = pchelper.get_obj(content, [vim.VirtualMachine], args.vm_name)

        if vm:
            console.print(f"Found VM: '[bold cyan]{vm.name}[/bold cyan]'", style="green")
            logger.info(f"Successfully found VM '{vm.name}' by {search_method}: {search_value}")
        else:
            console.print(f"VM not found using {search_method}: [bold]'{search_value}'[/bold]", style="red")
            logger.warning(f"VM not found using {search_method}: '{search_value}'")

    except vim.fault.InvalidState as e:
        error_msg = f"vSphere Error finding VM by {search_method} '{search_value}': {e.msg}"
        logger.error(error_msg)
        console.print(f"[bold red]Error:[/bold red] {e.msg}", style="red")
        vm = None
    except Exception:
        logger.exception(f"Unexpected error during VM search by {search_method} '{search_value}'")
        console.print("[bold red]An unexpected error occurred during VM search.[/bold red]", style="red")
        vm = None

    return vm


def handle_vm_power_interaction(vm: vim.VirtualMachine):
    """Handle the user interaction for VM power operations."""
    power_state = check_vm_power_state(vm)
    console.print(f"Current power state of '[bold cyan]{vm.name}[/bold cyan]' is: [bold yellow]{power_state}[/bold yellow]")

    if power_state == vim.VirtualMachine.PowerState.poweredOn:
        choice = Prompt.ask("Choose an action", choices=["off", "reboot", "none"], default="none")
        if choice == "off":
            logger.info(f"User chose to power off VM '{vm.name}'")
            if Confirm.ask(f"Are you sure you want to power off '[bold cyan]{vm.name}[/bold cyan]'?"):
                power_off_vm(vm)
        elif choice == "reboot":
            logger.info(f"User chose to reboot VM '{vm.name}'")
            if Confirm.ask(f"Are you sure you want to reboot '[bold cyan]{vm.name}[/bold cyan]'?"):
                reboot_vm(vm)
        else:
            logger.info(f"User chose not to change power state for VM '{vm.name}'")
            console.print("No action taken.")
    elif power_state == vim.VirtualMachine.PowerState.poweredOff:
        if Confirm.ask(f"Do you want to power on '[bold cyan]{vm.name}[/bold cyan]'?"):
            logger.info(f"User chose to power on VM '{vm.name}'")
            power_on_vm(vm)
        else:
            logger.info(f"User chose not to power on VM '{vm.name}'")
            console.print("No action taken.")


def main():
    """Main function to interact with VM power states in vSphere."""
    parser = cli.Parser()
    parser.add_optional_arguments(cli.Argument.VM_NAME, cli.Argument.DNS_NAME, cli.Argument.UUID, cli.Argument.VM_IP)
    # Add verbose flag manually if not part of standard cli.Argument
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG level) logging.",
    )
    args = parser.get_args()

    # Configure logging using the utility function
    log_level = logging.DEBUG if args.verbose else logging.INFO
    # Use script name for log file identification
    script_name = Path(__file__).stem
    setup_logging(level=log_level, script_name=script_name)

    logger.debug(f"Starting vmpower script with args: {args}")

    si = None
    exit_code = 0
    try:
        logger.info("Connecting to vCenter host specified in args...")
        si = service_instance.connect(args)
        if not si:
            # service_instance.connect likely logged/printed an error
            logger.error("Failed to connect to vSphere service instance.")
            raise SystemExit(1)
        logger.info(f"Successfully connected to vCenter: {args.host}")

        logger.info("Attempting to find VM...")
        vm = find_vm(si, args)

        if vm is None:
            # find_vm already logged the reason
            raise SystemExit(1)

        logger.info(f"Handling power interaction for VM '{vm.name}'")
        handle_vm_power_interaction(vm)

    except SystemExit as e:
        logger.debug(f"SystemExit called with code {e.code}. Exiting gracefully.")
        exit_code = e.code if isinstance(e.code, int) else 1  # Ensure exit code is int
        # No need to re-raise, finally block will execute
    except Exception:
        logger.exception("An unexpected error occurred in the main execution flow.")
        exit_code = 1
        # No need to re-raise, finally block will execute

    finally:
        if si:
            logger.info("Disconnecting from vCenter...")
            try:
                Disconnect(si)
                logger.info("Successfully disconnected.")
            except Exception:
                logger.exception("An error occurred during disconnection.")
                if exit_code == 0:
                    exit_code = 1  # Ensure we exit with error if disconnect fails

        logger.info(f"vmpower script finished with exit code {exit_code}.")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
