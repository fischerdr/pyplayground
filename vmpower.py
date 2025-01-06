from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

from tools import cli, pchelper, service_instance, tasks


def check_vm_power_state(vm):
    return vm.runtime.powerState

def power_on_vm(vm):
    if check_vm_power_state(vm) != vim.VirtualMachine.PowerState.poweredOn:
        task = vm.PowerOn()
        print("Powering on the VM...")
        task.Wait()
    else:
        print("The VM is already powered on.")

def power_off_vm(vm):
    if check_vm_power_state(vm) != vim.VirtualMachine.PowerState.poweredOff:
        task = vm.PowerOff()
        print("Powering off the VM...")
        task.Wait()
    else:
        print("The VM is already powered off.")

def reboot_vm(vm):
    if check_vm_power_state(vm) == vim.VirtualMachine.PowerState.poweredOn:
        if vm.guest.toolsStatus == vim.vm.GuestInfo.ToolsStatus.toolsOk:
            print("Rebooting the guest OS...")
            vm.RebootGuest()
        else:
            print("VMware Tools not available; performing a hard reset...")
            task = vm.ResetVM_Task()
            task.Wait()
    else:
        print("The VM is powered off and cannot be rebooted.")

def main():

    parser = cli.Parser()
    parser.add_optional_arguments(
        cli.Argument.VM_NAME, cli.Argument.DNS_NAME, cli.Argument.UUID, cli.Argument.VM_IP)
    args = parser.get_args()
    si = service_instance.connect(args)

    VM = None
    if args.uuid:
        VM = si.content.searchIndex.FindByUuid(None, args.uuid, True, True)
    elif args.dns_name:
        VM = si.content.searchIndex.FindByDnsName(None, args.dns_name, True)
    elif args.vm_ip:
        VM = si.content.searchIndex.FindByIp(None, args.vm_ip, True)
    elif args.vm_name:
        content = si.RetrieveContent()
        VM = pchelper.get_obj(content, [vim.VirtualMachine], args.vm_name)

    if VM is None:
        raise SystemExit("Unable to locate VirtualMachine.")

    # Check the power state
    power_state = check_vm_power_state(VM)
    print(f"The current power state of '{VM.name}' is: {power_state}")

    # Ask user if they want to power on, power off, or reboot
    if power_state == vim.VirtualMachine.PowerState.poweredOn:
        choice = input("Do you want to power off or reboot the VM? (off/reboot/no): ")
        if choice.lower() == 'off':
            power_off_vm(VM)
        elif choice.lower() == 'reboot':
            reboot_vm(VM)
    elif power_state == vim.VirtualMachine.PowerState.poweredOff:
        choice = input("Do you want to power on the VM? (yes/no): ")
        if choice.lower() == 'yes':
            power_on_vm(VM)


    tasks.wait_for_tasks(si, [TASK])
    # Disconnect from vCenter
    Disconnect(si)

if __name__ == "__main__":
    main()
