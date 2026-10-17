# -*- coding: utf-8 -*-
"""排序模型 walk-forward v2（purge/embargo 修正版）：3折滚动训练 + 每折样本外评估。

修正点（v1 的问题）：
1. purge：训练时剔除尾部 HORIZON 个交易日（train_rank --purge），训练标签不再
   覆盖到切分测试期开头（消除 train_rank 内部日志的乐观偏差）。
2. 每折评估统一为"cut 之后"的真样本外：样本外 IC（每日截面 Spearman）、
   Top5 未来收益 vs 全池超额、跑赢天数占比（新增列）。
3. 组合回测沿用 portfolio.py（次日收盘成交、真实成本、停牌 asof）。

输出 output/wf_rank_summary_v2.csv（与 v1 同列 + 新列）。
"""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
PY = sys.executable
SYMS_FILE = "output/symbols_300.txt"

HORIZON = 5   # 与 v1 一致，便于对比

FOLDS = [
    {"n": 1, "cut": "20241231", "test_start": "20250101", "test_end": "20250630"},
    {"n": 2, "cut": "20250630", "test_start": "20250701", "test_end": "20251231"},
    {"n": 3, "cut": "20251231", "test_start": "20260101", "test_end": "20260630"},
]

symbols = [s.strip() for s in open(SYMS_FILE, encoding="utf-8") if s.strip()]


def oos_metrics(model_path, cut, test_start, test_end):
    """cut 之后真样本外：每日截面 IC、Top5 超额、跑赢天数占比。"""
    from data_engine.database import load_daily
    from models.predict import add_rank_score
    from scipy.stats import spearmanr

    panels = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty:
            continue
        df = df[(df["date"] > cut) & (df["date"] <= test_end)]
        if len(df) < 40:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])
        df = add_rank_score(df, model_path=model_path, symbol=sym)
        df["fwd"] = df["close"].shift(-HORIZON) / df["close"] - 1
        panels[sym] = df.set_index("date")[["rank_score", "fwd"]]

    ic, topk_exc, beat = [], [], []
    all_dates = sorted(set().union(*[p.index for p in panels.values()]))
    for d in all_dates:
        g = {s: p.loc[d] for s, p in panels.items()
             if d in p.index and pd.notna(p.loc[d, "rank_score"])
             and pd.notna(p.loc[d, "fwd"])}
        if len(g) < 20:
            continue
        gdf = pd.DataFrame(g).T
        ic_v = spearmanr(gdf["rank_score"], gdf["fwd"]).correlation
        if pd.notna(ic_v):
            ic.append(ic_v)
        top = gdf.nlargest(5, "rank_score")["fwd"].mean()
        pool = gdf["fwd"].mean()
        topk_exc.append(top - pool)
        beat.append(top > pool)
    return (np.mean(ic) if ic else np.nan,
            np.mean(topk_exc) if topk_exc else np.nan,
            np.mean(beat) * 100 if beat else np.nan,
            len(ic))


rows = []
for f in FOLDS:
    i = f["n"]
    rank_model = f"output/wf_f{i}_rank_h{HORIZON}_v2.joblib"
    print(f"===== 折{i}: 训练截止 {f['cut']} (purge={HORIZON}), 测试 {f['test_start']}~{f['test_end']} =====")
    subprocess.run([PY, "train_rank.py", "--until", f["cut"], "--horizon", str(HORIZON),
                    "--purge", str(HORIZON), "--out", rank_model],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ic, exc, beat, n_days = oos_metrics(rank_model, f["cut"], f["test_start"], f["test_end"])
    print(f"  样本外 IC={ic:.4f} | Top5超额={exc*100:+.2f}pct/日 | 跑赢天数 {beat:.0f}% | 截面 {n_days} 日")

    out = f"output/wf_f{i}_rank_v2_port.csv"
    subprocess.run([PY, "backtest/portfolio.py", "--model", rank_model, "--scorer", "rank_score",
                    "--symbols-file", SYMS_FILE,
                    "--start", f["test_start"], "--end", f["test_end"],
                    "--top-n", "5", "--rebalance", "5", "--out", out],
                   check=True, stdout=subprocess.DEVNULL)
    df = pd.read_csv(out, encoding="utf-8-sig")
    for _, r in df.iterrows():
        rows.append({"折": i, "训练截止": f["cut"] + f" (purge{HORIZON})",
                     "测试期": f"{f['test_start']}~{f['test_end']}",
                     "组合": r["组合"], "总收益%": r["总收益%"], "年化%": r["年化%"],
                     "最大回撤%": r["最大回撤%"], "调仓次数": r.get("调仓次数", ""),
                     "样本外IC": round(ic, 4) if i else "",
                     "Top5日超额pct": round(exc * 100, 2) if i else "",
                     "跑赢天数%": round(beat, 1) if i else ""})

summary = pd.DataFrame(rows)
summary.to_csv("output/wf_rank_summary_v2.csv", index=False, encoding="utf-8-sig")
print("\n===== Walk-Forward v2（purge/embargo）汇总 =====")
print(summary.to_string(index=False))
print("\n已保存: output/wf_rank_summary_v2.csv")
