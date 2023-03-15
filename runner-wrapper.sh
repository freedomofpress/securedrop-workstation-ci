#!/bin/bash

set -eox pipefail

# Remove any old log
qvm-run --pass-io sd-ssh 'rm -f /home/user/securedrop-workstation-test.log'

# Run the runner script, and send the output to a log file directly piped to the sd-ssh VM
bash /home/user/runner.sh | qvm-run --pass-io sd-ssh 'cat >> /home/user/securedrop-workstation-test.log'