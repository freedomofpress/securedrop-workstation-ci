#!/usr/bin/env python3

import logging
import os
import qubesadmin
import shlex
import shutil
import subprocess
import sys
from datetime import datetime

class QubesCI:

    def __init__(self):
        """
        Set some environment variables and attributes,
        and also initialise our QubesVM objects.
        """
        os.environ["SECUREDROP_DEV_VM"] = "sd-ssh"
        os.environ["SECUREDROP_PROJECTS_DIR"] = "/home/user/projects/"
        os.environ["SECUREDROP_REPO_DIR"] = "securedrop-workstation"
        os.environ["SECUREDROP_DEV_DIR"] = os.environ["SECUREDROP_PROJECTS_DIR"] + os.environ["SECUREDROP_REPO_DIR"]

        # Set simpler variables for python use of the above env vars
        self.securedrop_dev_vm = os.environ["SECUREDROP_DEV_VM"]
        self.securedrop_usb_vm = "sys-usb"
        self.securedrop_projects_dir = os.environ["SECUREDROP_PROJECTS_DIR"]
        self.securedrop_repo_dir = os.environ["SECUREDROP_REPO_DIR"]
        self.securedrop_dev_dir = os.environ["SECUREDROP_DEV_DIR"]

        # Load our QubesVM objects
        self.q = qubesadmin.Qubes()
        self.ssh_vm = self.q.domains[self.securedrop_dev_vm]
        self.usb_vm = self.q.domains[self.securedrop_usb_vm]

        # Set our assumed status. If any step execution fails, we will change this to false
        self.commit_sha = ""
        self.status = "success"


    def setupLog(self):
        """
        Set up our logging handler.
        """
        now = datetime.now()
        date_name = now.strftime("%Y-%m-%d")
        time_name = now.strftime("%H%M%S%f")
        self.log_file = f"{date_name}-{time_name}.log.txt"
        self.logging = logging
        self.logging.basicConfig(
                format='%(levelname)s:%(message)s',
                level=logging.INFO,
                handlers=[
                    logging.FileHandler(self.log_file),
                    logging.StreamHandler()
                ]
        )


    def run_cmd(self, cmd):
        """
        Run a command via subprocess, ensuring stdout and stderr
        get logged to our logging handler. Also set a status
        flag based on whether the command succeeded or not.
        """
        def log_subprocess_output(pipe):
            for line in pipe:
                self.logging.info(line.decode('utf-8'))

        command_line_args = shlex.split(cmd)
        self.logging.info(f"Running: {cmd}")

        try:
            p = subprocess.Popen(
                    command_line_args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
            )

            out, err = p.communicate()
            out = out.splitlines()
            log_subprocess_output(out)
        except (OSError, subprocess.CalledProcessError) as e:
            self.logging.info(f"Exception occurred: {e}")
            self.status = "failure"
            return False
        else:
            self.logging.info("Step finished")
        return True


    def should_we_run(self):
        """
        Check if we should run the test (does the state file exist?)
        If so, also obtain the SHA commit hsah from the state file
        """
        # Does our state file exist?
        state_file = f"{self.securedrop_dev_dir}/run-me"
        try:
            state_file_exists = self.ssh_vm.run(f"cat {state_file}")
            self.commit_sha = state_file_exists[0].decode("utf-8")
            self.ssh_vm.run(f"rm -f {state_file}")
        except Exception as e:
            return False
        return True


    def build(self):
        """
        Build the package
        """
        home_dir = os.path.expanduser("~")
        os.chdir(home_dir)

        # Wipe out our existing working dir on dom0
        self.working_dir = f"{home_dir}/{self.securedrop_repo_dir}"
        if os.path.exists(self.working_dir):
            self.run_cmd(f"sudo chown -R {os.getlogin()} {self.working_dir}")
            shutil.rmtree(self.working_dir)

        # Generate our tarball in the appVM and extract it into dom0
        self.tar_file = f"{self.securedrop_repo_dir}.tar"
        with open(self.tar_file, "w") as tarball:
            subprocess.check_call([
                "qvm-run",
                "--pass-io",
                self.securedrop_dev_vm,
                f"tar -c -C {self.securedrop_projects_dir} {self.securedrop_repo_dir}",
            ], stdout = tarball)
            self.run_cmd(f"tar xvf {self.tar_file}")


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
        self.run_cmd(f"qvm-remove -f {self.securedrop_usb_vm}")

        # Rebuild the sys-usb with Salt
        self.run_cmd("sudo qubesctl state.sls qvm.sys-usb")

        # Uninstall all the other VMs
        self.run_cmd(f"{self.working_dir}/scripts/sdw-admin.py --uninstall --force")

        # Remove final remaining cruft on dom0
        cruft_dirs = [
            "/usr/share/securedrop",
            "/usr/share/securedrop-workstation-dom0-config"
        ]
        for cruft in cruft_dirs:
            if os.path.exists(cruft):
                self.run_cmd(f"sudo rm -rf {cruft}")
        if os.path.exists(self.tar_file):
            os.remove(self.tar_file)

    def uploadLog(self):
        """
        Copy the log file to the appVM and trigger the upload/status result in Github
        """
        subprocess.check_call([
            "qvm-copy-to-vm",
            self.securedrop_dev_vm,
            self.log_file
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
    if ci.should_we_run():
        ci.setupLog()
        ci.build()
        ci.test()
        ci.teardown()
        ci.uploadLog()
    else:
        sys.exit(0)