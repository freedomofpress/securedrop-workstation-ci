#!/usr/bin/env python3

import json
import os
import subprocess
import shutil

def run():
    owner = "freedomofpress"
    repo = "securedrop-workstation"

    working_dir = "/var/lib/sdci-ci-runner"
    subprocess.run(["sudo", "mkdir", "-p", working_dir])
    subprocess.run(["sudo", "chown", "user:user", working_dir])

    # Read context in from file
    context_filepath = "/home/user/QubesIncoming/dom0/context.json"
    if os.path.exists(context_filepath):
        with open(context_filepath, "r") as context_file:
            context = json.load(context_file)
    else:
        raise SystemError("context.json file not found!")
    commit_sha = context.get("commit", False)

    workspace = f"{repo}_{commit_sha}"

    # Remove copy of this repo if it exists
    if os.path.exists(f"{working_dir}/{workspace}"):
        shutil.rmtree(f"{working_dir}/{workspace}")

    # Clone and checkout that relevant commit
    subprocess.check_call(["git", "clone", f"https://github.com/{owner}/{repo}", f"{working_dir}/{workspace}"])
    subprocess.check_call(["git", "checkout", commit_sha], cwd=f"{working_dir}/{workspace}")

    # Copy the config files we need
    if os.path.exists(f"{working_dir}/{workspace}/files/config.json.example"):
        shutil.copy(f"{working_dir}/{workspace}/files/config.json.example", f"{working_dir}/{workspace}/config.json")

    if os.path.exists(f"{working_dir}/{workspace}/sd-journalist.sec.example"):
        shutil.copy(f"{working_dir}/{workspace}/sd-journalist.sec.example", f"{working_dir}/{workspace}/sd-journalist.sec")

    # Post pending status back to Github
    subprocess.check_call([
        "/usr/bin/python3",
        "/home/user/bin/status.py",
        "--status",
        "pending",
    ])

    # RPC call to trigger running the build on dom0
    subprocess.Popen(["qrexec-client-vm", "dom0", f"qubes.SDCIRunner+{workspace}"])


if __name__ == "__main__":
    run()
