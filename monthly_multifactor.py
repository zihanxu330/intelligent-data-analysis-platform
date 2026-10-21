# -*- coding: utf-8 -*-
"""月度行业中性多因子（v1）：point-in-time 财报 + 量价，Top20，次日开盘成交。

数据:
  output/fundamentals/yjbb_2021_2026.csv  (季度业绩报表，按法定披露截止日可用)
  output/quant.db                         (日线，检测拆股并后向复权)

因子: 合成用 EP + BP + 低波（行业内 z-score 等权）；同时输出 ROE/净利同比/
      营收同比/同比加速/12-1动量 的单因子 IC 供诊断
组合: Top20/50/100 等权，月度调仓，次日开盘买卖，按实际换手计成本
输出: output/analysis/monthly_mf_v1_*.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJ = r"C:\Users\22646\Desktop\项目\quant_ai_updated\quant"
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import DB_PATH  # noqa: E402

YJBB = "output/fundamentals/yjbb_2021_2026.csv"
IND = "output/symbols_industry_full.csv"
OUT = "output/analysis"
COST = 0.00312          # 单次往返：买 0.131% + 卖 0.181%
TOP_N = 20


def limit_pct(sym):
    if sym.startswith(("30", "68")):
        return 0.20
    if sym.startswith(("8", "4")):
        return 0.30
    return 0.10


def load_fundamentals():
    df = pd.read_csv(YJBB, dtype={"股票代码": str})
    df["symbol"] = df["股票代码"].str.strip().str.zfill(6)
    df["quarter"] = df["quarter"].astype(str)
    df["report_date"] = pd.to_datetime(df["quarter"], format="%Y%m%d")
    qn = df["quarter"].str[4:].map({"0331": 1, "0630": 2, "0930": 3, "1231": 4})
    df["q_num"] = qn

    def avail(row):
        y = row["report_date"].year
        md = row["quarter"][4:]
        if md == "0331":
            return pd.Timestamp(y, 4, 30)
        if md == "0630":
            return pd.Timestamp(y, 8, 31)
        if md == "0930":
            return pd.Timestamp(y, 10, 31)
        return pd.Timestamp(y + 1, 4, 30)

    df["avail"] = df.apply(avail, axis=1)
    df = df.rename(columns={
        "每股收益": "eps", "每股净资产": "bps", "净资产收益率": "roe",
        "净利润-同比增长": "np_yoy", "营业总收入-同比增长": "rev_yoy",
        "销售毛利率": "gross_margin", "净利润-净利润": "np",
        "营业总收入-营业总收入": "rev",
    })
    for c in ("eps", "bps", "roe", "np_yoy", "rev_yoy", "gross_margin", "np", "rev"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["symbol", "report_date"])
    df["roe_ann"] = df["roe"] * 4.0 / df["q_num"]
    df["eps_ann"] = df["eps"] * 4.0 / df["q_num"]
    df["accel"] = df.groupby("symbol")["np_yoy"].diff()
    return df[["symbol", "report_date", "avail", "q_num", "eps_ann", "bps",
               "roe_ann", "np_yoy", "rev_yoy", "gross_margin", "accel"]]


def load_prices():
    import sqlite3
    sql = ("SELECT symbol, date, open, close, turnover FROM daily_bars "
           "WHERE date BETWEEN '2020-06-01' AND '2026-10-16'")
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(sql, conn, parse_dates=["date"])
    close = df.pivot(index="date", columns="symbol", values="close").sort_index()
    open_ = df.pivot(index="date", columns="symbol", values="open").sort_index()
    turn = df.pivot(index="date", columns="symbol", values="turnover").sort_index()

    ret = close.pct_change()
    pct = pd.Series({s: limit_pct(s) for s in close.columns})
    susp = ret.abs().gt(pct + 0.005, axis=1) & ret.notna()
    factor = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    factor[susp] = 1.0 + ret[susp]
    rev = factor.iloc[::-1].cumprod().iloc[::-1]
    adj_factor = rev / factor
    return close, open_, turn, ret, adj_factor


def month_ends(idx):
    s = pd.Series(idx, index=idx)
    return s.groupby(idx.to_period("M")).max()


def zscore(s):
    s = s.astype(float)
    lo, hi = s.quantile(0.025), s.quantile(0.975)
    s = s.clip(lo, hi)
    sd = s.std()
    return (s - s.mean()) / sd if sd and sd > 0 else s * 0


def main():
    fund = load_fundamentals()
    close, open_, turn, ret, adj_factor = load_prices()
    adj_close = close * adj_factor
    adj_open = open_ * adj_factor

    names = pd.read_csv(IND, dtype={"code": str}, encoding="utf-8-sig").fillna("")
    names["code"] = names["code"].str.zfill(6)
    ind_map = dict(zip(names["code"], names["industry"]))
    name_map = dict(zip(names["code"], names["name"]))

    idx = adj_close.index
    me = month_ends(idx)
    dates = list(me.values)
    # 价格因子
    mom = adj_close.shift(21) / adj_close.shift(252) - 1
    ret_clean = ret.mask(ret.abs().gt(pd.Series({s: limit_pct(s) for s in close.columns}) + 0.005, axis=1))
    vol60 = ret_clean.rolling(60, min_periods=40).std() * np.sqrt(252)
    turn20 = turn.rolling(20, min_periods=10).mean()

    rows, ics = [], []
    fac_cols = ("ep", "bp", "roe", "np_yoy", "rev_yoy", "accel", "mom", "vol")
    fac_ics = {c: [] for c in fac_cols}
    topn_ret = {20: [], 50: [], 100: []}
    prev_picks = {20: set(), 50: set(), 100: set()}
    turnovers = {20: [], 50: [], 100: []}
    adj_stack = adj_factor.stack()
    rd_map = {d: idx.asof(d) for d in fund["report_date"].unique()}
    for t in dates:
        if t < pd.Timestamp("2022-01-01"):
            continue
        nxt = idx[idx > t]
        if len(nxt) == 0:
            continue
        t1 = nxt[0]
        # 下一个月的月末，再下一个交易日卖出
        cand = [d for d in dates if d > t]
        if not cand:
            continue
        t2 = cand[0]
        nxt2 = idx[idx > t2]
        if len(nxt2) == 0:
            continue
        t2n = nxt2[0]

        # point-in-time 财报
        f = fund[fund["avail"] <= t].sort_values("report_date").drop_duplicates("symbol", keep="last")
        f = f.set_index("symbol")
        if f.empty:
            continue

        # 估值：报告期到现在的拆股调整
        rep_adj = adj_stack.reindex(
            pd.MultiIndex.from_arrays([f["report_date"].map(rd_map).values, f.index.values])).values
        f["adj_rep"] = rep_adj
        px = adj_close.loc[t]
        ep = f["eps_ann"] * f["adj_rep"] / px
        bp = f["bps"] * f["adj_rep"] / px

        df = pd.DataFrame({
            "ep": ep, "bp": bp, "roe": f["roe_ann"], "np_yoy": f["np_yoy"],
            "rev_yoy": f["rev_yoy"], "accel": f["accel"],
            "mom": mom.loc[t].reindex(f.index), "vol": vol60.loc[t].reindex(f.index),
            "turn": turn20.loc[t].reindex(f.index),
            "industry": pd.Series([ind_map.get(s, "未知") for s in f.index], index=f.index),
            "name": pd.Series([name_map.get(s, "") for s in f.index], index=f.index),
            "px": px.reindex(f.index), "open1": adj_open.loc[t1].reindex(f.index) if t1 in adj_open.index else np.nan,
            "open2": adj_open.loc[t2n].reindex(f.index) if t2n in adj_open.index else np.nan,
        })
        df = df[(df["px"] > 2) & df["open1"].notna() & df["open2"].notna()]
        df = df[~df["name"].str.contains("ST|退", na=False)]
        df = df[df["industry"] != "未知"]
        if len(df) < 100:
            continue

        # 行业内 z-score
        z = pd.DataFrame(index=df.index)
        for c, sign in (("ep", 1), ("bp", 1), ("vol", -1)):
            raw = df[c]
            zz = raw.groupby(df["industry"]).transform(zscore)
            z[c] = sign * zz
        df["score"] = z.mean(axis=1, skipna=True)
        df = df[df["score"].notna()]
        if len(df) < TOP_N:
            continue

        picks = df.nlargest(TOP_N, "score")
        fwd = df["open2"] / df["open1"] - 1
        bench = float(fwd.mean())
        ic = spearmanr(df["score"], fwd).correlation
        ics.append({"date": t, "ic": ic, "n": len(df)})
        for c in fac_cols:
            x = pd.DataFrame({"f": df[c], "r": fwd}).dropna()
            if len(x) > 100:
                fac_ics[c].append(spearmanr(x["f"], x["r"]).correlation)
        for n in topn_ret:
            if len(df) >= n:
                idx_n = set(df.nlargest(n, "score").index)
                turn = 1.0 if not prev_picks[n] else 1 - len(idx_n & prev_picks[n]) / n
                topn_ret[n].append(float(fwd.reindex(list(idx_n)).mean()) - turn * COST)
                turnovers[n].append(turn)
                prev_picks[n] = idx_n
        port = topn_ret[20][-1] if topn_ret[20] else np.nan
        rows.append({
            "date": t, "port": port, "bench": bench,
            "n": len(df), "hold": ";".join(picks.index[:5]),
            "avg_ep": picks["ep"].mean(), "avg_roe": picks["roe"].mean(),
        })

    res = pd.DataFrame(rows).set_index("date")
    icdf = pd.DataFrame(ics).set_index("date")
    nav = (1 + res["port"]).cumprod()
    bnav = (1 + res["bench"]).cumprod()
    years = len(res) / 12
    total = nav.iloc[-1] - 1
    ann = (1 + total) ** (1 / years) - 1 if years > 0 else np.nan
    sharpe = res["port"].mean() / res["port"].std() * np.sqrt(12) if res["port"].std() > 0 else np.nan
    mdd = ((nav / nav.cummax()) - 1).min()
    btotal = bnav.iloc[-1] - 1
    bann = (1 + btotal) ** (1 / years) - 1 if years > 0 else np.nan
    bmdd = ((bnav / bnav.cummax()) - 1).min()

    os.makedirs(OUT, exist_ok=True)
    res.to_csv(os.path.join(OUT, "monthly_mf_v1_returns.csv"), encoding="utf-8-sig")
    icdf.to_csv(os.path.join(OUT, "monthly_mf_v1_ic.csv"), encoding="utf-8-sig")

    print(f"月份数 {len(res)} | 组合总收益 {total*100:+.2f}% 年化 {ann*100:+.2f}% "
          f"Sharpe {sharpe:.2f} 最大回撤 {mdd*100:.2f}%")
    print(f"基准（等权全池）总收益 {btotal*100:+.2f}% 年化 {bann*100:+.2f}% 最大回撤 {bmdd*100:.2f}%")
    print(f"月度 IC 均值 {icdf['ic'].mean():.4f} | IC 胜率 {(icdf['ic']>0).mean()*100:.1f}% | "
          f"月均超额 {(res['port']-res['bench']).mean()*100:+.2f}%")
    print("分因子月均 IC:", {c: round(float(np.mean(v)), 4) for c, v in fac_ics.items() if v})
    topdf = pd.DataFrame({f"Top{n}": rr for n, rr in topn_ret.items()}, index=res.index[:len(topn_ret[20])])
    for n, rr in topn_ret.items():
        if rr:
            navn = np.prod([1 + x for x in rr])
            navs = pd.Series(np.cumprod([1 + x for x in rr]), index=res.index[:len(rr)])
            mddn = ((navs / navs.cummax()) - 1).min()
            print(f"  Top{n}: 总收益 {(navn-1)*100:+.2f}% 年化 {((navn**(12/len(rr))-1)*100):+.2f}% "
                  f"最大回撤 {mddn*100:.2f}% 月均换手 {np.mean(turnovers[n])*100:.0f}%")
    for label, mask in (("2022-2024", topdf.index.year <= 2024), ("2025-2026", topdf.index.year >= 2025)):
        sub = topdf[mask]
        if len(sub):
            b = np.prod(1 + sub["Top100"]) ** (12 / len(sub)) - 1
            print(f"  {label}: Top100 年化 {b*100:+.2f}% | 基准 {((np.prod(1+res['bench'][mask])**(12/len(sub))-1)*100):+.2f}%")
    print("\n最近 6 个月:")
    print(res.tail(6)[["port", "bench", "n", "avg_ep", "avg_roe"]].assign(
        port=lambda x: (x["port"] * 100).round(2), bench=lambda x: (x["bench"] * 100).round(2)).to_string())


if __name__ == "__main__":
    main()
