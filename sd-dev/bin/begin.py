import argparse
import os
import subprocess
import shutil

def parse_args():
    """
    Handle CLI args.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit",
        default=False,
        required=True,
        action="store",
        help="Git commit to build from",
    )
    parser.add_argument(
        "--context",
        default="push",
        required=False,
        action="store",
        help="A context to help explain why the build ran. Used only in the Slack notification"
    )
    args = parser.parse_args()
    return args

def run(commit, context):
    owner = "freedomofpress"
    repo = "securedrop-workstation"

    working_dir = "/var/lib/sdci-ci-runner"
    subprocess.run(["sudo", "mkdir", "-p", working_dir])
    subprocess.run(["sudo", "chown", "user:user", working_dir])

    workspace = f"{repo}_{commit}"

    # Remove copy of this repo if it exists
    if os.path.exists(f"{working_dir}/{workspace}"):
        shutil.rmtree(f"{working_dir}/{workspace}")

    # Clone and checkout that relevant commit
    subprocess.check_call(["git", "clone", f"https://github.com/{owner}/{repo}", f"{working_dir}/{workspace}"])
    subprocess.check_call(["git", "checkout", commit], cwd=f"{working_dir}/{workspace}")

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
        "--sha",
        commit
    ])

    # RPC call to trigger running the build on dom0
    subprocess.Popen(["qrexec-client-vm", "dom0", f"qubes.SDCIRunner+{workspace}+{context}"])


if __name__ == "__main__":
    args = parse_args()
    run(args.commit, args.context)
