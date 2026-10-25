#!/usr/bin/env bash
# Install Drive Browser for the current user: a command in ~/.local/bin and an
# app-launcher entry that points at this checkout. Run it again after moving the folder.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="$HOME/.local/bin"
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$bin_dir" "$apps_dir"
ln -sfn "$here/drive-browser" "$bin_dir/drive-browser"
sed "s|^Exec=.*|Exec=$here/drive-browser|" "$here/drive-browser.desktop" > "$apps_dir/drive-browser.desktop"

echo "Installed:"
echo "  $bin_dir/drive-browser -> $here/drive-browser"
echo "  $apps_dir/drive-browser.desktop"
command -v proton-drive >/dev/null || echo "Note: proton-drive (the Proton Drive CLI) is not on PATH yet."
