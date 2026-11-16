#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -eq 0 ]]; then echo 'Run as normal user, not root.' >&2; exit 1; fi
for bin in python3 xclip xdotool xbindkeys; do command -v "$bin" >/dev/null || { echo "Missing $bin. Install: sudo pacman -S python tk xclip xdotool xbindkeys" >&2; exit 1; }; done
BASE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.config"
install -m 755 "$BASE/poe_overlay.py" "$HOME/.local/bin/poe-overlay-arch"
install -m 644 "$BASE/trade_engine.py" "$HOME/.local/bin/trade_engine.py"
install -m 644 "$BASE/poe-overlay-arch.desktop" "$HOME/.local/share/applications/poe-overlay-arch.desktop"
if [[ -f "$HOME/.xbindkeysrc" ]]; then echo 'Existing ~/.xbindkeysrc unchanged. Add entries from xbindkeys.conf manually.'; else cp "$BASE/xbindkeys.conf" "$HOME/.xbindkeysrc"; fi
echo 'Installed. Run: ~/.local/bin/poe-overlay-arch'
echo 'Start hotkeys in X11: xbindkeys'
