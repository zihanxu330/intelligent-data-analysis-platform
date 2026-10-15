# -*- coding: utf-8 -*-
"""
A股交易规则（真实市场约束）：
1. 交易成本：佣金（默认万3，单笔最低5元）+ 卖出印花税（0.05%）+ 过户费（0.001%，双边）
2. T+1：当日买入的股票当日不能卖出
3. 涨跌停：涨停买不进、跌停卖不出（近似：用当日收盘价是否触及涨/跌停判断）
4. 停牌：当日成交量=0 视为停牌，不做任何交易动作

说明：
- 佣金/印花税/过户费通过自定义 CommInfo 注入 broker。
- T+1/涨跌停/停牌通过 AShareRulesMixin 混入策略类（lazy 初始化，不侵入策略 __init__）。
- 涨跌幅按板块近似：沪深主板10%、创业板/科创板20%、北交所30%（不含ST）。
"""
import backtrader as bt


def limit_pct(symbol: str) -> float:
    """A股各板块涨跌幅限制（近似，不含ST/新股首日）。"""
    s = str(symbol)
    if s.startswith(("300", "301", "688")):
        return 0.20          # 创业板 / 科创板
    if s.startswith(("8", "4", "920")):
        return 0.30          # 北交所
    return 0.10              # 沪深主板


class AShareCommInfo(bt.CommInfoBase):
    """
    佣金 + 最低佣金 + 卖出印花税 + 双边过户费。
    backtrader 的 _getcommission(size, price, pseudoexec)：
        size>0 买入，size<0 卖出。
    """

    params = (
        ("commission", 0.0003),     # 佣金率，默认万3
        ("min_commission", 5.0),    # 单笔最低佣金（元）
        ("stamp_tax", 0.0005),      # 卖出印花税（2023-08-28 起 0.05%）
        ("transfer_fee", 0.00001),  # 过户费 0.001%，双边
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec):
        amt = abs(size) * price
        comm = amt * self.p.commission
        if comm > 0 and comm < self.p.min_commission:
            comm = self.p.min_commission
        comm += amt * self.p.transfer_fee          # 过户费双边
        if size < 0:                                # 卖出另加印花税
            comm += amt * self.p.stamp_tax
        return comm


class AShareRulesMixin:
    """
    A股交易规则混入类（T+1 / 涨跌停 / 停牌）。

    用法：
        class MyStrategy(AShareRulesMixin, bt.Strategy):
            def next(self):
                self._ashare_ensure()          # next() 开头调用
                ...
                if self._ashare_sell_blocked(): return
                if self._ashare_buy_blocked(): return
            def notify_order(self, order):
                self._ashare_on_fill(order)    # 与现有成交处理并存

    lazy 初始化：不在 __init__ 里做任何事，避免破坏策略现有的初始化链。
    """

    def _ashare_ensure(self):
        if getattr(self, "_ashare_ready", False):
            return
        self._ashare_ready = True
        self._ashare_symbol = str(getattr(self.data, "_name", "") or "")
        self._ashare_buy_date = None
        self._ashare_blocked_buys = 0
        self._ashare_blocked_sells = 0

    # ---- 成交回调：记录买入成交日期（T+1 依据）----
    def _ashare_on_fill(self, order):
        if order.status == order.Completed and order.isbuy():
            self._ashare_buy_date = self.data.datetime.date(0)

    # ---- T+1：当日买入的股票当日不能卖 ----
    def _ashare_t1_blocked(self) -> bool:
        today = self.data.datetime.date(0)
        return self._ashare_buy_date is not None and self._ashare_buy_date == today

    # ---- 涨跌停价（基于昨收，四舍五入到分）----
    def _ashare_limit_price(self, up: bool):
        prev_close = self.data.close[-1]
        if prev_close is None or prev_close != prev_close or prev_close <= 0:
            return None
        pct = limit_pct(self._ashare_symbol)
        base = prev_close * (1 + pct) if up else prev_close * (1 - pct)
        return round(base, 2)

    # ---- 停牌（成交量=0）----
    def _ashare_suspended(self) -> bool:
        v = self.data.volume[0]
        return v is not None and v == 0

    # ---- 买入是否被规则挡住：停牌 或 涨停买不进 ----
    def _ashare_buy_blocked(self) -> bool:
        if self._ashare_suspended():
            self._ashare_blocked_buys += 1
            return True
        up = self._ashare_limit_price(up=True)
        if up is not None and self.data.close[0] >= up - 1e-6:
            self._ashare_blocked_buys += 1
            return True
        return False

    # ---- 卖出是否被规则挡住：T+1 / 停牌 / 跌停卖不出 ----
    def _ashare_sell_blocked(self) -> bool:
        if self._ashare_t1_blocked():
            self._ashare_blocked_sells += 1
            return True
        if self._ashare_suspended():
            self._ashare_blocked_sells += 1
            return True
        down = self._ashare_limit_price(up=False)
        if down is not None and self.data.close[0] <= down + 1e-6:
            self._ashare_blocked_sells += 1
            return True
        return False

    def _ashare_stats(self):
        return self._ashare_blocked_buys, self._ashare_blocked_sells
