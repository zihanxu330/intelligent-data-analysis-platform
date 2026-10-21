# -*- coding: utf-8 -*-
"""个股区间涨跌归因：把"为什么涨/跌"拆成可复现的事实链。

用法:
    python analyze_move.py --symbol 603986 --start 20260101 --end 20261016
    python analyze_move.py --symbol 600519 --start 20260101 --end 20260630 --top-days 8

输出（output/analysis/）:
    <symbol>_<start>_<end>.md    人读报告
    <symbol>_<start>_<end>.json  结构化事实（供前端/LLM 引用）
    <symbol>_<start>_<end>.png   价格+成交量+相对强弱+回撤

说明:
    - 收益分解：市场(全市场等权) + 行业超额(行业等权-市场) + 个股特质(个股-行业)
    - 事件只做"时间对齐"，不宣称因果；公告数据仅覆盖最近一年。
    - 价格为库内收盘价（不复权），除权日可能出现非基本面下跌，报告会标记异常单日跌幅。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import DB_PATH, load_daily  # noqa: E402

IND_PATH = os.path.join(PROJ, "output", "symbols_industry_full.csv")
ANN_PATH = os.path.join(PROJ, "output", "events", "announcements.csv")
RES_PATH = os.path.join(PROJ, "output", "events", "research_reports.csv")
FIN_PATH = os.path.join(PROJ, "output", "financials.csv")
OUT_DIR = os.path.join(PROJ, "output", "analysis")
MARKET_CACHE = os.path.join(OUT_DIR, "_market_ew.csv")

MAJOR_KEYWORDS = ("业绩", "年报", "季报", "分红", "权益分派", "回购", "增持", "减持",
                  "重组", "收购", "中标", "合同", "停牌", "问询", "立案", "处罚",
                  "股权激励", "定增", "可转债", "重大")
# 更可能直接影响价格的公告（用于判断“事件驱动”是否成立）
HIGH_IMPACT = ("业绩", "预增", "预减", "扭亏", "重组", "收购", "中标", "合同",
               "减持", "增持", "立案", "处罚", "问询", "停牌", "分红")
LOW_IMPACT = ("说明会", "股东大会", "法律意见", "验资", "议事规则", "独立董事")


# ---------------------------------------------------------------- 数据

def load_names():
    df = pd.read_csv(IND_PATH, dtype={"code": str}, encoding="utf-8-sig").fillna("")
    df["code"] = df["code"].astype(str).str.strip().str.zfill(6)
    return ({c: str(n) for c, n in zip(df["code"], df["name"])},
            {c: (str(i) or "未知") for c, i in zip(df["code"], df["industry"])})


def db_max_date():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT MAX(date) FROM daily_bars").fetchone()[0]


def load_market_ew():
    """全市场等权日收益（单日收益截尾 ±21%，避免新股首日/异常值污染）。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    mx = db_max_date()
    if os.path.exists(MARKET_CACHE):
        cache = pd.read_csv(MARKET_CACHE, parse_dates=["date"])
        if not cache.empty and str(cache["date"].iloc[-1].date()) == mx:
            return cache.set_index("date")["mkt_ret"]
    sql = """
    WITH r AS (
      SELECT date, close / LAG(close) OVER (PARTITION BY symbol ORDER BY date) - 1 AS ret,
             ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS rn
      FROM daily_bars
    )
    SELECT date, AVG(CASE WHEN ret BETWEEN -0.21 AND 0.21 THEN ret END) AS mkt_ret
    FROM r WHERE rn > 20 GROUP BY date ORDER BY date
    """
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(sql, conn, parse_dates=["date"])
    df = df.dropna(subset=["mkt_ret"])
    df.to_csv(MARKET_CACHE, index=False, encoding="utf-8-sig")
    return df.set_index("date")["mkt_ret"]


def _closes_for(symbols, start, end, chunk=400):
    rows = []
    with sqlite3.connect(DB_PATH) as conn:
        for i in range(0, len(symbols), chunk):
            part = symbols[i:i + chunk]
            q = ("SELECT symbol, date, close FROM daily_bars "
                 f"WHERE symbol IN ({','.join('?' * len(part))}) AND date BETWEEN ? AND ?")
            rows.extend(conn.execute(q, part + [start, end]).fetchall())
    df = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_industry_ew(industry, exclude, start, end, ind_map):
    """行业等权日收益（截尾 ±21%），日期从 start 前 20 天开始以覆盖首日收益。"""
    peers = [c for c, v in ind_map.items() if v == industry and c != exclude]
    if len(peers) < 5:
        return None, peers
    s = (pd.Timestamp(start) - pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    e = pd.Timestamp(end).strftime("%Y-%m-%d")
    df = _closes_for(peers, s, e)
    if df.empty:
        return None, peers
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = wide.pct_change().clip(-0.21, 0.21)
    return rets.mean(axis=1, skipna=True).dropna(), peers


def load_announcements(symbol):
    if not os.path.exists(ANN_PATH):
        return pd.DataFrame(columns=["date", "type", "title", "url"])
    df = pd.read_csv(ANN_PATH, dtype={"代码": str, "公告类型": str, "公告标题": str, "网址": str})
    df = df[df["代码"].astype(str).str.zfill(6) == symbol].copy()
    df["date"] = pd.to_datetime(df["公告日期"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).rename(columns={"公告类型": "type", "公告标题": "title", "网址": "url"})
    return df[["date", "type", "title", "url"]].sort_values("date")


def load_research(symbol):
    if not os.path.exists(RES_PATH):
        return pd.DataFrame(columns=["date", "rating", "org", "title"])
    df = pd.read_csv(RES_PATH, dtype={"股票代码": str, "东财评级": str, "机构": str, "报告名称": str})
    df = df[df["股票代码"].astype(str).str.zfill(6) == symbol].copy()
    df["date"] = pd.to_datetime(df["日期"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).rename(columns={"东财评级": "rating", "机构": "org", "报告名称": "title"})
    return df[["date", "rating", "org", "title"]].sort_values("date")


def load_financials(symbol):
    cols = ["report_date", "avail", "net_profit_yoy", "revenue_yoy", "roe"]
    if not os.path.exists(FIN_PATH):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(FIN_PATH, dtype={"symbol": str})
    df = df[df["symbol"].astype(str).str.zfill(6) == symbol].copy()
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["avail"] = df["report_date"] + pd.Timedelta(days=90)   # 财报披露滞后，与训练口径一致
    return df.dropna(subset=["report_date"]).sort_values("report_date")


# ---------------------------------------------------------------- 指标

def limit_pct(symbol, is_st=False):
    if is_st and symbol.startswith(("60", "00")):
        return 0.05
    if symbol.startswith(("30", "68")):
        return 0.20
    if symbol.startswith(("8", "4")):
        return 0.30
    return 0.10


def rsi(series, window=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def pct_rank(history, value):
    h = pd.Series(history).dropna()
    if len(h) < 30 or pd.isna(value):
        return None
    return float((h <= value).mean())


def capm(stock_logret, market_logret):
    d = pd.concat([stock_logret, market_logret], axis=1).dropna()
    d.columns = ["r", "m"]
    if len(d) < 20:
        return None
    var_m = d["m"].var()
    if not np.isfinite(var_m) or var_m <= 0:
        return None
    beta = d["r"].cov(d["m"]) / var_m
    alpha = d["r"].mean() - beta * d["m"].mean()
    resid = d["r"] - (alpha + beta * d["m"])
    se = resid.std(ddof=2) / np.sqrt(len(d)) if len(d) > 2 else np.nan
    r2 = d["r"].corr(d["m"]) ** 2
    return {
        "beta": float(beta),
        "alpha_daily": float(alpha),
        "alpha_annual": float(alpha * 252),
        "alpha_t": float(alpha / se) if se and se > 0 else None,
        "r2": float(r2) if pd.notna(r2) else None,
        "n": int(len(d)),
    }


# ---------------------------------------------------------------- 主分析

def is_high_impact(ev):
    txt = f"{ev.get('type', '')}{ev.get('title', '')}"
    if any(k in txt for k in LOW_IMPACT):
        return False
    return any(k in txt for k in HIGH_IMPACT)


def analyze(symbol, start, end, top_days=5, event_window=2):
    names, ind_map = load_names()
    name = names.get(symbol, "")
    industry = ind_map.get(symbol, "未知")
    is_st = ("ST" in name.upper()) or ("退" in name)

    df = load_daily(symbol)
    if df.empty:
        raise SystemExit(f"{symbol} 本地库没有数据")
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    if len(df) < 90:
        raise SystemExit(f"{symbol} 历史数据只有 {len(df)} 行，不足以做归因（至少 90 行）")

    df["ret"] = df["close"].pct_change()
    df["logret"] = np.log1p(df["ret"])
    df["prev_close"] = df["close"].shift(1)
    df["gap"] = df["open"] / df["prev_close"] - 1
    df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean().shift(1)
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["vol20"] = df["ret"].rolling(20).std() * np.sqrt(252)
    df["rsi14"] = rsi(df["close"])
    df["pos60"] = ((df["close"] - df["low"].rolling(60).min())
                   / (df["high"].rolling(60).max() - df["low"].rolling(60).min()).replace(0, np.nan))

    market = load_market_ew()
    market = market[~market.index.duplicated()].sort_index()
    ind_ew, peers = load_industry_ew(industry, symbol, start, end, ind_map)
    if industry == "未知" or ind_ew is None:
        ind_ew = market.copy()   # 行业未知或同行不足时退化为市场基准
        ind_note = f"行业「{industry}」同行不足或无行业信息，行业基准退化为全市场"
    else:
        ind_note = f"行业 {industry} 等权（{len(peers)} 只同行）"

    df["mkt_ret"] = df["date"].map(market)
    df["ind_ret"] = df["date"].map(ind_ew)

    w = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))].copy()
    if len(w) < 10:
        raise SystemExit(f"区间 {start}~{end} 只有 {len(w)} 个交易日，无法分析")

    w = w.dropna(subset=["ret"])
    if len(w) < 5:
        raise SystemExit(f"区间 {start}~{end} 有效交易日不足 5 个，无法分析")
    total = float(np.expm1(w["logret"].sum()))
    mkt_log = float(np.log1p(w["mkt_ret"]).sum())
    ind_log = float(np.log1p(w["ind_ret"]).sum())
    mkt_comp = float(np.expm1(mkt_log))
    ind_comp = float(np.expm1(ind_log - mkt_log))
    spec_comp = float(np.expm1(w["logret"].sum() - ind_log))

    model = capm(w["logret"], np.log1p(w["mkt_ret"]))

    # ---- 关键交易日 ----
    direction = 1 if total >= 0 else -1
    w = w.copy()
    pick = w.sort_values("ret", ascending=(direction < 0)).head(top_days)
    opposite = w.sort_values("ret", ascending=(direction > 0)).head(2)

    ann = load_announcements(symbol)
    res = load_research(symbol)
    fin = load_financials(symbol)

    def events_near(day):
        a = ann[(ann["date"] - day).abs() <= pd.Timedelta(days=event_window)]
        r = res[(res["date"] - day).abs() <= pd.Timedelta(days=event_window)]
        if len(a):
            hit = (a["type"].astype(str).str.contains("|".join(MAJOR_KEYWORDS), na=False)
                   | a["title"].astype(str).str.contains("|".join(MAJOR_KEYWORDS), na=False))
            a = a[hit]
        return a, r

    def day_row(row, kind):
        day = row["date"]
        # 涨跌停按板块常规比例判定：用“当前”ST 名称回填历史会误伤（ST 认定时点未知）
        pct = limit_pct(symbol, is_st=False)
        up_price = round(row["prev_close"] * (1 + pct), 2) if pd.notna(row["prev_close"]) else np.nan
        dn_price = round(row["prev_close"] * (1 - pct), 2) if pd.notna(row["prev_close"]) else np.nan
        limit = "涨停" if pd.notna(up_price) and row["close"] >= up_price - 0.001 else (
            "跌停" if pd.notna(dn_price) and row["close"] <= dn_price + 0.001 else "")
        a, r = events_near(day)
        anns = [{"date": str(x.date()), "type": t, "title": ti}
                for x, t, ti in zip(a["date"], a["type"], a["title"])]
        anns.sort(key=lambda e: (not is_high_impact(e), e["date"]))
        return {
            "date": str(day.date()), "kind": kind, "ret": float(row["ret"]),
            "close": float(row["close"]),
            "gap": float(row["gap"]) if pd.notna(row["gap"]) else None,
            "vol_ratio": float(row["vol_ratio"]) if pd.notna(row["vol_ratio"]) else None,
            "limit": limit,
            "excess_vs_industry": float(row["ret"] - row["ind_ret"]),
            "announcements": anns,
            "research": [{"date": str(x.date()), "rating": rt, "org": og, "title": ti}
                         for x, rt, og, ti in zip(r["date"], r["rating"], r["org"], r["title"])],
        }

    top_rows = [day_row(w.loc[i], "top") for i in pick.index]
    opposite_rows = [day_row(w.loc[i], "opposite") for i in opposite.index]

    # ---- 事件时间线（区间内重大公告 / 研报 / 财报）----
    ann_win = ann[(ann["date"] >= pd.Timestamp(start)) & (ann["date"] <= pd.Timestamp(end))]
    ann_win = ann_win[ann_win["type"].astype(str).str.contains("|".join(MAJOR_KEYWORDS), na=False)]
    timeline = [{"date": str(d.date()), "type": t, "title": ti}
                for d, t, ti in zip(ann_win["date"], ann_win["type"], ann_win["title"])][-30:]
    res_win = res[(res["date"] >= pd.Timestamp(start)) & (res["date"] <= pd.Timestamp(end))]
    fin_win = fin[(fin["avail"] >= pd.Timestamp(start)) & (fin["avail"] <= pd.Timestamp(end))]

    # ---- 因子画像 ----
    last = w.iloc[-1]
    history = df[df["date"] <= pd.Timestamp(end)].tail(750)
    factors = {
        "mom20": (float(last["close"] / df["close"].shift(20).loc[last.name] - 1)
                  if pd.notna(df["close"].shift(20).loc[last.name]) else None),
        "mom60": (float(last["close"] / df["close"].shift(60).loc[last.name] - 1)
                  if pd.notna(df["close"].shift(60).loc[last.name]) else None),
        "vol20": float(last["vol20"]) if pd.notna(last["vol20"]) else None,
        "rsi14": float(last["rsi14"]) if pd.notna(last["rsi14"]) else None,
        "pos60": float(last["pos60"]) if pd.notna(last["pos60"]) else None,
        "vol_ratio": float(last["vol_ratio"]) if pd.notna(last["vol_ratio"]) else None,
        "dist_ma60": float(last["close"] / last["ma60"] - 1) if pd.notna(last["ma60"]) else None,
    }
    ranks = {
        "mom20": pct_rank(history["close"] / history["close"].shift(20) - 1, factors["mom20"]),
        "mom60": pct_rank(history["close"] / history["close"].shift(60) - 1, factors["mom60"]),
        "vol20": pct_rank(history["vol20"], factors["vol20"]),
        "rsi14": pct_rank(history["rsi14"], factors["rsi14"]),
        "pos60": pct_rank(history["pos60"], factors["pos60"]),
        "vol_ratio": pct_rank(history["vol_ratio"], factors["vol_ratio"]),
    }

    # ---- 结论（规则化，只引用上面的数字）----
    log_total = float(w["logret"].sum())
    comps = {"市场": mkt_log, "行业超额": ind_log - mkt_log, "个股特质": log_total - ind_log}
    total_abs = sum(abs(v) for v in comps.values()) or 1.0
    shares = {k: abs(v) / total_abs for k, v in comps.items()}
    top3_ret = float(np.expm1(w.loc[pick.head(3).index, "logret"].sum()))
    top3_ratio = (top3_ret / total) if abs(total) > 1e-6 else None
    matched_high = sum(1 for r in top_rows if any(is_high_impact(e) for e in r["announcements"]))
    matched_any = sum(1 for r in top_rows if r["announcements"] or r["research"])
    r60 = float(np.expm1(w["logret"].tail(60).sum()))

    drivers = []
    same = {k: v for k, v in comps.items() if v * total > 0}
    opp = {k: v for k, v in comps.items() if v * total < 0}
    if same:
        top = max(same, key=lambda k: abs(same[k]))
        drivers.append(f"{'上涨' if total >= 0 else '下跌'}的主要来源是**{top}**（{comps[top]*100:+.1f}pct）")
        rest = [k for k in same if k != top]
        if rest:
            o = max(rest, key=lambda k: abs(same[k]))
            drivers.append(f"{o}同向变化 {comps[o]*100:+.1f}pct")
    if opp:
        off = max(opp, key=lambda k: abs(opp[k]))
        drivers.append(f"{off} {comps[off]*100:+.1f}pct 形成反向对冲，最终区间 {total*100:+.1f}%")
    if abs(total) >= 0.1:
        if top3_ratio is not None and abs(top3_ratio) >= 0.5:
            tail = "（其余交易日整体为反向拖累）" if abs(top3_ratio) > 1 else ""
            drivers.append(f"收益高度集中：前 3 个交易日合计 {top3_ret*100:+.1f}%，"
                           f"相当于区间收益的 {top3_ratio:.0%}{tail}")
        elif top3_ratio is not None:
            drivers.append(f"收益相对分散：前 3 个交易日合计 {top3_ret*100:+.1f}%，仅占区间收益的 {top3_ratio:.0%}")
    elif abs(top3_ret) >= 0.1:
        drivers.append(f"区间净收益接近 0，但前 3 个交易日合计 {top3_ret*100:+.1f}%，其余交易日基本抵消")
    if model:
        if model["r2"] is not None and model["r2"] < 0.1:
            drivers.append(f"β={model['beta']:.2f}，但 R²={model['r2']:.2f}：与市场几乎无关，走势由行业/个股因素主导")
        else:
            drivers.append(f"β={model['beta']:.2f}（R²={model['r2']:.2f}），"
                           + ("放大市场波动" if model["beta"] > 1.15 else
                              "弱于市场波动" if model["beta"] < 0.85 else "与市场同步"))
    if matched_high:
        drivers.append(f"{matched_high}/{len(top_rows)} 个关键日匹配到业绩/增减持/合同等可能影响价格的公告")
    elif matched_any:
        drivers.append("关键日只匹配到股权激励/回购等例行公告，事件解释力有限")
    else:
        drivers.append("关键日前后未匹配到公告/研报，更可能是板块联动或资金行为")
    if total > 0 and r60 < -0.2:
        drivers.append(f"但末段回吐明显：近 60 日 {r60*100:+.1f}%，高点之后的下跌需要单独解释")
    elif total < 0 and r60 > 0.2:
        drivers.append(f"末段已反弹：近 60 日 {r60*100:+.1f}%")

    warnings = []
    last_bar = df["date"].iloc[-1]
    if (pd.Timestamp(end) - last_bar).days > 7:
        warnings.append(f"最后一根 K 线为 {last_bar.date()}，距区间末 {pd.Timestamp(end).date()} 有缺口"
                        "（停牌/退市？），末段走势未被覆盖")
    if is_st:
        warnings.append("当前名称为 ST/退，历史涨跌停按板块常规比例判定，ST 5% 期间可能漏标")
    if (pd.Timestamp(start) - df["date"].iloc[0]).days < 250:
        warnings.append("该股本地历史不足 1 年，分位数与 beta 的稳定性偏弱")
    if len(w) and (w["ret"].abs() > 0.21).any():
        warnings.append("区间内存在单日涨跌幅超过 ±21% 的记录，可能是除权/拆股，请在原始行情中核对")
    if os.path.exists(ANN_PATH):
        ann_min = ann["date"].min()
        if pd.notna(ann_min) and ann_min > pd.Timestamp(start):
            warnings.append(f"公告数据仅从 {ann_min.date()} 开始，区间前半段无法做事件解释")
    if res.empty:
        warnings.append("本地研报库未覆盖该股（仅 250 只），研报维度结论缺失")
    if ind_note.startswith("行业") and "退化" in ind_note:
        warnings.append(ind_note)

    return {
        "meta": {
            "symbol": symbol, "name": name, "industry": industry,
            "start": str(pd.Timestamp(start).date()), "end": str(pd.Timestamp(end).date()),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bars": int(len(w)), "is_st": bool(is_st),
            "last_bar": str(last_bar.date()),
            "benchmark": "全市场等权（剔除上市前20日，截尾±21%）",
            "industry_benchmark": ind_note,
        },
        "returns": {
            "total": total,
            "market": mkt_comp,
            "industry_excess": ind_comp,
            "stock_specific": spec_comp,
            "relative_to_market": float(np.expm1(w["logret"].sum() - mkt_log)),
            "relative_to_industry": float(np.expm1(w["logret"].sum() - ind_log)),
            "max_drawdown": float(((w["close"] / w["close"].cummax()) - 1).min()),
            "vol_annual": float(w["ret"].std() * np.sqrt(252)),
            "up_days": int((w["ret"] > 0).sum()),
            "down_days": int((w["ret"] < 0).sum()),
            "last20": float(np.expm1(w["logret"].tail(20).sum())),
            "last60": float(np.expm1(w["logret"].tail(60).sum())),
            "log": {
                "total": float(w["logret"].sum()),
                "market": float(mkt_log),
                "industry_excess": float(ind_log - mkt_log),
                "stock_specific": float(w["logret"].sum() - ind_log),
            },
        },
        "capm": model,
        "decomposition_shares": shares,
        "concentration_top3": top3_ratio,
        "concentration_top3_ret": top3_ret,
        "top_days": top_rows,
        "opposite_days": opposite_rows,
        "events": {
            "announcements": timeline,
            "research": [{"date": str(d.date()), "rating": rt, "org": og, "title": ti}
                         for d, rt, og, ti in zip(res_win["date"], res_win["rating"],
                                                  res_win["org"], res_win["title"])],
            "financials": [{"report_date": str(d.date()), "avail": str(a.date()),
                            "net_profit_yoy": None if pd.isna(np_) else float(np_),
                            "revenue_yoy": None if pd.isna(rv) else float(rv),
                            "roe": None if pd.isna(roe) else float(roe)}
                           for d, a, np_, rv, roe in zip(fin_win["report_date"], fin_win["avail"],
                                                         fin_win["net_profit_yoy"], fin_win["revenue_yoy"],
                                                         fin_win["roe"])],
        },
        "factors": {k: (None if v is None else float(v)) for k, v in factors.items()},
        "factor_ranks": ranks,
        "drivers": drivers,
        "warnings": warnings,
        "_data": {"w": w, "df": df, "market": market, "ind_ew": ind_ew, "name": name,
                  "industry": industry, "peers": peers},
    }


# ---------------------------------------------------------------- 输出

def _fmt_pct(x, nd=2):
    return "-" if x is None or pd.isna(x) else f"{x*100:+.{nd}f}%"


def _short(s, n=34):
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def render_md(r):
    m, ret, capm = r["meta"], r["returns"], r["capm"]
    L = []
    L.append(f"# {m['symbol']} {m['name']}｜{m['start']} ~ {m['end']} 涨跌归因")
    L.append("")
    gap = ""
    if m.get("last_bar") and m["last_bar"] != m["end"]:
        gap = f"｜末根K线：{m['last_bar']}"
    L.append(f"> 数据日：{m['end']}（{m['bars']} 个交易日）{gap}｜行业：{m['industry']}｜"
             f"基准：{m['benchmark']}｜生成：{m['generated_at']}")
    L.append("")
    L.append("## 一句话结论")
    for d in r["drivers"]:
        L.append(f"- {d}")
    L.append("")
    L.append("## 收益拆解")
    L.append("")
    L.append("| 项目 | 数值 | 说明 |")
    L.append("|---|---:|---|")
    L.append(f"| 区间收益 | {_fmt_pct(ret['total'])} | 以 start 前一交易日收盘为基准，不复权 |")
    L.append(f"| 近 20 日 | {_fmt_pct(ret['last20'])} | 区间末段走势 |")
    L.append(f"| 近 60 日 | {_fmt_pct(ret['last60'])} | 区间末段走势 |")
    L.append(f"| 市场贡献（对数） | {ret['log']['market']*100:+.2f}pct | 全市场等权，可加 |")
    L.append(f"| 行业超额（对数） | {ret['log']['industry_excess']*100:+.2f}pct | {m['industry_benchmark']} |")
    L.append(f"| 个股特质（对数） | {ret['log']['stock_specific']*100:+.2f}pct | 相对行业的残差 |")
    L.append(f"| 三项合计（对数） | {ret['log']['total']*100:+.2f}pct | 换算简单收益 {_fmt_pct(ret['total'])} |")
    L.append(f"| 相对市场 | {_fmt_pct(ret['relative_to_market'])} | 个股 / 市场 - 1 |")
    L.append(f"| 最大回撤 | {_fmt_pct(ret['max_drawdown'])} | 区间内从峰值回撤 |")
    L.append(f"| 年化波动 | {ret['vol_annual']*100:.1f}% | 日收益标准差×√252 |")
    L.append(f"| 上涨/下跌天数 | {ret['up_days']} / {ret['down_days']} | 交易日计数 |")
    L.append("")
    L.append("> 对数贡献可加：市场 + 行业超额 + 个股特质 = 区间对数收益；"
             "简单收益与对数收益的换算差在大涨大跌时会明显。")
    L.append("")
    if capm:
        L.append("## 市场敏感度（CAPM）")
        L.append("")
        if capm["r2"] is not None and capm["r2"] < 0.1:
            L.append(f"- β = **{capm['beta']:.2f}**，但 R² = {capm['r2']:.2f}：与市场几乎无关，β 仅供参考")
        else:
            L.append(f"- β = **{capm['beta']:.2f}**（>1 放大市场波动，<1 防御）")
        L.append(f"- 日 α = {capm['alpha_daily']*100:+.3f}%，年化 α（算术）≈ {capm['alpha_annual']*100:+.1f}%"
                 + (f"，t = {capm['alpha_t']:.2f}" if capm["alpha_t"] is not None else ""))
        L.append(f"- R² = {capm['r2']:.2f}（市场只能解释 {capm['r2']:.0%} 的日波动）")
        L.append("")
    L.append("## 关键交易日")
    L.append("")
    L.append("| 日期 | 涨跌幅 | 收盘 | 跳空 | 量比 | 涨跌停 | 行业超额 | 事件 |")
    L.append("|---|---:|---:|---:|---:|---|---:|---|")
    for row in r["top_days"] + r["opposite_days"]:
        ev = ""
        if row["announcements"]:
            ev = f"公告：{_short(row['announcements'][0]['title'], 26)}"
        elif row["research"]:
            ev = f"研报：{_short(row['research'][0]['title'], 26)}"
        vr = row["vol_ratio"]
        vr_txt = "-" if vr is None else f"{vr:.2f}x"
        L.append(f"| {row['date']} | {row['ret']*100:+.2f}% | "
                 f"{row['close']:.2f} | {_fmt_pct(row['gap'])} | {vr_txt} | "
                 f"{row['limit'] or '-'} | {row['excess_vs_industry']*100:+.2f}% | {ev} |")
    L.append("")
    if abs(ret["total"]) >= 0.1 and r["concentration_top3"] is not None:
        if abs(r["concentration_top3"]) >= 0.5:
            L.append(f"> 前 3 个交易日合计 {r['concentration_top3_ret']*100:+.1f}%，"
                     f"相当于区间收益的 {r['concentration_top3']:.0%}。")
        else:
            L.append(f"> 前 3 个交易日合计 {r['concentration_top3_ret']*100:+.1f}%，"
                     f"仅占区间收益的 {r['concentration_top3']:.0%}，收益相对分散。")
        L.append("")
    elif abs(r["concentration_top3_ret"]) >= 0.1:
        L.append(f"> 区间净收益 {_fmt_pct(ret['total'])}，前 3 个交易日合计 "
                 f"{r['concentration_top3_ret']*100:+.1f}%，其余交易日基本抵消。")
        L.append("")
    if r["events"]["announcements"]:
        L.append("## 重大公告时间线")
        L.append("")
        L.append("| 日期 | 类型 | 标题 |")
        L.append("|---|---|---|")
        for e in r["events"]["announcements"]:
            L.append(f"| {e['date']} | {_short(e['type'], 18)} | {_short(e['title'], 46)} |")
        L.append("")
    if r["events"]["research"]:
        L.append("## 研报覆盖")
        L.append("")
        L.append("| 日期 | 评级 | 机构 | 标题 |")
        L.append("|---|---|---|---|")
        for e in r["events"]["research"][-15:]:
            L.append(f"| {e['date']} | {e['rating'] or '-'} | {_short(e['org'], 12)} | {_short(e['title'], 40)} |")
        L.append("")
    if r["events"]["financials"]:
        L.append("## 财报（按 +90 天披露滞后对齐）")
        L.append("")
        L.append("| 报告期 | 可获取日 | 净利同比 | 营收同比 | ROE |")
        L.append("|---|---|---:|---:|---:|")
        for e in r["events"]["financials"]:
            ny = "-" if e["net_profit_yoy"] is None else f"{e['net_profit_yoy']*100:+.1f}%"
            ry = "-" if e["revenue_yoy"] is None else f"{e['revenue_yoy']*100:+.1f}%"
            roe = "-" if e["roe"] is None else f"{e['roe']*100:.2f}%"
            L.append(f"| {e['report_date']} | {e['avail']} | {ny} | {ry} | {roe} |")
        L.append("")
    L.append("## 因子画像（截至区间末）")
    L.append("")
    L.append("| 指标 | 当前值 | 自身 3 年分位 |")
    L.append("|---|---:|---:|")
    labels = {"mom20": "20日动量", "mom60": "60日动量", "vol20": "20日年化波动",
              "rsi14": "RSI14", "pos60": "60日价格位置", "vol_ratio": "量比", "dist_ma60": "偏离MA60"}
    for k, lab in labels.items():
        v = r["factors"].get(k)
        if v is None:
            continue
        if k in ("vol20",):
            val = f"{v*100:.1f}%"
        elif k in ("rsi14",):
            val = f"{v:.1f}"
        elif k in ("pos60",):
            val = f"{v:.2f}"
        else:
            val = f"{v*100:+.1f}%" if k != "vol_ratio" else f"{v:.2f}x"
        pr = r["factor_ranks"].get(k)
        L.append(f"| {lab} | {val} | {'-' if pr is None else f'{pr:.0%}'} |")
    L.append("")
    L.append("## 数据说明与局限")
    L.append("")
    L.append("- 收益按库内收盘价计算（不复权），除权除息日可能产生非基本面下跌。")
    L.append("- 公告仅覆盖 2025-10 之后；研报库仅覆盖 250 只老池股票。")
    L.append("- 基准为当前存续 5225 只股票的等权，历史区间存在幸存者偏差，早期年份的市场收益可能偏高。")
    L.append("- 事件只做时间对齐，不构成因果；'为什么'更准确的表述是'与什么同时发生'。")
    for w in r["warnings"]:
        L.append(f"- ⚠ {w}")
    L.append("")
    return "\n".join(L)


def render_png(r, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"):
        if any(x.name == f for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [f]
            break
    plt.rcParams["axes.unicode_minus"] = False

    d = r["_data"]
    w = d["w"].set_index("date")
    mkt = d["market"].reindex(w.index).ffill().fillna(0.0)
    ind = pd.Series(d["ind_ew"]).reindex(w.index).ffill().fillna(0.0)

    fig, axes = plt.subplots(4, 1, figsize=(12, 13), sharex=True,
                             gridspec_kw={"height_ratios": [2.6, 1.0, 1.3, 0.8]})
    ax = axes[0]
    ax.plot(w.index, w["close"], color="#1f4e79", lw=1.4, label="收盘价")
    ax.plot(w.index, w["ma20"], color="#f0a30a", lw=0.9, alpha=0.8, label="MA20")
    ax.plot(w.index, w["ma60"], color="#c00000", lw=0.9, alpha=0.8, label="MA60")
    for row in r["top_days"]:
        day = pd.Timestamp(row["date"])
        ax.scatter(day, row["close"], marker="^", s=70, color="#c00000", zorder=5)
    for row in r["opposite_days"]:
        day = pd.Timestamp(row["date"])
        ax.scatter(day, row["close"], marker="v", s=70, color="#00a650", zorder=5)
    ax.set_title(f"{r['meta']['symbol']} {r['meta']['name']}  {r['meta']['start']} ~ {r['meta']['end']}  "
                 f"区间 {r['returns']['total']*100:+.1f}%", fontsize=13)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)

    ax = axes[1]
    up = w["ret"] >= 0
    ax.bar(w.index, w["volume"] / 1e6, color=np.where(up, "#d62728", "#2ca02c"), width=1.0)
    ax.set_ylabel("成交量(百万)")

    ax = axes[2]
    base = w["close"].iloc[0]
    ax.plot(w.index, w["close"] / base, label="个股", color="#1f4e79", lw=1.4)
    ax.plot(w.index, (1 + mkt).cumprod() / (1 + mkt).iloc[0], label="全市场等权", color="#7f7f7f", lw=1.1)
    ax.plot(w.index, (1 + ind).cumprod() / (1 + ind).iloc[0], label="行业等权", color="#f0a30a", lw=1.1)
    ax.axhline(1.0, color="black", lw=0.6, alpha=0.4)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_ylabel("相对净值")
    ax.grid(alpha=0.25)

    ax = axes[3]
    dd = w["close"] / w["close"].cummax() - 1
    ax.fill_between(w.index, dd * 100, 0, color="#c00000", alpha=0.3)
    ax.set_ylabel("回撤(%)")
    ax.grid(alpha=0.25)

    for a in axes:
        a.tick_params(axis="x", labelsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- LLM 解读层

LLM_SYSTEM = """你是一名严谨的 A 股个股研究员。你的任务不是预测股价，而是把给定的结构化归因事实讲清楚。

硬性规则：
1. 只能使用用户提供的事实（JSON）。不得补充任何外部新闻、政策、研报、传闻或常识性猜测。
2. 每条结论必须引用事实中的日期或数字作为证据；没有证据就写“现有数据无法解释”。
3. 区分归因与因果：用“与……同时发生 / 可能相关”，不要用“导致 / 因为”。
4. 如果关键交易日没有匹配到公告，明确说“未找到公告层面的解释”，不要编造事件。
5. 不构成投资建议。

输出 Markdown，总字数不超过 600 字，严格使用以下四段：
### 核心结论
（1-2 句，直接回答这段时间为什么涨/跌）
### 证据链
（3-5 条，按重要性排序，每条带日期/数字）
### 无法解释的部分
（数据覆盖不到、或没有事件支持的部分）
### 置信度
（高/中/低 + 一句理由）"""


def llm_facts(r):
    """裁剪成适合 LLM 的事实包：保留结论所需字段，限制事件条数。"""
    def trim(rows):
        out = []
        for row in rows:
            d = dict(row)
            d["announcements"] = row["announcements"][:3]
            d["research"] = row["research"][:2]
            out.append(d)
        return out

    return {
        "meta": r["meta"],
        "returns": r["returns"],
        "capm": r["capm"],
        "decomposition_shares": r["decomposition_shares"],
        "concentration_top3": r["concentration_top3"],
        "concentration_top3_ret": r["concentration_top3_ret"],
        "rule_based_drivers": r["drivers"],
        "top_days": trim(r["top_days"]),
        "opposite_days": trim(r["opposite_days"]),
        "events": {
            "announcements": r["events"]["announcements"][-10:],
            "research": r["events"]["research"][-5:],
            "financials": r["events"]["financials"],
        },
        "factors": r["factors"],
        "factor_ranks": r["factor_ranks"],
        "warnings": r["warnings"],
    }


def build_llm_messages(r):
    facts = json.dumps(llm_facts(r), ensure_ascii=False, indent=1, default=str)
    user = ("以下是该股票在指定区间的结构化归因事实（JSON），"
            "请严格依据它写一段“为什么涨/跌”的解读。\n\n```json\n" + facts + "\n```")
    return [{"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": user}]


def call_llm(messages, base_url, model, key, timeout=90):
    import requests

    url = base_url.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1200},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def llm_env():
    key = (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY"))
    base = os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1"
    model = os.environ.get("LLM_MODEL") or "deepseek-chat"
    return key, base, model


def main():
    ap = argparse.ArgumentParser(description="个股区间涨跌归因")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--top-days", type=int, default=5)
    ap.add_argument("--event-window", type=int, default=2)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--llm", action="store_true",
                    help="调用 LLM 生成事实约束解读（需 LLM_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY）")
    ap.add_argument("--llm-dry-run", action="store_true", help="只生成 prompt、不调用 API")
    ap.add_argument("--llm-base-url", default=None, help="OpenAI 兼容 API 根地址，默认读 LLM_BASE_URL")
    ap.add_argument("--llm-model", default=None, help="模型名，默认读 LLM_MODEL")
    args = ap.parse_args()

    symbol = args.symbol.strip().zfill(6)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if end < start:
        raise SystemExit("--end 不能早于 --start")
    if args.top_days < 1:
        raise SystemExit("--top-days 必须 >= 1")
    if args.event_window < 0:
        raise SystemExit("--event-window 必须 >= 0")

    r = analyze(symbol, start, end, top_days=args.top_days, event_window=args.event_window)
    os.makedirs(args.out_dir, exist_ok=True)
    stem = f"{symbol}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"

    md_path = os.path.join(args.out_dir, stem + ".md")
    json_path = os.path.join(args.out_dir, stem + ".json")
    png_path = os.path.join(args.out_dir, stem + ".png")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(r))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in r.items() if not k.startswith("_")}, f,
                  ensure_ascii=False, indent=2, default=str)
    if not args.no_plot:
        render_png(r, png_path)

    lg = r["returns"]["log"]
    print(f"区间收益 {r['returns']['total']*100:+.2f}% | 市场 {lg['market']*100:+.2f}pct | "
          f"行业超额 {lg['industry_excess']*100:+.2f}pct | 个股特质 {lg['stock_specific']*100:+.2f}pct")
    for d in r["drivers"]:
        print(" -", d.replace("**", ""))
    print("报告:", md_path)
    print("事实:", json_path)
    if not args.no_plot:
        print("图表:", png_path)

    # ---- 可选：LLM 解读（事实约束）----
    if args.llm or args.llm_dry_run:
        messages = build_llm_messages(r)
        prompt_path = os.path.join(args.out_dir, stem + "_llm_prompt.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(messages[0]["content"] + "\n\n" + messages[1]["content"])
        chars = sum(len(m["content"]) for m in messages)
        if args.llm_dry_run:
            print(f"LLM prompt 已写入: {prompt_path}（{chars} 字符，dry-run 未调用 API）")
        else:
            key, base, model = llm_env()
            base = args.llm_base_url or base
            model = args.llm_model or model
            if not key:
                raise SystemExit("未配置 LLM_API_KEY（或 OPENAI_API_KEY / DEEPSEEK_API_KEY）；"
                                 "可先用 --llm-dry-run 查看 prompt")
            try:
                text = call_llm(messages, base, model, key)
            except Exception as exc:
                print(f"[LLM] 调用失败: {type(exc).__name__}: {exc}")
            else:
                llm_path = os.path.join(args.out_dir, stem + "_llm.md")
                with open(llm_path, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
                with open(md_path, "a", encoding="utf-8") as f:
                    f.write("\n## AI 解读（事实约束）\n\n" + text + "\n\n"
                            f"> 由 {model} 基于本报告事实生成；归因不等于因果，不构成投资建议。\n")
                print("LLM 解读:", llm_path)


if __name__ == "__main__":
    main()
