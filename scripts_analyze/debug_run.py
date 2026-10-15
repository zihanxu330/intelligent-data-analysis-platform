# -*- coding: utf-8 -*-
"""定位：run_backtest + AIDecisionStrategy 跑600519，打印交易与log"""
import os
import sys
import json

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from data.fetcher import fetch_stock_daily_local_first
from backtest.engine import run_backtest
from strategy.ai_decision import AIDecisionStrategy

df = fetch_stock_daily_local_first("600519", "20260601", "20261015")
print("df:", len(df))
model = os.path.join(PROJ, "output", "model_updown.joblib")
res = run_backtest(
    df,
    strategy_cls=AIDecisionStrategy,
    strategy_kwargs={"buy_threshold": 0.55, "sell_threshold": 0.45},
    initial_cash=100000.0,
    ai_model_path=model,
)
print("metrics:", res["metrics"])
print("trades:", json.dumps(res["trades"], ensure_ascii=False))
print("equity_curve len:", len(res["equity_curve"]))
