#!/usr/bin/env bash
# Build script — reproducible one-command Linux build (PyInstaller onedir).
# Usage: installer/build-linux.sh
# Output: dist/DarsPack/DarsPack  (+ dist/DarsPack/DarsPackMcp)
# Needs a venv with PyInstaller first:
#   python3 -m venv .venv-linux
#   .venv-linux/bin/pip install -r requirements-dev.txt
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv-linux/bin/pyinstaller ]; then
    PYINSTALLER=.venv-linux/bin/pyinstaller
elif [ -x .venv/bin/pyinstaller ]; then
    PYINSTALLER=.venv/bin/pyinstaller
else
    echo "PyInstaller not found. Create a venv first:"
    echo "  python3 -m venv .venv-linux"
    echo "  .venv-linux/bin/pip install -r requirements-dev.txt"
    exit 1
fi

"$PYINSTALLER" --noconfirm --clean installer/darspack-linux.spec
echo
echo "Build output: dist/DarsPack/DarsPack"
