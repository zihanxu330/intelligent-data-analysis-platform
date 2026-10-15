# -*- coding: utf-8 -*-
"""
策略信号诊断：用项目 factor_lib + ma_cross 规则，评估今日(2026-10-15)收盘后
各标的的因子状态与策略信号。

买入条件: MA10>MA30>MA60 且 20日动量>0 且 RSI∈(40,70)
卖出条件(持仓中): 价 < 买入价-3*ATR(ATR止损) | 价 < 最高价*0.88(移动止盈12%) | MA10跌破MA30(死叉)
"""
import os
import sys
import pandas as pd
import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from factors.factor_lib import add_moving_averages, add_momentum, add_rsi, add_atr

CACHE = os.path.join(PROJ, "output", "cache_sina")
SYMBOLS = {
    "600519": "贵州茅台", "601318": "中国平安", "300750": "宁德时代",
    "600036": "招商银行", "000858": "五粮液", "601899": "紫金矿业",
    "000001": "平安银行", "002594": "比亚迪",
}
# 策略参数（与 ma_cross.py 一致）
FAST, SLOW, TREND = 10, 30, 60
RSI_LO, RSI_HI = 40, 70
ATR_STOP, TRAIL = 3.0, 0.12

rows = []
for sym, name in SYMBOLS.items():
    fp = os.path.join(CACHE, f"{sym}.csv")
    df = pd.read_csv(fp, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # 计算因子
    df = add_moving_averages(df, windows=(FAST, SLOW, TREND))
    df = add_momentum(df, windows=(20,))
    df = add_rsi(df, 14)
    df = add_atr(df, 14)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    day_chg = (last["close"] / prev["close"] - 1) * 100

    ma10, ma30, ma60 = last["ma10"], last["ma30"], last["ma60"]
    mom20, rsi, atr = last["mom20"], last["rsi"], last["atr"]

    trend_ok = ma10 > ma30 > ma60
    momentum_ok = mom20 > 0
    rsi_ok = RSI_LO < rsi < RSI_HI

    # 买入条件状态
    buy_conditions = {
        "趋势多头(MA10>MA30>MA60)": bool(trend_ok),
        "20日动量>0": bool(momentum_ok),
        "RSI∈(40,70)": bool(rsi_ok),
    }
    all_ok = all(buy_conditions.values())

    # ---- 持仓模拟：假设策略在最近一次满足买入条件时建仓 ----
    # 找最近一次满足买入条件的日期
    mask = (df["ma10"] > df["ma30"]) & (df["ma30"] > df["ma60"]) & \
           (df["mom20"] > 0) & (df["rsi"] > RSI_LO) & (df["rsi"] < RSI_HI)
    hold_state = "空仓(无买入信号)"
    stop_notes = []
    if mask.any():
        entry_idx = mask[mask].index[-1]
        entry = df.iloc[entry_idx]
        buy_price = entry["close"]
        # 从建仓日至今的最高价（用于移动止盈）
        seg = df.iloc[entry_idx:len(df)]
        highest = seg["close"].max()
        cur = last["close"]

        atr_stop_price = buy_price - ATR_STOP * entry["atr"]
        trail_price = highest * (1 - TRAIL)
        crossed = df.iloc[-1]["ma10"] < df.iloc[-1]["ma30"]

        triggers = []
        if cur < atr_stop_price:
            triggers.append(f"ATR止损(触发价{atr_stop_price:.2f})")
        if cur < trail_price:
            triggers.append(f"移动止盈(触发价{trail_price:.2f})")
        if crossed:
            triggers.append("死叉趋势反转")

        if triggers:
            hold_state = f"持有中(买入价{buy_price:.2f}, 持仓期间最高{highest:.2f}) → 今日触发: {'、'.join(triggers)}"
        else:
            hold_state = f"持有中(买入价{buy_price:.2f}, 持仓期间最高{highest:.2f}) → 今日未触发卖出, 继续持有"
        stop_notes = [f"ATR止损价={atr_stop_price:.2f}", f"移动止盈价={trail_price:.2f}"]

    rows.append({
        "代码": sym, "名称": name,
        "今日收盘": round(float(last["close"]), 2),
        "今日涨跌%": round(float(day_chg), 2),
        "MA10": round(float(ma10), 2), "MA30": round(float(ma30), 2), "MA60": round(float(ma60), 2),
        "20日动量%": round(float(mom20 * 100), 2) if mom20 == mom20 else None,
        "RSI": round(float(rsi), 2) if rsi == rsi else None,
        "ATR": round(float(atr), 2) if atr == atr else None,
        "趋势多头": buy_conditions["趋势多头(MA10>MA30>MA60)"],
        "动量OK": buy_conditions["20日动量>0"],
        "RSI_OK": buy_conditions["RSI∈(40,70)"],
        "买入信号": "✓ 成立" if all_ok else "✗ 不成立",
        "持仓状态": hold_state,
    })

out = pd.DataFrame(rows)
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 80)
print(out[["代码", "名称", "今日收盘", "今日涨跌%", "MA10", "MA30", "MA60",
           "20日动量%", "RSI", "ATR", "趋势多头", "动量OK", "RSI_OK", "买入信号"]].to_string(index=False))
print("\n===== 持仓状态诊断 =====")
for _, r in out.iterrows():
    print(f"{r['代码']} {r['名称']}: {r['持仓状态']}")

out.to_csv(os.path.join(PROJ, "output", "strategy_diagnosis_20261015.csv"),
           index=False, encoding="utf-8-sig")
print("\n已保存: output/strategy_diagnosis_20261015.csv")
