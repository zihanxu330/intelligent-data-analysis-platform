# -*- coding: utf-8 -*-
"""
批量训练流水线：本地数据库里的所有股票 -> 因子特征 -> 训练一个"未来N日涨跌"分类模型。

用法：
    # 先确保本地库里有足够多股票的数据（见 data_engine/downloader.py --top N）
    python train_model.py --horizon 5 --n-estimators 300

产出：
    output/model_updown.joblib        训练好的模型 + 特征列名 + 元信息
    控制台打印：训练/测试集准确率、分类报告、和"永远猜多数类"的基线对比

设计要点：
1. 预测目标是分类问题（未来horizon日涨/跌），不是回归预测具体价格——
   股价具体数值几乎不可能预测准，涨跌方向是更现实、更常见的入门任务。
2. 特征全部转换成相对比例（价格/均线的偏离度、动量百分比、RSI、波动率等），
   不用绝对价格/均线数值——否则混合不同股价量级的股票一起训练，模型会被
   "谁的绝对数字更大"带偏，而不是学到真正有意义的规律。
3. 训练/测试集按时间顺序切分（每只股票各自按时间前80%/后20%切），
   不能随机打乱切分——随机切分会让模型"看到未来"，测试集准确率虚高，
   没有实际意义（这是金融机器学习最容易踩的坑）。
"""
import argparse
import os
import numpy as np
import pandas as pd
import joblib

from data_engine.database import list_symbols, load_daily
from factors.factor_lib import (
    add_moving_averages, add_momentum, add_volatility,
    add_rsi, add_bollinger, add_atr, add_trend_strength,
    add_extended_features,
)

# 最终喂给模型的特征列（全部是相对比例/百分比，不含任何绝对价格数值）
FEATURE_COLS = [
    "price_vs_ma5", "price_vs_ma20", "price_vs_ma60",
    "ma5_vs_ma20", "ma20_vs_ma60",
    "mom5", "mom20", "mom60",
    "vol20", "rsi", "boll_pct", "atr_pct", "trend_strength",
    # 特征升级（v2）：量比/区间位置/波动扩张/RSI斜率/VWAP偏离/振幅
    "vol_ratio", "price_pos_60", "vol_expansion", "rsi_slope", "vwap_dev", "range_pct",
]

# 财务特征（慢变量，季度频率；同花顺源，缺失补0=中性）
FIN_FEATURES = ["net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]

# ---- P1 事件特征（公告/研报，窗口聚合；缺失补0=无事件） ----
EVENT_FEATURES = [
    "has_ann_5d",            # 近5个交易日有公告
    "ev_reorg_5d", "ev_perf_5d", "ev_reduce_5d", "ev_buyback_5d",
    "ev_risk_5d", "ev_biz_5d",   # 近5日有对应事件组公告
    "praise_20d",            # 近20个交易日有"买入"评级研报（专家唱多）
    "praise_hi",             # 唱多 × 高位(price_pos_60>0.7)  交互
    "praise_mom5",           # 唱多 × 近5日大涨(mom5>0.10)    交互
]
EV_GROUPS = {
    "ev_reorg_5d": "重组并购", "ev_perf_5d": "业绩类", "ev_reduce_5d": "减持质押",
    "ev_buyback_5d": "增持回购", "ev_risk_5d": "风险类", "ev_biz_5d": "经营类",
}
ANN_GROUP_MAP = {
    "重组并购": ["保荐/核查意见", "其他增发事项公告", "关联交易", "收购报告书"],
    "业绩类": ["业绩预告", "三季度报告全文", "一季度报告全文", "半年度报告全文", "年度报告全文",
               "业绩快报", "分配方案实施", "分配方案预告", "业绩修正"],
    "减持质押": ["股份质押、冻结", "股东/实际控制人股份减持", "限售股份上市流通", "权益变动报告书"],
    "增持回购": ["回购预案", "回购进展情况", "股东/实际控制人股份增持", "员工持股计划", "股权激励进展公告"],
    "风险类": ["诉讼仲裁", "提供/对外担保公告", "借贷", "股票交易异常波动", "立案调查"],
    "经营类": ["签订协议", "月度经营情况", "中标"],
}


def _ann_group(t):
    t = str(t).strip()
    for g, types in ANN_GROUP_MAP.items():
        if t in types:
            return g
    return "常规低信息"


def build_event_map(symbols: list = None):
    """读公告+研报 -> {symbol: DataFrame[date, has_ann_5d, ev_*_5d, praise_20d]}。
    date = 该股实际交易日（升序）；各列=当日及之前窗口内有无事件（0/1），无未来泄漏。
    symbols=None 时用本地库全部股票（预测路径共用）。"""
    EV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "events")
    ann_path = os.path.join(EV_DIR, "announcements.csv")
    res_path = os.path.join(EV_DIR, "research_reports.csv")
    if not os.path.exists(ann_path):
        print("[事件] 无 announcements.csv，事件特征全 0")
        return {}
    if symbols is None:
        symbols = list_symbols()
    ann = pd.read_csv(ann_path, dtype={"代码": str})
    ann["代码"] = ann["代码"].str.zfill(6)
    ann["date"] = pd.to_datetime(ann["公告日期"]).dt.normalize()
    ann["group"] = ann["公告类型"].map(_ann_group)
    ann_by = {s: g for s, g in ann.groupby("代码")}

    res_by = {}
    if os.path.exists(res_path):
        res = pd.read_csv(res_path, dtype={"股票代码": str})
        res["股票代码"] = res["股票代码"].str.zfill(6)
        res["date"] = pd.to_datetime(res["日期"]).dt.normalize()
        res["praise"] = (res["东财评级"] == "买入").astype(int)
        res_by = {s: g for s, g in res.groupby("股票代码")}

    out = {}
    for sym in symbols:
        d = load_daily(sym)
        if d.empty:
            continue
        dates = pd.to_datetime(d["date"]).sort_values().reset_index(drop=True)
        n = len(dates)
        if n < 30:
            continue
        daily = {c: np.zeros(n) for c in ["has_ann"] + list(EV_GROUPS) + ["praise"]}
        ts = dates.to_numpy()

        # 公告：事件日对齐到 >= 公告日的第一个交易日（盘后/周末发布 → 下一交易日生效）
        a = ann_by.get(sym)
        if a is not None:
            for ev_date, g in zip(a["date"].to_numpy(), a["group"].to_numpy()):
                i = np.searchsorted(ts, ev_date)
                if i < n:
                    daily["has_ann"][i] = 1
                    gcol = [k for k, v in EV_GROUPS.items() if v == g]
                    if gcol:
                        daily[gcol[0]][i] = 1
        r = res_by.get(sym)
        if r is not None:
            pr = r[r["praise"] == 1]
            for ev_date in pr["date"].to_numpy():
                i = np.searchsorted(ts, ev_date)
                if i < n:
                    daily["praise"][i] = 1

        ddf = pd.DataFrame(daily, index=range(n))
        roll5 = ddf.rolling(5, min_periods=1).sum()
        out[sym] = pd.DataFrame({
            "date": dates,
            "has_ann_5d": (roll5["has_ann"] > 0).astype(int),
            **{c: (roll5[c] > 0).astype(int) for c in EV_GROUPS},
            "praise_20d": (ddf["praise"].rolling(20, min_periods=1).sum() > 0).astype(int),
        })
    print(f"[事件] 事件面板就绪: {len(out)}/{len(symbols)} 只")
    return out


FIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "financials.csv")


def load_fin_map():
    """读 financials.csv -> {symbol: DataFrame[avail, 财务特征]}；avail = 报告期+90天（近似披露延迟）。"""
    if not os.path.exists(FIN_PATH):
        return {}
    df = pd.read_csv(FIN_PATH, parse_dates=["report_date"], dtype={"symbol": str})
    df["symbol"] = df["symbol"].str.strip().str.zfill(6)   # 修复前导0丢失（2401 -> 002401）
    df["avail"] = df["report_date"] + pd.Timedelta(days=90)
    out = {}
    for sym, g in df.groupby("symbol"):
        out[sym] = g[["avail"] + FIN_FEATURES].sort_values("avail")
    return out


def build_features_one_symbol(symbol: str, horizon: int, until=None, fin_map=None, event_map=None) -> pd.DataFrame:
    """给单只股票算因子特征 + 标签，返回带symbol列的DataFrame（还没丢弃NaN）。
    until: 'YYYYMMDD' 或 'YYYY-MM-DD'，仅使用 <= until 的数据（样本外/walk-forward 训练用）。
    event_map: {symbol: 事件面板}（P1 新闻/公告信号，窗口聚合，0/1）。"""
    df = load_daily(symbol)
    if df.empty or len(df) < 80:
        return pd.DataFrame()

    if until is not None:
        df = df[df["date"] <= pd.to_datetime(until)]

    df = df.sort_values("date").reset_index(drop=True)
    df = add_moving_averages(df, windows=(5, 20, 60))
    df = add_momentum(df, windows=(5, 20, 60))
    df = add_volatility(df, window=20)
    df = add_rsi(df, window=14)
    df = add_bollinger(df, window=20)
    df = add_atr(df, window=14)
    df = add_trend_strength(df)
    df = add_extended_features(df)

    # ---- 转成相对比例特征，避免绝对价格量级差异干扰模型 ----
    df["price_vs_ma5"] = df["close"] / df["ma5"] - 1
    df["price_vs_ma20"] = df["close"] / df["ma20"] - 1
    df["price_vs_ma60"] = df["close"] / df["ma60"] - 1
    df["ma5_vs_ma20"] = df["ma5"] / df["ma20"] - 1
    df["ma20_vs_ma60"] = df["ma20"] / df["ma60"] - 1
    df["boll_pct"] = (df["close"] - df["boll_low"]) / (df["boll_up"] - df["boll_low"])
    df["atr_pct"] = df["atr"] / df["close"]

    # ---- 财务特征（慢变量）：按可用日(报告期+90天)前向填充，缺失补0 ----
    for c in FIN_FEATURES:
        df[c] = 0.0
    if fin_map and symbol in fin_map:
        fdf = fin_map[symbol]
        df["_date"] = df["date"]
        merged = pd.merge_asof(
            df.drop(columns=FIN_FEATURES).sort_values("_date"), fdf,
            left_on="_date", right_on="avail", direction="backward",
        )
        for c in FIN_FEATURES:
            df[c] = merged[c].fillna(0.0)
        df.drop(columns=["_date"], inplace=True)

    # ---- 事件特征（P1：公告/研报窗口聚合，缺失=0 无事件） ----
    for c in EVENT_FEATURES:
        df[c] = 0.0
    if event_map and symbol in event_map:
        evdf = event_map[symbol]
        df["_date"] = df["date"]
        base_ev = [c for c in EVENT_FEATURES if c not in ("praise_hi", "praise_mom5")]
        merged = pd.merge_asof(
            df.drop(columns=EVENT_FEATURES).sort_values("_date"), evdf,
            left_on="_date", right_on="date", direction="backward",
        )
        for c in base_ev:
            df[c] = merged[c].fillna(0.0)
        # 交互项：唱多 × 高位 / 唱多 × 近5日大涨（直接由当日价量状态现算）
        df["praise_hi"] = df["praise_20d"] * (df["price_pos_60"] > 0.7).astype(int)
        df["praise_mom5"] = df["praise_20d"] * (df["mom5"] > 0.10).astype(int)
        df.drop(columns=["_date"], inplace=True)

    # ---- 标签：未来horizon日后收盘价是否上涨 ----
    future_return = df["close"].shift(-horizon) / df["close"] - 1
    df["future_ret"] = future_return  # 排序学习(rank)用原始未来收益做组内排名标签
    df["target"] = (future_return > 0).astype(int)
    # 最后horizon行没有"未来"数据，标签是无效的，后面会连同NaN特征一起丢弃
    df.loc[df.index[-horizon:], "target"] = np.nan
    df.loc[df.index[-horizon:], "future_ret"] = np.nan

    df["symbol"] = symbol
    return df


def build_dataset(symbols: list, horizon: int, until=None, fin_map=None, event_map=None) -> pd.DataFrame:
    """批量拉所有股票的特征，拼成一张大表。"""
    frames = []
    for i, symbol in enumerate(symbols, 1):
        df = build_features_one_symbol(symbol, horizon, until=until, fin_map=fin_map, event_map=event_map)
        if df.empty:
            print(f"[跳过 {i}/{len(symbols)}] {symbol} 数据太少")
            continue
        frames.append(df)
        print(f"[{i}/{len(symbols)}] {symbol} 生成特征 {len(df)} 行")

    if not frames:
        raise RuntimeError("没有任何股票生成出特征数据，请先用 downloader 下载更多股票")

    full = pd.concat(frames, ignore_index=True)
    before = len(full)
    feature_cols = list(FEATURE_COLS)
    if fin_map:
        feature_cols += FIN_FEATURES
    if event_map:
        feature_cols += EVENT_FEATURES
    full = full.dropna(subset=feature_cols + ["target", "future_ret"]).reset_index(drop=True)
    print(f"\n合并后共 {before} 行，去除指标预热期/无标签的NaN后剩 {len(full)} 行可用于训练")
    return full, feature_cols


def time_based_split(df: pd.DataFrame, test_ratio: float = 0.2):
    """
    按时间顺序切分训练/测试集：每只股票各自按时间排序后，
    前(1-test_ratio)作训练，后test_ratio作测试，再拼起来。
    绝不能用sklearn的train_test_split随机切分，会造成用未来数据预测过去的信息泄漏。
    """
    train_parts, test_parts = [], []
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("date")
        cut = int(len(g) * (1 - test_ratio))
        train_parts.append(g.iloc[:cut])
        test_parts.append(g.iloc[cut:])
    return pd.concat(train_parts, ignore_index=True), pd.concat(test_parts, ignore_index=True)


def train_and_evaluate(train_df: pd.DataFrame, test_df: pd.DataFrame,
                       n_estimators: int = 300, model_type: str = "rf",
                       feature_cols: list = None):
    from sklearn.metrics import accuracy_score, classification_report

    feature_cols = feature_cols or FEATURE_COLS
    X_train, y_train = train_df[feature_cols], train_df["target"]
    X_test, y_test = test_df[feature_cols], test_df["target"]

    if model_type == "lgb":
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            raise RuntimeError("LightGBM 未安装，请先执行: pip install lightgbm")
        model = LGBMClassifier(
            n_estimators=n_estimators,
            max_depth=6,
            min_child_samples=30,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
    else:
        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=6,            # 限制树深，避免在噪声很大的金融数据上过拟合
            min_samples_leaf=30,    # 叶子节点至少30个样本，同样是为了抗过拟合
            random_state=42,
            n_jobs=-1,
        )
    model.fit(X_train, y_train)

    train_acc = accuracy_score(y_train, model.predict(X_train))
    test_acc = accuracy_score(y_test, model.predict(X_test))
    baseline_acc = max(y_test.mean(), 1 - y_test.mean())  # 永远猜多数类的准确率，作为对照基线

    print(f"\n===== 训练结果 (模型={model_type}, 特征数={len(feature_cols)}) =====")
    print(f"训练集准确率: {train_acc:.4f}")
    print(f"测试集准确率: {test_acc:.4f}")
    print(f"基线(永远猜多数类)准确率: {baseline_acc:.4f}  <- 模型必须明显高于这个数才算学到了东西")
    print(f"\n测试集详细分类报告:")
    print(classification_report(y_test, model.predict(X_test), target_names=["跌", "涨"]))

    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("特征重要性排序(Top 15):")
    print(importances.head(15).to_string())

    return model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=5, help="预测未来几个交易日后的涨跌")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="每只股票末尾多少比例数据作测试集")
    parser.add_argument("--n-estimators", type=int, default=300, help="随机森林树的数量")
    parser.add_argument("--symbols", type=str, default=None,
                         help="逗号分隔指定股票，不传则用本地库里所有已下载的股票")
    parser.add_argument("--until", type=str, default=None,
                         help="'YYYYMMDD'，只用 <= 该日期的数据训练（样本外验证时用，训练截止日）")
    parser.add_argument("--out", type=str, default="output/model_updown.joblib",
                         help="模型输出路径（walk-forward 每折输出到不同文件）")
    parser.add_argument("--model", type=str, default="rf", choices=["rf", "lgb"],
                         help="模型类型：rf=随机森林(默认) lgb=LightGBM")
    args = parser.parse_args()

    symbols = ([s.strip() for s in args.symbols.split(",")] if args.symbols
               else list_symbols())
    print(f"本次训练使用 {len(symbols)} 只股票: {symbols[:20]} ... 共{len(symbols)}只")
    if args.until:
        print(f"样本外模式：训练数据截止 {args.until}（之后的数据留给回测验证）")

    fin_map = load_fin_map()
    if fin_map:
        print(f"财务特征可用: {len(fin_map)} 只有财务数据")
    else:
        print("财务特征不可用（未找到 output/financials.csv，仅使用技术特征）")

    full, feature_cols = build_dataset(symbols, horizon=args.horizon, until=args.until, fin_map=fin_map)
    train_df, test_df = time_based_split(full, test_ratio=args.test_ratio)
    print(f"训练集 {len(train_df)} 行，测试集 {len(test_df)} 行")

    model = train_and_evaluate(train_df, test_df, n_estimators=args.n_estimators,
                               model_type=args.model, feature_cols=feature_cols)

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_cols": feature_cols,
        "horizon": args.horizon,
        "model_type": args.model,
        "trained_on_symbols": symbols,
        "train_until": args.until,
    }, out_path)
    print(f"\n模型已保存至 {out_path}")


if __name__ == "__main__":
    main()
