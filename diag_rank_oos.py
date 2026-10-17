# -*- coding: utf-8 -*-
import sys, os, numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from data_engine.database import load_daily
from models.predict import add_rank_score, add_ai_score

SYMS = [s.strip() for s in open("output/symbols_300.txt", encoding="utf-8") if s.strip()]
panels = {}
for sym in SYMS:
    df = load_daily(sym)
    if df.empty: continue
    df = df[(df["date"] >= "2026-01-01") & (df["date"] <= "2026-10-15")]
    if len(df) < 30: continue
    df = df.sort_values("date").reset_index(drop=True)
    df = add_rank_score(df, model_path="output/model_rank_h3p.joblib", symbol=sym)
    df = add_ai_score(df, model_path="output/model_oos_20260101.joblib", symbol=sym)
    df["fwd5"] = df["close"].shift(-5) / df["close"] - 1
    panels[sym] = df.set_index("date")[["close", "rank_score", "ai_prob", "fwd5"]]

# 每个交易日截面：rank_score Top-5 与 ai_prob Top-5 的未来5日收益 vs 全池
rows = []
for d in sorted(set().union(*[p.index for p in panels.values()])):
    g = {sym: p.loc[d] for sym, p in panels.items() if d in p.index and p.loc[d, "fwd5"] == p.loc[d, "fwd5"]}
    if len(g) < 20: continue
    gdf = pd.DataFrame(g).T
    if gdf["rank_score"].notna().sum() < 5 or gdf["ai_prob"].notna().sum() < 5: continue
    top_r = gdf.nlargest(5, "rank_score")["fwd5"].mean()
    top_a = gdf.nlargest(5, "ai_prob")["fwd5"].mean()
    pool = gdf["fwd5"].mean()
    rows.append({"rank_top5": top_r, "ai_top5": top_a, "pool": pool})
r = pd.DataFrame(rows)
print(f"截面数: {len(r)}")
print(f"rank Top-5 平均未来5日收益: {r['rank_top5'].mean()*100:.2f}%  vs 全池 {r['pool'].mean()*100:.2f}% (差{(r['rank_top5']-r['pool']).mean()*100:.2f}pct)")
print(f"ai   Top-5 平均未来5日收益: {r['ai_top5'].mean()*100:.2f}%  vs 全池 {r['pool'].mean()*100:.2f}% (差{(r['ai_top5']-r['pool']).mean()*100:.2f}pct)")
print(f"赢出比例 rank: {(r['rank_top5']>r['pool']).mean()*100:.0f}%  ai: {(r['ai_top5']>r['pool']).mean()*100:.0f}%")
