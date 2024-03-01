import argparse
import os
import requests
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
    args = parser.parse_args()
    return args

def run(commit):
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
    config_url = f"https://github.com/{owner}/{repo}/raw/main/files/config.json.example"
    config_response = requests.get(config_url)
    with open(os.path.join(f"{working_dir}/{workspace}", "config.json"), "wb") as config_file:
        config_file.write(config_response.content)

    # Download sd-journalist.sec.example
    sd_journalist_url = f"https://github.com/{owner}/{repo}/raw/main/sd-journalist.sec.example"
    sd_journalist_response = requests.get(sd_journalist_url)
    with open(os.path.join(f"{working_dir}/{workspace}", "sd-journalist.sec"), "wb") as sd_journalist_file:
        sd_journalist_file.write(sd_journalist_response.content)

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
    p = subprocess.Popen(["qrexec-client-vm", "dom0", f"qubes.SDCIRunner+{workspace}"])


if __name__ == "__main__":
    args = parse_args()
    run(args.commit)
