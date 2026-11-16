"""Offline regression tests (no PoE API account or network required)."""
import unittest

from trade_engine import (
    parse_item, canonical, attach_stats, make_query, listed_prices, relaxed_min
)

ITEM = """Item Class: Rings
Rarity: Rare
Storm Gyre
Amethyst Ring
--------
Requirements:
Level: 62
--------
Item Level: 84
--------
+19% to Chaos Resistance (implicit)
--------
+38% to Fire Resistance
+42 to maximum Life
15% increased Rarity of Items found
--------
Corrupted
"""

STATS = {
    "result": [
        {"id": "implicit", "entries": [{"id": "implicit.stat_001", "text": "+#% to Chaos Resistance"}]},
        {"id": "explicit", "entries": [
            {"id": "explicit.stat_002", "text": "+#% to Fire Resistance"},
            {"id": "explicit.stat_003", "text": "+# to maximum Life"},
            {"id": "explicit.stat_004", "text": "#% increased Rarity of Items found"},
        ]},
    ]
}


class TradeEngineTests(unittest.TestCase):
    def test_parses_clipboard(self):
        item = parse_item(ITEM)
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Storm Gyre")
        self.assertEqual(item.base, "Amethyst Ring")
        self.assertEqual(item.ilvl, 84)
        self.assertEqual(len(item.modifiers), 4)
        self.assertEqual(item.modifiers[0].group, "implicit")
        self.assertEqual(item.modifiers[1].values, [38.0])
        self.assertTrue(item.corrupted)

    def test_stat_matching_and_api_payload(self):
        item = parse_item(ITEM)
        attach_stats(item, STATS)
        self.assertEqual([len(m.candidates) for m in item.modifiers], [1, 1, 1, 1])
        filters = [(item.modifiers[1].candidates[0]["id"], "30"),
                   (item.modifiers[2].candidates[0]["id"], "40")]
        query = make_query(item, filters, include_ilvl=True, ilvl_min=84)
        self.assertEqual(query["query"]["type"], "Amethyst Ring")
        self.assertEqual(query["query"]["stats"][0]["filters"], [
            {"id": "explicit.stat_002", "value": {"min": 30.0}},
            {"id": "explicit.stat_003", "value": {"min": 40.0}},
        ])
        self.assertEqual(query["query"]["filters"]["misc_filters"]["filters"]["ilvl"]["min"], 84)
        self.assertEqual(query["sort"]["price"], "asc")

    def test_rejects_fake_stat_ids(self):
        item = parse_item(ITEM)
        attach_stats(item, STATS)
        with self.assertRaises(ValueError):
            make_query(item, [("explicit.stat_not_real", "90")])

    def test_numbered_mods(self):
        self.assertEqual(canonical("Adds 12 to 39 Fire Damage"),
                         canonical("Adds # to # Fire Damage"))
        self.assertEqual(relaxed_min([42]), "35")
        self.assertEqual(relaxed_min([-12]), "")

    def test_price_listing(self):
        prices = listed_prices([{
            "listing": {"price": {"amount": 15, "currency": "chaos"},
                        "account": {"name": "Player1"}, "indexed": "now"}
        }, {"listing": {"account": {}}}])
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["amount"], 15)


if __name__ == "__main__":
    unittest.main()
