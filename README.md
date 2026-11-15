# PoE Overlay — Arch Linux X11 prototype

An **independent Linux prototype**, inspired by [Kyusung4698/PoE-Overlay](https://github.com/Kyusung4698/PoE-Overlay), not a complete port of the original Overwolf Angular application. No original source code is bundled; the upstream repo is not modified. The original's Overwolf-based modules cannot be used directly on Linux. This is an early, untested-on-Arch implementation.

## Included

- Always-on-top, hideable desktop window (Tk/X11), no Electron/Mesa/Overwolf requirement.
- Read Path of Exile 1 item tooltips from X11 clipboard, show rarity/base/item level/quality/sockets/corruption.
- Global **Alt+D** for `Ctrl+C` + inspect, **Alt+Q** inspect existing clipboard, **Alt+M** toggle visibility, using xbindkeys.
- Open official trade page for selected league; open poe.ninja; copy parsed base name.
- Local Unix socket commands with 0600 permissions (no network listening).

## NOT included

Price API lookup, searchable trade listings, automatic whispers/trading, bulk exchange, incoming trade management, real-time map modifier intelligence, combat events, video replay, game memory integration, Wayland and Vulkan fullscreen overlays. PoE 2 clipboard syntax may differ. This application has **not** been tested with a live PoE session.

## Install on Arch / Manjaro

```bash
sudo pacman -S --needed python tk xclip xdotool xbindkeys
git clone https://github.com/bybaleh/poe-overlay-arch.git
cd poe-overlay-arch
chmod +x install.sh
./install.sh
~/.local/bin/poe-overlay-arch
```

In another terminal (same X11 session): `xbindkeys`. Optional autostart of `xbindkeys` via your desktop environment. If you already have `~/.xbindkeysrc`, append `xbindkeys.conf` and reload with `xbindkeys -p`.

**Path of Exile** should run in *windowed* or *borderless windowed* mode on an X11 desktop where the compositor permits always-on-top windows. True exclusive fullscreen can obscure the overlay. `xbindkeys` hotkeys may conflict with game bindings. Keep the application running as a regular user, never with sudo.

Check display server: `echo "$XDG_SESSION_TYPE"`. If `wayland`, log into an X11 session. `DISPLAY` must be set. Under Wine/Proton, clipboard integration must work: first manually hover an item, press Ctrl+C, and test `xclip -selection clipboard -o`.

## Run without installing

```bash
python3 poe_overlay.py
```

## Development notes

The original Overwolf `GameInfo`, `GameControl`, `Hotkeys`, `Clipboard`, `VideoCaptureSettings`, and `FileSystem` APIs need platform adapters, not package-name replacements. For a full Linux port, preserve the Angular UI and implement an alternative to Overwolf API, then port each module and test against current PoE/client behavior. The prototype intentionally does not impersonate Overwolf, request game memory access, or scrape authenticated trade APIs.
