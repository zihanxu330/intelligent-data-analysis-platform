# -*- coding: utf-8 -*-
"""拉取多只代表性个股日线（新浪源），保存为CSV供策略诊断"""
import os
import time
import akshare as ak
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)

START, END = "20260401", "20261015"
OUT = os.path.join(os.path.dirname(__file__), "..", "output", "cache_sina")
os.makedirs(OUT, exist_ok=True)

# 代码 → (名称, 前缀代码)
SYMBOLS = {
    "600519": "贵州茅台",
    "601318": "中国平安",
    "300750": "宁德时代",
    "600036": "招商银行",
    "000858": "五粮液",
    "601899": "紫金矿业",
    "000001": "平安银行",
    "002594": "比亚迪",
}

def sina_code(sym):
    if sym.startswith("6"):
        return "sh" + sym
    if sym.startswith(("0", "3")):
        return "sz" + sym
    return sym

rows = {}
for sym, name in SYMBOLS.items():
    cache = os.path.join(OUT, f"{sym}.csv")
    try:
        df = ak.stock_zh_a_daily(symbol=sina_code(sym), start_date=START, end_date=END, adjust="qfq")
        df["symbol"] = sym
        df["name"] = name
        df.to_csv(cache, index=False)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        chg = (last["close"] / prev["close"] - 1) * 100
        rows[sym] = df
        d = last["date"]
        d = d.date() if hasattr(d, "date") else d
        print(f"{sym} {name}: {len(df)}条, 今日收 {last['close']:.2f} ({chg:+.2f}%), 日期 {d}")
    except Exception as e:
        print(f"{sym} {name} failed: {type(e).__name__} {e}")
    time.sleep(1.0)

print("\n完成")
