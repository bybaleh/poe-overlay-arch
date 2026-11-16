"""PoE 1 clipboard parsing and official trade API integration (standard library only).

Stats are matched against live trade/data/stats IDs, never invented.
The app displays real listing *asking prices*, not item valuations.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://www.pathofexile.com"
USER_AGENT = "poe-overlay-arch/0.2.0 (+https://github.com/bybaleh/poe-overlay-arch)"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "poe-overlay-arch"
NUMBER = re.compile(r"(?<![A-Za-z#])([+-]?)(\d+(?:[.,]\d+)?)")
MOD_SUFFIX = re.compile(r"\s+\((implicit|crafted|enchant|fractured|scourge|rune|explicit)\)$", re.I)
PAREN_ROLL = re.compile(r"(?<=\d)\(\s*[-+]?\d+(?:[.,]\d+)?\s*(?:-\s*[-+]?\d+(?:[.,]\d+)?)?\)")
IGNORED = re.compile(
    r"^(?:Rarity|Item Class|Item Level|Level|Quality|Sockets|Requirements|"
    r"Armour|Evasion Rating|Energy Shield|Ward|Chance to Block|Block|"
    r"Physical Damage|Elemental Damage|Chaos Damage|Critical Strike Chance|"
    r"Attacks per Second|Weapon Range|Dex|Int|Str|Requires|Map Tier|"
    r"Area Level|Stack Size|Stored Experience|Experience|Tags|"
    r"Note|Unmet Requirements|Limited to|Unidentified|Corrupted|Mirrored|"
    r"Split|Synthesised Item|Fractured Item|Shaper Item|Elder Item|"
    r"Hunter Item|Warlord Item|Redeemer Item|Crusader Item)(?::|$)", re.I
)
ALLOWED_GROUPS = {"explicit", "implicit", "crafted", "enchant", "fractured", "scourge", "rune"}


class TradeError(Exception):
    pass


@dataclass
class Modifier:
    text: str
    group: str = "explicit"
    values: list[float] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


@dataclass
class Item:
    name: str
    base: str
    rarity: str
    item_class: str = ""
    ilvl: int | None = None
    quality: int | None = None
    links: int | None = None
    corrupted: bool = False
    modifiers: list[Modifier] = field(default_factory=list)
    raw: str = ""


def clean_num(s: str) -> float:
    return float(s.replace(",", "."))


def clean_mod_text(s: str) -> tuple[str, str]:
    s = s.strip()
    match = MOD_SUFFIX.search(s)
    group = match.group(1).lower() if match else "explicit"
    if match:
        s = s[:match.start()]
    s = PAREN_ROLL.sub("", s)
    s = re.sub(r"^\{\s*(?:Prefix|Suffix|Implicit|Explicit)\s+Modifier[^}]*\}\s*", "", s, flags=re.I)
    return s.strip(), group


def canonical(text: str) -> str:
    text, _ = clean_mod_text(text)
    text = text.replace("−", "-").replace("–", "-").replace("’", "'")
    # Preserve + and - around numeric values, as the trade stat text does.
    text = NUMBER.sub(lambda m: m.group(1) + "#", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_item(raw: str) -> Item | None:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.strip() for line in raw.splitlines()]
    rarity_i = next((i for i, line in enumerate(lines) if line.startswith("Rarity: ")), None)
    if rarity_i is None:
        return None
    rarity = lines[rarity_i].split(":", 1)[1].strip()
    header = []
    for line in lines[rarity_i + 1:]:
        if line.startswith("--------"):
            break
        if line:
            header.append(line)
    if not header:
        return None
    name = header[0]
    base = header[1] if rarity.lower() in ("rare", "unique", "magic") and len(header) > 1 else name
    # The trade site expects the base type rather than a randomly generated rare name.
    item = Item(name=name, base=base, rarity=rarity, raw=raw)
    match = re.search(r"^Item Class:\s*(.+)$", raw, re.M)
    if match: item.item_class = match.group(1)
    match = re.search(r"^Item Level:\s*(\d+)", raw, re.M)
    if match: item.ilvl = int(match.group(1))
    match = re.search(r"^Quality:\s*\+?(\d+)%", raw, re.M)
    if match: item.quality = int(match.group(1))
    match = re.search(r"^Sockets:\s*(.+)$", raw, re.M)
    if match:
        item.links = max((len(re.findall(r"[RGBWAD]", part)) for part in match.group(1).split(" ")), default=0)
    item.corrupted = bool(re.search(r"^Corrupted$", raw, re.M))
    in_body = False
    for line in lines[rarity_i + 1:]:
        if line.startswith("--------"):
            in_body = True
            continue
        if not in_body or not line or IGNORED.match(line):
            continue
        if line.startswith(("{", "}")) or line.startswith("«"):
            continue
        if line in ("Implicit Modifiers", "Explicit Modifiers", "Enchant Modifiers"):
            continue
        cleaned, group = clean_mod_text(line)
        if not cleaned or not re.search(r"[a-zA-Z]", cleaned):
            continue
        if cleaned.lower().startswith(("right click", "place into", "shift click", "this item")):
            continue
        nums = [clean_num(m.group(1) + m.group(2)) for m in NUMBER.finditer(cleaned)]
        # Static (no-number) mods such as "Cannot be Frozen" also match trade IDs.
        item.modifiers.append(Modifier(cleaned, group, nums))
    return item


def _stat_index(data: dict) -> dict[tuple[str, str], list[dict]]:
    index: dict[tuple[str, str], list[dict]] = {}
    for section in data.get("result", []):
        group = section.get("id", "")
        if group not in ALLOWED_GROUPS:
            continue
        for entry in section.get("entries", []):
            stat_id = entry.get("id", "")
            template = entry.get("text", "")
            if not stat_id.startswith(group + ".") or not template:
                continue
            # Options need their own choice UI; do not produce a misleading filter.
            if entry.get("option"):
                continue
            key = (group, canonical(template))
            index.setdefault(key, []).append({
                "id": stat_id, "text": template, "group": group,
            })
    return index


def attach_stats(item: Item, trade_stats: dict) -> None:
    index = _stat_index(trade_stats)
    for mod in item.modifiers:
        mod.candidates = index.get((mod.group, canonical(mod.text)), []).copy()
        # Some game exports omit "(explicit)"; an explicit match still works.
        # Never silently replace an implicit/crafted modifier with an explicit stat.


def relaxed_min(values: list[float]) -> str:
    if len(values) != 1:
        return ""
    number = values[0]
    if number < 0:
        # Negative rolls have different "better" directions. Avoid guessing.
        return ""
    if number == 0:
        return "0"
    n = math.floor(number * 0.85 * 100) / 100
    return str(int(n)) if n.is_integer() else str(n)


def make_query(item: Item, selected: list[tuple[str, str]], *,
               include_base: bool = True, include_ilvl: bool = False,
               ilvl_min: int | None = None, links_min: int | None = None,
               online: bool = True) -> dict:
    """selected: (verified stat id, user supplied minimum as text) pairs."""
    query: dict = {"status": {"option": "online" if online else "any"},
                   "stats": [{"type": "and", "filters": []}], "filters": {}}
    if include_base:
        query["type"] = item.base
        if item.rarity.lower() == "unique":
            query["name"] = item.name
    if item.rarity.lower() == "unique":
        query["filters"]["type_filters"] = {"filters": {"rarity": {"option": "unique"}}}
    elif item.rarity.lower() in ("rare", "magic", "normal"):
        query["filters"]["type_filters"] = {"filters": {"rarity": {"option": "nonunique"}}}
    if include_ilvl and ilvl_min is not None:
        query["filters"].setdefault("misc_filters", {"filters": {}})["filters"]["ilvl"] = {"min": ilvl_min}
    if links_min is not None and links_min > 0:
        query["filters"]["socket_filters"] = {"filters": {"links": {"min": links_min}}}
    valid_ids = {candidate["id"] for mod in item.modifiers for candidate in mod.candidates}
    for stat_id, min_text in selected:
        if stat_id not in valid_ids:
            raise ValueError(f"Unknown/unverified stat id: {stat_id}")
        filt: dict = {"id": stat_id}
        if min_text.strip():
            try:
                value = float(min_text.strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"Invalid minimum for {stat_id}: {min_text}") from exc
            if not math.isfinite(value):
                raise ValueError("Values must be finite.")
            filt["value"] = {"min": value}
        query["stats"][0]["filters"].append(filt)
    if not query["stats"][0]["filters"]:
        query["stats"] = []
    return {"query": query, "sort": {"price": "asc"}}


class TradeClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.block_until = 0.0

    def _request(self, path: str, payload: dict | None = None, *, minimum_delay: float = 1.5) -> dict:
        with self.lock:
            now = time.monotonic()
            if now < self.block_until:
                raise TradeError(f"Trade API rate limit: retry in {math.ceil(self.block_until - now)} sec.")
            delay = max(0.0, minimum_delay - (now - self.last_request))
            if delay:
                time.sleep(delay)
            self.last_request = time.monotonic()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        }, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=18) as response:
                data = response.read(8_000_000)
                parsed = json.loads(data)
        except urllib.error.HTTPError as e:
            retry = e.headers.get("Retry-After", "")
            if e.code == 429:
                try: seconds = min(max(int(retry), 30), 900)
                except ValueError: seconds = 60
                with self.lock:
                    self.block_until = time.monotonic() + seconds
                raise TradeError(f"Trade API HTTP 429: rate limited. Retry after {seconds}s.") from e
            if e.code in (401, 403):
                raise TradeError(f"Trade API HTTP {e.code}: request rejected (login or access restriction).") from e
            raise TradeError(f"Trade API HTTP {e.code}: {e.reason}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise TradeError(f"Trade API connection/response error: {e}") from e
        if not isinstance(parsed, dict):
            raise TradeError("Trade API returned an unexpected response.")
        if parsed.get("error"):
            err = parsed["error"]
            raise TradeError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
        return parsed

    def stats(self, *, refresh: bool = False) -> dict:
        cache_file = CACHE / "trade-stats-poe1.json"
        if cache_file.exists() and not refresh:
            try:
                if time.time() - cache_file.stat().st_mtime < 24 * 3600:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    if data.get("result"): return data
            except (OSError, json.JSONDecodeError):
                pass
        try:
            data = self._request("/api/trade/data/stats")
            if not isinstance(data.get("result"), list):
                raise TradeError("Trade stats list is missing.")
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(cache_file)
            return data
        except TradeError:
            # Use stale cache to continue working when offline.
            if cache_file.exists():
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    if data.get("result"): return data
                except (OSError, json.JSONDecodeError):
                    pass
            raise

    def search(self, league: str, query: dict) -> dict:
        if not league.strip() or "/" in league:
            raise TradeError("Specify a valid league name.")
        path = "/api/trade/search/" + urllib.parse.quote(league.strip(), safe="")
        data = self._request(path, query, minimum_delay=4)
        if not data.get("id") or not isinstance(data.get("result"), list):
            raise TradeError("Trade API did not return a search ID and results.")
        return data

    def fetch(self, ids: list[str], query_id: str) -> list[dict]:
        if not ids:
            return []
        # Trade API supports up to ten items per fetch.
        encoded = ",".join(urllib.parse.quote(i, safe="") for i in ids[:10])
        path = "/api/trade/fetch/" + encoded + "?query=" + urllib.parse.quote(query_id, safe="")
        data = self._request(path, minimum_delay=2)
        return [row for row in data.get("result", []) if isinstance(row, dict)]

    @staticmethod
    def search_url(league: str, query_id: str) -> str:
        return (BASE_URL + "/trade/search/" +
                urllib.parse.quote(league.strip(), safe="") + "/" +
                urllib.parse.quote(query_id, safe=""))


def listed_prices(entries: list[dict]) -> list[dict]:
    rows = []
    for entry in entries:
        listing = entry.get("listing") or {}
        price = listing.get("price") or {}
        if not isinstance(price.get("amount"), (int, float)) or not price.get("currency"):
            continue
        account = listing.get("account") or {}
        rows.append({
            "amount": price["amount"], "currency": str(price["currency"]),
            "seller": str(account.get("name", "")),
            "indexed": str(listing.get("indexed", "")),
        })
    return rows
