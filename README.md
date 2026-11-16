# PoE Overlay — Arch Linux / Manjaro (X11)

An independent Linux/X11 Path of Exile 1 trading helper. Inspired by the Kyusung4698/PoE-Overlay and Awakened PoE Trade workflows. This is not a complete port of Overwolf. **Beta: live game and API verification required.**

## Price-check workflow

1. In Path of Exile, hover an item and press Ctrl+C (or press Alt+D to copy and inspect).
2. Press Alt+Q to inspect the current clipboard. The overlay parses rarity, item base, item level, sockets/links and modifier rolls.
3. The client downloads official modifier definitions from https://www.pathofexile.com/api/trade/data/stats and maps readable item mods to valid trade stat IDs. The metadata is cached for 24 hours.
4. Each verified mod appears with a checkbox and editable minimum. Positive numeric rolls start near 85% of the item's roll. Clear Min to search only for the mod's existence.
5. Select only relevant modifiers; optionally filter by base, item level and links. Set the exact league name.
6. Click **Search trade prices**. The client sends a JSON POST to /api/trade/search/{league}, fetches up to 10 listings and shows seller asking prices.
7. Click **Open trade results** to view the official trade page with your filters already configured. The website URL uses a search ID that points to server-side query filters; the URL itself does not contain raw stat values.

Unknown, unsupported and ambiguous stat matches are displayed but disabled. Hybrid, conditional, localized or option-based mods can be unsupported. Asking prices are not completed trades or reliable item valuations.

## Install or update

```bash
sudo pacman -S --needed python tk xclip xdotool xbindkeys git
git clone https://github.com/bybaleh/poe-overlay-arch.git
cd poe-overlay-arch
chmod +x install.sh
./install.sh
~/.local/bin/poe-overlay-arch
```

If the repository is already cloned:

```bash
cd ~/poe-overlay-arch
git pull --ff-only
./install.sh
~/.local/bin/poe-overlay-arch
```

Stop the previous running instance before starting the new version. Run xbindkeys in a second terminal for global hotkeys. Existing ~/.xbindkeysrc is left untouched; append entries from xbindkeys.conf if necessary.

Hotkeys: **Alt+D** copy/inspect hovered item, **Alt+Q** inspect clipboard, **Alt+M** toggle window.

**Environment:** Arch/Manjaro X11, PoE 1 in windowed/borderless windowed mode. Do not use sudo. Exclusive fullscreen and Wayland are unsupported.

## Test without network

```bash
python -m unittest discover -s tests -v
python -m py_compile poe_overlay.py trade_engine.py
```

Tests use synthetic trade metadata. The program needs live validation in a real Path of Exile session.

## Limits and privacy

- Official API may return 403/429, or require a different league or authentication. The app displays errors and observes Retry-After on HTTP 429.
- The app does not request or store your POESESSID, passwords, credentials or cookies.
- Uses Python standard library and external xclip, xdotool, xbindkeys tools; no Electron/Overwolf.
- Does not read game memory, send chat messages, automate trading or capture replay video.
- Not a complete port of the original replay, map inspection or trade chat modules.
- No PoE 2-specific support.

Original project: https://github.com/Kyusung4698/PoE-Overlay . This project is unofficial and not endorsed by Grinding Gear Games or Overwolf.