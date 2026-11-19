#!/usr/bin/env bash
# Install a Linux build of DarsPack for the current user (no sudo needed).
#
#   installer/install-linux.sh            install dist/DarsPack
#   installer/install-linux.sh --uninstall
#
# Installs to ~/.local/share/DarsPack, puts a launcher in
# ~/.local/share/applications/darspack.desktop, and copies the icon
# next to the app. Build first with installer/build-linux.sh.
# Uninstall is just: installer/install-linux.sh --uninstall
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/DarsPack"
DESKTOP_DIR="$HOME/.local/share/applications"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$INSTALL_DIR" "$DESKTOP_DIR/darspack.desktop"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "DarsPack uninstalled. Your library was not touched."
    echo "(Library lives in ~/Documents/DarsPackLibrary or"
    echo " ~/.local/share/DarsPackLibrary — delete it yourself if you"
    echo " really want it gone.)"
    exit 0
fi

if [ ! -x dist/DarsPack/DarsPack ]; then
    echo "dist/DarsPack/DarsPack not found — build first:"
    echo "  installer/build-linux.sh"
    exit 1
fi

mkdir -p "$DESKTOP_DIR"
rm -rf "$INSTALL_DIR"
cp -r dist/DarsPack "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/DarsPack" "$INSTALL_DIR/DarsPackMcp"
cp src/darspack/assets/icon/darspack-128.png "$INSTALL_DIR/darspack.png"
sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" installer/darspack.desktop \
    > "$DESKTOP_DIR/darspack.desktop"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "Installed to $INSTALL_DIR"
echo "Launch DarsPack from your app menu, or run: $INSTALL_DIR/DarsPack"
