# -*- coding: utf-8 -*-
"""增量缺日检测：不依赖 MAX(date)，按明确目标交易日检查差集。"""
import os
import sqlite3


def normalize_dates(dates):
    out = []
    for d in dates:
        s = str(d)[:10]
        if s not in out:
            out.append(s)
    return sorted(out)


def missing_dates(symbol, target_dates, db_path=None):
    """返回 target_dates 中该证券缺失的日期。

    注意：缺失只表示“库里没有该日行”，不等于停牌/退市；
    调用方必须结合停牌状态、公告或数据源再确认。
    """
    from data_engine.database import DB_PATH
    path = db_path or DB_PATH
    target = normalize_dates(target_dates)
    if not os.path.exists(path) or not target:
        return target
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select date from daily_bars where symbol=? and date>=? and date<=?",
            (str(symbol).zfill(6), target[0], target[-1]),
        ).fetchall()
    finally:
        con.close()
    have = {r[0][:10] for r in rows}
    return [d for d in target if d not in have]


def missing_by_symbol(symbols, target_dates, db_path=None):
    return {str(s).zfill(6): missing_dates(s, target_dates, db_path) for s in symbols}
