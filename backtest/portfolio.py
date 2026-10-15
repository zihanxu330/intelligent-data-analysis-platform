# -*- coding: utf-8 -*-
"""组合化回测：定期再平衡的选股轮动框架（机构做法 = 打分选股 + 定期再平衡）。

对比三组组合（全部 A股成本、双边 0.05% 简化）：
  - AI组合:  每期按模型预测上涨概率(ai_prob)降序选 Top-N 等权
  - 动量组合: 每期按20日动量(mom20)降序选 Top-N 等权（规则对照）
  - 全池基准: 池内所有股票等权买入持有（不调仓）

纯 pandas/numpy 实现（不用 backtrader 多data），逻辑透明、可复现。

用法:
    python backtest/portfolio.py --model output/model_updown.joblib \
        --symbols-file output/symbols_300.txt --start 20250101 --end 20261015 \
        --top-n 5 --rebalance 20 --out output/portfolio_vs_20261015.csv
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from data_engine.database import load_daily
from models.predict import add_ai_score, add_rank_score

# A股真实成本（万3佣金 + 卖出印花税0.05% + 双边过户费0.001%）；最低5元佣金在等分大持仓下通常不触发，忽略
BUY_COST = 0.0003 + 0.00001      # 佣金万3 + 过户费
SELL_COST = 0.0003 + 0.0005 + 0.00001  # 佣金万3 + 印花税0.05% + 过户费
SIMPLE_COST = 0.0005             # 旧简化：单边0.05%


def load_panel(symbols, start, end, model_path, scorer="ai_prob", timing_model=None):
    """返回 {symbol: DataFrame(index=date, close, ai_prob, mom20)}，仅保留区间内且足长样本。
    scorer=rank_score 时加载排序模型打分列 rank_score（替代 ai_prob）。
    timing_model 额外加载分类模型 ai_prob 列，供市场状态择时使用。"""
    panel = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty:
            continue
        df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
        if len(df) < 30:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["mom20"] = df["close"].pct_change(20)
        if model_path:
            if scorer == "rank_score":
                df = add_rank_score(df, model_path=model_path, symbol=sym)
            else:
                df = add_ai_score(df, model_path=model_path, symbol=sym)
        if timing_model:
            df = add_ai_score(df, model_path=timing_model, symbol=sym)
        cols = ["close", "mom20"]
        cols.append("rank_score" if scorer == "rank_score" else "ai_prob")
        if timing_model and scorer == "rank_score":
            cols.append("ai_prob")  # 择时列（仅 rank 选股 + 分类择时 模式需要）
        panel[sym] = df.set_index("date")[cols]
    return panel


def run_rebalance(panel, scorer: str, top_n: int, rebalance_days: int,
                  cash: float = 1_000_000.0, warmup: int = 60,
                  timing_col: str = None, timing_threshold: float = 0.5,
                  timing_mode: str = "fixed", timing_window: int = 20,
                  next_day_exec: bool = True, cost_mode: str = "real"):
    """按给定打分列做定期再平衡轮动，返回 (净值Series, 调仓次数)。

    - 信号日收盘后打分（无未来函数）；next_day_exec=True 时在信号日次日按收盘价成交
      （消除"当日信号当日成交"的lookahead，等效 T+1 执行）。
    - timing_col: 择时列。fixed=均值低于阈值空仓；rolling=均值低于过去
      timing_window 个交易日的滚动均值则空仓（自适应）。
    - cost_mode: real=买0.031%/卖0.081%；simple=双边各0.05%。
    """
    buy_c = BUY_COST if cost_mode == "real" else SIMPLE_COST
    sell_c = SELL_COST if cost_mode == "real" else SIMPLE_COST

    all_dates = sorted(set().union(*[p.index for p in panel.values()]))
    all_dates = pd.to_datetime(all_dates)
    rebal_set = set(all_dates[i] for i in range(warmup, len(all_dates), rebalance_days))

    # 择时序列：fixed/rolling 用全池打分列均值；mavg 用全池等权指数(close均值)vs移动均线
    timing_series = None
    if timing_col and timing_mode != "mavg":
        timing_series = pd.Series({
            d: float(np.mean([p.loc[d, timing_col] for p in panel.values()
                              if d in p.index and pd.notna(p.loc[d, timing_col])]))
            for d in all_dates if any(d in p.index and pd.notna(p.loc[d, timing_col]) for p in panel.values())
        })
        timing_series = timing_series.reindex(all_dates)
        if timing_mode == "rolling":
            roll = timing_series.rolling(timing_window, min_periods=max(5, timing_window // 4)).mean()
            timing_series = timing_series.combine(roll, lambda cur, ref: cur if pd.isna(ref) or cur >= ref else np.nan)
            # np.nan 标记"低于滚动常态"→ 空仓；缺失(无常态)时按不空仓处理
    if timing_mode == "mavg":
        # 等权指数 = 每日全池收盘价均值（归一化）；低于自身N日均线 → 空仓
        idx = pd.Series({d: float(np.mean([p.loc[d, "close"] for p in panel.values()
                                           if d in p.index and pd.notna(p.loc[d, "close"])]))
                         for d in all_dates}).reindex(all_dates).ffill()
        idx = idx / idx.iloc[0]
        roll = idx.rolling(timing_window, min_periods=max(5, timing_window // 4)).mean()
        timing_series = idx.combine(roll, lambda cur, ref: cur if pd.isna(ref) or cur >= ref else np.nan)

    # 信号日 -> (scores, timed_out)，执行日在信号日之后首个交易日
    pending = {}
    holdings = {}          # sym -> shares
    nav = []
    total_rebals = 0
    for i, d in enumerate(all_dates):
        if d in rebal_set:
            scores = {sym: p.loc[d, scorer]
                      for sym, p in panel.items() if d in p.index and pd.notna(p.loc[d, scorer])}
            timed_out = False
            if timing_series is not None:
                tv = timing_series.loc[d]
                if timing_mode in ("rolling", "mavg"):
                    timed_out = bool(pd.isna(tv))  # 低于滚动/均线常态 → NaN → 空仓
                else:
                    timed_out = bool(tv < timing_threshold)
            exec_date = all_dates[i + 1] if i + 1 < len(all_dates) else None
            if exec_date is not None:
                pending[exec_date] = (scores, timed_out)
        if d in pending:
            scores, timed_out = pending.pop(d)
            # 卖出旧仓（按执行日收盘成交，停牌股按复牌后最近收盘价；扣卖出成本）
            if holdings:
                M = sum(sh * float(panel[sym]["close"].asof(d))
                        for sym, sh in holdings.items())
            else:
                M = nav[-1] if nav else cash
            M *= (1.0 - sell_c)
            if timed_out:
                holdings = {}
            elif len(scores) >= top_n:
                picks = sorted(scores, key=scores.get, reverse=True)[:top_n]
                M *= (1.0 - buy_c)  # 买入成本
                holdings = {sym: (M / top_n) / float(panel[sym]["close"].asof(d)) for sym in picks}
                total_rebals += 1
            else:
                holdings = {}
        # 每日净值（停牌股按最近收盘价估值）
        if holdings:
            v = sum(sh * float(panel[sym]["close"].asof(d)) for sym, sh in holdings.items())
        else:
            v = M if holdings or "M" in dir() else cash
        nav.append(v)

    nav_s = pd.Series(nav, index=all_dates)
    return nav_s, total_rebals


def run_benchmark(panel, cash=1_000_000.0):
    """全池等权买入持有基准：期初按每股 1/N 资金买入，之后市值自然变化，不调仓。"""
    starts = {}
    for sym, p in panel.items():
        row = p.iloc[0]
        starts[sym] = (row["close"], row.name)
    total_alloc = 0.0
    shares = {}
    for sym, (px, _d) in starts.items():
        w = cash / len(panel)
        shares[sym] = w / px
        total_alloc += w
    all_dates = sorted(set().union(*[p.index for p in panel.values()]))
    nav = []
    for d in all_dates:
        v = sum(sh * float(panel[sym]["close"].asof(d)) for sym, sh in shares.items())
        nav.append(v)
    return pd.Series(nav, index=pd.to_datetime(all_dates))


def summary(nav: pd.Series, name: str, rebals: int = None):
    total = nav.iloc[-1] / nav.iloc[0] - 1
    days = len(nav)
    annual = (1 + total) ** (252 / days) - 1 if days > 0 else 0
    peak = nav.cummax()
    mdd = ((nav - peak) / peak).min()
    row = {"组合": name, "总收益%": round(total * 100, 2), "年化%": round(annual * 100, 2),
           "最大回撤%": round(mdd * 100, 2)}
    if rebals is not None:
        row["调仓次数"] = rebals
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="AI模型路径(不传则AI组合不可用)")
    parser.add_argument("--symbols-file", type=str, default=None, help="股票代码列表文件(每行一个)")
    parser.add_argument("--start", type=str, default="20250101")
    parser.add_argument("--end", type=str, default="20261015")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--rebalance", type=int, default=20, help="调仓周期(交易日)")
    parser.add_argument("--scorer", type=str, default="ai_prob",
                        help="AI组合打分列：ai_prob(分类模型概率) 或 rank_score(排序模型分数)")
    parser.add_argument("--timing-model", type=str, default=None,
                        help="择时模型路径(分类模型)：调仓日用全池ai_prob均值做仓位择时，低于阈值则空仓")
    parser.add_argument("--timing-threshold", type=float, default=0.5)
    parser.add_argument("--timing-mode", type=str, default="fixed", choices=["fixed", "rolling", "mavg"],
                        help="fixed=低于固定阈值空仓；rolling=低于过去N日滚动均值则空仓；mavg=全池等权指数低于N日均线则空仓")
    parser.add_argument("--timing-window", type=int, default=20)
    parser.add_argument("--next-day", action="store_true", default=True,
                        help="信号次日收盘成交（消除当日信号当日成交的lookahead，等效T+1执行）")
    parser.add_argument("--cost-mode", type=str, default="real", choices=["real", "simple"],
                        help="real=A股真实成本(买0.031%/卖0.081%含印花税)；simple=双边0.05%")
    parser.add_argument("--out", type=str, default="output/portfolio_vs_20261015.csv")
    args = parser.parse_args()

    if args.symbols_file and os.path.exists(args.symbols_file):
        symbols = [s.strip() for s in open(args.symbols_file, encoding="utf-8") if s.strip()]
    else:
        symbols = [s.strip() for s in sys.stdin.read().split() if s.strip()]
    if not symbols:
        raise SystemExit("未提供股票列表：--symbols-file 或 stdin")

    panel = load_panel(symbols, args.start, args.end, args.model,
                       scorer=args.scorer, timing_model=args.timing_model)
    if not panel:
        raise SystemExit(f"区间 {args.start}~{args.end} 内没有有效股票数据（检查数据是否已下载）")
    print(f"组合回测: {len(panel)} 只有效股票, {args.start}~{args.end}, Top{args.top_n}, 每{args.rebalance}日调仓")

    timing_col = "ai_prob" if (args.timing_model and args.timing_mode != "mavg") else None

    rows = []
    nav_ai, nav_mom, nav_bench = None, None, None

    nav_mom, reb_mom = run_rebalance(panel, "mom20", args.top_n, args.rebalance,
                                     next_day_exec=args.next_day, cost_mode=args.cost_mode)
    nav_mom.to_csv(args.out.replace(".csv", "_mom.csv"), header=["净值"])
    rows.append(summary(nav_mom, "动量TopN组合", reb_mom))
    nav_bench = run_benchmark(panel)
    nav_bench.to_csv(args.out.replace(".csv", "_bench.csv"), header=["净值"])
    rows.append(summary(nav_bench, "全池等权基准"))

    if args.model:
        nav_ai, reb_ai = run_rebalance(panel, args.scorer, args.top_n, args.rebalance,
                                       timing_col=timing_col,
                                       timing_threshold=args.timing_threshold,
                                       timing_mode=args.timing_mode,
                                       timing_window=args.timing_window,
                                       next_day_exec=args.next_day, cost_mode=args.cost_mode)
        nav_ai.to_csv(args.out.replace(".csv", "_ai.csv"), header=["净值"])
        rows.append(summary(nav_ai, f"AI[{args.scorer}]TopN组合", reb_ai))

    out_df = pd.DataFrame(rows)
    print(out_df.to_string(index=False))
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print("已保存:", args.out)

    # 净值曲线合并输出（便于画图）
    merged = pd.DataFrame({"动量组合": nav_mom, "全池基准": nav_bench})
    if nav_ai is not None:
        merged[f"AI[{args.scorer}]组合"] = nav_ai
    merged.to_csv(args.out.replace(".csv", "_nav.csv"), encoding="utf-8-sig")


if __name__ == "__main__":
    main()
