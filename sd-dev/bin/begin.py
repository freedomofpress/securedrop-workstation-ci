#!/usr/bin/env python3

import json
import logging
import os
import subprocess
import shutil
from logging.handlers import SysLogHandler


def run():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    handler = SysLogHandler(facility=SysLogHandler.LOG_DAEMON, address="/dev/log")
    handler.setFormatter(logging.Formatter("sdw-ci-begin: %(message)s"))
    logger.addHandler(handler)

    owner = "freedomofpress"
    repo = "securedrop-workstation"

    working_dir = "/var/lib/sdci-ci-runner"
    subprocess.run(["sudo", "mkdir", "-p", working_dir])
    subprocess.run(["sudo", "chown", "user:user", working_dir])

    # Read context in from file
    context_filepath = "/home/user/context.json"
    if os.path.exists(context_filepath):
        with open(context_filepath, "r") as context_file:
            try:
                context = json.load(context_file)
            except json.JSONDecodeError as e:
                logger.debug(e)
                raise SystemError(e)
    else:
        e = "context.json file not found!"
        logger.debug(e)
        raise SystemError(e)
    try:
        commit_sha = context["commit"]
    except KeyError as e:
        logger.debug(e)
        raise SystemError(e)

    workspace = f"{repo}_{commit_sha}"

    # Remove copy of this repo if it exists
    if os.path.exists(f"{working_dir}/{workspace}"):
        shutil.rmtree(f"{working_dir}/{workspace}")

    # Clone and checkout that relevant commit
    logger.debug("Cloning the repo")
    subprocess.check_call(
        [
            "git",
            "clone",
            f"https://github.com/{owner}/{repo}",
            f"{working_dir}/{workspace}",
        ]
    )
    subprocess.check_call(
        ["git", "checkout", commit_sha], cwd=f"{working_dir}/{workspace}"
    )

    # Copy the config files we need
    if os.path.exists(f"{working_dir}/{workspace}/files/config.json.example"):
        shutil.copy(
            f"{working_dir}/{workspace}/files/config.json.example",
            f"{working_dir}/{workspace}/config.json",
        )

    if os.path.exists(f"{working_dir}/{workspace}/sd-journalist.sec.example"):
        shutil.copy(
            f"{working_dir}/{workspace}/sd-journalist.sec.example",
            f"{working_dir}/{workspace}/sd-journalist.sec",
        )

    # Post pending status back to Github
    logger.debug("Telling Github that the build is pending")
    subprocess.check_call(
        [
            "/usr/bin/python3",
            "/home/user/bin/status.py",
            "--status",
            "pending",
        ]
    )

    # RPC call to trigger running the build on dom0
    logger.debug("Telling dom0 to commence CI")
    subprocess.Popen(["qrexec-client-vm", "dom0", f"qubes.SDCIRunner+{workspace}"])


if __name__ == "__main__":
    run()
