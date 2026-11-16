#!/usr/bin/env python3
"""Arch/Manjaro X11 PoE 1 trade overlay with mod selection and live asking prices."""
from __future__ import annotations

import argparse
import os
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, messagebox

from trade_engine import (
    TradeClient, TradeError, parse_item, attach_stats, make_query,
    relaxed_min, listed_prices
)

APP = "poe-overlay-arch"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/{os.getuid()}"))
SOCK = RUNTIME / f"{APP}-{os.getuid()}.sock"


def run(*args, timeout=4):
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, check=False)


class Overlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PoE Overlay — trade price check · X11")
        self.root.geometry("850x740+100+70")
        self.root.minsize(620, 490)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.attributes("-topmost", True)
        self.item = None
        self.stat_rows = []
        self.trade = TradeClient()
        self.events = queue.Queue()
        self.busy = False
        self.result_url = None
        self.make_ui()
        RUNTIME.mkdir(parents=True, exist_ok=True)
        if SOCK.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.5)
                probe.connect(str(SOCK))
                raise RuntimeError("Another overlay instance is already running.")
            except (OSError, socket.timeout):
                SOCK.unlink(missing_ok=True)
            finally:
                probe.close()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(SOCK))
        SOCK.chmod(0o600)
        self.server.listen(5)
        threading.Thread(target=self.listen, daemon=True).start()
        self.root.after(100, self.poll)

    def make_ui(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("TButton", padding=6)
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="PoE Overlay · Trade search", font=("Sans", 16, "bold")).pack(anchor="w")
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=7)
        ttk.Label(bar, text="League").pack(side="left")
        self.league = tk.StringVar(value="Standard")
        ttk.Entry(bar, textvariable=self.league, width=20).pack(side="left", padx=6)
        ttk.Button(bar, text="Read clipboard (Alt+Q)", command=self.inspect).pack(side="left", padx=3)
        ttk.Button(bar, text="Copy from game (Alt+D)", command=self.evaluate).pack(side="left", padx=3)
        self.item_label = tk.StringVar(value="No item selected. Hover item in PoE, Ctrl+C, then Alt+Q.")
        ttk.Label(outer, textvariable=self.item_label, wraplength=770).pack(anchor="w", pady=(4, 8))
        config = ttk.Frame(outer)
        config.pack(fill="x", pady=(0, 8))
        self.include_base = tk.BooleanVar(value=True)
        self.include_ilvl = tk.BooleanVar(value=False)
        self.include_links = tk.BooleanVar(value=False)
        ttk.Checkbutton(config, text="Match base type", variable=self.include_base).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(config, text="Item level ≥ current", variable=self.include_ilvl).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(config, text="Links ≥ current", variable=self.include_links).pack(side="left")

        ttk.Label(outer, text="Mod filters — check relevant mods; edit min. Empty min = existence only.").pack(anchor="w")
        columns = ttk.Frame(outer)
        columns.pack(fill="x")
        ttk.Label(columns, text="Use", width=6).pack(side="left")
        ttk.Label(columns, text="Min", width=10).pack(side="left")
        ttk.Label(columns, text="Mod (matched official stat or a warning)").pack(side="left")
        scrollholder = ttk.Frame(outer)
        scrollholder.pack(fill="both", expand=True, pady=5)
        self.canvas = tk.Canvas(scrollholder, highlightthickness=0, height=250)
        sb = ttk.Scrollbar(scrollholder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.mod_frame = ttk.Frame(self.canvas)
        win = self.canvas.create_window((0, 0), window=self.mod_frame, anchor="nw")
        self.mod_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=6)
        self.search_button = ttk.Button(actions, text="Search trade prices", command=self.search)
        self.search_button.pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Open trade results", command=self.open_results).pack(side="left", padx=4)
        ttk.Button(actions, text="poe.ninja", command=lambda: webbrowser.open("https://poe.ninja/")).pack(side="left", padx=4)
        ttk.Button(actions, text="Hide (Alt+M)", command=self.hide).pack(side="right")
        self.status = tk.StringVar(value="Official trade stat metadata loads when an item is copied.")
        ttk.Label(outer, textvariable=self.status, wraplength=770).pack(anchor="w", pady=4)
        self.results = tk.Text(outer, height=8, wrap="word", state="disabled")
        self.results.pack(fill="both", expand=False, pady=(4, 0))
        self.root.bind("<Escape>", lambda _: self.hide())

    def status_text(self, value: str):
        self.status.set(value)

    def result_text(self, value: str):
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", value)
        self.results.configure(state="disabled")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def hide(self):
        self.root.withdraw()

    def evaluate(self):
        self.show()
        try:
            result = run("xdotool", "key", "--clearmodifiers", "ctrl+c", timeout=3)
            if result.returncode:
                self.status_text("Could not send Ctrl+C. Focus the PoE game window and copy the item manually.")
        except (OSError, subprocess.TimeoutExpired) as e:
            self.status_text(f"xdotool failed: {e}")
        self.root.after(350, self.inspect)

    def inspect(self):
        self.show()
        try:
            clipboard = run("xclip", "-selection", "clipboard", "-o")
        except (OSError, subprocess.TimeoutExpired) as e:
            self.status_text(f"Clipboard unavailable: {e}")
            return
        if clipboard.returncode:
            self.status_text("Cannot read clipboard. Install xclip and use X11.")
            return
        self.item = parse_item(clipboard.stdout)
        self.result_url = None
        self.stat_rows.clear()
        for child in self.mod_frame.winfo_children():
            child.destroy()
        if self.item is None:
            self.item_label.set("Clipboard is not a PoE 1 item. Copy hovered item with Ctrl+C.")
            self.status_text("No valid item text found.")
            return
        v = self.item
        self.item_label.set(f"{v.name} · {v.base} · {v.rarity} · ilvl {v.ilvl or '—'} · {len(v.modifiers)} possible mods")
        self.result_text("Stat matching is loading. Only verified stat IDs will be offered.")
        self.status_text("Loading PoE trade stat IDs…")
        self.run_async(lambda: self.trade.stats(), lambda stats: self.on_stats(stats, v))

    def on_stats(self, stats, item):
        if item is not self.item:
            return
        attach_stats(item, stats)
        self.render_mods()
        matched = sum(bool(m.candidates) for m in item.modifiers)
        self.status_text(f"Matched {matched}/{len(item.modifiers)} modifiers to official Trade API stats. "
                         "Unsupported/ambiguous rows are disabled. Adjust filters before searching.")
        self.result_text("Select mods and press Search trade prices. Asking prices are not guaranteed sale prices.")

    def render_mods(self):
        self.stat_rows.clear()
        for mod in self.item.modifiers:
            row = ttk.Frame(self.mod_frame)
            row.pack(fill="x", pady=2)
            selected = tk.BooleanVar(value=(len(mod.candidates) == 1))
            minimum = tk.StringVar(value=relaxed_min(mod.values))
            choices = mod.candidates
            if len(choices) == 1:
                ttk.Checkbutton(row, variable=selected).pack(side="left", padx=(8, 20))
                ttk.Entry(row, textvariable=minimum, width=9).pack(side="left", padx=(0, 10))
                ttk.Label(row, text=f"[{mod.group}] {mod.text}", wraplength=560).pack(side="left", anchor="w")
                self.stat_rows.append((selected, minimum, choices[0]["id"]))
            else:
                reason = "unmatched" if not choices else "ambiguous"
                ttk.Label(row, text="—", width=6).pack(side="left", padx=(8, 0))
                ttk.Label(row, text="—", width=10).pack(side="left")
                ttk.Label(row, text=f"[{reason}] [{mod.group}] {mod.text}",
                          foreground="#b67828", wraplength=560).pack(side="left", anchor="w")
        if not self.item.modifiers:
            ttk.Label(self.mod_frame, text="No candidate modifiers found in copied item text.").pack(anchor="w")

    def run_async(self, job, on_success):
        if self.busy:
            self.status_text("Request already in progress.")
            return
        self.busy = True
        self.search_button.configure(state="disabled")
        def background():
            try:
                data = job()
                self.events.put(("done", on_success, data))
            except Exception as e:
                self.events.put(("error", str(e)))
        threading.Thread(target=background, daemon=True).start()

    def search(self):
        if self.busy:
            return
        if self.item is None:
            self.status_text("Copy an item first.")
            return
        if not any(mod.candidates for mod in self.item.modifiers):
            self.status_text("No verified mods found. You may still search by base type.")
        selected = [(stat_id, minimum.get()) for check, minimum, stat_id in self.stat_rows if check.get()]
        if not selected and not self.include_base.get() and not self.include_links.get() and not self.include_ilvl.get():
            self.status_text("Select at least one actual filter; refusing a global trade search.")
            return
        try:
            payload = make_query(self.item, selected, include_base=self.include_base.get(),
                                 include_ilvl=self.include_ilvl.get(),
                                 ilvl_min=self.item.ilvl,
                                 links_min=self.item.links if self.include_links.get() else None)
            league = self.league.get().strip()
            if not league: raise ValueError("Enter a league name.")
        except (ValueError, TypeError) as e:
            self.status_text(f"Invalid filter: {e}")
            return
        self.result_url = None
        self.status_text("Searching official PoE trade listings (online sellers)…")
        self.result_text("Request in progress…")
        def job():
            search = self.trade.search(league, payload)
            entries = self.trade.fetch(search["result"][:10], search["id"])
            return league, search, entries
        self.run_async(job, self.on_search)

    def on_search(self, data):
        league, search, entries = data
        self.result_url = self.trade.search_url(league, search["id"])
        total = search.get("total", len(search.get("result", [])))
        prices = listed_prices(entries)
        lines = [
            f"Listings matched: {total} (showing asking prices from first {len(entries)} listings)",
            "Prices below are seller asking prices, not estimates or completed sales.",
            "",
        ]
        if not prices:
            lines.append("No priced listings among fetched results. Open trade results to inspect more.")
        for price in prices:
            lines.append(f"{price['amount']:g} {price['currency']} · {price['seller']} · {price['indexed']}")
        lines.append(f"\nTrade search: {self.result_url}")
        self.result_text("\n".join(lines))
        self.status_text("Search complete. Open trade results to see the selected filters and all listings.")

    def open_results(self):
        if self.result_url:
            webbrowser.open(self.result_url)
        else:
            self.status_text("Run a trade search first. The link is generated by official Trade API.")

    def listen(self):
        while True:
            try:
                client, _ = self.server.accept()
                with client:
                    action = client.recv(64).decode("ascii", "ignore").strip()
                    if action in ("inspect", "evaluate", "toggle"):
                        self.events.put(("action", action))
            except OSError:
                return

    def poll(self):
        while True:
            try: event = self.events.get_nowait()
            except queue.Empty: break
            if event[0] == "action":
                action = event[1]
                if action == "toggle":
                    self.hide() if self.root.state() != "withdrawn" else self.show()
                elif action == "evaluate": self.evaluate()
                elif action == "inspect": self.inspect()
            elif event[0] == "done":
                _, callback, data = event
                self.busy = False
                self.search_button.configure(state="normal")
                callback(data)
            elif event[0] == "error":
                self.busy = False
                self.search_button.configure(state="normal")
                self.status_text(f"Trade API error: {event[1]}")
                self.result_text("No price results retrieved. Check network access, selected league, "
                                 "mod filters and Trade API rate limits.")
        self.root.after(100, self.poll)


def send(action):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(2)
        client.connect(str(SOCK))
        client.sendall(action.encode("ascii"))
    except OSError:
        print("Overlay is not running. Start: poe-overlay-arch", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("inspect", "evaluate", "toggle"))
    args = parser.parse_args()
    if args.action:
        return send(args.action)
    if not os.environ.get("DISPLAY"):
        print("X11 DISPLAY missing.", file=sys.stderr)
        return 2
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        print("Warning: X11 environment expected (Wayland not supported).", file=sys.stderr)
    root = tk.Tk()
    app = None
    try:
        app = Overlay(root)
        root.mainloop()
    finally:
        if app is not None:
            app.server.close()
            SOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
