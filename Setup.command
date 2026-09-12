#!/bin/zsh
set -e
cd -- "${0:A:h}"
sh ./install.sh
echo 'Use the printed PATH command, then run task-relay telegram run and open the pairing link.'
read -r '?Press Enter to close.'
