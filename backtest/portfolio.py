# -*- coding: utf-8 -*-
"""组合化回测：定期再平衡的选股轮动框架（机构做法 = 打分选股 + 定期再平衡）。

对比三组组合（全部 A股成本）：
  - AI组合:  每期按模型打分(rank_score/ai_prob)降序选 Top-N 等权
  - 动量组合: 每期按20日动量(mom20)降序选 Top-N 等权（规则对照）
  - 全池基准: 池内所有股票等权买入持有（不调仓）

纯 pandas/numpy 实现，逻辑透明、可复现。

成交校准（第2项优化）：
  - 成交价：信号日次日开盘（默认 next_open）
  - 滑点：买 +slippage / 卖 -slippage（默认 0.1%）
  - 最低佣金：单笔佣金 max(万3×成交额, 5元)
  - 涨跌停：默认涨停不可买、跌停不可卖（按板块阈值近似，忽略ST）
  - 停牌：当日无交易数据 → 不可成交（卖出保留至可卖日，买入跳过）
  - 现金账户：停牌/涨跌停未成交部分保留现金，不复投（比旧"全仓单次扣费"更真实）

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

# A股成本
COMMISSION_RATE = 0.0003       # 佣金万3
STAMP_TAX = 0.0005             # 卖出印花税 0.05%
TRANSFER_FEE = 0.00001         # 过户费（双边）
SIMPLE_COST = 0.0005           # 旧简化：单边0.05%
STAMP_TAX_CHANGE_DATE = pd.Timestamp("2023-08-28")


def load_industry_map(path=None, symbols=None):
    """读取缓存行业映射；缺缓存时通过 AkShare 东财行业板块成分表构建。

    返回 (code -> industry, failures)。未知代码保留并映射为“未知”。"""
    path = path or os.path.join(PROJ, "output", "symbols_industry.csv")
    symbols = [str(x).strip().zfill(6) for x in (symbols or [])]
    cache = pd.DataFrame(columns=["code", "name", "industry"])
    if os.path.exists(path):
        try:
            cache = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig").fillna("")
            cache["code"] = cache["code"].astype(str).str.zfill(6)
            cache = cache.drop_duplicates("code", keep="last")
        except Exception as exc:
            print(f"行业映射缓存读取失败，将重建: {exc}")
    known = dict(zip(cache.get("code", []), cache.get("industry", [])))
    missing = [s for s in symbols if not known.get(s) or known.get(s) == "未知"]
    failures = {}
    if missing:
        try:
            import akshare as ak
            found = {}
            # Prefer Shenwan's stock classification history when its source is reachable.
            try:
                sw = ak.stock_industry_clf_hist_sw()
                if isinstance(sw, pd.DataFrame) and {"symbol", "industry_code"}.issubset(sw.columns):
                    if "update_time" in sw.columns:
                        sw = sw.sort_values("update_time")
                    sw = sw.drop_duplicates("symbol", keep="last")
                    for _, row in sw.iterrows():
                        code = str(row["symbol"]).strip().zfill(6)
                        found[code] = ("", str(row["industry_code"]).strip())
            except Exception:
                pass
            # Eastmoney's industry constituent API is the fallback and covers recent listings.
            boards = ak.stock_board_industry_name_em()
            if not isinstance(boards, pd.DataFrame) or "板块名称" not in boards.columns:
                raise ValueError(f"行业列表列结构异常: {getattr(boards, 'columns', None)}")
            for board in boards["板块名称"].dropna().astype(str).tolist():
                try:
                    members = ak.stock_board_industry_cons_em(symbol=board)
                    if not isinstance(members, pd.DataFrame) or not {"代码", "名称"}.issubset(members.columns):
                        continue
                    for _, row in members[["代码", "名称"]].iterrows():
                        code = str(row["代码"]).strip().zfill(6)
                        found.setdefault(code, (str(row["名称"]), board))
                except Exception as exc:
                    # Board failures are not fatal; later mark unresolved stocks explicitly.
                    continue
            for code in missing:
                cache = cache[cache["code"].astype(str).str.zfill(6) != code]
                if code in found:
                    name, industry = found[code]
                    cache.loc[len(cache)] = [code, name, industry]
                    known[code] = industry
                else:
                    failures[code] = "AkShare 行业成分表未覆盖该代码或接口请求失败"
                    cache.loc[len(cache)] = [code, "", "未知"]
                    known[code] = "未知"
        except Exception as exc:
            for code in missing:
                if code in locals().get("found", {}):
                    name, industry = found[code]
                    cache.loc[len(cache)] = [code, name, industry]
                    known[code] = industry
                else:
                    failures[code] = f"AkShare 行业映射失败: {type(exc).__name__}: {exc}"
                    cache.loc[len(cache)] = [code, "", "未知"]
                    known[code] = "未知"
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        cache[["code", "name", "industry"]].drop_duplicates("code", keep="last").to_csv(
            path, index=False, encoding="utf-8-sig")
    for code in symbols:
        if not known.get(code):
            known[code] = "未知"
            failures.setdefault(code, "缓存中无该代码，未能获取行业")
    return {s: known.get(s, "未知") or "未知" for s in symbols}, failures


def _allocate_capped_weights(symbols, industry_map, industry_cap=None, max_weight=None):
    """确定性等额水位分配，满足个股与行业上限；无法分完的资金留现金。"""
    if not symbols:
        return {}
    weights = {s: 0.0 for s in symbols}
    groups = {s: (industry_map or {}).get(s, "未知") or "未知" for s in symbols}
    for _ in range(len(symbols) + 2):
        residual = 1.0 - sum(weights.values())
        if residual <= 1e-10:
            break
        active = []
        for s in symbols:
            if max_weight is not None and weights[s] >= max_weight - 1e-10:
                continue
            group_total = sum(weights[x] for x in symbols if groups[x] == groups[s])
            if industry_cap is not None and group_total >= industry_cap - 1e-10:
                continue
            active.append(s)
        if not active:
            break
        increment = residual / len(active)
        changed = 0.0
        for s in active:
            room = increment
            if max_weight is not None:
                room = min(room, max_weight - weights[s])
            if industry_cap is not None:
                room = min(room, industry_cap - sum(weights[x] for x in symbols if groups[x] == groups[s]))
            room = max(0.0, room)
            weights[s] += room
            changed += room
        if changed <= 1e-12:
            break
    return weights


def stamp_tax_rate(execution_date) -> float:
    """卖出印花税历史费率：2023-08-28 前0.1%，当日起0.05%。"""
    return 0.001 if pd.Timestamp(execution_date) < STAMP_TAX_CHANGE_DATE else STAMP_TAX


def limit_pct(sym: str) -> float:
    """按板块返回涨停/跌停阈值（近似，忽略 ST/新股无涨跌幅限制期）。"""
    if sym.startswith(("30", "68")):
        return 0.195            # 创业板/科创板 ±20%
    if sym.startswith(("8", "4")):
        return 0.295            # 北交所 ±30%
    return 0.095                # 主板 ±10%


def load_panel(symbols, start, end, model_path, scorer="ai_prob", timing_model=None):
    """返回 {symbol: DataFrame(index=date, open, close, prev_close, mom20, [scorer])}，
    仅保留区间内且足长样本。prev_close 用于涨跌停判定。"""
    panel = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty:
            continue
        # 全历史先算指标：start 处过滤会丢掉 MA60/动量/模型特征所需的 lookback
        df = df.sort_values("date").reset_index(drop=True)
        df["prev_close"] = df["close"].shift(1)
        df["mom20"] = df["close"].pct_change(20)
        if model_path:
            if scorer == "rank_score":
                df = add_rank_score(df, model_path=model_path, symbol=sym)
            else:
                df = add_ai_score(df, model_path=model_path, symbol=sym)
        if timing_model:
            df = add_ai_score(df, model_path=timing_model, symbol=sym)
        df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
        if len(df) < 30:
            continue
        cols = ["open", "close", "prev_close", "mom20"]
        cols.append("rank_score" if scorer == "rank_score" else "ai_prob")
        if timing_model and scorer == "rank_score":
            cols.append("ai_prob")
        panel[sym] = df.set_index("date")[cols]
    return panel


def is_limit_up(p: pd.Series, sym: str) -> bool:
    if pd.isna(p.get("prev_close")) or p["prev_close"] == 0:
        return False
    return (p["close"] / p["prev_close"] - 1) >= limit_pct(sym)


def is_limit_down(p: pd.Series, sym: str) -> bool:
    if pd.isna(p.get("prev_close")) or p["prev_close"] == 0:
        return False
    return (p["close"] / p["prev_close"] - 1) <= -limit_pct(sym)


def run_rebalance(panel, scorer: str, top_n: int, rebalance_days: int,
                  cash: float = 1_000_000.0, warmup: int = 60,
                  timing_col: str = None, timing_threshold: float = 0.5,
                  timing_mode: str = "fixed", timing_window: int = 20,
                  next_day_exec: bool = True, cost_mode: str = "real",
                  fill_mode: str = "next_open", slippage: float = 0.001,
                  min_commission: float = 5.0, limit_check: bool = True,
                  lot100: bool = True, industry_cap: float = None,
                  max_weight: float = None, industry_map=None,
                  return_industry_metrics: bool = False):
    """按给定打分列做定期再平衡轮动，返回 (净值Series, 调仓次数)。

    - 信号日收盘后打分（无未来函数）；next_day_exec=True 时执行日为信号日次日
      （消除 lookahead，等效 T+1）。
    - fill_mode: next_open=执行日开盘价成交（真实）；next_close=执行日收盘价（旧口径）
    - slippage: 双边滑点比例（买上浮/卖下浮），默认 0.1%
    - min_commission: 单笔最低佣金（元），默认 5
    - limit_check: 涨停不可买/跌停不可卖，默认 True
    - lot100: A股 100 股整数倍，默认 True
    - cost_mode: real=佣金万3+历史印花税+过户费；simple=双边各0.05%
    """
    if not panel:
        raise ValueError("panel 不能为空")
    if top_n <= 0:
        raise ValueError("top_n 必须为正整数")
    if rebalance_days <= 0:
        raise ValueError("rebalance_days 必须为正整数")
    if warmup < 0:
        raise ValueError("warmup 不能为负数")
    if not np.isfinite(cash) or cash <= 0:
        raise ValueError("cash 必须是大于0的有限数值")
    if cost_mode not in ("real", "simple"):
        raise ValueError("cost_mode 必须是 'real' 或 'simple'")
    if fill_mode not in ("next_open", "next_close"):
        raise ValueError("fill_mode 必须是 'next_open' 或 'next_close'")
    if not np.isfinite(slippage) or not np.isfinite(min_commission) or slippage < 0 or min_commission < 0:
        raise ValueError("slippage/min_commission 必须是非负有限数值")
    for name, value in (("industry_cap", industry_cap), ("max_weight", max_weight)):
        if value is not None and (not np.isfinite(value) or value <= 0 or value > 1):
            raise ValueError(f"{name} 必须在 (0, 1] 范围内")
    if timing_mode not in ("fixed", "rolling", "mavg"):
        raise ValueError("timing_mode 必须是 fixed、rolling 或 mavg")
    if timing_window <= 0:
        raise ValueError("timing_window 必须为正整数")
    if not np.isfinite(timing_threshold):
        raise ValueError("timing_threshold 必须是有限数值")

    comm_rate = COMMISSION_RATE if cost_mode == "real" else 0.0
    buy_extra = TRANSFER_FEE if cost_mode == "real" else SIMPLE_COST
    sell_extra = TRANSFER_FEE if cost_mode == "real" else SIMPLE_COST

    all_dates = sorted(set().union(*[p.index for p in panel.values()]))
    all_dates = pd.to_datetime(all_dates)
    rebal_set = set(all_dates[i] for i in range(warmup, len(all_dates), rebalance_days))

    # 择时序列（沿用原逻辑）
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
    if timing_mode == "mavg":
        idx = pd.Series({d: float(np.mean([p.loc[d, "close"] for p in panel.values()
                                           if d in p.index and pd.notna(p.loc[d, "close"])]))
                         for d in all_dates}).reindex(all_dates).ffill()
        idx = idx / idx.iloc[0]
        roll = idx.rolling(timing_window, min_periods=max(5, timing_window // 4)).mean()
        timing_series = idx.combine(roll, lambda cur, ref: cur if pd.isna(ref) or cur >= ref else np.nan)

    pending = {}
    holdings = {}          # sym -> {shares, buy_date}
    nav = []
    max_industry_daily = []
    t1_blocked_sells = 0
    total_rebals = 0
    for i, d in enumerate(all_dates):
        if d in rebal_set:
            scores = {sym: p.loc[d, scorer]
                      for sym, p in panel.items() if d in p.index and pd.notna(p.loc[d, scorer])}
            timed_out = False
            if timing_series is not None:
                tv = timing_series.loc[d]
                if timing_mode in ("rolling", "mavg"):
                    timed_out = bool(pd.isna(tv))
                else:
                    timed_out = bool(tv < timing_threshold)
            exec_date = all_dates[i + 1] if i + 1 < len(all_dates) else None
            if exec_date is not None:
                pending[exec_date] = (scores, timed_out)

        if d in pending:
            scores, timed_out = pending.pop(d)

            def exec_price(sym):
                row = panel[sym].loc[d]
                return float(row["open"]) if fill_mode == "next_open" else float(row["close"])

            # ---- 卖出阶段（可卖才卖；停牌/跌停保留到可卖日）----
            new_hold = {}
            for sym, holding in holdings.items():
                sh = holding["shares"]
                if pd.Timestamp(holding["buy_date"]) == d:
                    t1_blocked_sells += 1
                    new_hold[sym] = holding
                    continue
                if d not in panel[sym].index:            # 停牌：当日无交易 → 不可成交
                    new_hold[sym] = holding
                    continue
                row = panel[sym].loc[d]
                if limit_check and is_limit_down(row, sym):   # 跌停卖不出
                    new_hold[sym] = holding
                    continue
                px = exec_price(sym) * (1.0 - slippage)
                gross = sh * px
                min_fee = min_commission if cost_mode == "real" else 0.0
                comm = max(gross * comm_rate, min_fee)
                tax = stamp_tax_rate(d) if cost_mode == "real" else 0.0
                cash += gross - comm - gross * (sell_extra + tax)
            holdings = new_hold

            # ---- 买入阶段 ----
            if not timed_out and len(scores) >= top_n:
                picks = sorted(scores, key=scores.get, reverse=True)[:top_n]
                buyable = []
                for sym in picks:
                    if d not in panel[sym].index:        # 停牌不可买
                        continue
                    row = panel[sym].loc[d]
                    if limit_check and is_limit_up(row, sym):  # 涨停买不进
                        continue
                    if sym not in holdings:
                        buyable.append(sym)
                if buyable:
                    mark_value = sum(h["shares"] * float(panel[s]["close"].asof(d))
                                     for s, h in holdings.items())
                    nav_budget = max(cash + mark_value, 0.0)
                    raw_weights = _allocate_capped_weights(buyable, industry_map, industry_cap, max_weight)
                    budget = min(cash, nav_budget)
                    if industry_cap is not None or max_weight is not None:
                        equal_weight = 1.0 / len(buyable)
                        capped = sum(max(0.0, equal_weight - raw_weights[s]) for s in buyable)
                        reallocated = sum(max(0.0, raw_weights[s] - equal_weight) for s in buyable)
                        mx_ind = max((sum(raw_weights[s] for s in buyable
                                           if (industry_map or {}).get(s, "未知") == ind)
                                      for ind in set((industry_map or {}).get(s, "未知") for s in buyable)), default=0.0)
                        print(f"[{d:%Y-%m-%d}] cap rebalance: max_industry={mx_ind:.1%}, "
                              f"capped={max(0.0, capped)*budget:,.0f} CNY, "
                              f"reallocated={reallocated*budget:,.0f} CNY")
                    for sym in buyable:
                        per = budget * raw_weights[sym]
                        px = exec_price(sym) * (1.0 + slippage)
                        min_fee = min_commission if cost_mode == "real" else 0.0
                        comm = max(per * comm_rate, min_fee)
                        # Treat `per` as the full cash budget including commission
                        # and transfer fee, so rounded lots cannot overspend.
                        alloc = max(0.0, (per - comm) / (1.0 + buy_extra))
                        sh = alloc / px
                        if lot100:
                            sh = int(sh / 100) * 100
                            alloc = sh * px
                            if sh <= 0:
                                continue
                            comm = max(alloc * comm_rate, min_fee)
                        else:
                            comm = max(alloc * comm_rate, min_fee)
                        cash -= alloc + comm + alloc * buy_extra
                        holdings[sym] = {"shares": sh, "buy_date": d}
                    total_rebals += 1
            else:
                pass  # 现金保留（holdings 仅剩停牌/跌停未卖部分）

        # 每日净值（停牌股按最近收盘价估值；现金计入）
        mv = 0.0
        industry_values = {}
        for sym, holding in holdings.items():
            value = holding["shares"] * float(panel[sym]["close"].asof(d))
            mv += value
            industry = (industry_map or {}).get(sym, "未知") or "未知"
            industry_values[industry] = industry_values.get(industry, 0.0) + value
        nav_value = cash + mv
        nav.append(nav_value)
        if industry_values and nav_value:
            max_industry_daily.append(max(industry_values.values()) / nav_value)

    nav_s = pd.Series(nav, index=all_dates)
    nav_s.attrs["t1_blocked_sells"] = t1_blocked_sells
    if return_industry_metrics:
        return nav_s, total_rebals, (float(np.median(max_industry_daily)) if max_industry_daily else None)
    return nav_s, total_rebals


def run_benchmark(panel, cash=1_000_000.0):
    """全池等权基准：上市前留作现金，首个有效日按等额初始资金买入。"""
    if not panel:
        raise ValueError("panel 不能为空")
    all_dates = pd.to_datetime(sorted(set().union(*[p.index for p in panel.values()])))
    allocation = cash / len(panel)
    shares = {sym: 0.0 for sym in panel}
    entered = set()
    nav = []
    for d in all_dates:
        v = 0.0
        for sym, p in panel.items():
            first_date = p.index[0]
            if sym not in entered and d >= first_date:
                px = float(p.loc[first_date, "close"])
                if np.isfinite(px) and px > 0:
                    shares[sym] = allocation / px
                    entered.add(sym)
            if sym in entered:
                px = p["close"].asof(d)
                if pd.notna(px):
                    v += shares[sym] * float(px)
            else:
                v += allocation
        nav.append(v)
    return pd.Series(nav, index=all_dates)


def summary(nav: pd.Series, name: str, rebals: int = None):
    if nav is None or nav.empty or nav.isna().any() or nav.iloc[0] <= 0:
        raise ValueError(f"{name} 的净值序列为空、含 NaN 或起始净值无效")
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
    parser.add_argument("--timing-model", type=str, default=None)
    parser.add_argument("--timing-threshold", type=float, default=0.5)
    parser.add_argument("--timing-mode", type=str, default="fixed", choices=["fixed", "rolling", "mavg"])
    parser.add_argument("--timing-window", type=int, default=20)
    parser.add_argument("--next-day", action="store_true", default=True,
                        help="信号次日成交（消除 lookahead，等效 T+1）")
    parser.add_argument("--cost-mode", type=str, default="real", choices=["real", "simple"])
    # 成交校准（第2项）
    parser.add_argument("--fill", type=str, default="next_open", choices=["next_open", "next_close"],
                        help="执行日成交价：next_open=开盘(真实) / next_close=收盘(旧口径)")
    parser.add_argument("--slippage", type=float, default=0.001, help="双边滑点比例（默认0.1%）")
    parser.add_argument("--min-commission", type=float, default=5.0, help="单笔最低佣金（元，默认5）")
    parser.add_argument("--limit-check", action=argparse.BooleanOptionalAction, default=True,
                        help="涨停不可买/跌停不可卖（默认开启，可用 --no-limit-check 关闭）")
    parser.add_argument("--lot100", action=argparse.BooleanOptionalAction, default=True,
                        help="A股100股整数倍（默认开启，可用 --no-lot100 关闭）")
    parser.add_argument("--industry-cap", type=float, default=None, help="行业市值占比上限，例如0.35")
    parser.add_argument("--max-weight", type=float, default=None, help="单只股票组合权重上限，例如0.25")
    parser.add_argument("--industry-map", type=str, default=None, help="行业映射CSV路径；默认使用output/symbols_industry.csv")
    parser.add_argument("--out", type=str, default="output/portfolio_vs_20261015.csv")
    args = parser.parse_args()

    if args.symbols_file and os.path.exists(args.symbols_file):
        symbols = [s.strip() for s in open(args.symbols_file, encoding="utf-8") if s.strip()]
    else:
        symbols = [s.strip() for s in sys.stdin.read().split() if s.strip()]
    if not symbols:
        raise SystemExit("未提供股票列表：--symbols-file 或 stdin")

    industry_map, industry_failures = load_industry_map(args.industry_map, symbols)
    if industry_failures:
        fail_path = os.path.join(PROJ, "output", "industry_mapping_failures.csv")
        pd.DataFrame([{"code": c, "reason": r} for c, r in industry_failures.items()]).to_csv(
            fail_path, index=False, encoding="utf-8-sig")
        print(f"行业未映射 {len(industry_failures)}/{len(symbols)}，明细: {fail_path}")
    panel = load_panel(symbols, args.start, args.end, args.model,
                       scorer=args.scorer, timing_model=args.timing_model)
    if not panel:
        raise SystemExit(f"区间 {args.start}~{args.end} 内没有有效股票数据（检查数据是否已下载）")
    print(f"组合回测: {len(panel)} 只有效股票, {args.start}~{args.end}, Top{args.top_n}, "
          f"每{args.rebalance}日调仓 | 成交={args.fill} 滑点={args.slippage} "
          f"最低佣金={args.min_commission} 涨跌停限制={args.limit_check}")

    timing_col = "ai_prob" if (args.timing_model and args.timing_mode != "mavg") else None

    rows = []
    nav_ai = None
    nav_mom, reb_mom = run_rebalance(panel, "mom20", args.top_n, args.rebalance,
                                     next_day_exec=args.next_day, cost_mode=args.cost_mode,
                                     fill_mode=args.fill, slippage=args.slippage,
                                     min_commission=args.min_commission,
                                     limit_check=args.limit_check, lot100=args.lot100)
    nav_mom.to_csv(args.out.replace(".csv", "_mom.csv"), header=["净值"])
    rows.append(summary(nav_mom, "动量TopN组合", reb_mom))
    nav_bench = run_benchmark(panel)
    nav_bench.to_csv(args.out.replace(".csv", "_bench.csv"), header=["净值"])
    rows.append(summary(nav_bench, "全池等权基准"))

    if args.model:
        nav_ai, reb_ai, max_industry_pct = run_rebalance(panel, args.scorer, args.top_n, args.rebalance,
                                       timing_col=timing_col,
                                       timing_threshold=args.timing_threshold,
                                       timing_mode=args.timing_mode,
                                       timing_window=args.timing_window,
                                       next_day_exec=args.next_day, cost_mode=args.cost_mode,
                                       fill_mode=args.fill, slippage=args.slippage,
                                       min_commission=args.min_commission,
                                       limit_check=args.limit_check, lot100=args.lot100,
                                       industry_cap=args.industry_cap, max_weight=args.max_weight,
                                       industry_map=industry_map, return_industry_metrics=True)
        print(f"AI T+1 当日卖出拦截次数: {nav_ai.attrs.get('t1_blocked_sells', 0)}")
        nav_ai.to_csv(args.out.replace(".csv", "_ai.csv"), header=["净值"])
        ai_row = summary(nav_ai, f"AI[{args.scorer}]TopN组合", reb_ai)
        industry_coverage = sum(industry_map.get(s, "未知") != "未知" for s in symbols) / len(symbols)
        if industry_coverage > 0 and max_industry_pct is not None:
            ai_row["max_industry_pct"] = round(max_industry_pct * 100, 2)
        rows.append(ai_row)

    out_df = pd.DataFrame(rows)
    print(out_df.to_string(index=False))
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print("已保存:", args.out)

    merged = pd.DataFrame({"动量组合": nav_mom, "全池基准": nav_bench})
    if nav_ai is not None:
        merged[f"AI[{args.scorer}]组合"] = nav_ai
    merged.to_csv(args.out.replace(".csv", "_nav.csv"), encoding="utf-8-sig")


if __name__ == "__main__":
    main()
