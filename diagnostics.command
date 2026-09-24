#!/usr/bin/env bash
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then echo "Python environment missing. Run:  bash setup.sh"; else .venv/bin/python diagnostics.py; fi
read -n 1 -s -r -p "Press any key to close"
