# Installation instructions

This document explains how to install the CI for Securedrop Workstation.

It involves a combination of dom0 and VM configuration on a Qubes installation, as well as steps in
Github.

The information assumes you'll be running this on a virtual machine such as VMware.

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

In our case, we also install `open-vm-tools` and run `sudo systemctl enable vmtoolsd`,
as our scripts use vmtoolsd to issue commands to the dom0 from the VMware API.

```
sudo qubes-dom0-update make open-vm-tools
```

6. Run any updates you see in the Qubes menu and then reboot.

7. In dom0, create the sd-dev StandaloneVM. If it's Qubes 4.2, you can use the debian-12-xfce template.

```
sudo qvm-create --standalone --template debian-11 --label red sd-dev
qvm-volume resize sd-dev:root 50G
qvm-volume resize sd-dev:private 20G
```

Also ensure that you check the box to 'Start qube automatically on boot' in the Qubes settings.

# Install podman on sd-dev VM

Open a terminal in the sd-dev VM and perform the following steps to install podman:

```
sudo apt-get install podman
```

# Snapshot the VM

At this point, if you're using VMware, you'll want to shut down and snapshot the VM, as it's now
in a good state and could be cloned to make more of them!

# Configure the scripts on GitHub

1. Generate a PAT in Github with full `repo:` access and ensure that that PAT is written to 
   `sd-dev/.sdci-ghp.txt` on the machine that will execute the run.py on the host machine.
   This will be used by `status.py`, so that the script can post git commit statuses back to Github.

2. Configure the webhook in your repository for the 'push' event, with the same secret you put in
   the systemd file.

The Payload URL of the webhook should be `https://ws-ci-runner.securedrop.org/hook/postreceive` and
the Content type should be `application/json`. Ensure you keep `Enable SSL verification` turned on.

# Test

Test the CI flow with `./run.py --version 4.1 --commit [some commit hash]`


# Options for `run.py`

There are a few options for `run.py` which is the main entry point that the webhook service calls.

## `--version [4.1|4.2]`

Set the version number of Qubes you are going to be running on, for example, 4.1 or 4.2.

This helps the script find a VM with that version in its name, to use for the CI run.

## `--commit [sha]`

If you pass a commit hash, this will be understood that you want to run CI tests.

## `--snapshot [id]`

If you pass this option, the VM will be reverted to this snapshot if it exists, before being
powered up.

If you do not pass this option, a snapshot ID will be read from the config file for this
VM, and the VM will be restored to that snapshot instead. (There is never a scenario whereby
the VM is *not* restored from snapshot first, as that is our way of guaranteeing a 'clean
start')
 
## `--update`

If you pass this flag, the system will boot the Qubes VM and run dom0, template and StandaloneVM
updates via salt in the standard Qubes way.

If you also passed `--commit`, it will be undertood that you want to run CI tests immediately
after having applied the updates. In this case, it will reboot the VM after applying updates
but before running the CI test suite. This flow is useful for running 'nightly' tests.

## `--save`

If you pass this flag, the system will save a new snapshot of the VM and store the new snapshot
ID in the config file. This option is meant to mainly be used in conjunction with `--update`,
e.g as an automatic routine patching procedure.


# Options for `nightlies.py`

The `nightlies.py` script is designed to run via cron or similar schedule. It takes `--branch` as
an argument.

It will clone the repo, check out that branch, detect the appropriate Qubes version from that
branch, detect the latest commit, then run `run.py` with the flag `--update` and the `--commit`
hash.

This is designed to apply software updates in Qubes, stop/start the guest and then proceed with
CI.
