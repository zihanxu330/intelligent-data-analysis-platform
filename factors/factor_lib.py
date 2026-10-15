# -*- coding: utf-8 -*-
"""
因子/技术指标计算库。
输入统一为包含 date/open/high/low/close/volume 列的DataFrame，
输出在原DataFrame上新增因子列，方便后续ML特征工程或策略调用。
"""
import numpy as np
import pandas as pd


def add_moving_averages(df: pd.DataFrame, windows=(5, 10, 20, 60)) -> pd.DataFrame:
    df = df.copy()
    for w in windows:
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    return df


def add_momentum(df: pd.DataFrame, windows=(5, 20, 60)) -> pd.DataFrame:
    """N日动量：当前收盘价相对N日前收盘价的涨跌幅"""
    df = df.copy()
    for w in windows:
        df[f"mom{w}"] = df["close"].pct_change(w)
    return df


def add_volatility(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """年化波动率（基于日收益率标准差）"""
    df = df.copy()
    ret = df["close"].pct_change()
    df[f"vol{window}"] = ret.rolling(window).std() * np.sqrt(252)
    return df


def add_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_bollinger(df: pd.DataFrame, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    mid = df["close"].rolling(window).mean()
    std = df["close"].rolling(window).std()
    df["boll_mid"] = mid
    df["boll_up"] = mid + n_std * std
    df["boll_low"] = mid - n_std * std
    return df


def build_full_factor_table(df: pd.DataFrame) -> pd.DataFrame:
    """一次性叠加常用因子集合，供ML特征工程使用"""
    df = add_moving_averages(df)
    df = add_momentum(df)
    df = add_volatility(df)
    df = add_rsi(df)
    df = add_bollinger(df)
    return df


def add_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """平均真实波幅 ATR 风险因子"""
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    ).max(axis=1)

    df["atr"] = tr.rolling(window).mean()
    return df


def add_trend_strength(df: pd.DataFrame) -> pd.DataFrame:
    """趋势强度"""
    df = df.copy()
    df["trend_strength"] = (
        (df["ma20"] - df["ma60"]) /
        df["ma60"]
    )
    return df


def add_extended_features(df: pd.DataFrame) -> pd.DataFrame:
    """特征升级：量比、价格区间位置、波动扩张、RSI斜率、VWAP偏离、振幅（全部无量纲比例，避免量纲干扰）"""
    df = df.copy()
    # 量比：当日成交量相对20日均量偏离
    df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean() - 1.0
    # 60日价格区间位置(0~1)：收盘价在60日高低点之间的相对位置
    h60 = df["high"].rolling(60).max()
    l60 = df["low"].rolling(60).min()
    df["price_pos_60"] = (df["close"] - l60) / (h60 - l60).replace(0, np.nan)
    # 波动扩张：5日波动 / 20日波动 - 1（放量突破信号）
    ret = df["close"].pct_change()
    df["vol_expansion"] = (
        ret.rolling(5).std() / ret.rolling(20).std().replace(0, np.nan) - 1.0
    )
    # RSI斜率：RSI 相对5日前变化（动能方向）
    df["rsi_slope"] = df["rsi"] - df["rsi"].shift(5)
    # VWAP偏离：收盘价相对20日量加权均价偏离
    vwap20 = (
        (df["close"] * df["volume"]).rolling(20).sum()
        / df["volume"].rolling(20).sum().replace(0, np.nan)
    )
    df["vwap_dev"] = df["close"] / vwap20 - 1.0
    # 当日振幅：日内(高-低)/收盘
    df["range_pct"] = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
    return df
