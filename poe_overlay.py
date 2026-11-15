#!/usr/bin/env python3
"""PoE Overlay for Arch Linux (X11): independent proof-of-concept, not an Overwolf runtime."""
import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from urllib.parse import quote

APP = 'poe-overlay-arch'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/{os.getuid()}'))
SOCK = RUNTIME / f'{APP}-{os.getuid()}.sock'


def run(*args, timeout=4):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def parse_item(raw):
    """Parse a copied PoE 1 item tooltip; do not treat it as authoritative price data."""
    raw = raw.replace('\r\n', '\n').strip()
    lines = [x.strip() for x in raw.splitlines()]
    def field(pattern):
        m = re.search(pattern, raw, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else None
    rarity = field(r'^Rarity:\s*(.+)$')
    if not rarity:
        return None
    nonempty = [x for x in lines if x and x != '--------']
    try:
        idx = next(i for i, line in enumerate(nonempty) if line.lower().startswith('rarity:'))
        following = nonempty[idx+1:idx+3]
    except StopIteration:
        following = []
    name = following[0] if following else 'Unknown item'
    base = following[1] if len(following) > 1 else name
    if rarity.lower() in ('normal','magic','currency','gem','divination card'):
        base = name
    return {
        'rarity': rarity, 'name': name, 'base': base,
        'item_level': field(r'^Item Level:\s*(\d+)'),
        'quality': field(r'^Quality:\s*\+?(\d+)%'),
        'links': field(r'^Sockets:\s*(.+)$'),
        'corrupted': bool(re.search(r'^Corrupted$', raw, re.MULTILINE)),
        'raw': raw,
    }


class Overlay:
    def __init__(self, root):
        self.root = root
        self.root.title('PoE Overlay — Arch Linux / X11')
        self.root.geometry('560x520+110+90')
        self.root.configure(bg='#141a23')
        self.root.attributes('-topmost', True)
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        self.msgq = []
        self.lock = threading.Lock()
        self.setup_ui()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        if SOCK.exists():
            try:
                test = socket.socket(socket.AF_UNIX)
                test.settimeout(.5)
                test.connect(str(SOCK))
                test.close()
                raise RuntimeError('Another instance is already running')
            except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
                SOCK.unlink(missing_ok=True)
        self.server.bind(str(SOCK))
        self.owns_socket = True
        SOCK.chmod(0o600)
        self.server.listen(5)
        threading.Thread(target=self.listen, daemon=True).start()
        self.root.after(100, self.pump)

    def setup_ui(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except tk.TclError: pass
        style.configure('TButton', padding=7)
        tk.Label(self.root, text='PoE OVERLAY', bg='#141a23', fg='#ebbf73',
                 font=('Sans', 18, 'bold')).pack(pady=(16, 2))
        tk.Label(self.root, text='Linux X11 · Item inspector / trade helper',
                 bg='#141a23', fg='#9cabbc').pack(pady=(0, 12))
        top = tk.Frame(self.root, bg='#141a23')
        top.pack(fill='x', padx=18)
        tk.Label(top, text='League:', bg='#141a23', fg='white').pack(side='left')
        self.league = tk.StringVar(value='Standard')
        ttk.Entry(top, textvariable=self.league, width=22).pack(side='left', padx=8)
        ttk.Button(top, text='Paste / inspect', command=self.inspect).pack(side='left', padx=5)
        self.result = tk.Text(self.root, height=12, bg='#1c2633', fg='#e7eef7',
                              insertbackground='white', relief='flat', wrap='word',
                              padx=12, pady=12)
        self.result.pack(fill='both', expand=True, padx=18, pady=12)
        self.result.insert('end', 'Hover an item in Path of Exile and press Ctrl+C, then click Paste / inspect.\n\n'
                                   'Or configure xbindkeys and use Alt+D to copy and inspect automatically.\n'
                                   'Alt+Q: inspect clipboard; Alt+M: show/hide overlay.\n\n'
                                   'PoE 1 tooltip format is supported. Price estimation is not implemented.')
        self.result.config(state='disabled')
        row = tk.Frame(self.root, bg='#141a23')
        row.pack(fill='x', padx=18, pady=(0, 12))
        ttk.Button(row, text='Official trade', command=self.trade).pack(side='left', padx=4)
        ttk.Button(row, text='poe.ninja', command=lambda: webbrowser.open('https://poe.ninja/')).pack(side='left', padx=4)
        ttk.Button(row, text='Copy item name', command=self.copy_name).pack(side='left', padx=4)
        ttk.Button(row, text='Hide', command=self.hide).pack(side='right', padx=4)
        self.item = None
        self.root.bind('<Escape>', lambda _: self.hide())

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes('-topmost', True)

    def hide(self):
        self.root.withdraw()

    def display(self, msg):
        self.result.config(state='normal')
        self.result.delete('1.0', 'end')
        self.result.insert('1.0', msg)
        self.result.config(state='disabled')
        self.show()

    def inspect(self):
        try:
            clip = run('xclip', '-selection', 'clipboard', '-o')
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.display(f'Cannot read clipboard: {exc}')
            return
        if clip.returncode:
            self.display('Clipboard is unavailable. Install xclip and use X11.')
            return
        self.item = parse_item(clip.stdout)
        if not self.item:
            self.display('No valid PoE item found in clipboard.\n\nCopy a hovered item with Ctrl+C in Path of Exile (PoE 1).')
            return
        v = self.item
        self.display('\n'.join([
            f"{v['name']}", f"Base: {v['base']}", f"Rarity: {v['rarity']}",
            f"Item level: {v['item_level'] or '—'}", f"Quality: {v['quality'] or '—'}",
            f"Sockets: {v['links'] or '—'}", f"Corrupted: {'yes' if v['corrupted'] else 'no'}",
            '\nNote: this is an item inspector, not a price valuation.',
            '\n--- Raw clipboard ---\n', v['raw'][:10000]
        ]))

    def copy_name(self):
        if self.item:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.item['base'])
            self.root.update()

    def trade(self):
        league = quote(self.league.get().strip() or 'Standard', safe='')
        webbrowser.open(f'https://www.pathofexile.com/trade/search/{league}')

    def act(self, action):
        if action == 'toggle':
            if self.root.state() == 'withdrawn': self.show()
            else: self.hide()
        elif action == 'inspect': self.inspect()
        elif action == 'evaluate':
            try: run('xdotool', 'key', '--clearmodifiers', 'ctrl+c', timeout=2)
            except (OSError, subprocess.TimeoutExpired): pass
            self.root.after(180, self.inspect)

    def listen(self):
        while True:
            try:
                client, _ = self.server.accept()
                with client:
                    data = client.recv(64).decode('ascii', 'ignore').strip()
                    if data in ('inspect', 'evaluate', 'toggle'):
                        with self.lock: self.msgq.append(data)
            except OSError:
                break

    def pump(self):
        with self.lock:
            actions, self.msgq = self.msgq, []
        for action in actions: self.act(action)
        self.root.after(100, self.pump)


def send(action):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(SOCK))
        sock.sendall(action.encode('ascii'))
    except OSError:
        print('Overlay not running. Launch: poe-overlay-arch', file=sys.stderr)
        return 1
    finally: sock.close()
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('inspect', 'evaluate', 'toggle'))
    args = parser.parse_args()
    if args.action: return send(args.action)
    if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        print('Warning: Wayland session detected. This build targets native X11.', file=sys.stderr)
    if not os.environ.get('DISPLAY'):
        print('DISPLAY not set. X11 required.', file=sys.stderr)
        return 2
    root = tk.Tk()
    app = None
    try:
        app = Overlay(root)
        root.mainloop()
    finally:
        if app is not None and getattr(app, 'owns_socket', False):
            app.server.close()
            SOCK.unlink(missing_ok=True)
    return 0


if __name__ == '__main__': sys.exit(main())
