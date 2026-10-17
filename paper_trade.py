# -*- coding: utf-8 -*-
"""模拟盘（Paper Trading）模块：把组合回测框架接到"每日收盘后例行"的实盘节奏上。

每次运行 = 一个交易日收盘后执行：
  1. akshare(新浪源) 拉最近 ~160 个交易日日线（300只），内存打分，不写库
  2. 排序模型打分 rank_score（截面横向比较用）
  3. 择时：全池等权指数 < 60日均线 → 空仓避险（与 backtest/portfolio.py 的 mavg 模式同口径）
  4. 调仓规则：距上次调仓 >= rebalance_days(5) 才调；每期选 rank_score Top-N 等权
  5. 真实A股成本：买 0.031% / 卖 0.081%（佣金万3 + 卖出印花税0.05% + 过户费）
  6. 成交简化：按当日收盘价模拟成交（严格实盘应次日开盘执行，此处注明简化）
状态持久化到 output/paper/paper_state.json，可多次运行增量更新。

用法:
    python paper_trade.py                          # 拉最新行情+例行更新
    python paper_trade.py --no-refresh             # 用本地库(调试/离线)
    python paper_trade.py --symbols 30             # 只跑前30只(调试)
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import load_daily          # noqa: E402
from models.predict import add_rank_score            # noqa: E402

PY = r"C:\Users\22646\AppData\Local\Programs\Python\Python311\python.exe"
STATE_DIR = os.path.join("output", "paper")
STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")
NAV_FILE = os.path.join(STATE_DIR, "paper_nav.csv")
HOLD_FILE = os.path.join(STATE_DIR, "paper_holdings.csv")
LOG_FILE = os.path.join(STATE_DIR, "paper_log.txt")

BUY_COST = 0.0003 + 0.00001        # 佣金万3 + 过户费
SELL_COST = 0.0003 + 0.0005 + 0.00001  # + 印花税
LOOKBACK_DAYS = 400                # 拉取的自然日跨度(≈270交易日)，确保60日预热+60日均线择时


def fetch_latest(symbols, lookback=LOOKBACK_DAYS, end=None):
    """akshare 新浪源拉最近 lookback 自然日日线，返回 {symbol: DataFrame}。"""
    import akshare as ak
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback)).strftime("%Y%m%d")
    out, fails = {}, []
    for i, sym in enumerate(symbols, 1):
        pref = ("sh" if sym.startswith("6") or sym.startswith("9") else "sz")
        try:
            df = ak.stock_zh_a_daily(symbol=f"{pref}{sym}", start_date=start, end_date=end, adjust="qfq")
            if df is None or df.empty:
                fails.append(sym)
                continue
            df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                                    "low": "low", "close": "close", "volume": "volume"})
            df["symbol"] = sym
            out[sym] = df[["date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            fails.append(f"{sym}:{str(e)[:40]}")
        if i % 60 == 0:
            print(f"  已拉取 {i}/{len(symbols)} 只…", flush=True)
            time.sleep(0.5)
    print(f"  完成 {len(out)}/{len(symbols)}，失败 {len(fails)}")
    if fails:
        print("  失败:", ", ".join(fails[:10]))
    return out


def load_panel_local(symbols):
    """本地库加载（调试/离线用），数据到本地库最后更新日。"""
    panel = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty:
            continue
        panel[sym] = df[["date", "open", "high", "low", "close", "volume"]]
    return panel


def build_snapshot(panel, model_path):
    """给最新交易日打分+算择时信号，返回 (last_date, scores, equity_index, ma60_ok)。"""
    all_dates = sorted(set().union(*[pd.to_datetime(p["date"]) for p in panel.values()]))
    last = all_dates[-1]
    scores = {}
    for sym, p in panel.items():
        p = p.sort_values("date").reset_index(drop=True)
        p = add_rank_score(p, model_path=model_path, symbol=sym)
        row = p.iloc[-1]
        if pd.notna(row.get("rank_score")):
            scores[sym] = float(row["rank_score"])
    # 等权指数（收盘均值，归一化）+ MA60
    closes = {d: [] for d in all_dates}
    for sym, p in panel.items():
        p = p.sort_values("date").reset_index(drop=True)
        for _, r in p.iterrows():
            d = pd.Timestamp(r["date"])
            if d in closes:
                closes[d].append(float(r["close"]))
    idx = pd.Series({d: float(np.mean(v)) for d, v in closes.items() if v}).sort_index()
    idx = idx / idx.iloc[0]
    ma60 = idx.rolling(60, min_periods=30).mean()
    ma60_ok = bool(idx.iloc[-1] >= ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else True
    return last, scores, idx, ma60_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="output/model_rank_h3p.joblib", help="排序模型路径")
    ap.add_argument("--symbols-file", default="output/symbols_300.txt")
    ap.add_argument("--symbols", type=int, default=None, help="只取前N只(调试)")
    ap.add_argument("--no-refresh", action="store_true", help="用本地库，不拉最新行情")
    ap.add_argument("--as-of", type=str, default=None,
                    help="模拟日期YYYYMMDD：行情截断到该日（演示/回填用；不传=最新交易日）")
    ap.add_argument("--state-file", type=str, default=STATE_FILE, help="状态文件路径(演示可用独立文件)")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--rebalance", type=int, default=5, help="调仓周期(交易日)")
    ap.add_argument("--timing-window", type=int, default=60)
    ap.add_argument("--cash", type=float, default=1_000_000.0)
    ap.add_argument("--report", action="store_true", help="生成下单日报 CSV+MD（供手工下单）")
    # 成交校准（第2项）：模拟盘手工下单参考价 = 收盘×(1±滑点)，涨跌停提示难成交
    ap.add_argument("--slippage", type=float, default=0.001, help="双边滑点比例（默认0.1%）")
    ap.add_argument("--min-commission", type=float, default=5.0, help="单笔最低佣金（元，默认5）")
    ap.add_argument("--no-limit-check", action="store_true", help="关闭涨跌停成交提示")
    args = ap.parse_args()

    os.makedirs(STATE_DIR, exist_ok=True)
    symbols = [s.strip() for s in open(args.symbols_file, encoding="utf-8") if s.strip()]
    if args.symbols:
        symbols = symbols[: args.symbols]

    # 1) 行情
    print(f"[1/5] 拉取行情 ({'本地库' if args.no_refresh else 'akshare新浪'})…")
    if args.no_refresh:
        panel = load_panel_local(symbols)
    else:
        panel = fetch_latest(symbols)
    if not panel:
        raise SystemExit("没有拉到任何行情")
    if args.as_of:
        asof = pd.Timestamp(args.as_of)
        for sym in list(panel):
            p = panel[sym]
            p = p[p["date"] <= asof]
            if len(p) < 40:
                del panel[sym]
            else:
                panel[sym] = p
        print(f"  行情截断到 {asof.date()}，有效股票 {len(panel)} 只")
    valid = [s for s in symbols if s in panel]
    print(f"  有效股票 {len(valid)} 只")

    # 2) 状态
    state = {}
    state_file = args.state_file
    if os.path.exists(state_file):
        with open(state_file, encoding="utf-8") as f:
            state = json.load(f)
    if not state:
        state = {"cash": args.cash, "holdings": {}, "last_rebal": None,
                 "total_rebals": 0, "orders": [], "created": str(pd.Timestamp.now())}
    state.setdefault("holdings", {})
    state.setdefault("buy_dates", {})  # symbol -> YYYY-MM-DD; legacy positions are treated as already T+1 eligible
    state.setdefault("orders", [])

    # 3) 打分+择时
    print("[2/5] 模型打分 + 择时信号…")
    last_date, scores, idx, ma60_ok = build_snapshot(panel, args.model)
    print(f"  最新交易日: {last_date.date()} | 择时MA{args.timing_window}: "
          f"{'做多(指数在均线上)' if ma60_ok else '空仓避险(指数在均线下)'}")

    # 4) 调仓判断：首次运行 或 距上次调仓 >= rebalance 个交易日
    rebal_needed = False
    if state["last_rebal"] is None:
        rebal_needed = True
    else:
        try:
            last_rebal = pd.Timestamp(state["last_rebal"])
            trading_days = len([d for d in idx.index if d > last_rebal and d <= last_date])
            rebal_needed = trading_days >= args.rebalance
        except Exception:
            rebal_needed = True
    print(f"[3/5] 调仓判断: {'需要调仓' if rebal_needed else '未到调仓日，仅更新净值'}")

    if rebal_needed:
        # 5) 调仓执行（成交校准：参考价=最新收盘×(1±滑点)，涨跌停难成交提示；严格实盘应次日开盘执行）
        print("[4/5] 执行调仓…")
        limit_check = not args.no_limit_check
        old_holdings = state["holdings"]
        buy_dates = state["buy_dates"]
        execution_date = str(last_date.date())
        retained = {}
        retained_buy_dates = {}
        sale_proceeds = 0.0
        for sym, sh in old_holdings.items():
            sh = float(sh)
            if buy_dates.get(sym) == execution_date:
                retained[sym] = sh
                retained_buy_dates[sym] = execution_date
                state["orders"].append({
                    "date": execution_date, "action": "HOLD", "symbol": sym,
                    "shares": round(sh, 2), "reason": "T+1限制：当日买入的持仓不可当日卖出"})
                continue
            if sym not in panel or not len(panel[sym]):
                retained[sym] = sh
                if sym in buy_dates:
                    retained_buy_dates[sym] = buy_dates[sym]
                state["orders"].append({
                    "date": execution_date, "action": "HOLD", "symbol": sym,
                    "shares": round(sh, 2), "reason": "行情缺失，暂时保留持仓"})
                continue
            px = float(panel[sym]["close"].iloc[-1])
            prev = float(panel[sym]["close"].iloc[-2]) if len(panel[sym]) > 1 else px
            limit_down = limit_check and prev > 0 and (px / prev - 1) <= -0.095
            if limit_down:
                retained[sym] = sh
                if sym in buy_dates:
                    retained_buy_dates[sym] = buy_dates[sym]
                state["orders"].append({
                    "date": execution_date, "action": "HOLD", "symbol": sym,
                    "shares": round(sh, 2), "price": round(px, 3),
                    "reason": "跌停难卖出，暂保留"})
                continue
            ref = round(px * (1.0 - args.slippage), 3)
            gross = sh * ref
            sale_proceeds += gross * (1.0 - SELL_COST)
            state["orders"].append({
                "date": execution_date, "action": "SELL", "symbol": sym,
                "shares": round(sh, 2), "price": ref,
                "cost_pct": round(SELL_COST * 100, 3),
                "reason": "建议次日开盘卖出"})
        state["holdings"] = retained
        state["buy_dates"] = retained_buy_dates
        M = float(state["cash"]) + sale_proceeds
        state["cash"] = M

        if ma60_ok and len(scores) >= args.top_n:
            picks = sorted(scores, key=scores.get, reverse=True)[: args.top_n]
            buyable = [sym for sym in picks if sym not in state["holdings"]]
            per = M * (1.0 - BUY_COST) / len(buyable) if buyable else 0.0
            spent = 0.0
            for sym in buyable:
                px = float(panel[sym]["close"].iloc[-1])
                prev = float(panel[sym]["close"].iloc[-2]) if len(panel[sym]) > 1 else px
                limit_up = limit_check and prev > 0 and (px / prev - 1) >= 0.095
                ref = round(px * (1.0 + args.slippage), 3)
                if limit_up:
                    state["orders"].append({
                        "date": str(last_date.date()), "action": "SKIP", "symbol": sym,
                        "shares": 0, "price": ref, "reason": "涨停买不进"})
                    continue
                sh = int(per / ref / 100) * 100  # A股买入须100股整数倍
                if sh <= 0:
                    state["orders"].append({
                        "date": str(last_date.date()), "action": "SKIP", "symbol": sym,
                        "shares": 0, "price": ref, "reason": "资金不足买100股"})
                    continue
                state["holdings"][sym] = sh
                state["buy_dates"][sym] = str(last_date.date())
                spent += sh * ref * (1.0 + BUY_COST)
                state["orders"].append({
                    "date": str(last_date.date()), "action": "BUY", "symbol": sym,
                    "shares": sh, "price": ref,
                    "cost_pct": round(BUY_COST * 100, 3),
                    "reason": f"参考价含{args.slippage*100:.1f}%滑点，以次日开盘为准"})
            state["cash"] = M - spent
        else:
            reason = "择时信号为空仓" if not ma60_ok else "有效分数不足"
            state["orders"].append({"date": str(last_date.date()), "action": "FLAT",
                                    "reason": reason})
        state["last_rebal"] = str(last_date.date())
        state["total_rebals"] += 1

    # 6) 净值更新
    print("[5/5] 更新净值…")
    mv = sum(sh * float(panel[sym]["close"].iloc[-1]) for sym, sh in state["holdings"].items()
             if sym in panel and len(panel[sym]))
    nav = state["cash"] + mv
    state.setdefault("nav_history", []).append({
        "date": str(last_date.date()), "nav": round(nav, 2),
        "market_value": round(mv, 2), "cash": round(state["cash"], 2),
        "timing": "long" if ma60_ok else "flat"})
    state["nav_history"] = state["nav_history"][-500:]  # 限长

    # 输出文件
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    nav_df = pd.DataFrame(state["nav_history"])
    nav_df.to_csv(state_file.replace("_state.json", "_nav.csv"), index=False, encoding="utf-8-sig")
    holds = []
    for sym, sh in state["holdings"].items():
        px = float(panel[sym]["close"].iloc[-1]) if sym in panel and len(panel[sym]) else np.nan
        holds.append({"symbol": sym, "shares": round(sh, 2),
                      "price": round(px, 3), "value": round(sh * px, 2) if px == px else ""})
    pd.DataFrame(holds).to_csv(state_file.replace("_state.json", "_holdings.csv"),
                               index=False, encoding="utf-8-sig")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n=== {pd.Timestamp.now()} | 交易日 {last_date.date()} | 调仓次数 {state['total_rebals']} ===\n")
        f.write(json.dumps({"nav": nav, "timing": "long" if ma60_ok else "flat",
                            "orders": state["orders"][-5:]}, ensure_ascii=False, indent=2))

    # 摘要
    total_ret = (nav / args.cash - 1) * 100
    nav_s = pd.Series([h["nav"] for h in state["nav_history"]])
    peak = nav_s.cummax()
    mdd = float(((nav_s - peak) / peak).min() * 100) if len(nav_s) > 1 else 0.0
    print("\n===== Paper Trading 账户 =====")
    print(f"交易日 {last_date.date()} | 净值 {nav:,.0f} | 总收益 {total_ret:+.2f}% | 最大回撤 {mdd:.2f}%")
    print(f"现金 {state['cash']:,.0f} | 持仓市值 {mv:,.0f} | 持仓 {len(state['holdings'])} 只 | 累计调仓 {state['total_rebals']} 次")
    if state["holdings"]:
        top = sorted(state["holdings"].items(), key=lambda kv: -kv[1])
        print("Top持仓:", ", ".join(f"{s}({sh:,.0f}股)" for s, sh in top[:5]))
    print(f"状态已保存: {state_file}")
    print(f"净值历史: {state_file.replace('_state.json', '_nav.csv')} | 当前持仓: {state_file.replace('_state.json', '_holdings.csv')}")

    # 7) 下单日报（--report）
    if args.report:
        gen_report(state, panel, last_date, ma60_ok, nav, total_ret, mdd, state_file)


def gen_report(state, panel, last_date, ma60_ok, nav, total_ret, mdd, state_file):
    """生成下单日报 CSV + MD：当日订单清单（BUY/SELL/SKIP/FLAT）与操作指引。"""
    today = str(last_date.date())
    orders = [o for o in state["orders"] if o.get("date") == today]
    stem = state_file.replace("_state.json", f"_report_{today}")

    # CSV：机器可读订单清单
    if orders:
        rows = [{"action": o["action"], "symbol": o.get("symbol", ""),
                 "shares": o.get("shares", ""), "ref_price": o.get("price", ""),
                 "cost_pct": o.get("cost_pct", ""),
                 "note": o.get("reason", o.get("cost_pct", "") and f"参考价≈昨收×1.00,次日开盘挂单") or ""}
                for o in orders]
        ord_df = pd.DataFrame(rows)
    else:
        ord_df = pd.DataFrame([{"action": "HOLD", "symbol": "", "shares": "",
                                "ref_price": "", "cost_pct": "",
                                "note": "非调仓日，今日无订单；持仓市值随行情波动"}])
    ord_df.to_csv(stem + ".csv", index=False, encoding="utf-8-sig")

    # MD：人可读日报
    timing_txt = "做多" if ma60_ok else "空仓避险"
    lines = [
        f"# 下单日报 {today}",
        "",
        f"- **账户净值**: {nav:,.0f} | 总收益 {total_ret:+.2f}% | 最大回撤 {mdd:.2f}%",
        f"- **择时信号**: {timing_txt}（{'全池等权指数在60日均线上方' if ma60_ok else '全池等权指数在60日均线下方'}）",
        f"- **现金**: {state['cash']:,.0f} | **持仓**: {len(state['holdings'])} 只 | **累计调仓**: {state['total_rebals']} 次",
        "",
        "## 今日订单",
    ]
    for _, r in ord_df.iterrows():
        if r["action"] == "HOLD":
            lines.append(f"- 无操作：{r['note']}")
        elif r["action"] == "FLAT":
            lines.append(f"- **清仓/空仓**：{r['note']}")
        elif r["action"] == "SKIP":
            lines.append(f"- 跳过 {r['symbol']}：{r['note']}")
        elif r["action"] == "BUY":
            lines.append(f"- **买入 {r['symbol']}** {r['shares']:,.0f}股，参考价≤昨收×1.01（次日开盘挂限价单）")
        elif r["action"] == "SELL":
            lines.append(f"- **卖出 {r['symbol']}** {r['shares']:,.0f}股，参考价≥昨收×0.99（次日开盘挂限价单）")
    lines += [
        "",
        "## 操作指引（重要）",
        "- 订单为**信号日收盘后生成，建议次日 9:25~9:30 集合竞价或开盘后按限价执行**（A股 T+1，当日买入次日才能卖）",
        "- 买入按 100 股整数倍，参考限价 = 昨日收盘价 ± 1%；若开盘大幅高开/低开（>2%），放弃该笔或改市价",
        "- **涨停不追买、跌停不卖**（无法成交会一直挂着）",
        "- 单票仓位上限 20%（本组合 Top5 等权天然 ~20%），单日总亏损 >2% 次日降半仓",
        "- 手工下单请先在银河 App 模拟盘核对代码与数量；本日报不构成投资建议",
    ]
    with open(stem + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"下单日报已生成: {stem}.csv / {stem}.md")


if __name__ == "__main__":
    main()
