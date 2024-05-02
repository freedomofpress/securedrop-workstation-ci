#!/usr/bin/env python3

import argparse
import json
import logging
import os
import requests
from logging.handlers import SysLogHandler


def parse_args():
    """
    Handle CLI arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log",
        default="",
        action="store",
        help="Path to the log file",
    )
    parser.add_argument(
        "--status",
        action="store",
        required=True,
        help="Status of the test to send as a Github commit status",
    )
    args = parser.parse_args()
    return args


class Status:
    def __init__(self):
        """
        Set up the Status class with attributes required.
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        handler = SysLogHandler(facility=SysLogHandler.LOG_DAEMON, address="/dev/log")
        handler.setFormatter(logging.Formatter("sdw-ci-status: %(message)s"))
        self.logger.addHandler(handler)

        # Read context in from file
        context_filepath = "/home/user/QubesIncoming/dom0/context.json"
        if os.path.exists(context_filepath):
            with open(context_filepath, "r") as context_file:
                # Load in the JSON
                try:
                    context = json.load(context_file)
                except json.JSONDecodeError as e:
                    self.logger.debug(e)
                    raise SystemError(e)

                # Set attributes from JSON
                try:
                    self.commit_message = context["message"].split("\n")[0]
                    self.commit_sha = context["commit"]
                    self.commit_author = context["author"]
                    self.reason = context["reason"]
                except KeyError as e:
                    self.logger.debug(e)
                    raise SystemError(e)
        else:
            e = "context.json file not found!"
            self.logger.debug(e)
            raise SystemError(e)

    def commit_status(self, status, log):
        """
        Reports a Github commit status
        """
        if status == "error":
            description = "There was a problem during the CI execution"
        elif status == "failure":
            description = "The build or test process failed"
        elif status == "success":
            description = "The build succeeded"
        elif status == "pending":
            description = "The build is queued"
        elif status == "running":
            description = "The build is running"
        elif status == "canceled":
            description = "The build was canceled by an administrator"
        else:
            raise SystemError(f"Unrecognized status: {status}")

        with open("/home/user/.sdci-ghp.txt") as f:
            github_token = f.read().strip()
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Content-Type": "application/json",
        }
        data = {}
        data["context"] = "sd-ci-runner"
        data["description"] = description
        if status in ["error", "failure", "success"]:
            data["target_url"] = f"https://ws-ci-runner.securedrop.org/{log}"

        # Github expects state 'error', 'failure', 'success' or 'pending'.
        # Override our non-standard statuses to the closest match to make the
        # API call work.
        if status == "canceled":
            status = "error"
        if status == "running":
            status = "pending"
        data["state"] = status

        self.logger.debug(f"Posting commit status for {self.commit_sha} to Github")
        requests.post(
            f"https://api.github.com/repos/freedomofpress/securedrop-workstation/statuses/{self.commit_sha}",
            json=data,
            headers=headers,
        )

    def notify_slack(self, status, log):
        """
        Notifies Slack upon build completion (whether success or failure/error)
        """
        with open("/home/user/.slack-webhook.txt", "r") as s:
            slack_webhook_url = s.readline().strip()

        commit_url = f"https://github.com/freedomofpress/securedrop-workstation/commit/{self.commit_sha}"
        if self.reason == "nightly":
            text = "This CI run was a nightly automated test of the HEAD commit"
        elif self.reason == "push":
            text = "This CI run was triggered by"
        else:
            text = self.reason
        text = (
            text
            + f": <{commit_url}|{self.commit_sha} by {self.commit_author}: {self.commit_message}>"
        )

        if status == "error" or status == "failure":
            color = "danger"
        elif status == "success":
            color = "good"
        else:
            # Don't send notifications for pending/running status
            self.logger.debug(
                "Not posting to Slack, the status is only that we are pending or running the build"
            )
            return

        message = {
            "attachments": [
                {
                    "color": color,
                    "pretext": f"SDW CI job {status}",
                    "title": "Commit",
                    "title_link": commit_url,
                    "text": text,
                    "fallback": text,
                    "actions": [
                        {
                            "type": "button",
                            "text": "View Log Output",
                            "url": f"https://ws-ci-runner.securedrop.org/{log}",
                        }
                    ],
                }
            ]
        }

        # Convert the message to JSON
        json_message = json.dumps(message)

        # Attempt to post the message to Slack
        try:
            self.logger.debug("Posting build status to Slack")
            response = requests.post(
                slack_webhook_url,
                data=json_message,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            e = "HTTP error while contacting Slack"
            self.logger.debug(e)
            raise SystemError(e)
        except Exception as err:
            e = f"Other error occurred while contacting Slack: {err}"
            self.logger.debug(e)
            raise SystemError(e)


if __name__ == "__main__":
    # Parse args
    args = parse_args()

    # Instantiate our class
    status = Status()

    # Report Github status check
    status.commit_status(args.status, args.log)

    # Slack notification for unsuccessful runs
    status.notify_slack(args.status, args.log)
