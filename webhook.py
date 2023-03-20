import os
import subprocess
import logging
from flask import Flask
from github_webhook import Webhook


secret = os.environ["SDCI_REPO_WEBHOOK_SECRET"]
workspace = os.environ["SDCI_REPO_WEBHOOK_WORKSPACE"]
flag_file = os.environ["SDCI_REPO_WEBHOOK_FLAG_FILE"]

app = Flask(__name__)
webhook = Webhook(app, secret=secret)
logging.basicConfig(level=logging.INFO)


@webhook.hook("push")
def on_push(data):
    ref = data["ref"]
    commit = data["after"]
    logging.info(f"running on {ref}")
    # checkout that relevant commit
    subprocess.check_call(["git", "fetch", "origin", ref], cwd=workspace)
    subprocess.check_call(["git", "checkout", commit], cwd=workspace)
    # touch the flag file to trigger dom0's cron/runner to fire
    with open(f"{workspace}/{flag_file}", "w") as state_file:
        state_file.write(commit)


if __name__ == "__main__":
    app.run(host="100.92.73.40", port=5000)