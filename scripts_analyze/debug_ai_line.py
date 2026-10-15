# -*- coding: utf-8 -*-
"""调试：逐bar打印 ai_prob，确认 line 是否被 backtrader 正确映射"""
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import backtrader as bt
from data.fetcher import fetch_stock_daily_local_first
from models.predict import add_ai_score
from backtest.engine import _AIPandasData


class DebugAI(bt.Strategy):
    def next(self):
        p = self.data.ai_prob[0]
        has = hasattr(self.data, "ai_prob")
        print(self.data.datetime.date(0), "has_ai_prob_line=", has, "prob=", p)


df = fetch_stock_daily_local_first("600519", "20260601", "20261015")
df = add_ai_score(df, model_path=os.path.join(PROJ, "output", "model_updown.joblib"))
print("df 行数:", len(df), "ai_prob 非空:", df["ai_prob"].notna().sum())

data = _AIPandasData(
    dataname=df.set_index("date"),
    open="open", high="high", low="low", close="close", volume="volume",
    openinterest=-1,
)

cerebro = bt.Cerebro()
cerebro.addstrategy(DebugAI)
cerebro.adddata(data)
cerebro.broker.setcash(100000.0)
cerebro.run()
