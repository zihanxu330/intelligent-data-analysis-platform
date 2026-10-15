# -*- coding: utf-8 -*-
"""
回测引擎封装。基于backtrader，加入常用分析器（夏普比率、最大回撤、交易统计），
并输出资金曲线图，方便快速评估一个策略的基本表现。
"""
import backtrader as bt
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 无GUI环境下渲染
import matplotlib.pyplot as plt

from models.predict import add_ai_score
from backtest.ashare import AShareCommInfo


class _AIPandasData(bt.feeds.PandasData):
    """在标准OHLCV基础上多暴露一条 ai_prob 线，供策略读取模型预测概率。"""
    lines = ("ai_prob",)
    params = (("ai_prob", -1),)  # -1 = 按列名"ai_prob"自动匹配


def run_backtest(df: pd.DataFrame, strategy_cls, strategy_kwargs=None,
                  initial_cash: float = 100000.0, commission: float = 0.0003,
                  plot_path: str = None, ai_model_path: str = None,
                  ashare_rules: bool = True, symbol: str = None):
    """
    运行回测，返回一份结构化结果，同时可选保存资金曲线图（本地CLI用）。

    参数:
        df: 包含 date/open/high/low/close/volume 列的DataFrame
        strategy_cls: backtrader.Strategy 子类（需要在 __init__ 里暴露 fast_ma/slow_ma，
                       并维护 self.trade_log 列表，参考 strategy/ma_cross.py）
        strategy_kwargs: 策略参数字典
        initial_cash: 初始资金
        commission: 手续费率（ashare_rules=False 时简化为单边固定比例；开启后按A股真实成本）
        plot_path: 若提供路径，保存资金曲线图到该路径（CLI用，API模式可不传）
        ai_model_path: 若提供，加载该路径的模型给每根K线算 ai_prob（未来上涨概率），
                        通过 data.ai_prob line 暴露给策略做AI过滤；不传则不启用AI过滤，
                        策略退化为纯规则判断。
        ashare_rules: 是否启用A股真实交易规则（佣金万3最低5元+卖出印花税0.05%+过户费0.001%），
                        默认 True。
        symbol: 股票代码，用于合并财务特征（financials.csv，若有）。

    返回:
        dict，结构如下（键均为英文，方便Node/前端直接消费）:
        {
            "metrics": {...},
            "candles": [{date, open, high, low, close, volume, ma_fast, ma_slow}, ...],
            "equity_curve": [{date, value}, ...],
            "trades": [{date, action, price, size}, ...],
        }
    """
    strategy_kwargs = strategy_kwargs or {}

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **strategy_kwargs)

    if ai_model_path:
        df = add_ai_score(df, model_path=ai_model_path, symbol=symbol)
        data = _AIPandasData(
            dataname=df.set_index("date"),
            open="open", high="high", low="low", close="close", volume="volume",
            openinterest=-1,
        )
    else:
        data = bt.feeds.PandasData(
            dataname=df.set_index("date"),
            open="open", high="high", low="low", close="close", volume="volume",
            openinterest=-1,
        )
    cerebro.adddata(data)

    cerebro.broker.setcash(initial_cash)
    if ashare_rules:
        # A股真实成本：佣金万3(最低5元) + 卖出印花税0.05% + 双边过户费0.001%
        cerebro.broker.addcommissioninfo(AShareCommInfo(commission=commission))
    else:
        cerebro.broker.setcommission(commission=commission)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn")

    start_value = cerebro.broker.getvalue()
    # runonce=False：逐bar运行，避免数据段较短（如样本外窗口只剩几十根bar）时
    # 指标周期接近数据长度的 IndexError 越界问题
    results = cerebro.run(runonce=False)
    end_value = cerebro.broker.getvalue()
    strat = results[0]

    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    dd = strat.analyzers.drawdown.get_analysis()
    trades_analysis = strat.analyzers.trades.get_analysis()
    timereturn = strat.analyzers.timereturn.get_analysis()

    total_trades = trades_analysis.get("total", {}).get("total", 0)
    won_trades = trades_analysis.get("won", {}).get("total", 0)
    win_rate = (won_trades / total_trades) if total_trades else None

    metrics = {
        "initial_cash": round(start_value, 2),
        "final_value": round(end_value, 2),
        "total_return": round(end_value / start_value - 1, 4),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "max_drawdown_pct": round(dd.get("max", {}).get("drawdown", 0), 4) if dd else None,
        "total_trades": total_trades,
        "won_trades": won_trades,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
    }

    equity_curve = _build_equity_curve(timereturn, start_value)

    # 把均线指标对齐进candle数据里，方便前端K线图叠加均线
    fast_vals = list(strat.fast_ma.array)
    slow_vals = list(strat.slow_ma.array)
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    n = len(dates)
    # backtrader指标数组长度与数据对齐，前面窗口不足的位置是nan
    fast_vals = fast_vals[-n:] if len(fast_vals) >= n else [None] * (n - len(fast_vals)) + fast_vals
    slow_vals = slow_vals[-n:] if len(slow_vals) >= n else [None] * (n - len(slow_vals)) + slow_vals

    candles = []
    for i in range(n):
        candles.append({
            "date": dates[i],
            "open": round(float(df["open"].iloc[i]), 2),
            "high": round(float(df["high"].iloc[i]), 2),
            "low": round(float(df["low"].iloc[i]), 2),
            "close": round(float(df["close"].iloc[i]), 2),
            "volume": int(df["volume"].iloc[i]),
            "ma_fast": round(float(fast_vals[i]), 2) if fast_vals[i] == fast_vals[i] and fast_vals[i] is not None else None,
            "ma_slow": round(float(slow_vals[i]), 2) if slow_vals[i] == slow_vals[i] and slow_vals[i] is not None else None,
        })

    result = {
        "metrics": metrics,
        "candles": candles,
        "equity_curve": equity_curve,
        "trades": list(getattr(strat, "trade_log", [])),
    }
    if hasattr(strat, "_ashare_stats"):
        strat._ashare_ensure()  # 数据段短于指标预热期时 next 从未执行，需确保统计已初始化
        b, s = strat._ashare_stats()
        result["ashare_blocked"] = {"buys": b, "sells": s}

    if plot_path:
        _plot_equity_curve(timereturn, start_value, plot_path)

    return result


def _build_equity_curve(timereturn: dict, start_value: float):
    equity = []
    value = start_value
    for dt, r in timereturn.items():
        value = value * (1 + r)
        date_str = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
        equity.append({"date": date_str, "value": round(value, 2)})
    return equity


def _plot_equity_curve(timereturn: dict, start_value: float, plot_path: str):
    dates = list(timereturn.keys())
    daily_rets = list(timereturn.values())
    equity = [start_value]
    for r in daily_rets:
        equity.append(equity[-1] * (1 + r))
    equity = equity[1:]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dates, equity, linewidth=1.5, color="#2563eb")
    ax.set_title("Equity Curve")
    ax.set_xlabel("Date")
    ax.set_ylabel("Account Value")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
