# -*- coding: utf-8 -*-
"""
quant_ai 一键流水线：批量下载数据 -> 训练AI模型 -> 规则决策 vs AI决策自动对比

用法（在 quant/ 目录下运行）：
    # 一键全流程：下载前50只股票 + 训练模型 + 全库回测对比
    python pipeline.py --all --top 50 --start 20250501 --end 20261015

    # 样本外对比（训练截止test-start前一天，回测只跑test-start之后——验证AI是否真跑赢规则）
    python pipeline.py --compare --test-start 20260701 --symbols 000001,600519

    # walk-forward 滚动样本外（4折：每折用折前数据训练、在该折回测，收益连乘）
    python pipeline.py --compare --wf-folds 4 --symbols 000001,600519

    # 分步执行
    python pipeline.py --download --top 50 --start 20250501 --end 20261015   # 只下载
    python pipeline.py --train                                              # 只训练（用本地库全部股票）
    python pipeline.py --compare --symbols 600519,000001                    # 只对比

说明：
- 数据源默认新浪（无需token）；iTick需要ITICK_TOKEN环境变量，未设置时自动跳过
- 新浪源限速约1秒/只，下载50只约1分钟；失败自动重试3次并跳过
- 训练管线复用 train_model.py（时间序切分，避免未来函数）
- 对比输出：output/rule_vs_ai_YYYYMMDD.csv
"""
import argparse
import os
import sys
import time
import random
import subprocess
import datetime
from pathlib import Path

import pandas as pd
import akshare as ak

PROJ = str(Path(__file__).resolve().parent)
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import save_daily, has_data, list_symbols, latest_date
from data_engine.incremental_gap import missing_dates
from data_engine.stock_list import get_stock_list

DEFAULT_SLEEP = 1.0
DEFAULT_RETRY = 3
DEFAULT_TOP = 50


def sina_code(sym: str) -> str:
    """6开头->沪，0/3开头->深（新浪源带市场前缀）"""
    sym = str(sym).zfill(6)
    if sym.startswith("6"):
        return "sh" + sym
    if sym.startswith(("0", "3")):
        return "sz" + sym
    return sym


def download_one_sina(sym: str, start: str, end: str, retry: int = DEFAULT_RETRY,
                      sleep: float = DEFAULT_SLEEP) -> bool:
    """新浪源下载单只并写入本地库；失败重试。"""
    for attempt in range(1, retry + 1):
        try:
            df = ak.stock_zh_a_daily(symbol=sina_code(sym), start_date=start,
                                     end_date=end, adjust="qfq")
            if df is None or df.empty:
                raise RuntimeError("返回空数据")
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                    "最高": "high", "最低": "low", "成交量": "volume",
                                    "成交额": "amount", "换手率": "turnover"})
            # 新浪返回列：date, open, high, low, close, volume, amount, outstanding_share, turnover
            # 保留流动性字段；turnover 是小数，写库统一为百分数。
            keep = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
            df = df[[c for c in keep if c in df.columns]]
            for c in ("amount", "turnover"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if "turnover" in df.columns:
                df["turnover"] = df["turnover"] * 100.0
            n = save_daily(sym, df)
            dmin = str(df["date"].min())[:10]
            dmax = str(df["date"].max())[:10]
            print(f"[OK] {sym} 写入 {n} 条 ({dmin}~{dmax})")
            return True
        except Exception as e:
            print(f"[重试 {attempt}/{retry}] {sym} 失败: {type(e).__name__} {e}")
            if attempt < retry:
                time.sleep(sleep * attempt)
    print(f"[跳过] {sym} 重试{retry}次后放弃")
    return False


def _norm_ymd(s: str) -> str:
    """'YYYYMMDD' -> 'YYYY-MM-DD'（与本地库latest_date返回格式一致）"""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def run_download(symbols: list, start: str, end: str, sleep: float = DEFAULT_SLEEP, target_dates: list = None):
    print(f"\n===== [1/3] 批量下载 {len(symbols)} 只 ({start}~{end}) =====")
    ok = fail = skip = 0
    for i, sym in enumerate(symbols, 1):
        # target_dates 明确时检查差集，避免“已有较新日期”掩盖中间缺日。
        if target_dates:
            miss = missing_dates(sym, target_dates)
            if not miss:
                print(f"[跳过 {i}/{len(symbols)}] {sym} 目标交易日已齐")
                skip += 1
                continue
            req_start, req_end = min(miss), max(miss)
        else:
            if has_data(sym) and latest_date(sym) >= _norm_ymd(end):
                print(f"[跳过 {i}/{len(symbols)}] {sym} 本地已有最新数据")
                skip += 1
                continue
            req_start, req_end = start, end
        print(f"[{i}/{len(symbols)}] 下载 {sym} ...")
        if download_one_sina(sym, req_start, req_end, sleep=sleep):
            ok += 1
        else:
            fail += 1
        time.sleep(sleep)
    print(f"===== 下载完成: 成功 {ok}, 失败 {fail}, 跳过 {skip} =====")


def run_train(symbols: list = None):
    print("\n===== [2/3] 训练AI模型 =====")
    local_symbols = list_symbols()
    if not local_symbols:
        print("本地库还没有任何股票数据，先跑 --download")
        return False
    print(f"本地库已有 {len(local_symbols)} 只股票，用于训练")
    cmd = [sys.executable, "train_model.py", "--horizon", "5", "--n-estimators", "300"]
    if symbols:
        cmd += ["--symbols", ",".join(symbols)]
    print("执行:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc != 0:
        print("训练失败")
        return False
    print("训练完成: output/model_updown.joblib")
    return True


def _train_oos(symbols: list, until: str, out_path: str, model_type: str = "rf") -> bool:
    """样本外/walk-forward 专用训练：只用 <=until 的数据，模型输出到 out_path。"""
    cmd = [sys.executable, "train_model.py", "--horizon", "5", "--n-estimators", "300",
           "--out", out_path, "--model", model_type]
    if until:
        cmd += ["--until", until]
    if symbols:
        cmd += ["--symbols", ",".join(symbols)]
    print("执行:", " ".join(cmd))
    return subprocess.call(cmd) == 0


def _bt_pair(sym: str, model: str, start: str, end: str):
    """对单只股票跑 规则 vs AI 两套回测，返回 (res_rule, res_ai)；无数据返回 None。"""
    from backtest.engine import run_backtest
    from strategy.ma_cross import MACrossStrategy
    from strategy.ai_decision import AIDecisionStrategy

    df = _load(sym, start, end)
    if df is None or df.empty:
        return None
    res_rule = run_backtest(df, MACrossStrategy,
                            strategy_kwargs={"fast_period": 10, "slow_period": 30},
                            initial_cash=100000.0, symbol=sym)
    res_ai = run_backtest(df, AIDecisionStrategy,
                          strategy_kwargs={"buy_threshold": 0.55, "sell_threshold": 0.45},
                          initial_cash=100000.0, ai_model_path=model, symbol=sym)
    return res_rule, res_ai


def _row_from(sym: str, pair) -> dict:
    """把一对回测结果转成汇总行（收益/交易数/胜率/差）。"""
    res_rule, res_ai = pair
    m_rule, m_ai = res_rule["metrics"], res_ai["metrics"]
    return {
        "代码": sym,
        "规则收益%": round(m_rule["total_return"] * 100, 2),
        "规则交易数": m_rule["total_trades"],
        "规则胜率%": round(m_rule["win_rate"] * 100, 2) if m_rule["win_rate"] is not None else None,
        "AI收益%": round(m_ai["total_return"] * 100, 2),
        "AI交易数": m_ai["total_trades"],
        "AI胜率%": round(m_ai["win_rate"] * 100, 2) if m_ai["win_rate"] is not None else None,
        "AI-规则差%": round((m_ai["total_return"] - m_rule["total_return"]) * 100, 2),
    }


def _dump_csv(rows, path):
    out = pd.DataFrame(rows)
    avg = out[["规则收益%", "AI收益%", "AI-规则差%"]].mean().round(2)
    avg["代码"] = "平均"
    out = pd.concat([out, pd.DataFrame([avg])], ignore_index=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print("\n===== 汇总（含平均） =====")
    print(out.to_string(index=False))
    print("\n已保存:", path)
    print(f"AI胜出 {sum(1 for r in rows if r['AI-规则差%'] > 0)}/{len(rows)} 只")


def _run_plain(symbols: list, start: str, end: str, model: str):
    """普通模式：回测整个 [start, end] 区间（训练/回测区间重叠，仅供链路验证）。"""
    rows = []
    for sym in symbols:
        pair = _bt_pair(sym, model, start, end)
        if pair is None:
            print(f"{sym}: 无数据，跳过")
            continue
        rows.append(_row_from(sym, pair))
        print(f"{sym}: 规则 {pair[0]['metrics']['total_return']*100:.2f}% / "
              f"AI {pair[1]['metrics']['total_return']*100:.2f}% "
              f"(差 {rows[-1]['AI-规则差%']}pct)")
    if not rows:
        print("没有可对比的数据")
        return
    _dump_csv(rows, os.path.join(PROJ, "output", f"rule_vs_ai_{datetime.datetime.now():%Y%m%d}.csv"))


def _run_holdout(symbols: list, start: str, end: str, test_start: str, model_type: str = "rf"):
    """样本外（holdout）：训练只用 <test_start 的数据，回测 [test_start, end]。"""
    until = (pd.Timestamp(test_start) - pd.Timedelta(days=1)).strftime("%Y%m%d")
    model = os.path.join(PROJ, "output", f"model_oos_{test_start}.joblib")
    print(f"样本外模式：训练截止 {until}（之后 {test_start}~{end} 全部留给回测，模型从未见过）")
    if not _train_oos(symbols, until, model, model_type=model_type):
        print("样本外训练失败，中止对比")
        return
    rows = []
    for sym in symbols:
        pair = _bt_pair(sym, model, test_start, end)
        if pair is None:
            print(f"{sym}: {test_start}~{end} 无数据，跳过")
            continue
        rows.append(_row_from(sym, pair))
        print(f"{sym}: 规则 {pair[0]['metrics']['total_return']*100:.2f}% / "
              f"AI {pair[1]['metrics']['total_return']*100:.2f}% "
              f"(差 {rows[-1]['AI-规则差%']}pct)")
    if not rows:
        print("没有可对比的数据")
        return
    path = os.path.join(PROJ, "output",
                        f"rule_vs_ai_oos_{test_start}_{datetime.datetime.now():%Y%m%d}.csv")
    _dump_csv(rows, path)


def _run_walkforward(symbols: list, start: str, end: str, folds: int, model_type: str = "rf"):
    """滚动样本外（walk-forward）：把区间切 folds 折，每折只用折前数据训练、在该折回测，
    最后把每只股票各折收益率连乘得到全区间样本外总收益。"""
    boundaries = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), periods=folds + 1)
    fold_rows = []  # fold_rows[k] = {sym: row}（该折每只一行）
    for k in range(folds):
        f_start = boundaries[k].strftime("%Y%m%d")
        f_end = boundaries[k + 1].strftime("%Y%m%d")
        until = (boundaries[k] - pd.Timedelta(days=1)).strftime("%Y%m%d")
        model = os.path.join(PROJ, "output", f"model_oos_wf{k + 1}.joblib")
        print(f"\n----- 折{k + 1}/{folds} [{f_start}~{f_end}] 训练截止 {until} -----")
        if not _train_oos(symbols, until, model, model_type=model_type):
            print(f"折{k + 1} 训练失败（起点之前历史数据不足），该折全部计 0（等同空仓）")
            fold_rows.append({sym: {
                "代码": sym, "规则收益%": 0.0, "规则交易数": 0,
                "规则胜率%": None, "AI收益%": 0.0, "AI交易数": 0,
                "AI胜率%": None, "AI-规则差%": 0.0,
            } for sym in symbols})
            continue
        rows = []
        for sym in symbols:
            pair = _bt_pair(sym, model, f_start, f_end)
            if pair is None:
                print(f"{sym}: 该折无数据，计0")
                rows.append({"代码": sym, "规则收益%": 0.0, "规则交易数": 0,
                             "规则胜率%": None, "AI收益%": 0.0, "AI交易数": 0,
                             "AI胜率%": None, "AI-规则差%": 0.0})
                continue
            rows.append(_row_from(sym, pair))
        fold_rows.append({r["代码"]: r for r in rows})
        avg_r = sum(r["规则收益%"] for r in rows) / len(rows)
        avg_a = sum(r["AI收益%"] for r in rows) / len(rows)
        wins = sum(1 for r in rows if r["AI-规则差%"] > 0)
        print(f"折{k + 1} 汇总: 规则平均 {avg_r:.2f}% / AI平均 {avg_a:.2f}% (AI胜 {wins}/{len(rows)})")

    # ---- 跨折汇总：收益连乘，交易数/胜率累计 ----
    merged = []
    for sym in symbols:
        agg_rule_r, agg_ai_r = 1.0, 1.0
        t_rule = t_ai = won_rule = won_ai = 0
        w_rule = w_ai = 0.0
        for fr in fold_rows:
            r = fr.get(sym)
            if r is None:
                continue
            agg_rule_r *= (1 + r["规则收益%"] / 100)
            agg_ai_r *= (1 + r["AI收益%"] / 100)
            t_rule += r["规则交易数"]; t_ai += r["AI交易数"]
            w_rule += round(r["规则交易数"] * (r["规则胜率%"] or 0) / 100)
            w_ai += round(r["AI交易数"] * (r["AI胜率%"] or 0) / 100)
        merged.append({
            "代码": sym,
            "规则收益%": round((agg_rule_r - 1) * 100, 2),
            "规则交易数": t_rule,
            "规则胜率%": round(w_rule / t_rule * 100, 2) if t_rule else None,
            "AI收益%": round((agg_ai_r - 1) * 100, 2),
            "AI交易数": t_ai,
            "AI胜率%": round(w_ai / t_ai * 100, 2) if t_ai else None,
            "AI-规则差%": round((agg_ai_r - agg_rule_r) * 100, 2),
        })
    path = os.path.join(PROJ, "output",
                        f"rule_vs_ai_wf{folds}_{datetime.datetime.now():%Y%m%d}.csv")
    _dump_csv(merged, path)
    print(f"\n[walk-forward] {folds} 折滚动样本外：每折训练只用该折起点前的数据，"
          f"收益为各折连乘结果")


def run_compare(symbols: list = None, start: str = None, end: str = None,
                test_start: str = None, wf_folds: int = None, model_type: str = "rf"):
    print("\n===== [3/3] 规则决策 vs AI决策 对比回测 =====")
    if symbols is None:
        symbols = list_symbols()
    if not symbols:
        print("本地库没有数据，先跑 --download")
        return

    start = start or "20241124"
    end = end or datetime.date.today().strftime("%Y%m%d")

    if test_start:
        _run_holdout(symbols, start, end, test_start, model_type=model_type)
    elif wf_folds and wf_folds >= 2:
        _run_walkforward(symbols, start, end, wf_folds, model_type=model_type)
    else:
        model = os.path.join(PROJ, "output", "model_updown.joblib")
        if not os.path.exists(model):
            print(f"模型不存在({model})，先跑 --train")
            return
        _run_plain(symbols, start, end, model)


def _load(sym: str, start: str, end: str):
    from data_engine.database import load_daily
    df = load_daily(sym, start, end)
    return df if not df.empty else None


def get_top_symbols(top: int) -> list:
    stock_list = get_stock_list()
    code_col = "code" if "code" in stock_list.columns else stock_list.columns[0]
    symbols = stock_list[code_col].astype(str).str.zfill(6).tolist()[:top]
    return symbols


def sample_symbols(n: int, seed: int = 42) -> list:
    """沪深均衡随机抽样 n 只（排除北交所 8xx/4xx/92x），固定seed保证可复现。
    相比 get_top_symbols 按代码序取前N（会全是深市000xxx），抽样能覆盖沪深两市。"""
    stock_list = get_stock_list()
    code_col = "code" if "code" in stock_list.columns else stock_list.columns[0]
    codes = stock_list[code_col].astype(str).str.zfill(6).tolist()
    codes = [c for c in codes if c.startswith(("0", "3", "6"))]
    rng = random.Random(seed)
    return rng.sample(codes, min(n, len(codes)))


def main():
    parser = argparse.ArgumentParser(description="quant_ai 一键流水线")
    parser.add_argument("--all", action="store_true", help="一键执行 下载+训练+对比")
    parser.add_argument("--download", action="store_true", help="只执行批量下载")
    parser.add_argument("--train", action="store_true", help="只执行训练")
    parser.add_argument("--compare", action="store_true", help="只执行对比")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="下载前N只股票")
    parser.add_argument("--symbols", type=str, default=None, help="逗号分隔指定股票，覆盖--top")
    parser.add_argument("--random", type=int, default=None, dest="random_n",
                        help="沪深均衡随机抽样N只（排除北交所），覆盖--top；固定随机种子42可复现")
    parser.add_argument("--start", type=str, default="20250501")
    parser.add_argument("--end", type=str, default=datetime.date.today().strftime("%Y%m%d"))
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    parser.add_argument("--target-dates", type=str, default=None, help="逗号分隔目标交易日，如 20261019,20261020；用于中间缺日检查")
    parser.add_argument("--test-start", type=str, default=None, dest="test_start",
                        help="样本外对比：训练只用该日期之前的数据，回测从该日期开始（YYYYMMDD）")
    parser.add_argument("--wf-folds", type=int, default=None, dest="wf_folds",
                        help="walk-forward 滚动样本外：把区间切成N折，每折用折前数据训练、该折回测")
    parser.add_argument("--model", type=str, default="rf", choices=["rf", "lgb"],
                        help="AI模型类型：rf=随机森林(默认) lgb=LightGBM")
    args = parser.parse_args()

    symbols = None
    if args.symbols:
        symbols = [s.strip().zfill(6) for s in args.symbols.split(",") if s.strip()]
    elif args.random_n:
        symbols = sample_symbols(args.random_n)
    elif args.top:
        symbols = get_top_symbols(args.top)

    do_all = args.all or not (args.download or args.train or args.compare)

    if do_all:
        run_download(symbols, args.start, args.end, sleep=args.sleep, target_dates=(args.target_dates.split(",") if args.target_dates else None))
        run_train(symbols)
        run_compare(symbols, start=args.start, end=args.end,
                    test_start=args.test_start, wf_folds=args.wf_folds,
                    model_type=args.model)
    else:
        if args.download:
            run_download(symbols, args.start, args.end, sleep=args.sleep, target_dates=(args.target_dates.split(",") if args.target_dates else None))
        if args.train:
            run_train(symbols)
        if args.compare:
            run_compare(symbols, start=args.start, end=args.end,
                        test_start=args.test_start, wf_folds=args.wf_folds,
                        model_type=args.model)


if __name__ == "__main__":
    main()
