# -*- coding: utf-8 -*-
"""
本地数据仓库（SQLite）。

设计目标：把"拉数据"和"用数据"彻底解耦。
- downloader.py 负责把 AkShare（或未来的Tushare等）数据一次性/定期写入这里。
- 回测、策略、因子计算只从这里读，完全不联网，不受代理/DNS/杀毒软件/接口限流影响。

表结构：
    daily_bars(symbol, date, open, high, low, close, volume, amount, turnover)
    唯一约束 (symbol, date)，重复写入自动覆盖（用于增量更新最新几天数据）。
"""
import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "quant.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_bars (
            symbol   TEXT NOT NULL,
            date     TEXT NOT NULL,
            open     REAL,
            high     REAL,
            low      REAL,
            close    REAL,
            volume   REAL,
            amount   REAL,
            turnover REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    return conn


def save_daily(symbol: str, df: pd.DataFrame) -> int:
    """
    把某只股票的日线数据写入本地库（存在则覆盖，即"upsert"）。
    df 需包含: date, open, high, low, close, volume（amount/turnover可选）。
    返回写入的行数。
    """
    if df is None or df.empty:
        return 0

    df = df.copy()
    df["symbol"] = symbol
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ("amount", "turnover"):
        if col not in df.columns:
            df[col] = None

    cols = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "turnover"]
    rows = df[cols].values.tolist()

    with get_conn() as conn:
        conn.executemany(f"""
            INSERT INTO daily_bars ({",".join(cols)})
            VALUES ({",".join(["?"] * len(cols))})
            ON CONFLICT(symbol, date) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume,
                amount=excluded.amount, turnover=excluded.turnover
        """, rows)
    return len(rows)


def load_daily(symbol: str, start: str = None, end: str = None) -> pd.DataFrame:
    """
    从本地库读取日线数据，完全不联网。
    start/end 格式 'YYYYMMDD' 或 'YYYY-MM-DD' 均可，不传则不限制。
    返回列与 data/fetcher.py 的 fetch_stock_daily 一致，方便无缝替换。
    """
    with get_conn() as conn:
        query = "SELECT date, open, high, low, close, volume, amount, turnover FROM daily_bars WHERE symbol = ?"
        params = [symbol]
        if start:
            query += " AND date >= ?"
            params.append(_normalize_date(start))
        if end:
            query += " AND date <= ?"
            params.append(_normalize_date(end))
        query += " ORDER BY date"
        df = pd.read_sql(query, conn, params=params, parse_dates=["date"])
    return df


def has_data(symbol: str) -> bool:
    """本地库里是否已经有这只股票的数据（用于downloader跳过已下载的）。"""
    with get_conn() as conn:
        cur = conn.execute("SELECT 1 FROM daily_bars WHERE symbol = ? LIMIT 1", (symbol,))
        return cur.fetchone() is not None


def latest_date(symbol: str) -> str | None:
    """本地库里这只股票最新的日期，用于增量更新（只补最新几天，不用全量重拉）。"""
    with get_conn() as conn:
        cur = conn.execute("SELECT MAX(date) FROM daily_bars WHERE symbol = ?", (symbol,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def list_symbols() -> list[str]:
    """本地库里已经有数据的所有股票代码。"""
    with get_conn() as conn:
        cur = conn.execute("SELECT DISTINCT symbol FROM daily_bars ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


def _normalize_date(d: str) -> str:
    return pd.to_datetime(d).strftime("%Y-%m-%d")


if __name__ == "__main__":
    # 简单自测：写入几行假数据再读出来
    fake = pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "open": [100, 101], "high": [102, 103], "low": [99, 100],
        "close": [101, 102], "volume": [1_000_000, 1_100_000],
    })
    n = save_daily("TEST001", fake)
    print(f"写入 {n} 行")
    print(load_daily("TEST001"))
    print("已有数据的股票:", list_symbols())
