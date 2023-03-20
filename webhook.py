import os
import subprocess
import logging
import shutil
from flask import Flask
from github_webhook import Webhook

secret = os.environ["SDCI_REPO_WEBHOOK_SECRET"]
app = Flask(__name__)
webhook = Webhook(app, secret=secret)
logging.basicConfig(level=logging.INFO)


@webhook.hook("push")
def on_push(data):
    ref = data["ref"]
    repo = data["repository"]["name"]
    clone_url = data["repository"]["clone_url"]
    commit = data["after"]
    logging.info(f"running on {ref}")
    # checkout that relevant commit
    workspace = f"{repo}_{commit}"
    if os.path.exists(workspace):
        shutil.rmtree(workspace)
    subprocess.check_call(["git", "clone", sclone_url, workspace])
    subprocess.check_call(["git", "checkout", commit], cwd=workspace)
    # Copy the config files we need
    shutil.copyfile("config.json", f"{workspace}/config.json")
    shutil.copyfile("sd-journalist.sec", f"{workspace}/sd-journalist.sec")
    # RPC call to trigger running the build on dom0
    subprocess.check_call(["qrexec-client-vm", "-e", "dom0", f"qubes.SDCIRunner+{workspace}"])


if __name__ == "__main__":
    app.run(host="100.92.73.40", port=5000)