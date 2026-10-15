# -*- coding: utf-8 -*-
"""
Enhanced Quant Strategy V2

升级点:
1. 双均线趋势 -> 多因子趋势策略
2. 加入市场趋势过滤(MA60)
3. 加入RSI避免追高
4. 加入动量确认
5. ATR动态止损
6. 移动止盈
7. 动态仓位控制

逻辑:
买入:
    MA10 > MA30 > MA60
    + 20日动量 > 0
    + RSI在40~70之间

卖出:
    MA10跌破MA30
    或 ATR移动止损
    或 RSI过热后趋势反转

仅用于研究和回测，不构成投资建议。
"""

import backtrader as bt
from backtest.ashare import AShareRulesMixin


class MACrossStrategy(AShareRulesMixin, bt.Strategy):

    params = dict(
        fast_period=10,
        slow_period=30,
        trend_period=60,

        max_position=0.7,     # 最大仓位70%
        atr_period=14,
        atr_stop=3.0,         # ATR止损倍数
        trailing_stop=0.12,   # 最大盈利回撤12%

        rsi_period=14,

        use_ai_filter=True,     # 是否启用AI过滤（只有传了ai_model_path给run_backtest时ai_prob才有数据）
        ai_prob_threshold=0.55, # 规则信号成立后，模型预测上涨概率要高于这个值才真正买入
    )

    def __init__(self):

        # 趋势指标
        self.fast_ma = bt.indicators.SMA(
            self.data.close, period=self.p.fast_period
        )
        self.slow_ma = bt.indicators.SMA(
            self.data.close, period=self.p.slow_period
        )
        self.trend_ma = bt.indicators.SMA(
            self.data.close, period=self.p.trend_period
        )

        self.crossover = bt.indicators.CrossOver(
            self.fast_ma,
            self.slow_ma
        )

        # 动量
        self.momentum = bt.indicators.Momentum(
            self.data.close,
            period=20
        )

        # RSI
        self.rsi = bt.indicators.RSI(
            self.data.close,
            period=self.p.rsi_period
        )

        # ATR风险控制
        self.atr = bt.indicators.ATR(
            self.data,
            period=self.p.atr_period
        )

        self.order = None
        self.buy_price = None
        self.highest_price = None

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
                self.highest_price = price

                self.trade_log.append({
                    "date":date,
                    "action":"buy",
                    "price":round(price,2),
                    "size":order.executed.size
                })

            else:

                self.trade_log.append({
                    "date":date,
                    "action":"sell",
                    "price":round(price,2),
                    "size":order.executed.size
                })

        self.order=None



    def next(self):

        self._ashare_ensure()

        if self.order:
            return


        position = self.getposition(self.data).size
        price = self.data.close[0]


        # ======================
        # 持仓风险管理
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

            if price > self.highest_price:
                self.highest_price = price


            # ATR动态止损
            atr_stop_price = (
                self.buy_price -
                self.p.atr_stop*self.atr[0]
            )


            # 移动止盈
            trailing_price = (
                self.highest_price *
                (1-self.p.trailing_stop)
            )


            if price < atr_stop_price:

                self.log("ATR止损")
                self.order=self.close()
                return


            if price < trailing_price:

                self.log("移动止盈")
                self.order=self.close()
                return


            # 趋势破坏
            if self.crossover < 0:

                self.log("趋势反转")
                self.order=self.close()
                return



        # ======================
        # 买入逻辑
        # ======================

        if position == 0:


            trend_ok = (
                self.fast_ma[0] >
                self.slow_ma[0] >
                self.trend_ma[0]
            )


            momentum_ok = (
                self.momentum[0] > 0
            )


            rsi_ok = (
                self.rsi[0] > 40 and
                self.rsi[0] < 70
            )

            # ======================
            # AI过滤：规则信号成立后，再看模型预测的上涨概率是否够高
            # ai_prob 这条线只有 run_backtest(..., ai_model_path=...) 传了模型路径才会有值；
            # 没启用AI过滤、或指标预热期内还没有预测值(NaN)时，不拦截，退化为纯规则策略。
            # ======================
            ai_ok = True
            ai_prob = None
            if self.p.use_ai_filter and hasattr(self.data, 'ai_prob'):
                ai_prob = self.data.ai_prob[0]
                if ai_prob == ai_prob:  # 排除NaN（预热期/模型不可用）
                    ai_ok = ai_prob > self.p.ai_prob_threshold
                else:
                    ai_prob = None


            if (
                trend_ok and
                momentum_ok and
                rsi_ok and
                ai_ok
            ):

                # A股规则：停牌 / 涨停 当日买不进
                if self._ashare_buy_blocked():
                    if self.data.volume[0] == 0:
                        self.log("停牌不交易")
                    else:
                        self.log("涨停买不进")
                    return

                cash = self.broker.get_cash()

                size = int(
                    cash *
                    self.p.max_position /
                    price /
                    100
                )*100


                if size > 0:

                    prob_note = f"(AI概率={ai_prob:.2f})" if ai_prob is not None else ""
                    self.log(
                        f"多因子买入{prob_note} size={size}"
                    )

                    self.order=self.buy(
                        size=size
                    )

            elif trend_ok and momentum_ok and rsi_ok and not ai_ok:
                # 规则条件本来成立，但AI概率不够，被过滤掉了——记一下方便复盘
                self.log(f"规则信号被AI过滤(概率={ai_prob:.2f} <= 阈值{self.p.ai_prob_threshold})")
