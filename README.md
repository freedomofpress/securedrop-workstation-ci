# Securedrop Workstation Continuous Integration scripts for QubesOS

## About

This collection of scripts is for running the securedrop-workstation CI on a Qubes machine.

Given the nature of Qubes, it is a complex component with a few moving parts.

This document tries to help FPF/SD engineers install the scripts on a Qubes 4.1+ machine.

## Instructions for dom0

1. Set up Qubes 4.1 per the Nextcloud doc.

2. Put the file `runner.py` in `/home/user/`.

3. Put the file `qubes.SDCIRunner`in `/etc/qubes-rpc/`.

4. Put the file `qubes.SDCIRunner.policy as `/etc/qubes-rpc/policy/`.


## Instructions for sd-ssh

1. `sudo mkdir /var/lib/sdci-ci-runner`

2. Put the file webhook.py in `/var/lib/sdci-ci-runner`

3. Put a `config.json` and `sd-journalist.sec` (prepared earlier as part of installation instructions) in `/var/lib/sdci-ci-runner`

4. Put `upload-file` in `/home/user/bin`. Generate a PAT with `repo:` access and ensure that PAT is in `upload-file` so that this file can post git commit statuses.

5. Put `sdci-repo-webhook.service` in `/etc/systemd/system/`. Configure a webhook 'secret' in this systemd file.

6. Run `sudo dnf install python3-pip python3-flask python3-paramiko python3-scp`

7. Run `sudo pip3 install github-webhook`

8. Run `systemctl daemon-reload; systemctl enable sdci-repo-webhook; systemctl start sdci-repo-webhook`

9. You will need to have opened port 5000 for the webhook in your tailscale iptables rules (`iptables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT`), and configured relevant Tailscale ACLs in the Tailscale admin dashboard. Riley took care of the latter for Mig.

10. Configure the webhook in your repository with the same secret you put in the systemd file in step 5. The URL would be https://ws-ci-runner.securedrop.org/hook/postreceive per https://github.com/freedomofpress/infrastructure/pull/4111 . You will also need to have an Nginx proxy somewhere answering for the 'outer' HTTPS request, and proxying through to your sd-ssh machine's port 5000 Flask app (via Tailscale)

11. Generate an SSH key and ensure this key is in the `/home/wscirunner/.ssh/authorized_keys` on the ws-ci-runner droplet proxy (so that `upload-file` can scp up the log results). You may need to ssh to the ws-ci-runner the first time to accept the host key signature

12. Try and push a commit and see if the webhook works.

## What should happen, if it works

The webhook should obtain info about the commit/repo and clone the repo into `/var/lib/sdci-repo-webhook/securedrop-workstation_{SHA}` on the sd-ssh VM.

It will then trigger an RPC call to dom0 to run the `runner.py` (wrapped in flock to avoid concurrent builds).

The runner.py will tarball up the codebase from sd-ssh and proceed with the `make clone; make dev; make test` sequence, logging to a log file the whole time.

Then, the dom0 will leverage the securedrop-workstation's `scripts/sdw-admin.py --uninstall --force` to tear everything down, along with cleaning up some remaining cruft.

If any of the steps fail, there will be a 'status' value of 'success' or 'failure'.

At the end of the process, the dom0 will copy its log file to the sd-ssh machine and then call `upload-file` via `qvm-run` on that machine. 

That script will upload the log to the ws-ci-runner proxy for viewing in a browser, and will also post a commit status to Github, with the `target_url` pointing to the HTTPS URL of that log file on the ws-ci-runner.