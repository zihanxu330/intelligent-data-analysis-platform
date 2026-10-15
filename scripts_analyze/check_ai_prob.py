# -*- coding: utf-8 -*-
"""检查 ai_prob 在8只标的上分布，确认AI决策确实生效"""
import os
import sys
import pandas as pd

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from data.fetcher import fetch_stock_daily_local_first
from models.predict import add_ai_score

SYMBOLS = {
    "600519": "贵州茅台", "601318": "中国平安", "300750": "宁德时代",
    "600036": "招商银行", "000858": "五粮液", "601899": "紫金矿业",
    "000001": "平安银行", "002594": "比亚迪",
}
START, END = "20260601", "20261015"
print("代码 名称  有效概率天数  概率均值  概率min  概率max  最后一日概率")
for sym, name in SYMBOLS.items():
    df = fetch_stock_daily_local_first(sym, START, END)
    df = add_ai_score(df, model_path=os.path.join(PROJ, "output", "model_updown.joblib"))
    p = df["ai_prob"].dropna()
    if p.empty:
        print(f"{sym} {name}: 无有效概率")
        continue
    last = p.iloc[-1]
    print(f"{sym} {name}  {len(p):3d}天  {p.mean():.3f}  {p.min():.3f}  {p.max():.3f}  {last:.3f}")
