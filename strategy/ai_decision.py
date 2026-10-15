# -*- coding: utf-8 -*-
"""
AIDecisionStrategy —— 纯AI决策策略（无均线/动量/RSI规则）

决策完全由机器学习模型驱动：
- 买入：模型预测"未来horizon日上涨概率" >= buy_threshold 且当前空仓 -> 买入
- 卖出：持仓中模型预测概率 < sell_threshold -> 卖出（模型认为上涨概率走弱）
- 兜底风控：可选ATR止损（use_atr_stop=True时生效），只在模型失效/价格极端下兜底，
  不属于交易决策规则，可关闭。

与规则策略(ma_cross)的区别：ma_cross靠MA/动量/RSI条件组合触发买卖，
本策略买卖时机只取决于模型输出的概率，不含任何技术指标规则。

说明：self.fast_ma/self.slow_ma 仅用于回测引擎在K线图上叠加均线展示，
不参与任何决策逻辑。
"""
import backtrader as bt
from backtest.ashare import AShareRulesMixin


class AIDecisionStrategy(AShareRulesMixin, bt.Strategy):

    params = dict(
        buy_threshold=0.55,     # 上涨概率>=该值才买入
        sell_threshold=0.45,    # 持仓中概率<=该值就卖出
        max_position=0.7,       # 单次最多用70%资金
        atr_period=14,
        use_atr_stop=True,      # 是否启用ATR止损兜底（风控，非决策规则）
        atr_stop=3.0,           # ATR止损倍数
    )

    def __init__(self):
        # 仅供引擎绘图叠加均线，不参与决策
        self.fast_ma = bt.indicators.SMA(self.data.close, period=10)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=30)

        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        self.order = None
        self.buy_price = None
        self.trade_log = []

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f"{dt} {txt}")

    def notify_order(self, order):
        if order.status == order.Completed:
            price = order.executed.price
            date = self.datas[0].datetime.date(0).isoformat()
            self._ashare_on_fill(order)
            if order.isbuy():
                self.buy_price = price
                self.trade_log.append({
                    "date": date, "action": "buy",
                    "price": round(price, 2), "size": order.executed.size,
                })
            else:
                self.trade_log.append({
                    "date": date, "action": "sell",
                    "price": round(price, 2), "size": order.executed.size,
                })
        self.order = None

    def _ai_prob(self):
        """读取当前bar的模型预测概率；NaN（预热期/模型不可用）返回None，策略不动作。"""
        if not hasattr(self.data, "ai_prob"):
            return None
        p = self.data.ai_prob[0]
        if p != p:  # NaN
            return None
        return float(p)

    def next(self):
        self._ashare_ensure()
        if self.order:
            return

        position = self.getposition(self.data).size
        price = self.data.close[0]
        prob = self._ai_prob()

        # ======================
        # 持仓管理
        # ======================
        if position > 0:
            # A股规则：T+1 / 停牌 / 跌停 当日不能卖
            if self._ashare_sell_blocked():
                if self._ashare_t1_blocked():
                    self.log("T+1限制(当日买入不能卖)")
                elif self.data.volume[0] == 0:
                    self.log("停牌不交易")
                else:
                    self.log("跌停卖不出")
                return

            # ATR止损兜底（风控，可关闭）
            if self.p.use_atr_stop and self.buy_price is not None:
                atr_stop_price = self.buy_price - self.p.atr_stop * self.atr[0]
                if price < atr_stop_price:
                    self.log("ATR止损(风控兜底)")
                    self.order = self.close()
                    return

            # AI决策卖出：模型预测上涨概率走弱
            if prob is not None and prob < self.p.sell_threshold:
                self.log(f"AI概率走弱卖出(p={prob:.2f})")
                self.order = self.close()
                return

        # ======================
        # 买入（空仓 & 模型看多）
        # ======================
        if position == 0 and prob is not None:
            # A股规则：停牌 / 涨停 当日买不进
            if self._ashare_buy_blocked():
                if self.data.volume[0] == 0:
                    self.log("停牌不交易")
                else:
                    self.log("涨停买不进")
                return
            if prob >= self.p.buy_threshold:
                cash = self.broker.get_cash()
                size = int(cash * self.p.max_position / price / 100) * 100
                if size > 0:
                    self.log(f"AI决策买入(p={prob:.2f}) size={size}")
                    self.order = self.buy(size=size)
