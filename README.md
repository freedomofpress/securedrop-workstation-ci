# Securedrop Workstation Continuous Integration scripts

## About

This collection of scripts is for running the securedrop-workstation CI on a Qubes machine.

Given the nature of Qubes, it is a complex component with a few moving parts.

This document tries to help FPF/SD engineers install the scripts on a Qubes 4.1+ machine.

## Instructions for dom0

1. Set up Qubes 4.1 per the Nextcloud doc.

2. Put the file `runner.py` in `/home/user/`.

3. Put the file `qubes.SDCIRunner` in `/etc/qubes-rpc/`.

4. Put the file `qubes.SDCIRunner.policy` as `/etc/qubes-rpc/policy/qubes.SDCIRunner`.


## Instructions for sd-ssh

1. `sudo mkdir /var/lib/sdci-ci-runner`

2. Put the file webhook.py in `/var/lib/sdci-ci-runner` . You may need to change the IP of the binding IP to your sd-ssh machine's tailscale IP

3. Put a `config.json` and `sd-journalist.sec` (prepared earlier as part of installation instructions) in `/var/lib/sdci-ci-runner`. At this point, `sudo chown -R user.user /var/lib/sdci-ci-runner`

4. Put `upload-file` in `/home/user/bin`. Generate a PAT in Github with full `repo:` access and ensure that that PAT is in `upload-file`, so that the script can post git commit statuses back to Github.

5. Put `sdci-repo-webhook.service` in `/etc/systemd/system/`. Configure a webhook 'secret' in this systemd file. Also adjust the `FLASK_RUN_HOST` to the IP of your sd-ssh machine's Tailscale IP.

6. Install some dependencies: `sudo dnf install python3-pip python3-flask python3-paramiko python3-scp; sudo pip3 install github-webhook`

7. Enable and start the flask service via systemd: `systemctl daemon-reload; systemctl enable sdci-repo-webhook; systemctl start sdci-repo-webhook`

8. You will need to have opened port 5000 for the webhook in your tailscale iptables rules (`iptables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT`), and configured relevant Tailscale ACLs in the Tailscale admin dashboard. Riley took care of the latter for Mig.

9. Configure the webhook in your repository for the 'push' event, with the same secret you put in the systemd file in step 5. The URL would be https://ws-ci-runner.securedrop.org/hook/postreceive per https://github.com/freedomofpress/infrastructure/pull/4111 . You will also need to have an Nginx proxy somewhere answering for the 'outer' HTTPS request, and proxying through to your sd-ssh machine's port 5000 Flask app (via Tailscale)

10. Generate an SSH key on sd-ssh with `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_sdci_upload`, and ensure this key is in the `/home/wscirunner/.ssh/authorized_keys` on the ws-ci-runner droplet proxy (so that `upload-file` can scp up the log results). Run `ssh -i ~/.ssh/id_ed25519_sdci_upload wscirunner@ws-ci-runner.securedrop.org` once to accept the host key signature.


## Test it

Try and push a commit and see if the webhook works!

### What should happen, if it works

1. The webhook should obtain info about the commit/repo and clone the repo into `/var/lib/sdci-ci-runner/securedrop-workstation_{SHA}` on the sd-ssh VM.

2. It will then trigger an RPC call to dom0 to run the `runner.py` (wrapped in flock to avoid concurrent builds).

3. The runner.py will tarball up the codebase from sd-ssh and proceed with the `make clone; make dev; make test` sequence, logging to a log file the whole time.

4. Then, the dom0 will leverage the securedrop-workstation's `scripts/sdw-admin.py --uninstall --force` to tear everything down, along with cleaning up some remaining cruft.

The runner.py will detect if any of the commands succeed or fail but it should not abort on failure (so that the teardown still completes).

5. At the end of the process, the dom0 will copy its log file to the sd-ssh machine and then call `upload-file` via `qvm-run` on that machine, with a 'status' indicating whether the build succeeded or failed.

That script will upload the log to the ws-ci-runner proxy for viewing in a browser, and will also post a commit status to Github, with the `target_url` pointing to the HTTPS URL of that log file on the ws-ci-runner, and with the status of the build.
