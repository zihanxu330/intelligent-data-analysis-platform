# -*- coding: utf-8 -*-
"""批量对比：规则决策(MACrossStrategy) vs AI决策(AIDecisionStrategy)，8只标的同区间"""
import os
import sys
import json

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from data.fetcher import fetch_stock_daily_local_first
from backtest.engine import run_backtest
from strategy.ma_cross import MACrossStrategy
from strategy.ai_decision import AIDecisionStrategy

SYMBOLS = {
    "600519": "贵州茅台", "601318": "中国平安", "300750": "宁德时代",
    "600036": "招商银行", "000858": "五粮液", "601899": "紫金矿业",
    "000001": "平安银行", "002594": "比亚迪",
}
START, END = "20260601", "20261015"
MODEL = os.path.join(PROJ, "output", "model_updown.joblib")

rows = []
for sym, name in SYMBOLS.items():
    df = fetch_stock_daily_local_first(sym, START, END)
    if df.empty:
        print(f"{sym} {name}: 无数据")
        continue

    # 规则决策
    res_rule = run_backtest(
        df, MACrossStrategy,
        strategy_kwargs={"fast_period": 10, "slow_period": 30},
        initial_cash=100000.0,
    )
    # AI决策
    res_ai = run_backtest(
        df, AIDecisionStrategy,
        strategy_kwargs={"buy_threshold": 0.55, "sell_threshold": 0.45},
        initial_cash=100000.0,
        ai_model_path=MODEL,
    )

    m_rule, m_ai = res_rule["metrics"], res_ai["metrics"]
    rows.append({
        "代码": sym, "名称": name,
        "规则收益%": round(m_rule["total_return"] * 100, 2),
        "规则交易数": m_rule["total_trades"],
        "规则胜率%": round(m_rule["win_rate"] * 100, 2) if m_rule["win_rate"] is not None else None,
        "AI收益%": round(m_ai["total_return"] * 100, 2),
        "AI交易数": m_ai["total_trades"],
        "AI胜率%": round(m_ai["win_rate"] * 100, 2) if m_ai["win_rate"] is not None else None,
        "AI差于规则": round(m_ai["total_return"] - m_rule["total_return"], 4),
    })
    print(f"\n===== {sym} {name} =====")
    print("规则:", json.dumps(m_rule, ensure_ascii=False))
    print("规则trades:", json.dumps(res_rule["trades"], ensure_ascii=False))
    print("AI  :", json.dumps(m_ai, ensure_ascii=False))
    print("AItrades:", json.dumps(res_ai["trades"], ensure_ascii=False))

    # 保存完整结果
    os.makedirs(os.path.join(PROJ, "output", "api_runs"), exist_ok=True)
    with open(os.path.join(PROJ, "output", "api_runs", f"{sym}_ai_result.json"), "w", encoding="utf-8") as f:
        json.dump(res_ai, f, ensure_ascii=False, default=str)

import pandas as pd
out = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print("\n===== 汇总对比 =====")
print(out.to_string(index=False))
out.to_csv(os.path.join(PROJ, "output", "rule_vs_ai_20261015.csv"), index=False, encoding="utf-8-sig")
print("\n已保存: output/rule_vs_ai_20261015.csv")
