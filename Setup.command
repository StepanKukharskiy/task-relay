#!/bin/zsh
cd -- "${0:A:h}" || exit 1
print 'Starting Task Relay installation from this folder…'
if sh ./install.sh; then
  print '\nThe setup page has closed. Your installation and saved settings remain here.'
  relay_result=0
else
  relay_result=$?
  print '\nInstallation or setup stopped. The error above explains what to fix; open Setup.command again to retry.'
fi
read -r '?Press Return to close this window.'
exit "$relay_result"
