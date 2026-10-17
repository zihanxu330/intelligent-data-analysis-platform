# -*- coding: utf-8 -*-
"""
用 train_model.py 训练好的模型，给行情数据算出 ai_prob（涨概率）和 rank_score（截面排序分）。
特征工程必须和 train_model.py 的 build_features_one_symbol 完全一致。
"""
import os
import numpy as np
import pandas as pd

from factors.factor_lib import (
    add_moving_averages, add_momentum, add_volatility,
    add_rsi, add_bollinger, add_atr, add_trend_strength,
    add_extended_features,
)
from models.model_io import load_bundle

# 必须和 train_model.py 里的 FEATURE_COLS 保持一致
FEATURE_COLS = [
    "price_vs_ma5", "price_vs_ma20", "price_vs_ma60",
    "ma5_vs_ma20", "ma20_vs_ma60",
    "mom5", "mom20", "mom60",
    "vol20", "rsi", "boll_pct", "atr_pct", "trend_strength",
    "vol_ratio", "price_pos_60", "vol_expansion", "rsi_slope", "vwap_dev", "range_pct",
]
FIN_FEATURES = ["net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]
EVENT_FEATURES = [
    "has_ann_5d", "ev_reorg_5d", "ev_perf_5d", "ev_reduce_5d", "ev_buyback_5d",
    "ev_risk_5d", "ev_biz_5d", "praise_20d", "praise_hi", "praise_mom5",
]
FIN_LAG_DAYS = 90   # 财报公告滞后，避免未来函数；需与训练一致
FIN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "output", "financials.csv")

_fin_map_cache = None
_ev_map_cache = None


def _get_fin_map():
    """lazy 读取 financials.csv -> {symbol: DataFrame[avail, 财务特征]}"""
    global _fin_map_cache
    if _fin_map_cache is None:
        _fin_map_cache = {}
        if os.path.exists(FIN_PATH):
            df = pd.read_csv(FIN_PATH, parse_dates=["report_date"], dtype={"symbol": str})
            df["symbol"] = df["symbol"].str.strip().str.zfill(6)   # 修复前导0丢失（2401 -> 002401）
            df["avail"] = df["report_date"] + pd.Timedelta(days=FIN_LAG_DAYS)
            for sym, g in df.groupby("symbol"):
                _fin_map_cache[sym] = g[["avail"] + FIN_FEATURES].sort_values("avail")
    return _fin_map_cache


def _safe_div(a, b):
    """除零/inf 统一变 NaN，避免 LightGBM 吃到 inf。"""
    return (a / b.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def _get_event_map():
    """lazy 读公告/研报事件面板（与训练 train_model.build_event_map 同源）。"""
    global _ev_map_cache
    if _ev_map_cache is None:
        try:
            from train_model import build_event_map
            _ev_map_cache = build_event_map()   # 全部本地库股票
        except Exception as e:
            print(f"[事件] 加载事件面板失败: {e}，事件特征全 0")
            _ev_map_cache = {}
    return _ev_map_cache


def build_features(df: pd.DataFrame, symbol: str = None) -> pd.DataFrame:
    """单只股票的相对比例特征。输入会按 date 排序；缺财务数据时填 0（中性），与训练一致。"""
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[us]")  # 统一精度，避免 merge_asof dtype 不匹配
    df = add_moving_averages(df, windows=(5, 20, 60))
    df = add_momentum(df, windows=(5, 20, 60))
    df = add_volatility(df, window=20)
    df = add_rsi(df, window=14)
    df = add_bollinger(df, window=20)
    df = add_atr(df, window=14)
    df = add_trend_strength(df)
    df = add_extended_features(df)

    for w, a in ((5, "close"), (20, "close"), (60, "close")):
        df[f"price_vs_ma{w}"] = _safe_div(df[a], df[f"ma{w}"]) - 1
    df["ma5_vs_ma20"] = _safe_div(df["ma5"], df["ma20"]) - 1
    df["ma20_vs_ma60"] = _safe_div(df["ma20"], df["ma60"]) - 1
    df["boll_pct"] = _safe_div(df["close"] - df["boll_low"], df["boll_up"] - df["boll_low"])
    df["atr_pct"] = _safe_div(df["atr"], df["close"])

    for c in FIN_FEATURES:
        df[c] = 0.0
    fin = _get_fin_map().get(symbol) if symbol else None
    if fin is not None:
        merged = pd.merge_asof(df[["date"]], fin, left_on="date",
                               right_on="avail", direction="backward")
        for c in FIN_FEATURES:
            df[c] = merged[c].fillna(0.0).to_numpy()

    # 事件特征（与训练一致：窗口聚合 + 交互项现算）
    for c in EVENT_FEATURES:
        df[c] = 0.0
    ev = _get_event_map().get(symbol) if symbol else None
    if ev is not None:
        base_ev = [c for c in EVENT_FEATURES if c not in ("praise_hi", "praise_mom5")]
        ev2 = ev.copy()
        ev2["date"] = pd.to_datetime(ev2["date"]).astype("datetime64[us]")
        merged = pd.merge_asof(df[["date"]], ev2, left_on="date", right_on="date",
                               direction="backward")
        for c in base_ev:
            df[c] = merged[c].fillna(0.0).to_numpy()
        df["praise_hi"] = df["praise_20d"] * (df["price_pos_60"] > 0.7).astype(int)
        df["praise_mom5"] = df["praise_20d"] * (df["mom5"] > 0.10).astype(int)
    return df


def _score(df, model_path, symbol, out_col, tag, want_objective):
    """公共打分流程。结果按 date 对齐写回，不依赖输入 df 的顺序/索引。"""
    df = df.copy()
    df[out_col] = np.nan
    try:
        bundle = load_bundle(model_path)
    except Exception as e:
        print(f"[{tag}] 加载模型失败({model_path}): {e}，本次不启用")
        return df
    if bundle.get("objective") != want_objective:
        print(f"[{tag}] {model_path} 的 objective={bundle.get('objective')}，需要 {want_objective}，跳过")
        return df

    model = bundle["model"]
    cols = bundle.get("feature_cols") or FEATURE_COLS
    feat = build_features(df, symbol=symbol)
    missing = [c for c in cols if c not in feat.columns]
    if missing:
        print(f"[{tag}] 特征缺失 {missing}，跳过")
        return df

    X = feat[cols].replace([np.inf, -np.inf], np.nan)
    valid = X.notna().all(axis=1)
    if not valid.any():
        print(f"[{tag}] 数据太短，预热期内没有完整特征，本次不生效")
        return df

    if want_objective == "rank":
        pred = model.predict(X[valid])
    else:
        pred = model.predict_proba(X[valid])[:, 1]

    s = pd.Series(pred, index=feat.loc[valid, "date"].to_numpy())
    s = s[~s.index.duplicated(keep="last")]
    df[out_col] = pd.to_datetime(df["date"]).map(s).to_numpy()
    return df


def add_ai_score(df, model_path="output/model_updown.joblib", symbol=None):
    """加列 ai_prob（0~1）。NaN = AI 不参与判断，策略层不得当 0 处理。"""
    return _score(df, model_path, symbol, "ai_prob", "AI过滤", "binary")


def add_rank_score(df, model_path="output/model_rank_h3p.joblib", symbol=None):
    """加列 rank_score（无量纲，仅用于同截面比较，供组合轮动选 Top-N）。"""
    return _score(df, model_path, symbol, "rank_score", "AI排序", "rank")
