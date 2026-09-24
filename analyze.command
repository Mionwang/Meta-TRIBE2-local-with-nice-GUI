#!/usr/bin/env bash
# macOS command-line analysis. Usage: ./analyze.command [path/to/video.mp4] [--video-device mps|cpu]
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then echo "Python environment missing. Run:  bash setup.sh"; exit 1; fi
.venv/bin/python analyze.py "$@"
code=$?
if [[ $# -eq 0 ]]; then read -n 1 -s -r -p "Press any key to close"; fi
exit $code
