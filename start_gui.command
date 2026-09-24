#!/usr/bin/env bash
# Double-click in Finder to start TRIBE Response Lab (macOS).
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Python environment missing. Run:  bash setup.sh"
  read -n 1 -s -r -p "Press any key to close"; exit 1
fi
exec .venv/bin/python gui.py "$@"
