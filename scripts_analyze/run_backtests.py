# -*- coding: utf-8 -*-
"""批量跑真实回测：8只标的 20260601~20261015，输出绩效与交易明细"""
import os
import sys
import json

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from data.fetcher import fetch_stock_daily_local_first
from backtest.engine import run_backtest
from strategy.ma_cross import MACrossStrategy

SYMBOLS = {
    "600519": "贵州茅台", "601318": "中国平安", "300750": "宁德时代",
    "600036": "招商银行", "000858": "五粮液", "601899": "紫金矿业",
    "000001": "平安银行", "002594": "比亚迪",
}
START, END = "20260601", "20261015"

summary = []
for sym, name in SYMBOLS.items():
    df = fetch_stock_daily_local_first(sym, START, END)
    if df.empty:
        print(f"{sym} {name}: 无数据")
        continue
    res = run_backtest(
        df,
        strategy_cls=MACrossStrategy,
        strategy_kwargs={"fast_period": 10, "slow_period": 30},
        initial_cash=100000.0,
    )
    m = res["metrics"]
    trades = res["trades"]
    summary.append({
        "代码": sym, "名称": name,
        "总收益%": round(m["total_return"] * 100, 2),
        "期末资金": m["final_value"],
        "夏普": m["sharpe_ratio"],
        "最大回撤%": round(m["max_drawdown_pct"] * 100, 2),
        "交易次数": m["total_trades"],
        "胜率%": round(m["win_rate"] * 100, 2) if m["win_rate"] is not None else None,
    })
    print(f"\n===== {sym} {name} =====")
    print(json.dumps(m, ensure_ascii=False))
    print("trades:", json.dumps(trades, ensure_ascii=False))

    # 保存完整结果
    os.makedirs(os.path.join(PROJ, "output", "api_runs"), exist_ok=True)
    with open(os.path.join(PROJ, "output", "api_runs", f"{sym}_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, default=str)

print("\n===== 汇总 =====")
for s in summary:
    print(s)
