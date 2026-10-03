#!/usr/bin/env bash
# KillSwitch template (root-only, Master)
[ "$EUID" -ne 0 ] && { echo "root required"; exit 1; }
echo "killswitch: placeholder"
