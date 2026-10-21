# -*- coding: utf-8 -*-
"""全池批量异动扫描：逐日找“个股相对行业”的异常收益日，计算事件窗口 CAR，
输出明细 + 按 行业×事件类型 汇总的事件因子候选池。

用法:
    python scan_anomalies.py --start 20260101 --end 20261016 --top 50 --window 2

输出:
    output/analysis/anomalies_<start>_<end>.csv
    output/analysis/anomalies_<start>_<end>_summary.csv

口径:
    - AR = 个股日收益 - 行业等权日收益；行业等权直接复用 analyze_move.load_industry_ew
      （pct_change + 截尾 ±21%），并做 leave-one-out 修正（剔除个股自身），与单股分析一致。
    - 涨跌停按板块常规比例（主板10%/创业板科创板20%/北交所30%），不用当前 ST 名称回填历史。
    - 事件只做时间对齐：CAR 是统计量，不代表因果。
"""
import argparse
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import DB_PATH  # noqa: E402
from analyze_move import load_industry_ew, is_high_impact, MAJOR_KEYWORDS  # noqa: E402
from paper_trade import is_limit_up, is_limit_down, limit_pct  # noqa: E402

# 这些公告是对股价异动的“事后反应”，不能当事件因子（否则是未来函数）
REACTIVE_KEYWORDS = ("异常波动", "股价异动", "风险提示", "澄清")

IND_PATH = os.path.join(PROJ, "output", "symbols_industry_full.csv")
ANN_PATH = os.path.join(PROJ, "output", "events", "announcements.csv")
RES_PATH = os.path.join(PROJ, "output", "events", "research_reports.csv")
FIN_PATH = os.path.join(PROJ, "output", "financials.csv")
OUT_DIR = os.path.join(PROJ, "output", "analysis")


def load_maps():
    df = pd.read_csv(IND_PATH, dtype={"code": str}, encoding="utf-8-sig").fillna("")
    df["code"] = df["code"].astype(str).str.strip().str.zfill(6)
    return ({c: str(n) for c, n in zip(df["code"], df["name"])},
            {c: (str(i) or "未知") for c, i in zip(df["code"], df["industry"])})


def load_prices(start, end):
    """一次性取全池日线，返回 close/open/volume 三个 date×symbol 矩阵。"""
    sql = ("SELECT symbol, date, open, close, volume FROM daily_bars "
           "WHERE date BETWEEN ? AND ?")
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(sql, conn, params=[start, end], parse_dates=["date"])
    if df.empty:
        raise SystemExit(f"区间 {start}~{end} 没有日线数据")
    close = df.pivot(index="date", columns="symbol", values="close").sort_index()
    open_ = df.pivot(index="date", columns="symbol", values="open").sort_index()
    vol = df.pivot(index="date", columns="symbol", values="volume").sort_index()
    return close, open_, vol


def industry_matrices(close, ind_map, start, end):
    """复用 analyze_move.load_industry_ew 得到行业等权均值，并构造同行有效数矩阵。"""
    dates = close.index
    stocks = close.columns
    raw = close.pct_change()
    clipped = raw.clip(-0.21, 0.21)

    mean_mat = pd.DataFrame(np.nan, index=dates, columns=stocks, dtype=float)
    cnt_mat = pd.DataFrame(np.nan, index=dates, columns=stocks, dtype=float)
    industries = sorted(set(ind_map.values()) - {"未知"})
    used = 0
    for ind in industries:
        peers = [c for c in stocks if ind_map.get(c) == ind]
        if len(peers) < 5:
            continue
        series, _ = load_industry_ew(ind, "", start, end, ind_map)
        if series is None or series.empty:
            continue
        s = series.reindex(dates)
        n = clipped[peers].notna().sum(axis=1).reindex(dates)
        mean_mat[peers] = np.repeat(s.values[:, None], len(peers), axis=1)
        cnt_mat[peers] = np.repeat(n.values[:, None], len(peers), axis=1)
        used += 1
    return raw, mean_mat, cnt_mat, used


def bulk_events(symbols, start, end, window):
    """一次性读取公告/研报/财报，按 symbol 建事件列表。"""
    lo = pd.Timestamp(start) - pd.Timedelta(days=window)
    hi = pd.Timestamp(end) + pd.Timedelta(days=window)
    symset = set(symbols)
    events = {}

    if os.path.exists(ANN_PATH):
        ann = pd.read_csv(ANN_PATH, dtype={"代码": str, "公告类型": str, "公告标题": str})
        ann["代码"] = ann["代码"].astype(str).str.zfill(6)
        ann["date"] = pd.to_datetime(ann["公告日期"], errors="coerce").dt.normalize()
        ann = ann[(ann["代码"].isin(symset)) & (ann["date"] >= lo) & (ann["date"] <= hi)]
        major = ("|".join(MAJOR_KEYWORDS))
        keep = (ann["公告类型"].astype(str).str.contains(major, na=False)
                | ann["公告标题"].astype(str).str.contains(major, na=False))
        ann = ann[keep]
        ann = ann[~ann["公告标题"].astype(str).str.contains("|".join(REACTIVE_KEYWORDS), na=False)]
        for code, d, t, title in zip(ann["代码"], ann["date"], ann["公告类型"], ann["公告标题"]):
            ev = {"date": d, "category": "公告", "type": str(t), "title": str(title),
                  "high": is_high_impact({"type": str(t), "title": str(title)})}
            events.setdefault(code, []).append(ev)

    if os.path.exists(RES_PATH):
        res = pd.read_csv(RES_PATH, dtype={"股票代码": str, "东财评级": str, "机构": str,
                                           "报告名称": str})
        res["股票代码"] = res["股票代码"].astype(str).str.zfill(6)
        res["date"] = pd.to_datetime(res["日期"], errors="coerce").dt.normalize()
        res = res[(res["股票代码"].isin(symset)) & (res["date"] >= lo) & (res["date"] <= hi)]
        for code, d, rating, org, title in zip(res["股票代码"], res["date"], res["东财评级"],
                                               res["机构"], res["报告名称"]):
            events.setdefault(code, []).append({
                "date": d, "category": "研报", "type": str(rating or "研报"),
                "title": f"{org or ''} {title or ''}".strip(), "high": False})

    if os.path.exists(FIN_PATH):
        fin = pd.read_csv(FIN_PATH, dtype={"symbol": str})
        fin["symbol"] = fin["symbol"].astype(str).str.zfill(6)
        fin["report_date"] = pd.to_datetime(fin["report_date"], errors="coerce")
        fin = fin.dropna(subset=["report_date"]).drop_duplicates(["symbol", "report_date"], keep="last")
        fin = fin.sort_values(["symbol", "report_date"])
        fin["prev_yoy"] = fin.groupby("symbol")["net_profit_yoy"].shift(1)
        fin["yoy_diff"] = fin["net_profit_yoy"] - fin["prev_yoy"]
        fin["avail"] = fin["report_date"] + pd.Timedelta(days=90)
        fin = fin[(fin["symbol"].isin(symset)) & (fin["avail"] >= lo) & (fin["avail"] <= hi)]
        for code, d, rd, yoy, prev, diff in zip(
                fin["symbol"], fin["avail"], fin["report_date"],
                fin["net_profit_yoy"], fin["prev_yoy"], fin["yoy_diff"]):
            if pd.isna(yoy):
                typ = "财报_无数据"
            elif pd.isna(prev):
                typ = "财报_首次"
            elif diff > 0:
                typ = "财报_改善"
            elif diff < 0:
                typ = "财报_恶化"
            else:
                typ = "财报_持平"
            title = (f"{rd.date() if pd.notna(rd) else ''} 净利同比="
                     f"{yoy*100:+.1f}% 上期={prev*100:+.1f}%")
            events.setdefault(code, []).append({
                "date": d, "category": "财报", "type": typ, "title": title, "high": False})

    return events


def match_event(events, symbol, day, window):
    """返回 (事件, 带符号距离)。距离 <0 表示公告在异常日之前，>0 表示之后。"""
    best = None
    for ev in events.get(symbol, []):
        dist = (ev["date"] - day).days
        if abs(dist) > window:
            continue
        score = (1 if ev["high"] else 0, -abs(dist), ev["date"])
        if best is None or score > best[0]:
            best = (score, ev, dist)
    if best is None:
        return None, None
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser(description="全池异动扫描 → 事件因子候选池")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--top", type=int, default=50, help="每交易日最多记录异常数")
    ap.add_argument("--window", type=int, default=2, help="CAR 窗口（默认2：CAR[-1,+2]/CAR[0,+3]）")
    ap.add_argument("--min-ar", type=float, default=0.04, help="|AR| 下限（默认4%）")
    ap.add_argument("--min-vol", type=float, default=1.2, help="量比下限（默认1.2）")
    ap.add_argument("--event-window", type=int, default=3, help="事件对齐窗口（天）")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    t0 = time.time()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if end < start:
        raise SystemExit("--end 不能早于 --start")
    if args.top < 1 or args.window < 1 or args.event_window < 0:
        raise SystemExit("--top/--window 必须 >=1，--event-window 必须 >=0")

    names, ind_map = load_maps()
    # 多取 60 天做量比/收益预热，多取 20 天覆盖 CAR 的前瞻窗口
    load_start = (start - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    load_end = (end + pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    close, open_, vol = load_prices(load_start, load_end)
    print(f"[1/4] 载入日线 {close.shape[0]} 个交易日 × {close.shape[1]} 只", flush=True)

    raw, mean_mat, cnt_mat, used_ind = industry_matrices(
        close, ind_map, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    ar = raw - (cnt_mat * mean_mat - raw) / (cnt_mat - 1).replace(0, np.nan)
    print(f"[2/4] 行业等权计算完成（{used_ind} 个行业）", flush=True)

    # 量比 / 跳空 / CAR
    vol_ma = vol.rolling(20, min_periods=20).mean().shift(1)
    vol_ratio = vol / vol_ma
    prev_close = close.shift(1)
    gap = open_ / prev_close - 1

    # 除权嫌疑：单日涨跌幅超出板块限制、且收盘不在涨跌停价（否则是正常涨跌停）
    pct_series = pd.Series({s: limit_pct(s, is_st=False) for s in close.columns})
    pct_mat = pd.DataFrame(np.tile(pct_series.values, (len(close), 1)),
                           index=close.index, columns=close.columns)
    up_px = (prev_close * (1 + pct_mat)).round(2)
    dn_px = (prev_close * (1 - pct_mat)).round(2)
    at_limit = ((close - up_px).abs() <= 0.005) | ((close - dn_px).abs() <= 0.005)
    suspicious = raw.notna() & (raw.abs() > pct_mat + 0.001) & ~at_limit
    # CAR 窗口 [-1, +3] 内是否含除权嫌疑日
    susp_win = (suspicious.shift(1).iloc[::-1]
                .rolling(5, min_periods=1).max().iloc[::-1]).fillna(0).astype(bool)
    print(f"      除权嫌疑日 {int(suspicious.values.sum())} 个", flush=True)
    if suspicious.values.any():
        vals = raw.where(suspicious).abs()
        i, j = np.unravel_index(np.nanargmax(vals.values), vals.shape)
        _sym = close.columns[j]
        print(f"      除权嫌疑样例: {close.index[i].date()} {_sym} "
              f"收益={raw.values[i, j]*100:+.1f}%（板块限制 ±{pct_series[_sym]*100:.0f}%）", flush=True)

    logret = np.log1p(raw)
    cs = logret.cumsum()
    w = args.window
    car_m1_p2 = np.expm1(cs.shift(-w) - cs.shift(1))
    car_0_p3 = np.expm1(cs.shift(-(w + 1)) - cs)

    seen = close.notna().cumsum()
    seasoned = seen > 20

    events_cache = bulk_events(list(close.columns), start, end, args.event_window)
    print(f"      事件缓存: {len(events_cache)} 只股票有公告/研报/财报", flush=True)

    scan_dates = [d for d in close.index if start <= d <= end]
    rows = []
    skipped_car = 0
    for d in scan_dates:
        ar_row = ar.loc[d]
        vr_row = vol_ratio.loc[d]
        ok = ar_row.notna() & seasoned.loc[d].fillna(False)
        cand = ar_row[ok & (ar_row.abs() >= args.min_ar) & (vr_row >= args.min_vol)]
        if cand.empty:
            continue
        cand = cand.reindex(cand.abs().sort_values(ascending=False).index).head(args.top)
        for sym, arv in cand.items():
            c1, c2 = car_m1_p2.at[d, sym], car_0_p3.at[d, sym]
            if pd.isna(c1) or pd.isna(c2):
                skipped_car += 1
                continue
            px, prev = close.at[d, sym], prev_close.at[d, sym]
            if pd.isna(px) or pd.isna(prev) or prev <= 0:
                continue
            ind = ind_map.get(sym, "未知")
            ev, dist = match_event(events_cache, sym, d, args.event_window)
            susp_today = bool(suspicious.at[d, sym])
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "symbol": sym,
                "name": names.get(sym, ""),
                "industry": ind,
                "ret_pct": round(raw.at[d, sym] * 100, 3),
                "ar_pct": round(arv * 100, 3),
                "vol_ratio": round(vr_row[sym], 3),
                "gap_pct": round(gap.at[d, sym] * 100, 3),
                "limit": ("" if susp_today else
                          "涨停" if is_limit_up(px, prev, sym) else
                          "跌停" if is_limit_down(px, prev, sym) else ""),
                "is_gap": bool(abs(gap.at[d, sym]) > 0.03) if pd.notna(gap.at[d, sym]) else False,
                "is_volume": bool(vr_row[sym] > 2),
                "car_m1_p2_pct": round(c1 * 100, 3),
                "car_0_p3_pct": round(c2 * 100, 3),
                "event_category": ev["category"] if ev else "",
                "event_type": ev["type"] if ev else "",
                "event_title": ev["title"] if ev else "",
                "event_date": ev["date"].strftime("%Y-%m-%d") if ev else "",
                "事件发布日期": ev["date"].strftime("%Y-%m-%d") if ev else "",
                "event_distance": dist,
                "has_event": bool(ev),
                "has_high_impact": bool(ev["high"]) if ev else False,
                "含除权日": bool(susp_win.at[d, sym]),
                "除权嫌疑日": susp_today,
            })

    detail = pd.DataFrame(rows)
    if detail.empty:
        raise SystemExit("没有扫描到异常日：可尝试降低 --min-ar / --min-vol")

    print(f"[3/4] 异常日 {len(detail)} 条（另有 {skipped_car} 条因 CAR 前瞻不足跳过）", flush=True)

    # 汇总：行业 × 事件类型（剔除 CAR 窗口含除权日的样本）
    detail["event_type"] = detail["event_type"].replace("", "无事件")
    clean = detail[~detail["含除权日"]].copy()
    print(f"[3/4] 异常日 {len(detail)} 条，剔除含除权日 {int(detail['含除权日'].sum())} 条，"
          f"汇总样本 {len(clean)} 条（另有 {skipped_car} 条因 CAR 前瞻不足跳过）", flush=True)

    g = clean.groupby(["industry", "event_type"], dropna=False)

    def _tstat(s):
        s = s.dropna()
        if len(s) < 3:
            return np.nan
        sd = s.std(ddof=1)
        return float(s.mean() / (sd / np.sqrt(len(s)))) if sd and sd > 0 else np.nan

    tvals = g["car_0_p3_pct"].apply(_tstat)
    summary = g.agg(
        样本数=("ar_pct", "size"),
        AR均值_pct=("ar_pct", "mean"),
        CAR_m1p2均值_pct=("car_m1_p2_pct", "mean"),
        CAR_0p3均值_pct=("car_0_p3_pct", "mean"),
        CAR_0p3中位数_pct=("car_0_p3_pct", "median"),
        胜率_m1p2=("car_m1_p2_pct", lambda s: float((s > 0).mean() * 100)),
        胜率_0p3=("car_0_p3_pct", lambda s: float((s > 0).mean() * 100)),
        事件前占比=("event_distance", lambda s: float((s.dropna() <= 0).mean() * 100) if s.notna().any() else np.nan),
        高影响事件数=("has_high_impact", "sum"),
    )
    summary["t值_0p3"] = tvals
    summary = summary.reset_index()

    # 按月稳定性（只统计整体 N>=30 的组合）
    clean["month"] = clean["date"].str[:7]
    clean["combo_n"] = clean.groupby(["industry", "event_type"])["car_0_p3_pct"].transform("size")
    monthly = (clean[clean["combo_n"] >= 30]
               .groupby(["industry", "event_type", "month"], dropna=False)
               .agg(样本数=("ar_pct", "size"),
                    CAR_0p3均值_pct=("car_0_p3_pct", "mean"),
                    胜率_0p3=("car_0_p3_pct", lambda s: float((s > 0).mean() * 100)))
               .reset_index())
    if not monthly.empty:
        def _month_stats(d):
            contrib = d["CAR_0p3均值_pct"] * d["样本数"]
            total_n = d["样本数"].sum()
            total = contrib.sum()
            mean_all = total / total_n if total_n else np.nan
            k = contrib.abs().idxmax()
            n_k = d["样本数"].loc[k]
            return pd.Series({
                "覆盖月数": d["month"].nunique(),
                "正值月占比": float((d["CAR_0p3均值_pct"] > 0).mean() * 100),
                "同号月占比": float((np.sign(d["CAR_0p3均值_pct"]) == np.sign(mean_all)).mean() * 100),
                "最差月CAR_pct": float(d["CAR_0p3均值_pct"].min()),
                "最大月贡献占比": float(abs(contrib.loc[k]) / abs(total) * 100) if total else np.nan,
                "剔除最大月CAR_pct": (float((total - contrib.loc[k]) / (total_n - n_k))
                                       if total_n > n_k else np.nan),
            })

        stab = monthly.groupby(["industry", "event_type"], dropna=False).apply(_month_stats).reset_index()
        summary = summary.merge(stab, on=["industry", "event_type"], how="left")
    else:
        for c in ("覆盖月数", "正值月占比", "同号月占比", "最差月CAR_pct",
                  "最大月贡献占比", "剔除最大月CAR_pct"):
            summary[c] = np.nan

    summary["备注"] = np.where(summary["样本数"] < 30, "N<30 仅供参考", "")
    summary["_sig"] = summary["样本数"] >= 30
    summary = summary.sort_values(["_sig", "CAR_0p3均值_pct", "样本数"],
                                  ascending=[False, False, False]).drop(columns="_sig")
    for c in ("AR均值_pct", "CAR_m1p2均值_pct", "CAR_0p3均值_pct", "CAR_0p3中位数_pct",
              "胜率_m1p2", "胜率_0p3", "事件前占比", "t值_0p3",
              "正值月占比", "同号月占比", "最差月CAR_pct", "最大月贡献占比", "剔除最大月CAR_pct"):
        summary[c] = summary[c].round(3)

    os.makedirs(args.out_dir, exist_ok=True)
    stem = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    detail_path = os.path.join(args.out_dir, f"anomalies_{stem}.csv")
    summary_path = os.path.join(args.out_dir, f"anomalies_{stem}_summary.csv")
    monthly_path = os.path.join(args.out_dir, f"anomalies_{stem}_monthly.csv")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    monthly_out = monthly.drop(columns=[c for c in ("_overall", "_same") if c in monthly.columns])
    monthly_out.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    print(f"[4/4] 已保存: {detail_path}")
    print(f"        汇总: {summary_path}")
    print(f"        月度: {monthly_path}")

    # 控制台概览
    print(f"\n===== 概览（{start.date()} ~ {end.date()}）=====")
    print(f"异常日 {len(detail)} 条 | 覆盖 {detail['date'].nunique()} 个交易日 | "
          f"{detail['symbol'].nunique()} 只股票 | 事件对齐 {int(detail['has_event'].sum())} 条"
          f"（高影响 {int(detail['has_high_impact'].sum())}）")
    direct = detail[detail["除权嫌疑日"]]
    print(f"含除权日样本（CAR 窗口）{int(detail['含除权日'].sum())} 条 | "
          f"异常日当天即除权嫌疑 {len(direct)} 条")
    if len(direct):
        b = direct.reindex(direct["ret_pct"].abs().sort_values(ascending=False).index).iloc[0]
        print(f"  样例: {b['date']} {b['symbol']} {b['name']} 收益={b['ret_pct']:+.2f}% "
              f"（超出板块涨跌停限制，判定为除权/数据异常）")
    print(f"耗时 {time.time() - t0:.1f}s")

    print("\nTop 5 异常日（按 |AR|）:")
    top5 = detail.reindex(detail["ar_pct"].abs().sort_values(ascending=False).index).head(5)
    for _, r in top5.iterrows():
        print(f"  {r['date']} {r['symbol']} {r['name']} [{r['industry']}] "
              f"AR={r['ar_pct']:+.2f}% 量比={r['vol_ratio']:.2f} CAR0p3={r['car_0_p3_pct']:+.2f}% "
              f"{r['limit'] or ''} {r['event_type'] if r['has_event'] else ''}")

    sig = summary[(summary["样本数"] >= 30)
                  & (~summary["event_type"].isin(["无事件", "其他"]))]
    print("\nTop 3 行业×事件类型（CAR[0,+3] 均值，N>=30，已剔除 无事件/其他）:")
    if sig.empty:
        print("  （没有 N>=30 的可用组合）")
    for _, r in sig.head(3).iterrows():
        print(f"  {r['industry']} × {r['event_type']}: CAR0p3均值={r['CAR_0p3均值_pct']:+.2f}% "
              f"中位数={r['CAR_0p3中位数_pct']:+.2f}% t={r['t值_0p3']:.2f} "
              f"胜率={r['胜率_0p3']:.0f}% N={r['样本数']} 事件前占比={r['事件前占比']:.0f}%")

    # 财报方向拆分后的候选
    fin_sum = summary[(summary["样本数"] >= 30)
                      & summary["event_type"].astype(str).str.startswith("财报_")]
    print("\n财报方向组合（按 CAR[0,+3] 均值，N>=30）:")
    for _, r in fin_sum.head(3).iterrows():
        print(f"  {r['industry']} × {r['event_type']}: N={r['样本数']} "
              f"CAR均值={r['CAR_0p3均值_pct']:+.2f}% 中位数={r['CAR_0p3中位数_pct']:+.2f}% "
              f"胜率={r['胜率_0p3']:.0f}% 同号月={r['同号月占比']:.0f}% "
              f"覆盖月={r['覆盖月数']:.0f} 最差月={r['最差月CAR_pct']:+.2f}% "
              f"最大月贡献={r['最大月贡献占比']:.0f}% 剔除最大月={r['剔除最大月CAR_pct']:+.2f}%")

    stable = fin_sum[fin_sum["同号月占比"] >= 60].copy()
    ok = stable[((stable["event_type"] == "财报_改善") & (stable["CAR_0p3均值_pct"] > 0))
                | ((stable["event_type"] == "财报_恶化") & (stable["CAR_0p3均值_pct"] < 0))]
    if ok.empty:
        print("  入模初筛：无组合同时满足 N>=30 + 同号月占比>=60% + 方向一致")
    else:
        print("  入模初筛通过（N>=30 + 同号月占比>=60% + 方向一致）:")
        for _, r in ok.iterrows():
            print(f"    {r['industry']} × {r['event_type']}: N={r['样本数']} "
                  f"CAR={r['CAR_0p3均值_pct']:+.2f}% 中位数={r['CAR_0p3中位数_pct']:+.2f}% "
                  f"同号月={r['同号月占比']:.0f}% 最大月贡献={r['最大月贡献占比']:.0f}% "
                  f"剔除最大月={r['剔除最大月CAR_pct']:+.2f}%")
    robust = ok[ok["最大月贡献占比"] <= 60] if not ok.empty else ok
    if robust.empty:
        print("  稳健性复核：无组合通过（要求最大单月贡献<=60%，避免单月驱动）")
    else:
        print("  稳健性复核通过（最大单月贡献<=60%）:")
        for _, r in robust.iterrows():
            print(f"    {r['industry']} × {r['event_type']}: N={r['样本数']} "
                  f"CAR={r['CAR_0p3均值_pct']:+.2f}% 同号月={r['同号月占比']:.0f}%")


if __name__ == "__main__":
    main()
