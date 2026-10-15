# -*- coding: utf-8 -*-
"""
用 train_model.py 训练好的涨跌分类模型，给一段行情数据算出每一天"未来上涨"的概率，
供策略在规则信号基础上做进一步过滤。

特征工程必须和 train_model.py 里的 build_features_one_symbol 完全一致，
否则模型看到的输入分布和训练时不一样，预测会失真——这里是特意保持同一套计算方式。
"""
import os
import numpy as np
import pandas as pd
import joblib

from factors.factor_lib import (
    add_moving_averages, add_momentum, add_volatility,
    add_rsi, add_bollinger, add_atr, add_trend_strength,
    add_extended_features,
)

# 必须和 train_model.py 里的 FEATURE_COLS 保持一致
FEATURE_COLS = [
    "price_vs_ma5", "price_vs_ma20", "price_vs_ma60",
    "ma5_vs_ma20", "ma20_vs_ma60",
    "mom5", "mom20", "mom60",
    "vol20", "rsi", "boll_pct", "atr_pct", "trend_strength",
    "vol_ratio", "price_pos_60", "vol_expansion", "rsi_slope", "vwap_dev", "range_pct",
]

FIN_FEATURES = ["net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]
FIN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "financials.csv")

_fin_map_cache = None


def _get_fin_map():
    """lazy 读取 financials.csv -> {symbol: DataFrame[avail, 财务特征]}，与 train_model 同口径。"""
    global _fin_map_cache
    if _fin_map_cache is not None:
        return _fin_map_cache
    _fin_map_cache = {}
    if os.path.exists(FIN_PATH):
        df = pd.read_csv(FIN_PATH, parse_dates=["report_date"])
        df["avail"] = df["report_date"] + pd.Timedelta(days=90)
        for sym, g in df.groupby("symbol"):
            _fin_map_cache[sym] = g[["avail"] + FIN_FEATURES].sort_values("avail")
    return _fin_map_cache


def build_features(df: pd.DataFrame, symbol: str = None) -> pd.DataFrame:
    """给单只股票的行情算一遍相对比例特征（逻辑同 train_model.py，去掉了symbol/target）。
    symbol 用于合并财务特征（若有 financials.csv），缺失财务时填 0（中性），保证与训练一致。"""
    df = df.sort_values("date").reset_index(drop=True)
    df = add_moving_averages(df, windows=(5, 20, 60))
    df = add_momentum(df, windows=(5, 20, 60))
    df = add_volatility(df, window=20)
    df = add_rsi(df, window=14)
    df = add_bollinger(df, window=20)
    df = add_atr(df, window=14)
    df = add_trend_strength(df)
    df = add_extended_features(df)

    df["price_vs_ma5"] = df["close"] / df["ma5"] - 1
    df["price_vs_ma20"] = df["close"] / df["ma20"] - 1
    df["price_vs_ma60"] = df["close"] / df["ma60"] - 1
    df["ma5_vs_ma20"] = df["ma5"] / df["ma20"] - 1
    df["ma20_vs_ma60"] = df["ma20"] / df["ma60"] - 1
    df["boll_pct"] = (df["close"] - df["boll_low"]) / (df["boll_up"] - df["boll_low"])
    df["atr_pct"] = df["atr"] / df["close"]

    for c in FIN_FEATURES:
        df[c] = 0.0
    fin_map = _get_fin_map()
    if fin_map and symbol and symbol in fin_map:
        df["_date"] = df["date"]
        merged = pd.merge_asof(
            df.sort_values("_date"), fin_map[symbol],
            left_on="_date", right_on="avail", direction="backward",
        )
        for c in FIN_FEATURES:
            df[c] = merged[c].fillna(0.0)
        df.drop(columns=["_date"], inplace=True)
    return df


def add_ai_score(df: pd.DataFrame, model_path: str = "output/model_updown.joblib",
                 symbol: str = None) -> pd.DataFrame:
    """
    给df加一列 ai_prob：模型预测的"未来horizon日后上涨"概率（0~1）。
    指标预热期（均线还没形成）或模型加载失败时填 NaN，策略层遇到NaN要当作
    "AI暂时不参与判断"处理，不能当成0来阻止所有买入。
    """
    df = df.copy()
    try:
        bundle = joblib.load(model_path)
    except Exception as e:
        print(f"[AI过滤] 加载模型失败({model_path}): {e}，本次回测不启用AI过滤")
        df["ai_prob"] = np.nan
        return df

    model = bundle["model"]
    feature_cols = bundle.get("feature_cols", FEATURE_COLS)

    feat = build_features(df, symbol=symbol)
    valid = feat[feature_cols].notna().all(axis=1)

    df["ai_prob"] = np.nan
    if valid.any():
        proba = model.predict_proba(feat.loc[valid, feature_cols])[:, 1]
        df.loc[valid, "ai_prob"] = proba
    else:
        print("[AI过滤] 这段数据太短，指标预热期内没有一天能算出完整特征，AI过滤本次不生效")

    return df


def add_rank_score(df: pd.DataFrame, model_path: str = "output/model_rank.joblib",
                   symbol: str = None) -> pd.DataFrame:
    """
    给df加一列 rank_score：排序模型(LGBMRanker)预测的"未来收益在截面中排名"分数。
    分数本身无量纲，只用于同截面横向比较——组合轮动(backtest/portfolio.py)用它选Top-N。
    指标预热期或模型加载失败时填 NaN，策略层按"该股当日不参与排序"处理。
    """
    df = df.copy()
    try:
        bundle = joblib.load(model_path)
    except Exception as e:
        print(f"[AI排序] 加载模型失败({model_path}): {e}，本次回测不启用排序打分")
        df["rank_score"] = np.nan
        return df

    if bundle.get("objective") != "rank":
        print(f"[AI排序] 模型 {model_path} 不是排序模型(objective={bundle.get('objective')})，跳过")
        df["rank_score"] = np.nan
        return df

    model = bundle["model"]
    feature_cols = bundle.get("feature_cols", FEATURE_COLS)

    feat = build_features(df, symbol=symbol)
    valid = feat[feature_cols].notna().all(axis=1)

    df["rank_score"] = np.nan
    if valid.any():
        scores = model.predict(feat.loc[valid, feature_cols])
        df.loc[valid, "rank_score"] = scores
    else:
        print("[AI排序] 这段数据太短，指标预热期内没有一天能算出完整特征，排序打分本次不生效")

    return df
