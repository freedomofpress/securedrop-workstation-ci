# Installation instructions

This document explains how to install the CI for Securedrop Workstation.

It involves a combination of dom0 and VM configuration on a Qubes installation, as well as steps in
Github/Tailscale.

# Qubes install and initial provisioning

1. [Download and verify Qubes](https://workstation.securedrop.org/en/stable/admin/install.html#download-and-verify-qubes-os). We have last tested this with 4.1.2.

2. Install Qubes, referring to
   [the SecureDrop Workstation docs](https://workstation.securedrop.org/en/stable/admin/install.html#install-qubes-os-estimated-wait-time-30-45-minutes);
   see below for areas that will diverge from a typical install.

3. Keep all configuration defaults, except:

- Turn off FDE (we could later investigate doing this with FDE enabled, see
  [this issue](https://github.com/freedomofpress/securedrop/issues/816))
- After the first reboot, uncheck the creation of default qubes such as
  `personal` and `work`.

4. In dom0, confirm you can start sys-usb (because it’s given us some issues with different
hardware) by running `qvm-start sys-usb`.

5. Update dom0 and install `make`, referring again to
[the next section of SDW docs](https://workstation.securedrop.org/en/stable/admin/install.html#apply-dom0-updates-estimated-wait-time-15-30-minutes)

```
sudo qubes-dom0-update make
```

6. Run any updates you see in the Qubes menu and then reboot.

7. In dom0, create the sd-ssh StandaloneVM:

```
sudo qvm-create --standalone --template fedora-37 --label red sd-ssh
qvm-volume resize sd-ssh:root 50G
qvm-volume resize sd-ssh:private 20G
qvm-tags sd-ssh add sd-client
```

Also ensure that you check the box to 'Start qube automatically on boot' in the Qubes settings.

# Install dependencies on sd-ssh VM

1. Open a terminal in the sd-ssh VM and perform the following steps to install the core dependencies:

```
sudo dnf install openssh-server rpm-build dnf-plugins-core python3-pip python3-flask python3-paramiko python3-scp
sudo pip3 install github-webhook
sudo systemctl ssh enable
```

2. Install Tailscale:

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-tags=tag:servers,tag:sd-ci-servers
```

Complete the approval of the device in Tailscale as an admin, by copying
the link that is returned in the last step.

Sign in with your GitHub account and approve your VM as a device on the
`freedomofpress.org.github` tailnet, with a name describing the
hardware like `sd-ssh-t14`; it will show up on [the machines
list](https://login.tailscale.com/admin/machines). When authorizing
Tailscale in Github OAuth consent, be sure to choose the "Multi-user"
`freedomofpress` tailnet, if your Github account is a member of
multiple organizations.

3. Setup the firewall:

```
sudo -i

iptables -I INPUT 3 -m tcp -p tcp --dport 22 -i tailscale0 -j ACCEPT
ip6tables -I INPUT 3 -m tcp -p tcp --dport 22 -i tailscale0 -j ACCEPT
iptables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT
ip6tables -I INPUT 3 -m tcp -p tcp --dport 5000 -i tailscale0 -j ACCEPT
iptables-save > /etc/qubes/iptables.rules
ip6tables-save > /etc/qubes/ip6tables.rules
```

4. Setup docker:

```
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -a -G docker user
systemctl enable docker
```

# Install the CI scripts from this repository

You're nearly done! Now you need to install the actual CI scripts, systemd unit files, and other
config from this very repo into your dom0 and sd-ssh.

1. In `sd-ssh`, run

```
sudo ./install/sd-ssh
```

This will pull up the `sdci-repo-webhook.service` file. Edit it to fill in
`SDCI_REPO_WEBHOOK_SECRET` and adjust the `FLASK_RUN_HOST` to the IP of your sd-ssh machine's
Tailscale IP so that the service listens only on that interface.

2. Copy files from `sd-ssh` to `dom0` (do this any time you pull an
   update to the git repository, from the home directory):

```
qvm-run --pass-io sd-ssh 'tar -c -C /home/user securedrop-workstation-ci' | tar xvf -
```

3. In `dom0`, run

```
sudo ./install/dom0
```

# Configure the scripts on GitHub

1. Generate a PAT in Github with full `repo:` access and ensure that that PAT is written to
   `/home/user/sdci-ghp.txt`. This will be used by `upload-report`, so that the script can post git
   commit statuses back to Github.

2. Configure the webhook in your repository for the 'push' event, with the same secret you put in
   the systemd file in step 7.

The Payload URL of the webhook should be `https://ws-ci-runner.securedrop.org/hook/postreceive` and
the Content type should be `application/json`. Ensure you keep `Enable SSL verification` turned on.

# Generate SSH upload key

Generate an SSH key on sd-ssh with `ssh-keygen -t ed25519 -f
~/.ssh/id_ed25519_sdci_upload`, and ensure that this key is in the
`/home/wscirunner/.ssh/authorized_keys` on the tailscale proxy droplet.
This ensures that the `upload-report` script can successfully scp up the
log file to the proxy droplet. Run `ssh -i ~/.ssh/id_ed25519_sdci_upload
wscirunner@ws-ci-runner.securedrop.org` once, on the sd-ssh VM, to
accept the host key signature for the first time.

(TODO: cover setting up an SSH config file.)

## Reboot and test

Do a full reboot of the Qubes system.

Then, double-check that sd-ssh has started automatically at boot and that it has started the Flask
webhook service (look for a process `/usr/bin/python3 -m flask run`).

After that, you can push a commit to the repository and test the webhook and CI process works.
