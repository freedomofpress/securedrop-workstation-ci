# Installation instructions

This document explains how to install the CI for Securedrop Workstation.

It involves a combination of dom0 and VM configuration on a Qubes installation, as well as steps in
Github/Tailscale.

# Qubes install and initial provisioning

1. Download and verify Qubes per
   [these instructions](https://workstation.securedrop.org/en/stable/admin/install.html#download-and-verify-qubes-os).

2. Install Qubes, mostly following
   [these instructions](https://workstation.securedrop.org/en/stable/admin/install.html#install-qubes-os-estimated-wait-time-30-45-minutes)
   (see exceptions below).

2a. Keep all configuration defaults, except:

- Turn off FDE (we could later investigate doing this with FDE enabled, see
  [this issue](https://github.com/freedomofpress/securedrop/issues/816))
- Uncheck the creation of the personal and work qubes (this will show up as an option after reboot)

2b. In dom0, confirm you can start sys-usb (because it’s given us some issues with different
hardware) by running `qvm-start sys-usb`.

2c. Update dom0 per
[these instructions](https://workstation.securedrop.org/en/stable/admin/install.html#apply-dom0-updates-estimated-wait-time-15-30-minutes)

2d. Run any updates you see in the Qubes menu and then reboot.

3. In dom0, install `make` and then create the sd-ssh StandaloneVM:

```
sudo qubes-dom0-update make
sudo qvm-create --standalone --template fedora-37 --label red sd-ssh
qvm-volume resize sd-ssh:root 50G
qvm-volume resize sd-ssh:private 20G
qvm-tags sd-ssh add sd-client
```

Also ensure that you check the box to 'Start qube automatically on boot' in the Qubes settings.

# Install dependencies on sd-ssh VM

Open a terminal in the sd-ssh VM and perform the following steps to install the core dependencies
and Tailscale.

```
sudo dnf install openssh-server rpm-build dnf-plugins-core python3-pip python3-flask python3-paramiko python3-scp
sudo pip3 install github-webhook
sudo systemctl ssh enable

curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-tags=tag:servers,tag:sd-ci-servers
```

You will need to go and complete the approval of the device in Tailscale as an admin, by copying the
link that is returned in the last step.

Then come back and proceed with the following steps.

```
sudo -i

iptables -I INPUT 3 -m tcp -p tcp --dport 22 -i tailscale0 -j ACCEPT
ip6tables -I INPUT 3 -m tcp -p tcp --dport 22 -i tailscale0 -j ACCEPT
iptables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT
ip6tables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT
iptables-save > /etc/qubes/iptables.rules
ip6tables-save > /etc/qubes/ip6tables.rules

sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -a -G docker user
systemctl enable docker
```

# Install the CI scripts from this repository

You're nearly done! Now you need to install the actual CI scripts, systemd unit files, and other
config from this very repo into your dom0 and sd-ssh.

## Instructions for dom0

1. Put the file `runner.py` in `/home/user/`. Ensure it is executable.

2. Put the files `qubes.SDCIRunner` and `qubes.SDCICanceler` in `/etc/qubes-rpc/`. Ensure they are
   executable.

3. Put the files `qubes.SDCIRunner.policy` and `qubes.SDCICanceler.policy` as
   `/etc/qubes-rpc/policy/qubes.SDCIRunner` and `/etc/qubes-rpc/policy/qubes.SDCICanceler`.

These policy files do not need to be executable.

4. Put the files `sd-ssh-update.service` and `sd-ssh-update.timer` in `/etc/systemd/system/` and run
   `systemctl enable sd-ssh-update.service; systemctl enable sd-ssh-update.timer; systemctl start sd-ssh-update.timer`
   as root.

5. Put the file `sd-ssh-update.sh` in `/home/user/`.

## Instructions for sd-ssh

1. Create the CI runner working directory with `sudo mkdir /var/lib/sdci-ci-runner`.

2. Put the file `webhook.py` in `/var/lib/sdci-ci-runner`.

3. Create a `config.json` copied from
   [this example](https://github.com/freedomofpress/securedrop-workstation/blob/main/files/config.json.example)
   and a `sd-journalist.sec` copied from
   [this example](https://github.com/freedomofpress/securedrop-workstation/blob/main/sd-journalist.sec.example),
   and store them in `/var/lib/sdci-ci-runner`.

4. At this point, `sudo chown -R user.user /var/lib/sdci-ci-runner`.

5. Put `upload-report` and `cancel.py` in `/home/user/bin`.

6. Generate a PAT in Github with full `repo:` access and ensure that that PAT is set in the
   `upload-report` script as the `github_token` variable, so that the script can post git commit
   statuses back to Github.

7. Put `sdci-repo-webhook.service` in `/etc/systemd/system/`. Set a value for
   `SDCI_REPO_WEBHOOK_SECRET` in this file. Also adjust the `FLASK_RUN_HOST` to the IP of your
   sd-ssh machine's Tailscale IP so that the service listens only on that interface.

8. Enable and start the flask webhook service via systemd:
   `sudo systemctl daemon-reload; sudo systemctl enable sdci-repo-webhook; sudo systemctl start sdci-repo-webhook`.

9. Configure the webhook in your repository for the 'push' event, with the same secret you put in
   the systemd file in step 7.

The Payload URL of the webhook should be https://ws-ci-runner.securedrop.org/hook/postreceive and
the Content type should be `application/json`. Ensure you keep `Enable SSL verification` turned on.

10. Generate an SSH key on sd-ssh with `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_sdci_upload`, and
    ensure that this key is in the `/home/wscirunner/.ssh/authorized_keys` on the tailscale proxy
    droplet. This ensures that the `upload-report` script can successfully scp up the log file to
    the proxy droplet. Run
    `ssh -i ~/.ssh/id_ed25519_sdci_upload wscirunner@ws-ci-runner.securedrop.org` once, on the
    sd-ssh VM, to accept the host key signature for the first time.

## Reboot and test

Do a full reboot of the Qubes system.

Then, double-check that sd-ssh has started automatically at boot and that it has started the Flask
webhook service (look for a process `/usr/bin/python3 -m flask run`).

After that, you can push a commit to the repository and test the webhook and CI process works.
