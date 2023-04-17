#!/usr/bin/env python3

import argparse
import os
import subprocess
import shutil


def parse_args():
    """
    Handle CLI arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sha", required=True, action="store", help="SHA commit hash to cancel"
    )
    args = parser.parse_args()
    return args


def cancel(sha):
    workspace = f"/var/lib/sdci-ci-runner/securedrop-workstation_{sha}"
    if os.path.exists(workspace):
        shutil.rmtree(workspace)

    # RPC call to trigger canceling the build on dom0
    subprocess.check_call(["qrexec-client-vm", "dom0", f"qubes.SDCICanceler+{sha}"])

    # Post pending status back to Github
    subprocess.check_call(
        ["/home/user/bin/upload-report", "--status", "canceled", "--sha", sha]
    )


if __name__ == "__main__":
    # Parse args
    args = parse_args()
    cancel(args.sha)
