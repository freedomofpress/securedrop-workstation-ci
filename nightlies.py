#!/usr/bin/env python3

import argparse
import git
import logging
import os
import re
import subprocess
import tempfile
import yaml


def parse_args():
    """
    Handle CLI args.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--branch",
        default="main",
        required=True,
        action="store",
        help="Branch of SDW repo to check out"
    )
    args = parser.parse_args()
    return args


def nightly(branch):
    repo_url = "https://github.com/freedomofpress/securedrop-workstation.git"
    logging.info(f"Running nightly SDW CI against branch {branch}")

    with tempfile.TemporaryDirectory() as repo_working_dir:
        # Clone the repo and check out this branch
        subprocess.check_call(["git", "clone", "--branch", branch, repo_url, repo_working_dir])

        # Get the latest commit hash on this branch
        repo = git.Repo(repo_working_dir)

        # Get the latest commit SHA
        commit = repo.head.commit
        sha = commit.hexsha

        # Get the author
        author = commit.author

        # Get the commit message
        message = commit.message

        # Check if 'qubes' attribute exists in the YAML data.
        yaml_data = {}
        ci_file = f"{repo_working_dir}/.github/workstation-ci.yml"
        if os.path.exists(ci_file):
            try:
                with open(ci_file, "r") as y:
                    yaml_data = yaml.safe_load(y)
            except yaml.YAMLError as e:
                logging.info(f"Error reading CI YAML file {ci_file}: {e}")
                return

            # If it does, run the CI.
            if "qubes" in yaml_data:
                qubes_version = yaml_data["qubes"]
                if re.match(r'^\d+\.\d+$', qubes_version):
                    context = {
                        "commit": sha,
                        "author": author,
                        "message": message,
                        "reason": "nightly"
                    }
                    subprocess.Popen([
                        "/home/wscirunner/venv/bin/python",
                        "/home/wscirunner/securedrop-workstation-ci/run.py",
                        "--version",
                        qubes_version,
                        "--update",
                        "--context",
                        json.dumps(context)
                    ],cwd="/home/wscirunner/securedrop-workstation-ci")
                else:
                    logging.info(f"Didn't recognise the qubes version in the YAML file {ci_file}.")
                    return
            else:
                logging.info(f"The 'qubes' attribute does not exist in the YAML file {ci_file}.")
                return
        else:
            logging.info(f"The CI YAML file {ci_file} does not exist.")
            return


if __name__ == "__main__":
    args = parse_args()
    nightly(branch=args.branch)
