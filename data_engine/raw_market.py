# -*- coding: utf-8 -*-
"""可复用的 raw 行情抓取、解析、校验与独立存储。

设计原则：
- 只接受未复权 raw 日线；
- 原始响应必须落盘并记录 SHA-256；
- 解析失败、无目标行、请求失败分开；
- amount/turnover 不猜测、不补零；
- 独立 SQLite 只追加，冲突不覆盖；
- 不接触生产 ``output/quant.db``。

用法：
    python -m data_engine.raw_market init --db output/forward_raw.db
    python -m data_engine.raw_market parse --klc fixture.js --symbol 600000 --date 2026-10-20
    python -m data_engine.raw_market fetch --symbols 600000,000001 --date 2026-10-20 \
        --raw-dir output/raw --db output/forward_raw.db
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Iterable, Optional

import requests

TARGET_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SYMBOL_RE = re.compile(r"^\d{6}$")
ALLOWED_STATUS = {"ok", "suspended", "no_data", "source_error", "partial_date"}
ALLOWED_SOURCE_STATUS = {"ok", "no_data", "parse_failed", "request_failed", "http_error", "date_mismatch"}


@contextmanager
def _connect(path: str):
    con = sqlite3.connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


class RawMarketError(Exception):
    """Base error."""


class ValidationError(RawMarketError):
    """A raw bar failed validation."""


class ParseError(RawMarketError):
    """Source payload could not be decoded."""


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_symbol(symbol: str) -> str:
    s = str(symbol).strip().zfill(6)
    if not SYMBOL_RE.match(s):
        raise ValidationError(f"invalid symbol: {symbol!r}")
    return s


def normalize_date(date: str) -> str:
    d = str(date)[:10]
    if not TARGET_DATE_RE.match(d):
        raise ValidationError(f"invalid date: {date!r}")
    return d


def source_prefix(symbol: str) -> str:
    return "sh" if normalize_symbol(symbol).startswith(("6", "9")) else "sz"


def parse_amount_jsonp(text: str) -> Optional[list[dict[str, Any]]]:
    """Parse Sina amount JSONP. Returns None for ``(null)``, else list of records."""
    text = text or ""
    left, right = text.find("("), text.rfind(")")
    if left < 0 or right <= left:
        raise ParseError("amount jsonp has no parenthesized payload")
    payload = text[left:right + 1]
    try:
        value = json.loads(payload[1:-1].strip())
    except json.JSONDecodeError as exc:
        raise ParseError(f"amount jsonp json error: {exc}") from exc
    if value is None:
        return None
    if not isinstance(value, list):
        raise ParseError("amount jsonp payload is not a list")
    return value


def parse_klc_bytes(body: bytes) -> list[dict[str, Any]]:
    """Decode Sina KLC body with the frozen AkShare JS decoder.

    Kept lazy so importing this module does not require py_mini_racer unless KLC is parsed.
    """
    try:
        import py_mini_racer
        from akshare.stock.stock_zh_a_sina import hk_js_decode
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ParseError(f"KLC decoder unavailable: {exc}") from exc
    text = body.decode("utf-8", "replace")
    try:
        payload = text.split("=", 1)[1].split(";", 1)[0].replace('"', "")
        js = py_mini_racer.MiniRacer()
        js.eval(hk_js_decode)
        rows = js.call("d", payload)
    except Exception as exc:
        raise ParseError(f"KLC decode failed: {exc}") from exc
    if not isinstance(rows, list):
        raise ParseError("KLC decoder returned non-list")
    return rows


def outstanding_share_asof(amount_rows: Optional[list[dict[str, Any]]], target_date: str) -> Optional[float]:
    """Return outstanding share (shares, not 10k) as of target date.

    Sina amount JSONP is a history of share changes; selecting the latest row
    without filtering by date can leak a future share count into turnover.
    """
    if not amount_rows:
        return None
    target = normalize_date(target_date)
    usable = []
    for row in amount_rows:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", ""))[:10]
        raw = row.get("amount")
        if d and d <= target and raw is not None:
            try:
                usable.append((d, float(raw)))
            except (TypeError, ValueError):
                continue
    if not usable:
        return None
    _, shares_wan = max(usable, key=lambda x: x[0])
    return shares_wan * 10000.0 if shares_wan > 0 else None


def pick_target(rows: Iterable[dict[str, Any]], target_date: str) -> tuple[Optional[dict[str, Any]], str]:
    target_date = normalize_date(target_date)
    rows = list(rows or [])
    hits = [r for r in rows if str(r.get("date", ""))[:10] == target_date]
    if hits:
        return hits[0], target_date
    last = max((str(r.get("date", ""))[:10] for r in rows), default="")
    return None, last


@dataclass(frozen=True)
class RawBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float]
    turnover: Optional[float]
    source: str
    source_status: str
    retrieved_at: str
    raw_response_path: str
    raw_response_sha256: str
    price_basis: str = "raw"
    unit_status: str = "unit_unverified"

    def validate(self) -> None:
        sym = normalize_symbol(self.symbol)
        if sym != self.symbol:
            raise ValidationError("symbol must be 6-digit zero-padded")
        normalize_date(self.date)
        if self.price_basis != "raw":
            raise ValidationError("price_basis must be raw")
        if self.source_status not in ALLOWED_SOURCE_STATUS:
            raise ValidationError(f"invalid source_status: {self.source_status}")
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value != value or value < 0:
                raise ValidationError(f"{name} must be a non-negative number")
        if self.high < max(self.open, self.close, self.low):
            raise ValidationError("high < max(open, close, low)")
        if self.low > min(self.open, self.close, self.high):
            raise ValidationError("low > min(open, close, high)")
        for name in ("amount", "turnover"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or value != value or value < 0):
                raise ValidationError(f"{name} must be null or non-negative")
        if not self.source:
            raise ValidationError("source is required")
        if len(self.raw_response_sha256) != 64:
            raise ValidationError("raw_response_sha256 must be 64 hex chars")
        int(self.raw_response_sha256, 16)

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def build_bar(symbol: str, target_date: str, row: dict[str, Any], *, source: str,
              source_status: str, retrieved_at: str, raw_path: str, raw_sha: str,
              amount_rows: Optional[list[dict[str, Any]]] = None,
              unit_status: str = "unit_unverified") -> RawBar:
    """Convert one KLC record to a validated RawBar.

    Turnover is derived only when outstanding_share is present and positive.
    """
    sym = normalize_symbol(symbol)
    date = normalize_date(target_date)
    volume = float(row["volume"])
    amount = float(row["amount"]) if row.get("amount") is not None else None
    turnover = None
    shares = outstanding_share_asof(amount_rows, date)
    if shares and volume > 0:
        turnover = volume / shares
    bar = RawBar(symbol=sym, date=date, open=float(row["open"]), high=float(row["high"]),
                 low=float(row["low"]), close=float(row["close"]), volume=volume,
                 amount=amount, turnover=turnover, source=source, source_status=source_status,
                 retrieved_at=retrieved_at, raw_response_path=raw_path,
                 raw_response_sha256=raw_sha, price_basis="raw", unit_status=unit_status)
    bar.validate()
    return bar


@dataclass
class FetchResult:
    symbol: str
    target_date: str
    status: str
    bar: Optional[RawBar]
    klc_path: str
    klc_sha256: str
    amount_path: str
    amount_sha256: str
    http_status: Any
    last_date: str = ""
    error: str = ""


class SinaRawSource:
    """Thin, auditable Sina raw fetcher. Never touches credentials."""

    HIST_URL = "https://finance.sina.com.cn/realstock/company/{}/hisdata_klc2/klc_kl.js"
    AMOUNT_URL = "https://stock.finance.sina.com.cn/stock/api/jsonp.php/var%20KKE_ShareAmount_{}=/StockService.getAmountBySymbol?_=20&symbol={}"

    def __init__(self, timeout: int = 15, session: Optional[requests.Session] = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 Chrome/120.0 Safari/537.36",
        }

    def _get(self, url: str) -> requests.Response:
        return self.session.get(url, headers=self.headers, timeout=self.timeout)

    def fetch(self, symbol: str, target_date: str, raw_dir: str,
              with_amount: bool = True) -> FetchResult:
        sym = normalize_symbol(symbol)
        target = normalize_date(target_date)
        os.makedirs(raw_dir, exist_ok=True)
        ss = source_prefix(sym) + sym
        stamp = datetime.now().isoformat(timespec="seconds")
        kp = os.path.join(raw_dir, f"{sym}_klc.js")
        ap = os.path.join(raw_dir, f"{sym}_amount.jsonp")

        try:
            r = self._get(self.HIST_URL.format(ss))
        except Exception as exc:
            return FetchResult(sym, target, "request_failed", None, "", "", "", "", "ERR", error=str(exc)[:160])
        if r.status_code != 200:
            return FetchResult(sym, target, "http_error", None, "", "", "", "", r.status_code,
                               error=f"HTTP {r.status_code}")
        open(kp, "wb").write(r.content)
        klc_sha = sha256_bytes(r.content)
        try:
            rows = parse_klc_bytes(r.content)
        except ParseError as exc:
            return FetchResult(sym, target, "parse_failed", None, kp, klc_sha, "", "", 200, error=str(exc)[:160])
        hit, last = pick_target(rows, target)
        if hit is None:
            return FetchResult(sym, target, "no_data", None, kp, klc_sha, "", "", 200, last_date=last)

        amount_rows = None
        amount_sha = ""
        if with_amount:
            try:
                ra = self._get(self.AMOUNT_URL.format(ss, ss))
                if ra.status_code == 200:
                    open(ap, "wb").write(ra.content)
                    amount_sha = sha256_bytes(ra.content)
                    amount_rows = parse_amount_jsonp(ra.text)
            except Exception:
                amount_rows = None
        try:
            bar = build_bar(sym, target, hit, source="sina_klc_kl_js", source_status="ok",
                            retrieved_at=stamp, raw_path=kp, raw_sha=klc_sha,
                            amount_rows=amount_rows,
                            unit_status="unit_unverified" if not amount_rows else "amount_derived_turnover")
        except ValidationError as exc:
            return FetchResult(sym, target, "parse_failed", None, kp, klc_sha, ap if os.path.exists(ap) else "",
                               amount_sha, 200, error=str(exc)[:160])
        return FetchResult(sym, target, "ok", bar, kp, klc_sha, ap if os.path.exists(ap) else "",
                           amount_sha, 200)


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_daily (
  symbol TEXT NOT NULL CHECK(length(symbol)=6),
  date TEXT NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  volume REAL NOT NULL, amount REAL, turnover REAL,
  source TEXT NOT NULL, source_status TEXT NOT NULL,
  retrieved_at TEXT NOT NULL, raw_response_path TEXT NOT NULL,
  raw_response_sha256 TEXT NOT NULL CHECK(length(raw_response_sha256)=64),
  price_basis TEXT NOT NULL CHECK(price_basis='raw'),
  unit_status TEXT NOT NULL, ingested_at TEXT NOT NULL,
  PRIMARY KEY(symbol,date)
);
CREATE TABLE IF NOT EXISTS raw_daily_conflicts (
  symbol TEXT NOT NULL, date TEXT NOT NULL,
  existing_json TEXT NOT NULL, incoming_json TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  PRIMARY KEY(symbol,date,detected_at)
);
CREATE TABLE IF NOT EXISTS daily_status (
  symbol TEXT NOT NULL, date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','suspended','no_data','source_error','partial_date')),
  source TEXT, source_status TEXT, price_basis TEXT, unit_status TEXT,
  evidence_path TEXT, evidence_sha256 TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY(symbol,date)
);
"""


class RawStore:
    """Append-only raw store; conflicts are recorded, never silently overwritten."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with _connect(path) as con:
            con.executescript(SCHEMA)

    def append(self, bar: RawBar) -> str:
        bar.validate()
        with _connect(self.path) as con:
            old = con.execute(
                "SELECT symbol,date,open,high,low,close,volume,amount,turnover,source,source_status,"
                "retrieved_at,raw_response_path,raw_response_sha256,price_basis,unit_status "
                "FROM raw_daily WHERE symbol=? AND date=?", (bar.symbol, bar.date)).fetchone()
            incoming = (bar.symbol, bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume,
                        bar.amount, bar.turnover, bar.source, bar.source_status, bar.retrieved_at,
                        bar.raw_response_path, bar.raw_response_sha256, bar.price_basis, bar.unit_status)
            if old:
                if tuple(old) == incoming:
                    return "duplicate_noop"
                con.execute("INSERT OR REPLACE INTO raw_daily_conflicts VALUES(?,?,?,?,?)",
                            (bar.symbol, bar.date, json.dumps(old, ensure_ascii=False),
                             json.dumps(incoming, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
                return "conflict_kept_existing"
            con.execute("INSERT INTO raw_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*incoming, datetime.now().isoformat(timespec="seconds")))
            return "inserted"

    def set_status(self, symbol: str, date: str, status: str, source: str = "sina_klc_kl_js",
                   source_status: str = "", price_basis: str = "raw", unit_status: str = "unit_unverified",
                   evidence_path: str = "", evidence_sha256: str = "") -> None:
        if status not in ALLOWED_STATUS:
            raise ValidationError(f"invalid status: {status}")
        with _connect(self.path) as con:
            con.execute("INSERT OR REPLACE INTO daily_status VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (normalize_symbol(symbol), normalize_date(date), status, source, source_status,
                         price_basis, unit_status, evidence_path, evidence_sha256,
                         datetime.now().isoformat(timespec="seconds")))

    def count(self) -> dict[str, int]:
        with _connect(self.path) as con:
            return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("raw_daily", "raw_daily_conflicts", "daily_status")}


def fetch_universe(symbols: Iterable[str], target_date: str, raw_dir: str, store: RawStore,
                   with_amount: bool = True, source: Optional[SinaRawSource] = None) -> list[FetchResult]:
    """Fetch a list sequentially, persisting bars/statuses. No concurrency by design."""
    source = source or SinaRawSource()
    out = []
    for sym in symbols:
        r = source.fetch(sym, target_date, raw_dir, with_amount=with_amount)
        if r.bar is not None:
            store.append(r.bar)
            store.set_status(sym, target_date, "ok", source_status="ok", unit_status=r.bar.unit_status,
                             evidence_path=r.klc_path, evidence_sha256=r.klc_sha256)
        elif r.status == "no_data":
            store.set_status(sym, target_date, "no_data", source_status="no_data",
                             evidence_path=r.klc_path, evidence_sha256=r.klc_sha256)
        else:
            store.set_status(sym, target_date, "source_error", source_status=r.status,
                             evidence_path=r.klc_path, evidence_sha256=r.klc_sha256)
        out.append(r)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Raw A-share daily fetch/clean/store")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("init")
    q.add_argument("--db", required=True)

    q = sub.add_parser("parse")
    q.add_argument("--klc", required=True)
    q.add_argument("--amount")
    q.add_argument("--symbol", required=True)
    q.add_argument("--date", required=True)

    q = sub.add_parser("fetch")
    q.add_argument("--symbols", required=True, help="comma list or file")
    q.add_argument("--date", required=True)
    q.add_argument("--raw-dir", required=True)
    q.add_argument("--db", required=True)
    q.add_argument("--no-amount", action="store_true")

    a = p.parse_args(argv)
    if a.cmd == "init":
        s = RawStore(a.db); print(json.dumps(s.count(), ensure_ascii=False)); return 0
    if a.cmd == "parse":
        rows = parse_klc_bytes(open(a.klc, "rb").read())
        hit, last = pick_target(rows, a.date)
        if hit is None:
            print(json.dumps({"status": "no_data", "last_date": last}, ensure_ascii=False)); return 0
        amount_rows = parse_amount_jsonp(open(a.amount, encoding="utf-8").read()) if a.amount else None
        bar = build_bar(a.symbol, a.date, hit, source="sina_klc_kl_js", source_status="ok",
                        retrieved_at=datetime.now().isoformat(timespec="seconds"),
                        raw_path=a.klc, raw_sha=sha256_file(a.klc), amount_rows=amount_rows)
        print(json.dumps(bar.as_record(), ensure_ascii=False, indent=2)); return 0
    if a.cmd == "fetch":
        if os.path.isfile(a.symbols):
            syms = [x.strip() for x in open(a.symbols, encoding="utf-8") if x.strip()]
        else:
            syms = [x.strip() for x in a.symbols.split(",") if x.strip()]
        s = RawStore(a.db)
        results = fetch_universe(syms, a.date, a.raw_dir, s, with_amount=not a.no_amount)
        for r in results:
            print(json.dumps({"symbol": r.symbol, "status": r.status, "last_date": r.last_date,
                              "error": r.error}, ensure_ascii=False))
        print(json.dumps(s.count(), ensure_ascii=False)); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
