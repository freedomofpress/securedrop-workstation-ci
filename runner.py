#!/usr/bin/env python3

import logging
import os
import qubesadmin
import re
import shlex
import shutil
import subprocess
import sys
import getpass
from datetime import datetime

class QubesCI:

    def __init__(self):
        """
        Set some environment variables and attributes, logging handler
        and also initialise our QubesVM objects.
        """
        os.environ["SECUREDROP_DEV_VM"] = "sd-ssh"
        os.environ["SECUREDROP_PROJECTS_DIR"] = "/var/lib/sdci-ci-runner/"
        os.environ["SECUREDROP_REPO_DIR"] = sys.argv[1]
        os.environ["SECUREDROP_DEV_DIR"] = os.environ["SECUREDROP_PROJECTS_DIR"] + os.environ["SECUREDROP_REPO_DIR"]

        # Set simpler variables for python use of the above env vars
        self.securedrop_dev_vm = os.environ["SECUREDROP_DEV_VM"]
        self.securedrop_usb_vm = "sys-usb"
        self.securedrop_projects_dir = os.environ["SECUREDROP_PROJECTS_DIR"]
        self.securedrop_repo_dir = os.environ["SECUREDROP_REPO_DIR"]
        self.securedrop_dev_dir = os.environ["SECUREDROP_DEV_DIR"]
        self.securedrop_dom0_dev_dir = "securedrop-workstation"
        # Running under su, the `os` functions can be wonky, so use getpass to try environment
        # variables and make some assumptions about Qubes home dir locations
        self.username = getpass.getuser()
        self.home_dir = f"/home/{self.username}"

        # Load our QubesVM objects
        self.q = qubesadmin.Qubes()
        self.ssh_vm = self.q.domains[self.securedrop_dev_vm]
        self.usb_vm = self.q.domains[self.securedrop_usb_vm]

        # Parse the sha out of the dir name
        self.commit_sha = self.securedrop_repo_dir.split("_")[1]
        # Set our assumed status. If any step execution fails, we will change this to false
        self.status = "success"

        # Set up our logging handler.
        now = datetime.now()
        date_name = now.strftime("%Y-%m-%d")
        time_name = now.strftime("%H%M%S%f")
        self.log_file = f"{date_name}-{time_name}.log.txt"
        self.logging = logging
        self.logging.basicConfig(
                format='%(levelname)s:%(message)s',
                level=logging.INFO,
                handlers=[
                    logging.FileHandler(f"{self.home_dir}/{self.log_file}"),
                    logging.StreamHandler()
                ]
        )

        # Report to Github that the build has started running
        subprocess.check_call([
            "qvm-run",
            self.securedrop_dev_vm,
            "/home/user/bin/upload-report",
            "--status",
            "running",
            "--sha",
            self.commit_sha
        ])

        self.dirty_file = "/var/tmp/sd-ci-runner.dirty"
        # Is our environment 'dirty' (bad teardown during last build?)
        if os.path.exists(self.dirty_file):
            message = "Can't proceed with build: environment is dirty"
            self.logging.info(message)
            self.status = "error"
            self.uploadLog()
            raise SystemError(message)

    def run_cmd(self, cmd, teardown=False):
        """
        Run any command as a subprocess, and ensure both its
        stdout and stderr get logged to the logging handler.
        
        Also detect if the command returned a non-zero returncode,
        and if so, mark the overall status as a failure so that
        we report it as such as a git commit status later.
        """
        def format_current_timestamp():
            now = datetime.now()
            date_name = now.strftime("%Y-%m-%d")
            time_name = now.strftime("%H:%M:%S:%f")
            timestamp = f"{date_name}-{time_name}"
            return timestamp

        def log_subprocess_output(pipe):
            ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
            for line in pipe:
                timestamp = format_current_timestamp()
                line_decoded = ansi_escape.sub('', line.decode('utf-8'))
                self.logging.info(f"[{timestamp}] {line_decoded}")

        command_line_args = shlex.split(cmd)
        timestamp = format_current_timestamp()
        self.logging.info(f"[{timestamp}] Running: {cmd}")

        p = subprocess.Popen(
                command_line_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
        )

        out, err = p.communicate()
        out = out.splitlines()
        log_subprocess_output(out)
        timestamp = format_current_timestamp()
        if p.returncode != 0:
            self.logging.info(f"[{timestamp}] Exception occurred during: {cmd}")
            if teardown:
                self.status = "error"
                # Mark the environment as 'dirty' - it may need manual cleaning up
                # to avoid skewing results on the next build
                open(self.dirty_file, "w").close()
            else:
                self.status = "failure"
        else:
            self.logging.info(f"[{timestamp}] Step finished")


    def build(self):
        """
        Build the package
        """
        os.chdir(self.home_dir)

        # Wipe out our existing working dir on dom0
        self.working_dir = f"{self.home_dir}/{self.securedrop_dom0_dev_dir}"
        if os.path.exists(self.working_dir):
            self.run_cmd(f"sudo chown -R {self.username} {self.working_dir}")
            shutil.rmtree(self.working_dir)

        # Generate our tarball in the appVM and extract it into dom0
        self.tar_file = f"{self.home_dir}/{self.securedrop_repo_dir}.tar"
        with open(self.tar_file, "w") as tarball:
            subprocess.check_call([
                "qvm-run",
                "--pass-io",
                self.securedrop_dev_vm,
                f"tar -c -C {self.securedrop_projects_dir} {self.securedrop_repo_dir}",
            ], stdout = tarball)
            self.run_cmd(f"tar xvf {self.tar_file}")
            shutil.move(f"{self.home_dir}/{self.securedrop_repo_dir}", self.working_dir)


    def test(self):
        """
        Run the tests!
        """
        os.chdir(self.working_dir)
        self.run_cmd("make clone")
        self.run_cmd("make dev")
        self.run_cmd("make test")


    def teardown(self):
        """
        Teardown - uninstall all the VMs/templates and any other cruft.
        """
        if self.usb_vm.is_running():
            self.usb_vm.kill()
        self.run_cmd(f"qvm-remove -f {self.securedrop_usb_vm}", teardown=True)

        # Rebuild the sys-usb with Salt
        self.run_cmd("sudo qubesctl state.sls qvm.sys-usb", teardown=True)

        # Uninstall all the other VMs
        self.run_cmd(f"{self.working_dir}/scripts/sdw-admin.py --uninstall --force", teardown=True)

        # Remove final remaining cruft on dom0
        cruft_dirs = [
            self.working_dir,
            "/usr/share/securedrop",
            "/usr/share/securedrop-workstation-dom0-config"
        ]
        for cruft in cruft_dirs:
            if os.path.exists(cruft):
                self.run_cmd(f"sudo rm -rf {cruft}", teardown=True)
        if os.path.exists(self.tar_file):
            self.run_cmd(f"rm -f {self.tar_file}", teardown=True)
        # Remove the original working dir on the appVM that was populated by the webhook
        self.run_cmd(f"qvm-run {self.securedrop_dev_vm} rm -rf {self.securedrop_dev_dir}", teardown=True)


    def uploadLog(self):
        """
        Copy the log file to the appVM and trigger the upload/commit status in Github.
        """
        subprocess.check_call([
            "qvm-copy-to-vm",
            self.securedrop_dev_vm,
            f"{self.home_dir}/{self.log_file}"
        ])
        subprocess.check_call([
            "qvm-run",
            self.securedrop_dev_vm,
            "/home/user/bin/upload-report",
            "--file",
            self.log_file,
            "--status",
            self.status,
            "--sha",
            self.commit_sha
        ])


if __name__ == "__main__":
    ci = QubesCI()
    ci.build()
    ci.test()
    ci.teardown()
    ci.uploadLog()
