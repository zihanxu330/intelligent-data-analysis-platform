# -*- coding: utf-8 -*-
"""只读项目健康检查。

默认只检查、不联网、不写项目文件；SQLite 一律使用 mode=ro。

用法：
    python tools/project_healthcheck.py
    python tools/project_healthcheck.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import date
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORWARD_DB = Path("output/research_stage21_forward_market_20261020/forward_raw.db")
MODEL = Path("output/model_rank_h3p_full.joblib")
SYMBOLS = Path("output/symbols_full.txt")
INDUSTRY = Path("output/symbols_industry_full.csv")
MAIN_DB = Path("output/quant.db")
ENTRYPOINTS = [
    "main.py", "pipeline.py", "paper_trade.py", "predict_weekly_top20.py",
    "train_rank.py", "data_engine/database.py", "data_engine/raw_market.py",
]
STAGE_DIRS = [
    "output/research_stage37_eligible_pool_20261021",
    "output/research_stage38_execution_20261022",
    "output/research_stage39_execution_20261022",
]
DEPS = ["pandas", "numpy", "sklearn", "lightgbm", "joblib", "requests", "akshare", "py_mini_racer"]


@dataclass
class Check:
    name: str
    status: str  # ok, warning, blocked, unverified
    detail: str


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _file_check(root: Path, rel: str) -> Check:
    p = root / rel
    if not p.exists():
        return Check(rel, "blocked", "missing")
    if not p.is_file():
        return Check(rel, "blocked", "not a file")
    return Check(rel, "ok", f"{p.stat().st_size} bytes")


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def _db_check(root: Path, rel: str, table: str, expect_forward: bool = False) -> tuple[Check, dict[str, Any]]:
    p = root / rel
    info: dict[str, Any] = {"path": rel}
    if not p.exists():
        return Check(rel, "blocked", "missing"), info
    try:
        con = _ro(p)
    except Exception as exc:
        return Check(rel, "blocked", f"cannot open read-only: {exc}"), info
    try:
        info["sha256"] = _sha(p)
        info["mtime_ns"] = p.stat().st_mtime_ns
        if not _table_exists(con, table):
            return Check(rel, "blocked", f"missing table {table}"), info
        info["rows"] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if table == "daily_bars":
            try:
                info["max_date"] = con.execute("SELECT MAX(date) FROM daily_bars").fetchone()[0]
            except sqlite3.OperationalError as exc:
                return Check(rel, "blocked", f"date column unavailable: {exc}"), info
            info["duplicate_keys"] = con.execute(
                "SELECT COUNT(*) FROM (SELECT symbol,date,COUNT(*) c FROM daily_bars GROUP BY symbol,date HAVING c>1)"
            ).fetchone()[0]
        else:
            try:
                info["max_date"] = con.execute("SELECT MAX(date) FROM raw_daily").fetchone()[0]
            except sqlite3.OperationalError as exc:
                return Check(rel, "blocked", f"date column unavailable: {exc}"), info
            info["duplicate_keys"] = con.execute(
                "SELECT COUNT(*) FROM (SELECT symbol,date,COUNT(*) c FROM raw_daily GROUP BY symbol,date HAVING c>1)"
            ).fetchone()[0]
            if _table_exists(con, "daily_status"):
                info["status_rows"] = con.execute("SELECT COUNT(*) FROM daily_status").fetchone()[0]
                info["status_counts"] = dict(con.execute(
                    "SELECT status,COUNT(*) FROM daily_status GROUP BY status"
                ).fetchall())
            else:
                return Check(rel, "warning", "raw_daily present but daily_status missing"), info
        return Check(rel, "ok", f"table={table} rows={info.get('rows')}"), info
    finally:
        con.close()


def _symbol_checks(root: Path) -> list[Check]:
    out = []
    p = root / SYMBOLS
    if not p.exists():
        return [Check(str(SYMBOLS), "blocked", "missing")]
    syms = [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    bad = [s for s in syms if len(s) != 6 or not s.isdigit()]
    dup = len(syms) - len(set(syms))
    out.append(Check(str(SYMBOLS), "ok" if not bad and not dup else "warning",
                     f"count={len(syms)} bad={len(bad)} duplicates={dup}"))
    if bad:
        out[-1].detail += f"; first_bad={bad[:3]}"
    ip = root / INDUSTRY
    if not ip.exists():
        out.append(Check(str(INDUSTRY), "blocked", "missing"))
    else:
        out.append(Check(str(INDUSTRY), "ok", f"{ip.stat().st_size} bytes"))
    return out


def _freshness(main_info: dict[str, Any], fwd_info: dict[str, Any], as_of: date,
               expected: date | None) -> dict[str, Any]:
    main_latest = main_info.get("max_date")
    fwd_latest = fwd_info.get("max_date")
    if expected is None:
        return {
            "as_of": as_of.isoformat(), "expected_date": None, "status": "unknown",
            "main_status": "unknown", "forward_status": "unknown",
            "basis": "no expected_date supplied; trading calendar is not inferred",
            "allow_paper_execution": False,
            "paper_hint": "not allowed: expected date is not specified",
        }
    if expected > as_of:
        status = "not_yet_available"
        basis = "expected_date is after as_of; future data cannot be called missing/stale"
    elif main_latest is None or fwd_latest is None:
        status = "unknown"
        basis = "one or both market databases have no usable date"
    elif str(main_latest)[:10] == expected.isoformat() and str(fwd_latest)[:10] == expected.isoformat():
        status = "fresh"
        basis = "main and forward latest dates equal expected_date; trading-day calendar not independently verified"
    elif str(main_latest)[:10] < expected.isoformat() or str(fwd_latest)[:10] < expected.isoformat():
        status = "stale"
        basis = "at least one database latest date is before expected_date; trading-day calendar not independently verified"
    else:
        status = "fresh"
        basis = "latest dates are at or after expected_date"
    def side(latest):
        if latest is None:
            return "unknown"
        d = str(latest)[:10]
        if d == expected.isoformat():
            return "fresh"
        return "stale" if d < expected.isoformat() else "fresh"
    allow = status == "fresh"
    return {
        "as_of": as_of.isoformat(), "expected_date": expected.isoformat(), "status": status,
        "main_status": side(main_latest), "forward_status": side(fwd_latest),
        "basis": basis, "allow_paper_execution": allow,
        "paper_hint": ("data freshness gate passed; this is not an instruction to trade" if allow
                       else "not allowed: market data freshness gate failed"),
    }


def run(root: Path | None = None, as_of: date | None = None,
        expected_date: date | None = None) -> dict[str, Any]:
    root = (root or PROJECT_ROOT).resolve()
    as_of = as_of or date.today()
    checks: list[Check] = []
    py_ok = sys.version_info[:2] == (3, 11)
    checks.append(Check("python", "ok" if py_ok else "warning", sys.version.split()[0]))
    for dep in DEPS:
        found = importlib.util.find_spec(dep) is not None
        checks.append(Check(f"dep:{dep}", "ok" if found else "warning", "importable" if found else "not importable"))
    for rel in ENTRYPOINTS:
        checks.append(_file_check(root, rel))
    checks.append(_file_check(root, str(MODEL)))
    for rel in STAGE_DIRS:
        p = root / rel
        checks.append(Check(rel, "ok" if p.is_dir() else "warning", "present" if p.is_dir() else "missing"))
    checks.extend(_symbol_checks(root))
    db_check, db_info = _db_check(root, str(MAIN_DB), "daily_bars")
    checks.append(db_check)
    fwd_check, fwd_info = _db_check(root, str(FORWARD_DB), "raw_daily", expect_forward=True)
    checks.append(fwd_check)
    if any(c.status == "blocked" for c in checks):
        structure = "blocked"
    elif any(c.status == "warning" for c in checks):
        structure = "warning"
    else:
        structure = "ok"
    freshness = _freshness(db_info, fwd_info, as_of, expected_date)
    if structure != "ok":
        freshness["allow_paper_execution"] = False
        freshness["paper_hint"] = "not allowed: structure_status is not ok"
    report = {
        "root": str(root), "python": sys.version.split()[0],
        "structure_status": structure, "status": structure,
        "market_data_status": freshness["status"], "market_data": freshness,
        "checks": [asdict(c) for c in checks],
        "databases": {"main": db_info, "forward": fwd_info},
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only project health check; never writes project files.")
    ap.add_argument("--root", default=None, help="project root; default is repository root")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON")
    ap.add_argument("--as-of", type=_date_arg, default=None, help="evaluation date YYYY-MM-DD; default today")
    ap.add_argument("--expected-date", type=_date_arg, default=None, help="expected market date YYYY-MM-DD")
    args = ap.parse_args(argv)
    report = run(Path(args.root) if args.root else None, as_of=args.as_of, expected_date=args.expected_date)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"root: {report['root']}")
        print(f"python: {report['python']}")
        print(f"structure_status: {report['structure_status']}")
        print(f"market_data_status: {report['market_data_status']}")
        print(f"market_data: {report['market_data']}")
        for c in report["checks"]:
            print(f"[{c['status']:9}] {c['name']}: {c['detail']}")
        print(f"main db: {report['databases'].get('main')}")
        print(f"forward db: {report['databases'].get('forward')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
