#!/usr/bin/env python3

import argparse
import requests


def parse_args():
    """
    Handle CLI arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
            "--log",
            default = "",
            action="store",
            help="Path to the log file",
    )
    parser.add_argument(
            "--status",
            action="store",
            required=True,
            help="Status of the test to send as a Github commit status",
    )
    parser.add_argument(
            "--sha",
            required=True,
            action="store",
            help="SHA commit hash to report the commit status for"
    )
    args = parser.parse_args()
    return args


def report_status(status, sha, log):
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

    requests.post(f"https://api.github.com/repos/freedomofpress/securedrop-workstation/statuses/{sha}", json=data, headers=headers)


if __name__ == "__main__":
    # Parse args
    args = parse_args()
    # Report Github status check
    report_status(args.status, args.sha, args.log)
