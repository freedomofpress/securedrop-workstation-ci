#!/bin/bash

set -eox pipefail

NOW=$(date +%y%m%s%H%M%S)
LOG="/home/user/securedrop-workstation-test.log"
SECUREDROP_DEV_VM="sd-ssh"

# Run the runner script, and send the output to a log file directly piped to the sd-ssh VM
bash /home/user/runner.sh | qvm-run --pass-io "${SECUREDROP_DEV_VM}" "cat > ${LOG}"

# Rename log so the next job doesn't clobber it
qvm-run --pass-io "${SECUREDROP_DEV_VM}" "test -s ${LOG} && mv ${LOG} ${LOG}.${NOW}"