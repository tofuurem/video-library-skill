#!/bin/bash
# Double-click in Finder: sorts everything in this folder into days and cameras.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "python3 not found. Install: xcode-select --install"
else
  "$PY" -I "../_tools/sort_inbox.py" "$@"
fi
echo
read -n 1 -s -r -p "Press any key to close this window"
echo
