#!/bin/bash

set -eo pipefail

NOW=$(date +%y%m%s%H%M%S)
LOG="/home/user/securedrop-workstation-test.log"
export SECUREDROP_DEV_VM=sd-ssh
export SECUREDROP_PROJECTS_DIR="/home/user/projects/"
export SECUREDROP_REPO_DIR="securedrop-workstation"
export SECUREDROP_DEV_DIR="${SECUREDROP_PROJECTS_DIR}${SECUREDROP_REPO_DIR}"

# Check to see if run-me file has been created ?
qvm-run --pass-io "${SECUREDROP_DEV_VM}" "stat ${SECUREDROP_DEV_DIR}/run-me"

# If it has, proceed with tests
if [ $? -eq 0 ]; then
    # Remove our run-me script - to let other CI jobs set it again when they get their turn?
    qvm-run --pass-io "${SECUREDROP_DEV_VM}" "rm -f ${SECUREDROP_DEV_DIR}/run-me"

    # Run the runner script, and send the output to a log file directly piped to the sd-ssh VM
    bash /home/user/runner.sh |& qvm-run --pass-io "${SECUREDROP_DEV_VM}" "cat > ${LOG}"

    # Rename log so the next job doesn't clobber it
    qvm-run --pass-io "${SECUREDROP_DEV_VM}" "mv ${LOG} ${LOG}.${NOW}"
fi