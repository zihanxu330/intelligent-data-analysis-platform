# -*- coding: utf-8 -*-
"""调试：直接 cerebro + AIDecisionStrategy，逐bar打印决策判断"""
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import backtrader as bt
from data.fetcher import fetch_stock_daily_local_first
from models.predict import add_ai_score
from backtest.engine import _AIPandasData
from strategy.ai_decision import AIDecisionStrategy


class DebugDecision(AIDecisionStrategy):
    def next(self):
        position = self.getposition(self.data).size
        prob = self._ai_prob()
        print(self.data.datetime.date(0),
              "pos=", position,
              "prob=", prob,
              "threshold=", self.p.buy_threshold,
              "would_buy=", (position == 0 and prob is not None and prob >= self.p.buy_threshold))
        super().next()


df = fetch_stock_daily_local_first("600519", "20260601", "20261015")
df = add_ai_score(df, model_path=os.path.join(PROJ, "output", "model_updown.joblib"))

data = _AIPandasData(
    dataname=df.set_index("date"),
    open="open", high="high", low="low", close="close", volume="volume",
    openinterest=-1,
)

cerebro = bt.Cerebro()
cerebro.addstrategy(DebugDecision, buy_threshold=0.55, sell_threshold=0.45)
cerebro.adddata(data)
cerebro.broker.setcash(100000.0)
cerebro.run()
