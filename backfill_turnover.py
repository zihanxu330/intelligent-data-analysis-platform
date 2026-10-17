# -*- coding: utf-8 -*-
"""Backfill daily_bars.amount and daily_bars.turnover for the configured stock pool.

Only UPDATEs rows already present in daily_bars. Price and volume columns are never written.
Run with the project's Python 3.11 interpreter:
    python backfill_turnover.py
"""
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJ, "output", "quant.db")
SYMBOLS_PATH = os.path.join(PROJ, "output", "symbols_300.txt")
LOG_PATH = os.path.join(PROJ, "output", "paper", "backfill_log.txt")
RETRIES = 2
PER_SYMBOL_SLEEP = 0.50


def setup_logger():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("backfill_turnover")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.info("=== backfill run started ===")
    return logger


def coverage(conn, pool):
    total = conn.execute(
        "SELECT COUNT(*), SUM(amount IS NOT NULL), SUM(turnover IS NOT NULL) FROM daily_bars"
    ).fetchone()
    placeholders = ",".join("?" for _ in pool)
    pool_row = conn.execute(
        f"SELECT COUNT(*), SUM(amount IS NOT NULL), SUM(turnover IS NOT NULL) "
        f"FROM daily_bars WHERE symbol IN ({placeholders})", pool
    ).fetchone()
    def pct(row, index):
        return 100.0 * (row[index] or 0) / row[0] if row[0] else 0.0
    return {
        "full_rows": total[0], "full_amount_pct": pct(total, 1),
        "full_turnover_pct": pct(total, 2),
        "pool_rows": pool_row[0], "pool_amount_pct": pct(pool_row, 1),
        "pool_turnover_pct": pct(pool_row, 2),
    }


def main():
    logger = setup_logger()
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH}")
    if not os.path.exists(SYMBOLS_PATH):
        raise SystemExit(f"Symbols file not found: {SYMBOLS_PATH}")
    symbols = list(dict.fromkeys(
        line.strip().zfill(6) for line in open(SYMBOLS_PATH, encoding="utf-8-sig") if line.strip()
    ))
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    before = coverage(conn, symbols)
    logger.info("coverage before: %s", before)
    ranges = {sym: (start, end) for sym, start, end in conn.execute(
        "SELECT symbol, MIN(date), MAX(date) FROM daily_bars "
        "WHERE symbol IN (%s) GROUP BY symbol" % ",".join("?" for _ in symbols), symbols
    ).fetchall()}
    missing_from_db = [s for s in symbols if s not in ranges]
    if missing_from_db:
        logger.warning("symbols not present in daily_bars: %s", ",".join(missing_from_db))

    import akshare as ak
    failed_downloads = []
    updated_rows_total = 0
    eastmoney_available = True
    for i, sym in enumerate(symbols, 1):
        date_range = ranges.get(sym)
        if not date_range:
            failed_downloads.append((sym, "no existing daily_bars rows"))
            logger.error("[%d/%d] %s failed: no existing database rows", i, len(symbols), sym)
            time.sleep(PER_SYMBOL_SLEEP)
            continue
        start_date = pd.Timestamp(date_range[0]).strftime("%Y%m%d")
        end_date = pd.Timestamp(date_range[1]).strftime("%Y%m%d")
        hist = None
        source = "Eastmoney stock_zh_a_hist"
        error = None
        for attempt in range(RETRIES + 1) if eastmoney_available else []:
            try:
                hist = ak.stock_zh_a_hist(
                    symbol=sym, period="daily", start_date=start_date,
                    end_date=end_date, adjust=""
                )
                if hist is None or hist.empty:
                    raise ValueError("AkShare returned no daily rows")
                required = {"日期", "成交额", "换手率"}
                if not required.issubset(hist.columns):
                    raise ValueError(f"unexpected AkShare columns: {list(hist.columns)}")
                error = None
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%d/%d] %s attempt %d/%d failed: %s",
                               i, len(symbols), sym, attempt + 1, RETRIES + 1, error)
                if attempt < RETRIES:
                    time.sleep(0.8 * (attempt + 1))
        if not eastmoney_available and error is None:
            error = "Eastmoney disabled after repeated proxy disconnects"
        if error is not None:
            # A repeated proxy disconnect is host-wide; open a circuit and use AkShare's Sina
            # endpoint for later symbols. Each fallback still gets up to two retries.
            if "ProxyError" in error or "ConnectionError" in error:
                eastmoney_available = False
            prefix = "sh" if sym.startswith(("6", "9")) else "sz"
            fallback_error = None
            fallback = None
            for fallback_attempt in range(RETRIES + 1):
                try:
                    fallback = ak.stock_zh_a_daily(
                        symbol=f"{prefix}{sym}", start_date=start_date,
                        end_date=end_date, adjust=""
                    )
                    if fallback is None or fallback.empty or not {"date", "amount", "turnover"}.issubset(fallback.columns):
                        raise ValueError(f"Sina fallback returned invalid schema: {getattr(fallback, 'columns', None)}")
                    fallback_error = None
                    break
                except Exception as exc:
                    fallback_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("[%d/%d] %s Sina attempt %d/%d failed: %s",
                                   i, len(symbols), sym, fallback_attempt + 1, RETRIES + 1, fallback_error)
                    if fallback_attempt < RETRIES:
                        time.sleep(0.8 * (fallback_attempt + 1))
            if fallback_error is not None:
                failure = f"Eastmoney: {error}; Sina: {fallback_error}"
                failed_downloads.append((sym, failure))
                logger.error("[%d/%d] %s exhausted retries and fallback: %s", i, len(symbols), sym, failure)
                time.sleep(PER_SYMBOL_SLEEP)
                continue
            hist = fallback[["date", "amount", "turnover"]].copy()
            hist["date"] = pd.to_datetime(hist["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            hist["amount"] = pd.to_numeric(hist["amount"], errors="coerce")
            # Sina provides turnover as a fraction; daily_bars uses percent units.
            hist["turnover"] = pd.to_numeric(hist["turnover"], errors="coerce") * 100.0
            source = "Sina stock_zh_a_daily"
            logger.warning("[%d/%d] %s used Sina fallback after Eastmoney failure: %s",
                           i, len(symbols), sym, error)
        else:
            hist = hist[["日期", "成交额", "换手率"]].copy()
            hist["date"] = pd.to_datetime(hist["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
            hist["amount"] = pd.to_numeric(hist["成交额"], errors="coerce")
            hist["turnover"] = pd.to_numeric(hist["换手率"], errors="coerce")
        hist = hist.dropna(subset=["date"]).drop_duplicates("date", keep="last")
        rows = [(None if pd.isna(a) else float(a),
                 None if pd.isna(t) else float(t), sym, d)
                for d, a, t in hist[["date", "amount", "turnover"]].itertuples(index=False, name=None)]
        # COALESCE keeps any existing non-null source value if AkShare has a null.
        changes_before = conn.total_changes
        with conn:
            conn.executemany(
                "UPDATE daily_bars SET amount=COALESCE(?, amount), "
                "turnover=COALESCE(?, turnover) WHERE symbol=? AND date=?",
                rows
            )
        updated = conn.total_changes - changes_before
        updated_rows_total += updated
        logger.info("[%d/%d] %s source=%s range=%s..%s fetched=%d matched_updates=%d",
                    i, len(symbols), sym, source, start_date, end_date, len(rows), updated)
        time.sleep(PER_SYMBOL_SLEEP)

    after = coverage(conn, symbols)
    placeholders = ",".join("?" for _ in symbols)
    still_missing = conn.execute(
        "SELECT symbol, SUM(amount IS NULL), SUM(turnover IS NULL), COUNT(*) "
        f"FROM daily_bars WHERE symbol IN ({placeholders}) GROUP BY symbol "
        "HAVING SUM(amount IS NULL)>0 OR SUM(turnover IS NULL)>0 ORDER BY symbol", symbols
    ).fetchall()
    conn.close()
    logger.info("coverage after: %s", after)
    logger.info("matched rows updated: %d", updated_rows_total)
    logger.info("download failures (%d): %s", len(failed_downloads), failed_downloads)
    logger.info("symbols with remaining null pool rows (%d): %s",
                len(still_missing), still_missing)
    logger.info("=== backfill run finished ===")
    print("\nCoverage report")
    print(f"Full table: amount {before['full_amount_pct']:.6f}% -> {after['full_amount_pct']:.6f}%; "
          f"turnover {before['full_turnover_pct']:.6f}% -> {after['full_turnover_pct']:.6f}% "
          f"({after['full_rows']:,} rows)")
    print(f"300 pool: amount {before['pool_amount_pct']:.6f}% -> {after['pool_amount_pct']:.6f}%; "
          f"turnover {before['pool_turnover_pct']:.6f}% -> {after['pool_turnover_pct']:.6f}% "
          f"({after['pool_rows']:,} rows)")
    print("Download failures:", failed_downloads)
    print("Symbols still missing:", [r[0] for r in still_missing])
    print("Detailed log:", LOG_PATH)
    if after["pool_amount_pct"] < 95 or after["pool_turnover_pct"] < 95:
        logger.error("acceptance not met: pool coverage below 95%%")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
