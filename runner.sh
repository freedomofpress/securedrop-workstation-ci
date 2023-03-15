#!/bin/bash

set -eox pipefail

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
  
  builtin cd "${HOME}"

  # Remove our working dir on dom0 - really this should be as part of teardown,
  # but if something goes wrong during teardown, we want to ensure we can start
  # again
  sudo rm -rf "${SECUREDROP_REPO_DIR}"

  # Copy the codebase from our VM to dom0
  qvm-run --pass-io "${SECUREDROP_DEV_VM}" "tar -c -C ${SECUREDROP_PROJECTS_DIR} ${SECUREDROP_REPO_DIR}" | tar xvf -

  # Now build
  builtin cd "${HOME}/${SECUREDROP_REPO_DIR}"

  make clone
  make dev
  make test

  # Teardown: uninstall everything!

  # For some reason, when sdw-admin.py --uninstall stopped/restarted(/destroyed/recreated?)
  # sys-usb, I got a PCI error, so I'm manually destroying and recreating
  # it myself and attaching the PCI device.. seemed to help...
  qvm-shutdown --wait sys-usb
  qvm-remove --force sys-usb
  sudo qubesctl state.sls qvm.sys-usb
  USB_CONTROLLER=$(qvm-pci | grep -i "USB controller" | awk {'print $1'})
  qvm-pci detach sys-usb "${USB_CONTROLLER}"
  qvm-pci attach --persistent -o no-strict-reset=True sys-usb "${USB_CONTROLLER}"

  # Now leverage our uninstall script to remove everything
  sudo python3 scripts/sdw-admin.py --uninstall --force

  # There is still some cruft left here as mentioned in the output of the above
  # command, so remove that too
  sudo rm -rf /usr/share/securedrop /usr/share/securedrop-workstation-dom0-config
fi