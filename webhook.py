import os
import subprocess
import logging
import shutil
from flask import Flask
from github_webhook import Webhook

secret = os.environ["SDCI_REPO_WEBHOOK_SECRET"]
listen_ip = os.environ["FLASK_RUN_HOST"]
listen_port = 5000

app = Flask(__name__)
webhook = Webhook(app, secret=secret)
logging.basicConfig(level=logging.INFO)


@webhook.hook("push")
def on_push(data):
    ref = data["ref"]
    repo = data["repository"]["name"]
    ssh_url = data["repository"]["clone_url"]
    commit = data["after"]
    logging.info(f"running on {ref}")
    # checkout that relevant commit
    workspace = f"{repo}_{commit}"
    if os.path.exists(workspace):
        shutil.rmtree(workspace)
    subprocess.check_call(["git", "clone", ssh_url, workspace])
    subprocess.check_call(["git", "checkout", commit], cwd=workspace)
    # Copy the config files we need
    shutil.copyfile("config.json", f"{workspace}/config.json")
    shutil.copyfile("sd-journalist.sec", f"{workspace}/sd-journalist.sec")
    # RPC call to trigger running the build on dom0
    # Note: I don't call p.communicate() (or use check_call()/check_output() instead of Pppen)
    # because it otherwise waits for the dom0 runner.py to finish, which takes a long time, and
    # that would cause Github to report that the webhook POST 'timed out' with an error. That
    # doesn't stop anything from working but it looks ugly to have an error in the Webhook deliveries
    p = subprocess.Popen(["qrexec-client-vm", "dom0", f"qubes.SDCIRunner+{workspace}"])


if __name__ == "__main__":
    app.run(host=listen_ip, port=listen_port)
