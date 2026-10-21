# -*- coding: utf-8 -*-
"""Offline tests for the paper settlement calculator (no network, no DB)."""
import unittest

from tools.paper_settlement import buy_fill, settle_book


class SettlementTests(unittest.TestCase):
    def test_normal_buy(self):
        f = buy_fill("600000", "top20_r20", 100, 10.0, 1_000_000)
        self.assertEqual(f.status, "filled")
        self.assertAlmostEqual(f.fill_price, 10.01)
        self.assertAlmostEqual(f.gross, 1001.0)
        self.assertAlmostEqual(f.commission, 5.0)
        self.assertAlmostEqual(f.transfer, 0.01001)

    def test_min_commission(self):
        f = buy_fill("600000", "top20_r20", 100, 1.0, 1_000_000)
        self.assertEqual(f.commission, 5.0)

    def test_insufficient_cash(self):
        f = buy_fill("600000", "top20_r20", 1000, 10.0, 100.0)
        self.assertEqual(f.status, "insufficient_cash")

    def test_zero_shares_blocked(self):
        f = buy_fill("600000", "top50_r20", 0, 10.0, 1_000_000)
        self.assertEqual(f.status, "blocked_lot_min")

    def test_no_bar(self):
        f = buy_fill("600000", "top20_r20", 100, None, 1_000_000)
        self.assertEqual(f.status, "no_target_bar")

    def test_books_independent_and_nav(self):
        orders = [
            {"rule": "a", "symbol": "600000", "target_shares": 100, "status": "pending_no_fill"},
            {"rule": "b", "symbol": "600000", "target_shares": 200, "status": "pending_no_fill"},
        ]
        prices = {"600000": (10.0, 10.5)}
        a = settle_book([orders[0]], prices, 1_000_000)
        b = settle_book([orders[1]], prices, 1_000_000)
        self.assertEqual(a["counts"].get("filled"), 1)
        self.assertEqual(b["counts"].get("filled"), 1)
        self.assertNotEqual(a["cash"], b["cash"])
        self.assertAlmostEqual(a["nav"], a["cash"] + 100 * 10.5)
        self.assertAlmostEqual(b["nav"], b["cash"] + 200 * 10.5)


if __name__ == "__main__":
    unittest.main()
