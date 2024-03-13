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
        os.environ["SECUREDROP_DEV_VM"] = "sd-dev"
        os.environ["SECUREDROP_PROJECTS_DIR"] = "/var/lib/sdci-ci-runner/"
        os.environ["SECUREDROP_REPO_DIR"] = sys.argv[1]
        os.environ["SECUREDROP_DEV_DIR"] = (
            os.environ["SECUREDROP_PROJECTS_DIR"] + os.environ["SECUREDROP_REPO_DIR"]
        )

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
        self.working_dir = f"{self.home_dir}/{self.securedrop_dom0_dev_dir}"

        # Load our QubesVM objects
        self.q = qubesadmin.Qubes()
        self.ssh_vm = self.q.domains[self.securedrop_dev_vm]
        self.usb_vm = self.q.domains[self.securedrop_usb_vm]

        # Parse the sha out of the dir name
        self.commit_sha = self.securedrop_repo_dir.split("_")[1]
        # Set our assumed status. If any step execution fails, we will change this to false
        self.status = "success"

        # Set up our logging handler.
        with open("/home/user/.logfile", "r") as l:
            self.log_file = l.readline().strip()
        self.logging = logging
        self.logging.basicConfig(
            format="%(levelname)s:%(message)s",
            level=logging.INFO,
            handlers=[
                logging.FileHandler(f"{self.home_dir}/{self.log_file}"),
                logging.StreamHandler(),
            ],
        )

        # Report to Github that the build has started running
        subprocess.check_call(
            [
                "qvm-run",
                self.securedrop_dev_vm,
                "/usr/bin/python3",
                "/home/user/bin/status.py",
                "--status",
                "running",
                "--sha",
                self.commit_sha,
            ]
        )

    def run_cmd(self, cmd):
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
            ansi_escape = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")
            for line in pipe:
                timestamp = format_current_timestamp()
                line_decoded = ansi_escape.sub("", line.decode("utf-8"))
                self.logging.info(f"[{timestamp}] {line_decoded}")

        command_line_args = shlex.split(cmd)
        timestamp = format_current_timestamp()
        self.logging.info(f"[{timestamp}] Running: {cmd}")

        p = subprocess.Popen(
            command_line_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        out, err = p.communicate()
        out = out.splitlines()
        log_subprocess_output(out)
        timestamp = format_current_timestamp()
        if p.returncode != 0:
            msg = f"[{timestamp}] Exception occurred during: {cmd}"
            self.logging.info(msg)
            self.status = "failure"
            # We failed on a step, so stop the build and report the status and log
            self.reportStatus()
            raise SystemExit(msg)
        else:
            self.logging.info(f"[{timestamp}] Step finished")

    def build(self):
        """
        Build the package
        """
        os.chdir(self.home_dir)

        # Wipe out our existing working dir on dom0
        if os.path.exists(self.working_dir):
            self.run_cmd(f"sudo chown -R {self.username} {self.working_dir}")
            shutil.rmtree(self.working_dir)

        # Generate our tarball in the appVM and extract it into dom0
        self.tar_file = f"{self.home_dir}/{self.securedrop_repo_dir}.tar"
        with open(self.tar_file, "w") as tarball:
            subprocess.check_call(
                [
                    "qvm-run",
                    "--pass-io",
                    self.securedrop_dev_vm,
                    f"tar -c -C {self.securedrop_projects_dir} {self.securedrop_repo_dir}",
                ],
                stdout=tarball,
            )
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


    def reportStatus(self):
        """
        Report the commit status in Github.
        """
        subprocess.check_call(
            [
                "qvm-run",
                self.securedrop_dev_vm,
                "/usr/bin/python3",
                "/home/user/bin/status.py",
                "--log",
                self.log_file,
                "--status",
                self.status,
                "--sha",
                self.commit_sha,
            ]
        )
if __name__ == "__main__":
    ci = QubesCI()
    ci.build()
    ci.test()
    ci.reportStatus()

