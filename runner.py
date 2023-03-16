#!/usr/bin/env python3

import os
import qubesadmin
import shutil
import subprocess
import sys

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


    def should_we_run(self):
        """
        Check if we should run the test (does the state file exist?)
        """
        # Does our state file exist?
        state_file = f"{self.securedrop_dev_dir}/run-me"
        try:
            state_file_exists = self.ssh_vm.run(f"stat {state_file} && rm -f {state_file}")
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
            subprocess.check_call(["sudo", "chown", "-R", os.getlogin(), self.working_dir])
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
            subprocess.check_call(["tar", "xvf", self.tar_file])


    def test(self):
        """
        Run the tests!
        """
        os.chdir(self.working_dir)
        subprocess.check_call(["make", "clone"])
        subprocess.check_call(["make", "dev"])
        subprocess.check_call(["make", "test"])


    def teardown(self):
        """
        Teardown - uninstall all the VMs/templates and any other cruft.
        """
        if self.usb_vm.is_running():
            self.usb_vm.kill()
        subprocess.check_call(["qvm-remove", "-f", self.securedrop_usb_vm])

        # Rebuild the sys-usb with Salt
        subprocess.check_call(["sudo", "qubesctl", "state.sls", "qvm.sys-usb"])

        # Uninstall all the other VMs
        subprocess.check_call([f"{self.working_dir}/scripts/sdw-admin.py", "--uninstall", "--force"])

        # Remove final remaining cruft on dom0
        cruft_dirs = [
            "/usr/share/securedrop",
            "/usr/share/securedrop-workstation-dom0-config"
        ]
        for cruft in cruft_dirs:
            if os.path.exists(cruft):
                subprocess.check_call(["sudo", "rm", "-rf", cruft])
        if os.path.exists(self.tar_file):
            os.remove(self.tar_file)


if __name__ == "__main__":
    ci = QubesCI()
    if ci.should_we_run():
        ci.build()
        ci.test()
        ci.teardown()
    else:
        # exit 1 will prevent the wrapper from moving a potentially empty log file on each cron run
        sys.exit(1)