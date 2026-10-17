# -*- coding: utf-8 -*-
"""排序学习训练：用 LightGBM 的 LGBMRanker 直接优化"选股排名"。

为什么换目标：当前分类模型预测"未来5日涨/跌"只有52%准确率（弱信号），
而组合化回测真正需要的是"同一批股票里选谁"——排序损失(lambdarank)让模型
直接学习截面内未来收益的相对高低，弱信号也能被"排名正确"放大成组合收益差。

数据组织：
  - 组(Query/Group)：每个交易日一个截面，组内样本 = 当日所有股票
  - 标签(Label)：指定 horizon 日收益在截面内的升序排名(1..n，越大=未来收益越高=越相关)
  - 特征：与 train_model.py 完全一致的 23 个（技术19 + 财务4）

用法:
    python train_rank.py --until 20251231 --out output/model_rank_h3p.joblib
    python train_rank.py --symbols 000001,600519 --out output/model_rank_small.joblib

验证：控制台输出测试期按截面的排序质量及 Top5 平均收益 vs 全池平均。
最终效果以组合化回测为准（backtest/portfolio.py --scorer rank_score）。
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)

from train_model import build_dataset, load_fin_map, build_event_map
from data_engine.database import list_symbols
from models.model_io import save_bundle


def add_rank_labels(full: pd.DataFrame) -> pd.DataFrame:
    """截面内对未来5日收益排名，压缩成 5 档相关度(0..4) 作为排序标签；组=交易日。
    LightGBM lambdarank 的 label 是离散 relevance 等级（不是连续大范围排名），
    分档(0=最差1/5，4=最好1/5)是标准做法，也规避 label 等级数量上限。"""
    full = full.copy()
    rank = full.groupby("date")["future_ret"].rank(method="first")
    size = full.groupby("date")["future_ret"].transform("size")
    full["rank_label"] = ((rank - 1) / size * 5).astype(int).clip(0, 4)
    return full


def date_split_by_dates(full: pd.DataFrame, test_ratio: float = 0.2, purge: int = 0):
    """按日期切分并在训练/验证之间留 purge 个完整交易日的空档。"""
    if not 0 < test_ratio < 1:
        raise ValueError("test_ratio 必须介于 0 和 1 之间")
    if purge < 0:
        raise ValueError("purge 不能为负数")
    dates = np.array(sorted(full["date"].unique()))
    cut = int(len(dates) * (1 - test_ratio))
    if cut <= purge or cut >= len(dates):
        raise ValueError("日期样本不足以在 purge 间隔后切出训练集和验证集")
    train_dates = set(dates[:max(0, cut - purge)])
    test_dates = set(dates[cut:])
    train_df = full[full["date"].isin(train_dates)]
    test_df = full[full["date"].isin(test_dates)]
    return train_df, test_df


def ndcg_at_k(test_df: pd.DataFrame, k: int = 5):
    """测试期按截面评估：模型打分Top-k 的平均未来收益 vs 全池平均收益。"""
    rows = []
    for d, g in test_df.groupby("date"):
        if len(g) <= k:
            continue
        top = g.nlargest(k, "rank_score")
        rows.append({
            "date": d,
            "topk_ret": top["future_ret"].mean(),
            "pool_ret": g["future_ret"].mean(),
        })
    if not rows:
        return None
    r = pd.DataFrame(rows)
    return r["topk_ret"].mean(), r["pool_ret"].mean()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=3,
                        help="排序标签预测期限（默认3日，与默认模型名 model_rank_h3p.joblib 一致）")
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--symbols", type=str, default=None,
                        help="逗号分隔指定股票，不传则用本地库全部股票")
    parser.add_argument("--until", type=str, default=None,
                        help="只用 <= 该日期的数据训练（样本外口径）")
    parser.add_argument("--purge", type=int, default=None,
                        help="从训练数据尾部剔除最后N个交易日（防标签跨越切分点；默认=horizon）")
    parser.add_argument("--out", type=str, default="output/model_rank_h3p.joblib")
    parser.add_argument("--no-prune", action="store_true",
                        help="关闭死特征剪枝（默认剪掉 vwap_dev/price_vs_ma20/boll_pct/trend_strength）")
    event_group = parser.add_mutually_exclusive_group()
    event_group.add_argument("--with-event", action="store_true", dest="with_event",
                             help="显式加入公告/研报特征（用于消融对比；默认关闭）")
    event_group.add_argument("--no-event", action="store_false", dest="with_event",
                             help="不加载公告/研报事件特征（默认）")
    parser.set_defaults(with_event=False)
    args = parser.parse_args()

    if args.horizon < 1 or args.n_estimators < 1:
        parser.error("--horizon 和 --n-estimators 必须为正整数")
    if args.purge is not None and args.purge < 0:
        parser.error("--purge 不能为负数")
    if not 0 < args.test_ratio < 1:
        parser.error("--test-ratio 必须介于 0 和 1 之间")

    symbols = ([s.strip() for s in args.symbols.split(",")] if args.symbols
               else list_symbols())
    print(f"排序学习训练: {len(symbols)} 只, 特征与 train_model 一致")
    if args.until:
        print(f"样本外模式：训练数据截止 {args.until}")

    fin_map = load_fin_map()
    event_map = build_event_map(symbols) if args.with_event else {}
    full, feature_cols = build_dataset(symbols, horizon=args.horizon,
                                       until=args.until, fin_map=fin_map, event_map=event_map)
    full = add_rank_labels(full)
    # purge/embargo：剔除尾部 N 个交易日，使训练集最后一日的标签窗口不跨越
    # 后续的 train/test 切分点（标签 future_ret 用到 +horizon 日，若跨过切分点即泄漏）。
    purge = args.purge if args.purge is not None else args.horizon
    if purge > 0:
        all_dates = sorted(full["date"].unique())
        if len(all_dates) <= purge + 1:
            parser.error("样本日期不足以执行指定的 purge")
        keep_until = all_dates[-purge - 1]
        full = full[full["date"] <= keep_until]
        print(f"purge/embargo: 剔除尾部 {purge} 个交易日（训练标签不再覆盖切分点）")
    # 死特征剪枝：三组 horizon 重要性反复垫底的 4 个特征（降噪，保留其余）
    PRUNE = {"vwap_dev", "price_vs_ma20", "boll_pct", "trend_strength"}
    if not args.no_prune:
        feature_cols = [c for c in feature_cols if c not in PRUNE]
        print(f"已剪枝 {len(PRUNE)} 个死特征: {sorted(PRUNE)}")
    print(f"特征维度: {len(feature_cols)}")
    full = full.sort_values("date")
    # time-decay sample weight: more recent cross-sections matter more (half-life ~180 trading days)
    dates = pd.to_datetime(full["date"])
    days_from_last = (dates.max() - dates).dt.days
    full["sample_weight"] = np.exp(-days_from_last / 180.0)

    train_df, test_df = date_split_by_dates(full, test_ratio=args.test_ratio,
                                            purge=max(args.horizon, purge))
    print(f"训练集 {len(train_df)} 行（{train_df['date'].nunique()} 个交易日截面）")
    print(f"测试集 {len(test_df)} 行（{test_df['date'].nunique()} 个交易日截面）")

    from lightgbm import LGBMRanker
    model = LGBMRanker(
        objective="lambdarank",
        n_estimators=args.n_estimators,
        max_depth=6,
        min_child_samples=30,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    group_sizes = train_df.groupby("date").size().tolist()
    model.fit(
        train_df[feature_cols], train_df["rank_label"],
        group=group_sizes,
        sample_weight=train_df["sample_weight"].to_numpy(),
    )

    imp = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\nFeature importance (Top 15):")
    print(imp.head(15).to_string())
    print("Bottom 5:", list(imp.tail(5).index))

    test_df = test_df.copy()
    test_df["rank_score"] = model.predict(test_df[feature_cols])
    train_df = train_df.copy()
    train_df["rank_score"] = model.predict(train_df[feature_cols])

    ndcg = ndcg_at_k(test_df, k=5)
    if ndcg:
        topk, pool = ndcg
        print(f"\n===== 测试期排序质量 =====")
        print(f"Top-5平均未来{args.horizon}日收益: {topk * 100:.2f}%  vs  全池平均: {pool * 100:.2f}%  (差 {(topk - pool) * 100:.2f}pct)")
        print(f"→ 正值说明模型选出的Top-5确实比随机/全池强")

    # 验证完成后，用完整的可用训练区间（外部 cut 前已 purge）重训最终模型。
    final_groups = full.groupby("date").size().tolist()
    model.fit(full[feature_cols], full["rank_label"], group=final_groups,
              sample_weight=full["sample_weight"].to_numpy())
    save_bundle(model, feature_cols, args.out, objective="rank",
                meta={"horizon": args.horizon, "model_type": "lgb_ranker",
                      "trained_on_symbols": symbols, "train_until": args.until,
                      "purge_days": max(args.horizon, purge)})
    out_path = args.out
    print(f"\n排序模型已保存至 {out_path}")
    print("用法: python backtest/portfolio.py --model <模型> --scorer rank_score ...")


if __name__ == "__main__":
    main()
