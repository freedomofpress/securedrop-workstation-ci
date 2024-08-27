#!/usr/bin/env python3
import argparse
import atexit
import certifi
import configparser
import json
import logging
import os
import re
import requests
import ssl
import time
from datetime import datetime
from logging.handlers import SysLogHandler
from pyVim.connect import SmartConnect, Disconnect
from pyVim.task import WaitForTask
from pyVmomi import vim

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    """
    Handle CLI args.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        default=False,
        required=True,
        action="store",
        help="Qubes version to run on",
    )
    parser.add_argument(
        "--context",
        required=False,
        action="store",
        help="A JSON object that represents the commit details and reason for this build.",
    )
    parser.add_argument(
        "--snapshot",
        default=False,
        required=False,
        action="store",
        help="Snapshot to restore. If none is chosen, it will be read from a config file.",
    )
    parser.add_argument(
        "--update",
        default=False,
        required=False,
        action="store_true",
        help="Whether to run dom0 and domU updates (used for nightlies)",
    )
    parser.add_argument(
        "--save",
        default=False,
        required=False,
        action="store_true",
        help="Whether to save a snapshot after running other tasks, for use in future runs",
    )

    args = parser.parse_args()
    return args


class CiRunner:
    def __init__(self):
        """
        Set up the CiRunner class with attributes required.
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        handler = SysLogHandler(
            facility=SysLogHandler.LOG_DAEMON,
            address="/dev/log"
        )
        handler.setFormatter(logging.Formatter('ws-ci-runner: %(message)s'))
        self.logger.addHandler(handler)

        # Read ESXi server details from config file
        self.config = configparser.ConfigParser()
        home_dir = os.path.expanduser("~")
        self.config_file = os.path.join(home_dir, ".esx.ini")
        self.config.read(self.config_file)
        self.esxi_server = self.config.get("ESXi", "server")
        self.username = self.config.get("ESXi", "username")
        self.password = self.config.get("ESXi", "password")

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(certifi.where())

        self.si = SmartConnect(
            host=self.esxi_server,
            user=self.username,
            pwd=self.password,
            customHeaders={"cookie": "vmware_client=VMware;"},
            sslContext=ssl_context,
        )
        atexit.register(Disconnect, self.si)

        self.pm = self.si.content.guestOperationsManager.processManager
        self.creds = vim.vm.guest.NamePasswordAuthentication(
            username=self.config.get("Qubes","username"),
            password=self.config.get("Qubes", "password")
        )
        self.file_attribute = vim.vm.guest.FileManager.FileAttributes()
        self.vm = None
        self.content = None


    def get_all_snapshots(self, snapshot):
        """
        Recursively get all snapshots in a snapshot tree.
        """
        snapshots = [snapshot]
        if hasattr(snapshot, 'childSnapshotList'):
            for child_snapshot in snapshot.childSnapshotList:
                snapshots.extend(self.get_all_snapshots(child_snapshot))
        return snapshots


    def find_snapshot_recursive(self, snapshot, snapshot_name):
        """
        Recursive function to find a snapshot by name.
        """
        if snapshot.name == snapshot_name:
            return snapshot

        for child_snapshot in snapshot.childSnapshotList:
            found_snapshot = self.find_snapshot_recursive(child_snapshot, snapshot_name)
            if found_snapshot:
                return found_snapshot
        return None


    def get_snapshot_by_name(self, snapshot_name):
        """
        Retrieve a snapshot by name from a VM, recursively
        if need be.
        """
        for snapshot in self.vm.snapshot.rootSnapshotList:
            if snapshot.name == snapshot_name:
                return snapshot.snapshot
            else:
                # If the snapshot is not at the root level, traverse through the nested snapshots
                nested_snapshot = self.find_snapshot_recursive(snapshot, snapshot_name)
                if nested_snapshot:
                    return nested_snapshot.snapshot
        return None

    def notify_github_queued(self, commit):
        """Notify GitHub of queued status early, the rest are handled by status.py"""
        with open(os.path.join(CURRENT_DIR, "sd-dev/.sdci-ghp.txt")) as f:
            github_token = f.read().strip()
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Content-Type": "application/json",
        }
        data = {
            "context": "sd-ci-runner",
            "description": "The build is queued",
            "state": "pending",
        }
        self.logger.debug(f"Posting queued commit status for {commit} to GitHub")
        requests.post(
            f"https://api.github.com/repos/freedomofpress/securedrop-workstation/statuses/{commit}",
            json=data,
            headers=headers,
        )


    def run_command_in_dom0(self, command, args=False, wait=True):
        """
        Run a command in dom0 (including any qvm-run commands into sd-dev)
        """
        if args:
            program_spec = vim.vm.guest.ProcessManager.ProgramSpec(
                programPath=command, arguments=args
            )
        else:
            program_spec = vim.vm.guest.ProcessManager.ProgramSpec(programPath=command)

        res = self.pm.StartProgramInGuest(self.vm, self.creds, program_spec)
        if res > 0:
            if wait:
                pid_exitcode = self.pm.ListProcessesInGuest(self.vm, self.creds, [res]).pop().exitCode
                # If it's not a numeric result code, it says None on submit
                while re.match('[^0-9]+', str(pid_exitcode)):
                    self.logger.debug("Program running, PID is %d" % res)
                    time.sleep(5)
                    pid_exitcode = self.pm.ListProcessesInGuest(self.vm, self.creds, [res]).pop().exitCode
                    if pid_exitcode == 0:
                        self.logger.debug("Program %d completed with success" % res)
                        break
                    # Look for non-zero code to fail
                    elif re.match('[1-9]+', str(pid_exitcode)):
                        self.logger.debug("ERROR: Program %d completed with Failure" % res)
                        self.logger.debug("ERROR: More info on process")
                        self.logger.debug(self.pm.ListProcessesInGuest(self.vm, self.creds, [res]))
                        break
            else:
                time.sleep(5)
                pid_exitcode = self.pm.ListProcessesInGuest(self.vm, self.creds, [res]).pop().exitCode
                # Look for non-zero code to fail
                if re.match("[1-9]+", str(pid_exitcode)):
                    self.logger.debug("ERROR: Program %d completed with Failure" % res)
                    self.logger.debug("ERROR: More info on process")
                    self.logger.debug(self.pm.ListProcessesInGuest(self.vm, self.creds, [res]))
                    raise SystemError("Error running command in dom0")


    def run_command_chain(self, commands):
        """
        Convenience function to pass a list of commands
        to the run_command_in_dom0 function.
        """
        for command, args in commands:
            self.run_command_in_dom0(command, args)


    def store_files_in_dom0(self, context):
        """
        Stores various files on the dom0 and calls commands to move
        them to Qubes VMs.
        """
        FILES_FOR_DOM0 = [
            "runner.py",
            "qubes.SDCIRunner",
            "qubes.SDCIRunner.policy",
        ]
        for dom0_file in FILES_FOR_DOM0:
            file_path = os.path.join(CURRENT_DIR, "dom0", dom0_file)
            with open(file_path, "rb") as myfile:
                data_to_send = myfile.read()

            url = self.content.guestOperationsManager.fileManager.InitiateFileTransferToGuest(
                self.vm,
                self.creds,
                f"/home/user/{dom0_file}",
                self.file_attribute,
                len(data_to_send),
                True,
            )

            # When : host argument becomes https://*:443/guestFile?
            # Ref: https://github.com/vmware/pyvmomi/blob/master/docs/ \
            #            vim/vm/guest/FileManager.rst
            # Script fails in that case, saying URL has an invalid label.
            # By having hostname in place will take take care of this.
            url = re.sub(r"^https://\*:", "https://" + str(self.esxi_server) + ":", url)

            # PUT the request
            resp = requests.put(url, data=data_to_send)
            if not resp.status_code == 200:
                raise SystemError(f"Error while uploading file {dom0_file}")
            else:
                self.logger.debug(f"Successfully uploaded {dom0_file} into dom0")

        # Move the RPC files into place and with appropriate perms
        commands = [
            ("/usr/bin/chmod", "755 runner.py qubes.SDCIRunner && sudo mv qubes.SDCIRunner /etc/qubes-rpc/"),
            ("/usr/bin/sudo", "mv qubes.SDCIRunner.policy /etc/qubes-rpc/policy/qubes.SDCIRunner"),
            ("/usr/bin/systemctl", "restart qubes-qrexec-policy-daemon"),
            ("/usr/bin/mkdir", "-p /home/user/sd-dev/bin"),
        ]
        self.run_command_chain(commands)

        # Write the JSON context to a file. Use the commit hash in the name
        # to avoid a concurrent CI run clobbering the same file.
        commit = context["commit"]
        context_filename = f"context_{commit}.json"
        with open(os.path.join(CURRENT_DIR, "sd-dev", context_filename), "w") as context_file:
            json.dump(context, context_file, indent=4)

        FILES_FOR_SD_DEV = [
            "bin/status.py",
            "bin/begin.py",
            ".sdci-ghp.txt",
            ".slack-webhook.txt",
            context_filename
        ]

        for sd_dev_file in FILES_FOR_SD_DEV:
            file_path = os.path.join(CURRENT_DIR, "sd-dev", sd_dev_file)
            with open(file_path, "rb") as myfile:
                data_to_send = myfile.read()

            url = self.content.guestOperationsManager.fileManager.InitiateFileTransferToGuest(
                self.vm,
                self.creds,
                f"/home/user/sd-dev/{sd_dev_file}",
                self.file_attribute,
                len(data_to_send),
                True,
            )
            url = re.sub(r"^https://\*:", "https://" + str(self.esxi_server) + ":", url)
            # PUT the request
            resp = requests.put(url, data=data_to_send)
            if not resp.status_code == 200:
                raise SystemError(f"Error while uploading file {sd_dev_file}")
            else:
                self.logger.debug(f"Successfully uploaded the file {sd_dev_file} into dom0")

        # Now copy the files into place
        commands = [
            ("/usr/bin/qvm-copy-to-vm", "sd-dev /home/user/sd-dev/bin"),
            ("/usr/bin/qvm-run", "sd-dev mv /home/user/QubesIncoming/dom0/bin /home/user/"),
            ("/usr/bin/qvm-copy-to-vm", "sd-dev /home/user/sd-dev/.sdci-ghp.txt"),
            ("/usr/bin/qvm-copy-to-vm", "sd-dev /home/user/sd-dev/.slack-webhook.txt"),
            ("/usr/bin/qvm-copy-to-vm", f"sd-dev /home/user/sd-dev/{context_filename}"),
            ("/usr/bin/qvm-run", "sd-dev mv /home/user/QubesIncoming/dom0/.sdci-ghp.txt /home/user/"),
            ("/usr/bin/qvm-run", "sd-dev mv /home/user/QubesIncoming/dom0/.slack-webhook.txt /home/user/"),
            ("/usr/bin/qvm-run", f"sd-dev mv /home/user/QubesIncoming/dom0/{context_filename} /home/user/context.json"),
        ]
        self.run_command_chain(commands)

        # Remove the context file from the working dir
        os.remove(os.path.join(CURRENT_DIR, "sd-dev", context_filename))


    def get_files_from_dom0(self, source, dest):
        """
        Fetches a file's contents from the VM and writes it to disk.
        """
        fti = self.content.guestOperationsManager.fileManager.InitiateFileTransferFromGuest(self.vm, self.creds, source)
        url = re.sub(r"^https://\*:", "https://" + str(self.esxi_server) + ":", fti.url)

        resp = requests.get(url)
        # Write output into file
        with open(dest, 'wb') as f:
            f.write(resp.content)


    def apply_updates(self, run_ci):
        """
        Run updates on dom0, templates and standalone VMs.
        Then either reboot (if we are going to run CI as
        the next step) or power off the VM otherwise.
        """
        self.logger.debug(f"Applying updates on {self.vm.name}")
        commands = [
            ("/usr/bin/sudo", "/usr/bin/qubes-dom0-update"),
            ("/usr/bin/sudo", "/usr/bin/qubes-vm-update --show-output --no-progress --templates --standalones --force-update --apply-to-all --max-concurrency 4"),
        ]
        self.run_command_chain(commands)
        if run_ci:
            self.shutdown()
            self.startup()


    def run_ci(self, context, log_file):
        """
        Store files on the dom0 and sd-dev VMs and then instruct
        dom0 to tell sd-dev to begin the CI execution.

        Finally, retrieve the log file from the CI execution and
        store it in /var/www/html/reports for viewing.
        """
        self.store_files_in_dom0(context)

        # Set the log file name that the dom0 runner.py should use. It needs to know
        # the name to set in the commit statuses to Github, but we also need to know
        # it in the bastion to retrieve it and store it in /var/www/html/reportsA
        self.run_command_in_dom0("/usr/bin/echo", f"{log_file} | /usr/bin/tee /home/user/.logfile")

        # Now execute the command on sd-dev to run the test suite
        self.logger.debug(f"Commencing the CI execution on {self.vm.name}")
        cmd = "sd-dev /usr/bin/python3 /home/user/bin/begin.py"
        self.run_command_in_dom0("/usr/bin/qvm-run", cmd)

        # Fetch the log file
        source = f"/home/user/{log_file}"
        dest = f"/var/www/html/reports/{log_file}"
        self.get_files_from_dom0(source, dest)

        # Shut down the VM to free it up for use by other runners
        self.shutdown()


    def remove_old_snapshots(self, prefix, keep):
        """
        Removes all but the last N snapshots based on
        a common prefix in the name.
        """
        # Get all snapshots for the VM
        all_snapshots = []
        for snapshot in self.vm.snapshot.rootSnapshotList:
            all_snapshots.extend(self.get_all_snapshots(snapshot))

        # Filter snapshots that start with "update_"
        update_snapshots = [snapshot for snapshot in all_snapshots if snapshot.name.startswith(prefix)]

        # Sort the snapshots by creation time in descending order
        update_snapshots.sort(key=lambda x: x.createTime, reverse=True)

        # Keep the last 3 snapshots
        snapshots_to_keep = update_snapshots[:3]

        # Delete snapshots that are not in the snapshots_to_keep list
        for snapshot in update_snapshots[3:]:
            if snapshot not in snapshots_to_keep:
                self.logger.debug(f"Deleting old snapshot: {snapshot.name}")
                task = snapshot.snapshot.RemoveSnapshot_Task(removeChildren=False)
                WaitForTask(task)


    def shutdown(self):
        """
        Shutdown and then power off the VM.
        """
        self.logger.debug(f"Shutting down {self.vm.name}")
        self.vm.ShutdownGuest()
        time.sleep(30)
        state = self.vm.runtime.powerState
        if state != "poweredOff":
            WaitForTask(self.vm.PowerOffVM_Task())


    def startup(self):
        """
        Power up the VM.
        """
        self.logger.debug(f"Powering on {self.vm.name}")
        WaitForTask(self.vm.PowerOnVM_Task())

        # Give some time to let Qubes boot up.
        max_attempts = 10
        power_on_attempts = 0
        while power_on_attempts < max_attempts:
            if self.vm.runtime.powerState == "poweredOn":
                if self.vm.guest.toolsStatus == vim.vm.GuestInfo.ToolsStatus.toolsOk:
                    time.sleep(60)
                    self.logger.debug(f"VM {self.vm.name} is now ready, moving on with next steps")
                    break
                else:
                    self.logger.debug(f"VM {self.vm.name} is not yet fully booted, waiting for it to be ready")
            else:
                self.logger.debug(f"VM {self.vm.name} is not yet powered on.")

            time.sleep(10)
            power_on_attempts += 1

        if power_on_attempts == max_attempts:
            raise SystemError(f"Max attempts reached, VM {self.vm.name} did not seem to get fully booted")


    def take_snapshot(self):
        """
        Take a snapshot of the VM and save its ID to the
        config file for use in future CI runs.
        """
        self.shutdown()

        now = datetime.now()
        machine_timestamp = now.strftime("%Y%m%d%H%M%S")
        human_timestamp = now.strftime("%a, %d %B %Y %H:%M:%S")
        new_snapshot_name = f"update_{machine_timestamp}"
        new_snapshot_desc = f"Snapshot taken at {human_timestamp} after applying updates"
        dumpMemory = False
        quiesce = False
        self.logger.debug(f"Taking snapshot of {self.vm.name} with snapshot ID {new_snapshot_name}")
        WaitForTask(self.vm.CreateSnapshot(new_snapshot_name, new_snapshot_desc, dumpMemory, quiesce))

        # Save the changes to the config file
        self.logger.debug("Saving the snapshot info to config for future runs")
        if not self.config.has_section(self.vm.config.uuid):
            self.config.add_section(self.vm.config.uuid)
        self.config.set(self.vm.config.uuid, "snapshot", new_snapshot_name)
        with open(self.config_file, "w") as c:
            self.config.write(c)

        # We now want to delete old snapshots to conserve space and try to help performance
        self.remove_old_snapshots(prefix="update_", keep=3)


    def main(self, version, context, snapshot_name=False, update=False):
        """
        Main entry point to the script.

        Look for a VM that is powered off and which matches our desired version.
        If we find one, restore it to the desired snapshot and power it up.

        Then run CI (if --context passed in), update routines (if --update passed in),
        saving new snapshot (if --save passed in).

        Finally, power off the VM again.

        If we couldn't find an available VM, sleep for a while and keep trying
        (it may be that other VMs are already running a CI run).
        """

        # Used for the log file name, to get a sense of when it started.
        now = datetime.now()
        date_name = now.strftime("%Y-%m-%d")
        time_name = now.strftime("%H%M%S%f")

        # Load the context and get commit hash
        context = json.loads(context)
        commit = context["commit"]
        self.notify_github_queued(commit)

        # Start a loop to try and find a VM to run tasks on.
        start_time = time.time()
        # Loop until 2 hours have passed, then give up - no machines were available
        while time.time() - start_time < 7200:
            self.vm = None
            # Find source VM
            content = self.si.RetrieveContent()
            vm_folder = content.rootFolder.childEntity[0].vmFolder
            source_vm_name = f"Qubes_{version}"

            for vm in vm_folder.childEntity:
                state = vm.runtime.powerState
                if source_vm_name in vm.name and state == "poweredOff":
                    self.vm = vm
                    self.content = content
                    break  # Found a suitable VM, no need to continue the loop

            if self.vm:
                # Great, the machine matches the version we want and it is off,
                # meaning it is not running any CI
                self.logger.debug(f"Using machine {self.vm.name} for CI")

                # If no snapshot was specified explicitly, fetch the latest ID
                # from the config file for this version.
                if not snapshot_name:
                    snapshot_name = self.config.get(self.vm.config.uuid, "snapshot")

                # Restore to known clean snapshot
                snapshot = self.get_snapshot_by_name(snapshot_name)
                if snapshot:
                    self.logger.debug(f"First reverting {self.vm.name} to snapshot {snapshot_name}")
                    WaitForTask(snapshot.RevertToSnapshot_Task())
                else:
                    raise SystemError(
                        f"Could not find snapshot with name {snapshot_name} for {self.vm.name}"
                    )

                # Use snapshot in the log file name, but make sure it has no spaces
                snapshot_name_for_log = snapshot_name.replace(' ', '-')

                # Power on VM
                self.startup()

                try:
                    # Set the machine to shutdown in just under 2 hours in case it gets stuck during CI run or during updates
                    self.run_command_in_dom0("/usr/bin/sudo", "/usr/sbin/shutdown -h +110")

                    # If we are doing a nightly test, apply updates and reboot, reconnect
                    if update:
                        self.apply_updates(True)

                    log_file = f"{date_name}-{time_name}-{commit}-{self.vm.name}-{snapshot_name_for_log}.log.txt"

                    # Run CI
                    self.run_ci(context, log_file)

                    # Return here, so that we never risk saving the post-CI state to snapshot
                    return True
                except Exception as e:
                    self.logger.debug(f"Error occurred during execution: {e}")
                    self.vm.PowerOffVM_Task()
                    return False
            else:
                # Continue to the next iteration if the desired VM is not found
                self.logger.debug(
                    f"Couldn't find any VMs matching version {version} that are not in use, sleeping for 60 seconds"
                )
                time.sleep(60)
        else:
            raise SystemError("Gave up after 1 hour trying to find a VM to run CI on.")


    def save(self, version, snapshot_name, update):
        """
        Functionality to (optionally) perform updates and save
        a new snapshot.
        This log is separate to the above main() run because it
        needs to iterate over *each* VM that matches the version,
        not just the first one it finds a match for.
        """
        self.content = self.si.RetrieveContent()
        vm_folder = self.content.rootFolder.childEntity[0].vmFolder
        source_vm_name = f"Qubes_{version}"

        for vm in vm_folder.childEntity:
            state = vm.runtime.powerState
            if source_vm_name in vm.name and state == "poweredOff":
                self.vm = vm
                # Fetch the latest snapshot ID from the config file for this VM
                # if we didn't explicitly pass one in as an arg
                if not snapshot_name:
                    s = self.config.get(self.vm.config.uuid, "snapshot")
                else:
                    s = snapshot_name

                # Restore to known clean snapshot
                snapshot = self.get_snapshot_by_name(s)
                if snapshot:
                    self.logger.debug(f"First reverting {self.vm.name} to snapshot {s}")
                    WaitForTask(snapshot.RevertToSnapshot_Task())
                else:
                    raise SystemError(
                        f"Could not find snapshot with name {s} for {self.vm.name}"
                    )

                # Power on VM
                self.startup()
                try:
                    # If we are doing a nightly test, apply updates and reboot, reconnect
                    if update:
                        self.apply_updates(False)
                    self.take_snapshot()
                except Exception as e:
                    # Don't abort, we want want to move on to the next machine
                    self.logger.debug(f"Error occurred during execution: {e}")
                    self.vm.PowerOffVM_Task()


if __name__ == "__main__":
    args = parse_args()

    ci = CiRunner()

    if args.save:
        ci.save(args.version, args.snapshot, args.update)
    else:
        ci.main(args.version, args.context, args.snapshot, args.update)
