# -*- coding: utf-8 -*-
"""Offline tests for tools/project_healthcheck.py (no network, no production DB)."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.project_healthcheck import main, run


def make_root(tmp: Path, *, complete=True, daily_table=True, forward_table=True,
              symbols=("600000", "000001"), dup_keys=False):
    for rel in ["main.py", "pipeline.py", "paper_trade.py", "predict_weekly_top20.py", "train_rank.py",
                "data_engine/database.py", "data_engine/raw_market.py"]:
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text("# test\n", encoding="utf-8")
    (tmp / "output").mkdir(exist_ok=True)
    (tmp / "output/model_rank_h3p_full.joblib").write_bytes(b"test")
    (tmp / "output/symbols_full.txt").write_text("\n".join(symbols) + "\n", encoding="utf-8")
    (tmp / "output/symbols_industry_full.csv").write_text("code,name,industry\n" + "\n".join(
        f"{s},Name,Industry" for s in symbols) + "\n", encoding="utf-8")
    for d in ["research_stage37_eligible_pool_20261021", "research_stage38_execution_20261022",
              "research_stage39_execution_20261022"]:
        (tmp / "output" / d).mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp / "output/quant.db")
    if daily_table:
        pk = "" if dup_keys else ",primary key(symbol,date)"
        con.execute(f"create table daily_bars(symbol text,date text,open real,close real{pk})")
        for idx, s in enumerate(dict.fromkeys(symbols)):
            con.execute("insert into daily_bars values(?,?,?,?)", (s, f"2026-10-{20 + idx:02d}", 1, 1))
        if dup_keys:
            con.execute("insert into daily_bars values(?,?,?,?)", (symbols[0], "2026-10-20", 2, 2))
    con.commit(); con.close()
    (tmp / "output/research_stage21_forward_market_20261020").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp / "output/research_stage21_forward_market_20261020/forward_raw.db")
    if forward_table:
        con.execute("create table raw_daily(symbol text,date text,primary key(symbol,date))")
        con.execute("create table daily_status(symbol text,date text,status text,primary key(symbol,date))")
        con.execute("insert into raw_daily values('600000','2026-10-21')")
        con.execute("insert into daily_status values('600000','2026-10-21','ok')")
    con.commit(); con.close()
    return tmp


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_okish(self):
        make_root(self.root)
        r = run(self.root)
        self.assertIn(r["status"], ("ok", "warning"))
        self.assertEqual(r["databases"]["main"]["rows"], 2)
        self.assertEqual(r["databases"]["forward"]["rows"], 1)

    def test_missing_file_blocked(self):
        make_root(self.root)
        (self.root / "pipeline.py").unlink()
        r = run(self.root)
        self.assertTrue(any(c["status"] == "blocked" and c["name"] == "pipeline.py" for c in r["checks"]))

    def test_forward_missing_table_blocked(self):
        make_root(self.root)
        os.remove(self.root / "output/research_stage21_forward_market_20261020/forward_raw.db")
        r = run(self.root)
        self.assertTrue(any(c["status"] == "blocked" and "forward_raw.db" in c["name"] for c in r["checks"]))

    def test_missing_table_blocked(self):
        make_root(self.root, daily_table=False)
        r = run(self.root)
        self.assertTrue(any(c["status"] == "blocked" and "daily_bars" in c["detail"] for c in r["checks"]))

    def test_duplicate_key_warning(self):
        make_root(self.root, dup_keys=True)
        r = run(self.root)
        self.assertEqual(r["databases"]["main"]["duplicate_keys"], 1)

    def test_duplicate_symbol_warning(self):
        make_root(self.root, symbols=("600000", "600000"))
        r = run(self.root)
        self.assertTrue(any(c["status"] == "warning" and "duplicates=1" in c["detail"] for c in r["checks"]))

    def test_freshness_equal(self):
        make_root(self.root)
        # This fixture represents the supported, fully installed environment.
        # Keep this test independent from the developer machine's packages.
        with patch("tools.project_healthcheck.sys.version_info", (3, 11, 9)), \
             patch("tools.project_healthcheck.importlib.util.find_spec", return_value=True):
            r = run(self.root, as_of=__import__("datetime").date(2026, 10, 21), expected_date=__import__("datetime").date(2026, 10, 21))
        self.assertEqual(r["structure_status"], "ok")
        self.assertEqual(r["market_data_status"], "fresh")
        self.assertTrue(r["market_data"]["allow_paper_execution"])

    def test_fresh_data_does_not_override_an_environment_warning(self):
        make_root(self.root)
        with patch("tools.project_healthcheck.sys.version_info", (3, 12, 0)), \
             patch("tools.project_healthcheck.importlib.util.find_spec", return_value=True):
            r = run(self.root, as_of=__import__("datetime").date(2026, 10, 21), expected_date=__import__("datetime").date(2026, 10, 21))
        self.assertEqual(r["market_data_status"], "fresh")
        self.assertEqual(r["structure_status"], "warning")
        self.assertFalse(r["market_data"]["allow_paper_execution"])

    def test_freshness_stale(self):
        make_root(self.root)
        r = run(self.root, as_of=__import__("datetime").date(2026, 10, 23), expected_date=__import__("datetime").date(2026, 10, 22))
        self.assertEqual(r["market_data_status"], "stale")
        self.assertFalse(r["market_data"]["allow_paper_execution"])

    def test_freshness_future(self):
        make_root(self.root)
        r = run(self.root, as_of=__import__("datetime").date(2026, 10, 21), expected_date=__import__("datetime").date(2026, 10, 22))
        self.assertEqual(r["market_data_status"], "not_yet_available")

    def test_freshness_unknown_without_target(self):
        make_root(self.root)
        r = run(self.root, as_of=__import__("datetime").date(2026, 10, 21))
        self.assertEqual(r["market_data_status"], "unknown")
        self.assertFalse(r["market_data"]["allow_paper_execution"])

    def test_date_column_missing(self):
        make_root(self.root)
        db = self.root / "output/quant.db"
        con = sqlite3.connect(db); con.execute("drop table daily_bars"); con.execute("create table daily_bars(symbol text,close real)"); con.commit(); con.close()
        r = run(self.root, as_of=__import__("datetime").date(2026, 10, 21), expected_date=__import__("datetime").date(2026, 10, 21))
        self.assertEqual(r["structure_status"], "blocked")
        self.assertIn(r["market_data_status"], ("unknown", "not_yet_available"))

    def test_read_only_does_not_change_db(self):
        make_root(self.root)
        db = self.root / "output/quant.db"
        before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
        run(self.root)
        after = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
        self.assertEqual(before, after)

    def test_json_cli(self):
        make_root(self.root)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--root", str(self.root), "--json", "--as-of", "2026-10-21", "--expected-date", "2026-10-21"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["root"], str(self.root.resolve()))
        self.assertIn("checks", payload)


if __name__ == "__main__":
    unittest.main()
