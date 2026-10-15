# -*- coding: utf-8 -*-
"""
诊断脚本：不跑完整回测，直接用pandas算一遍策略的买入条件，
看看这段时间里到底有多少天满足 MA10>MA30>MA60 / 动量>0 / RSI在40~70，
以及三个条件同时满足的天数——用来判断"0笔交易"是策略太严格，还是数据/逻辑有问题。

用法: python diagnose_strategy.py 600519
"""
import sys
import numpy as np
import pandas as pd
from data_engine.database import load_daily


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def diagnose(symbol: str):
    df = load_daily(symbol)
    if df.empty:
        print(f"本地库里没有 {symbol} 的数据，先用 downloader 下载")
        return

    df = df.sort_values("date").reset_index(drop=True)
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma30"] = df["close"].rolling(30).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["momentum20"] = df["close"] - df["close"].shift(20)
    df["rsi14"] = compute_rsi(df["close"], 14)

    valid = df.dropna(subset=["ma10", "ma30", "ma60", "momentum20", "rsi14"])
    n = len(valid)
    print(f"{symbol} 共 {len(df)} 条数据，指标预热后剩 {n} 条可判断的交易日 "
          f"({valid['date'].min().date()} ~ {valid['date'].max().date()})")

    trend_ok = (valid["ma10"] > valid["ma30"]) & (valid["ma30"] > valid["ma60"])
    momentum_ok = valid["momentum20"] > 0
    rsi_ok = (valid["rsi14"] > 40) & (valid["rsi14"] < 70)
    all_ok = trend_ok & momentum_ok & rsi_ok

    print(f"  三线多头排列(MA10>MA30>MA60): {trend_ok.sum()} 天 ({trend_ok.mean():.1%})")
    print(f"  20日动量>0: {momentum_ok.sum()} 天 ({momentum_ok.mean():.1%})")
    print(f"  RSI在40~70之间: {rsi_ok.sum()} 天 ({rsi_ok.mean():.1%})")
    print(f"  三个条件同时满足(会触发买入信号): {all_ok.sum()} 天")

    if all_ok.sum() == 0:
        print("\n  => 确认策略这段时间从未同时满足三个条件，0笔交易是策略逻辑本身的结果，不是bug。")
        if trend_ok.sum() == 0:
            print("     其中 '三线多头排列' 这个条件本身就从未满足过，"
                  "说明这段时间该股票没有出现过持续上升趋势，策略偏保守，在震荡/下跌行情里本来就应该空仓观望。")
    else:
        print(f"\n  => 满足条件的天数>0，但回测结果是0笔交易，这就要去看backtrader执行细节"
              f"（比如size计算是否为0、broker资金是否够用等），值得进一步排查。")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "600519"
    diagnose(symbol)
