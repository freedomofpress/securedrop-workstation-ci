#!/bin/bash

set -e

VM="sd-ssh"

# Run update
/usr/bin/flock -w 3600 /var/tmp/sd-ci-runner.lock -c "sudo /usr/bin/qubesctl --skip-dom0 --targets ${VM} state.sls update.qubes-vm"

# Reboot
qvm-shutdown --wait "${VM}"
qvm-start "${VM}"
