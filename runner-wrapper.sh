#!/bin/bash

set -eo pipefail

NOW=$(date +%y%m%d%H%M%S)
LOG="/home/user/securedrop-workstation-test.log"
SECUREDROP_DEV_VM="sd-ssh"

# Run the runner script, and send the output to a log file directly piped to the sd-ssh VM
/home/user/runner.py |& qvm-run --pass-io "${SECUREDROP_DEV_VM}" "cat > ${LOG}"

# Rename log so the next job doesn't clobber it
qvm-run --pass-io "${SECUREDROP_DEV_VM}" "mv ${LOG} ${LOG}.${NOW}"

# Upload it to the proxy droplet
qvm-run --pass-io "${SECUREDROP_DEV_VM}" "/home/user/bin/upload-report -f ${LOG}.${NOW}"