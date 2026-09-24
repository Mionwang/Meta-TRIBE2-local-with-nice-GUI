#!/usr/bin/env bash
# macOS (Apple Silicon) setup for TRIBE Response Lab. Windows users: run setup.ps1 instead.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
TRIBE_COMMIT="af58661791a351a448a489042a28f6c37e1c14b7"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "setup.sh is for macOS. On Windows run: powershell -ExecutionPolicy Bypass -File .\\setup.ps1"; exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This needs an Apple Silicon Mac (M1 or newer). Intel Macs have no PyTorch 2.6 builds."; exit 1
fi
command -v git >/dev/null || { echo "Git is needed. Run: xcode-select --install"; exit 1; }

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in python3.12 /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [[ -z "$PY" ]]; then
  echo "Python 3.12 is needed. Install it with:  brew install python@3.12"
  echo "(or from python.org), then rerun:  bash setup.sh"
  echo "Or point to one explicitly:  PYTHON=/path/to/python3.12 bash setup.sh"
  exit 1
fi

mkdir -p INPUT OUTPUT cache vendor
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv
fi
VPY="$ROOT/.venv/bin/python"

if [[ ! -d vendor/tribev2 ]]; then
  git clone https://github.com/facebookresearch/tribev2.git vendor/tribev2
  git -C vendor/tribev2 checkout "$TRIBE_COMMIT"
fi

"$VPY" -m pip install --upgrade pip
# Standard PyPI wheels for Apple Silicon include Metal (MPS) support.
"$VPY" -m pip install torch==2.6.0 torchvision==0.21.0
"$VPY" -m pip install -e vendor/tribev2 -r requirements-local.txt

# Make the launchers double-clickable (web uploads and zips can drop the executable bit)
chmod +x start_gui.command analyze.command diagnostics.command setup.sh 2>/dev/null || true
xattr -dr com.apple.quarantine . 2>/dev/null || true

"$VPY" diagnostics.py
echo
echo "Setup complete. Double-click start_gui.command (or run ./start_gui.command) to open the app."
