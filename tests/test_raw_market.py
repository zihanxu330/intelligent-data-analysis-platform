# -*- coding: utf-8 -*-
"""Offline tests for data_engine.raw_market (no network)."""
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from data_engine.raw_market import (
    RawBar, RawStore, ValidationError, build_bar, outstanding_share_asof, parse_amount_jsonp, pick_target,
    parse_klc_bytes, FetchResult, fetch_universe,
)


class RawMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "raw.db")
        self.store = RawStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def bar(self, **kw):
        base = dict(symbol="600000", date="2026-10-20", open=10.0, high=10.5, low=9.8,
                    close=10.2, volume=1_000_000, amount=10_200_000.0, turnover=0.01,
                    source="sina_klc_kl_js", source_status="ok",
                    retrieved_at="2026-10-21T12:00:00",
                    raw_response_path="raw/600000_klc.js",
                    raw_response_sha256="a" * 64, price_basis="raw",
                    unit_status="unit_unverified")
        base.update(kw)
        return RawBar(**base)

    def test_valid_bar(self):
        b = self.bar(); b.validate()
        self.assertEqual(self.store.append(b), "inserted")

    def test_reject_qfq(self):
        with self.assertRaises(ValidationError):
            self.bar(price_basis="qfq").validate()

    def test_reject_bad_ohlc(self):
        with self.assertRaises(ValidationError):
            self.bar(high=9.0).validate()

    def test_duplicate_idempotent(self):
        b = self.bar()
        self.assertEqual(self.store.append(b), "inserted")
        self.assertEqual(self.store.append(b), "duplicate_noop")
        self.assertEqual(self.store.count()["raw_daily"], 1)

    def test_conflict_kept(self):
        b = self.bar()
        self.store.append(b)
        c = replace(b, close=10.3)
        self.assertEqual(self.store.append(c), "conflict_kept_existing")
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT close FROM raw_daily").fetchone()[0], 10.2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM raw_daily_conflicts").fetchone()[0], 1)

    def test_status_distinct(self):
        self.store.set_status("000001", "2026-10-20", "suspended", source_status="no_data")
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT status FROM daily_status").fetchone()[0], "suspended")

    def test_fetch_failure_isolated(self):
        class FakeSource:
            def fetch(self, sym, target, raw_dir, with_amount=True):
                if sym == "600000":
                    b = RawBar(symbol=sym, date=target, open=10, high=11, low=9, close=10,
                               volume=1000, amount=10000, turnover=0.01, source="fake",
                               source_status="ok", retrieved_at="2026-10-21T12:00:00",
                               raw_response_path="x", raw_response_sha256="a" * 64)
                    return FetchResult(sym, target, "ok", b, "x", "a" * 64, "", "", 200)
                if sym == "000001":
                    return FetchResult(sym, target, "no_data", None, "x", "b" * 64, "", "", 200, last_date="2026-10-20")
                return FetchResult(sym, target, "request_failed", None, "", "", "", "", "ERR", error="offline")
        results = fetch_universe(["600000", "000001", "000002"], "2026-10-21", self.tmp.name, self.store, source=FakeSource())
        self.assertEqual(len(results), 3)
        self.assertEqual(self.store.count()["raw_daily"], 1)
        with closing(sqlite3.connect(self.db)) as con:
            st = dict(con.execute("SELECT symbol,status FROM daily_status").fetchall())
        self.assertEqual(st["600000"], "ok")
        self.assertEqual(st["000001"], "no_data")
        self.assertEqual(st["000002"], "source_error")

    def test_amount_jsonp_null(self):
        self.assertIsNone(parse_amount_jsonp("var KKE=(null);"))

    def test_amount_jsonp_list(self):
        got = parse_amount_jsonp('var KKE=([{"date":"2026-10-20","amount":12.5}]);')
        self.assertEqual(got[0]["amount"], 12.5)

    def test_klc_decoder_dependency_contract(self):
        """The pinned mini-racer distribution must expose the module/API used by AkShare."""
        import py_mini_racer
        from akshare.stock.stock_zh_a_sina import hk_js_decode

        self.assertTrue(callable(py_mini_racer.MiniRacer))
        self.assertTrue(hk_js_decode)

    @unittest.skipUnless(os.environ.get("RUN_KLC_RUNTIME_SMOKE") == "1",
                         "engine runtime smoke is enabled in CI; local sandbox may block Windows socketpair")
    def test_klc_runtime_smoke(self):
        code = "import py_mini_racer; e=py_mini_racer.MiniRacer(); assert e.eval('1 + 1') == 2"
        try:
            result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                    text=True, timeout=20, check=False)
        except subprocess.TimeoutExpired as exc:
            self.fail(f"mini-racer runtime did not initialize within 20 seconds: {exc}")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_parse_klc_uses_decoder_without_network(self):
        engine = MagicMock()
        engine.call.return_value = [{"date": "2026-10-21"}]
        with patch("py_mini_racer.MiniRacer", return_value=engine):
            rows = parse_klc_bytes(b'var klc="fixture-payload";')
        self.assertEqual(rows, [{"date": "2026-10-21"}])
        engine.eval.assert_called_once()
        engine.call.assert_called_once_with("d", "fixture-payload")

    def test_pick_target_missing(self):
        hit, last = pick_target([{"date": "2026-09-30T00:00:00.000Z"}], "2026-10-20")
        self.assertIsNone(hit)
        self.assertEqual(last, "2026-09-30")

    def test_outstanding_share_asof(self):
        rows = [{"date": "2026-01-01", "amount": 10.0}, {"date": "2026-11-01", "amount": 20.0}]
        self.assertEqual(outstanding_share_asof(rows, "2026-10-20"), 100000.0)
        self.assertIsNone(outstanding_share_asof([], "2026-10-20"))

    def test_build_bar_no_amount(self):
        b = build_bar("000001", "2026-10-20",
                      {"open": 1, "high": 1.1, "low": 0.9, "close": 1.0,
                       "volume": 100, "amount": 1000},
                      source="sina_klc_kl_js", source_status="ok",
                      retrieved_at="2026-10-21T12:00:00", raw_path="x", raw_sha="b" * 64)
        self.assertIsNone(b.turnover)
        self.assertEqual(b.unit_status, "unit_unverified")


if __name__ == "__main__":
    unittest.main()
