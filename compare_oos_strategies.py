# -*- coding: utf-8 -*-
"""任务一(用户自定优先级④)：同一样本外(OOS)区间 模型/动量/基准 绩效对比。

背景与口径（只读，不改动任何现有文件、不写数据库）：
- 三策略 NAV 序列来自已有 output/wf_f{i}_rank_v2_port_{ai,mom,bench}.csv：
    * AI  : 按 rank_score 降序 Top5、每 5 个交易日再平衡（backtest/portfolio.py）。
    * 动量: 按 mom20 降序 Top5、每 5 日再平衡（规则对照）。
    * 基准: 全池(300)等权买入持有，期初每票 1/N 资金、之后不调仓。
- 已知缺陷：wf_f{i}_rank_v2_port_bench.csv 的基准净值前 87/117 个交易日全为 NaN
  （backtest/portfolio.py:run_benchmark 在全并集首日对"尚未上市"的票做 close.asof(d)
  返回 NaN，而 Python sum() 一旦混入 NaN 整行变 NaN），导致 wf_rank_summary_v2.csv
  基准行 总收益%/年化% 为空。本脚本按同一"全池等权买入持有"口径**重建**基准净值：
  未上市票的权重先以现金(0 收益)计，上市当日按其首日收盘转持仓——上市后区段与原
  run_benchmark 输出逐点一致（脚本内做尾部对账自检）。

指标口径（与 backtest/portfolio.py:summary 完全一致，便于对账）：
  总收益 = NAV[-1]/NAV[0]-1；年化 = (1+总收益)^(252/交易日)-1；
  最大回撤 = ((NAV-累计max)/累计max).min；Sharpe = 日收益均值/日收益std*sqrt(252)(rf=0)；
  Calmar = 年化/|最大回撤|；跑赢天数占比 = mean(策略日收益 > 基准日收益)；
  样本外 IC 直接引用 wf_rank_summary_v2.csv（每日截面 Spearman，cut 之后）。

输出：
  output/oos_strategy_compare.csv  长表(折×策略)
  output/oos_strategy_compare.md   可读版 + 每折解读 + 结论
  output/oos_nav_compare.png       3 折×3 策略净值对比(3 面板, 归一到起点=1)
"""
import os
import sys

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
sys.path.insert(0, PROJ)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_engine.database import load_daily

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ANN = 252
INIT_CASH = 1_000_000.0
SYMS_FILE = "output/symbols_300.txt"

FOLDS = [
    {"n": 1, "ts": "20250101", "te": "20250630", "label": "折1 2025H1"},
    {"n": 2, "ts": "20250701", "te": "20251231", "label": "折2 2025H2"},
    {"n": 3, "ts": "20260101", "te": "20260630", "label": "折3 2026H1"},
]

STRAT_FILE = {"AI": "_ai.csv", "动量": "_mom.csv", "基准": "_bench.csv"}
STRAT_NAME = {"AI": "AI[rank_score]TopN", "动量": "动量TopN", "基准": "全池等权基准"}


def read_nav(i, strat):
    """读已有 *_port_*.csv 的净值列（AI/动量完整；基准原文件前置 NaN 不直接用）。"""
    path = f"output/wf_f{i}_rank_v2_port{STRAT_FILE[strat]}"
    s = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
    s.index = pd.to_datetime(s.index)
    return s.iloc[:, 0].sort_index()


def rebuild_benchmark(ts, te, min_len=30):
    """按 run_benchmark 口径重建全池等权买入持有净值；未上市票权重计现金(0收益)。"""
    symbols = [s.strip() for s in open(SYMS_FILE, encoding="utf-8") if s.strip()]
    panels = {}
    for sym in symbols:
        df = load_daily(sym, ts, te)
        if df.empty or len(df) < min_len:
            continue
        panels[sym] = df.set_index("date")["close"].sort_index()
    n = len(panels)
    w = INIT_CASH / n                       # 每票期初等额本金
    shares = {sym: w / s.iloc[0] for sym, s in panels.items()}
    all_dates = sorted(set().union(*[set(s.index) for s in panels.values()]))
    nav = []
    for d in all_dates:
        v = 0.0
        for sym, s in panels.items():
            px = s.asof(d)                  # d 早于该票首日 -> NaN -> 计现金 w
            v += w if pd.isna(px) else shares[sym] * px
        nav.append(v)
    return pd.Series(nav, index=pd.to_datetime(all_dates))


def perf(nav, bench_ret=None):
    nav = nav.dropna()
    days = len(nav)
    total = nav.iloc[-1] / nav.iloc[0] - 1.0
    annual = (1.0 + total) ** (ANN / days) - 1.0 if days > 0 else np.nan
    peak = nav.cummax()
    mdd = ((nav - peak) / peak).min()
    r = nav.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(ANN) if r.std() and r.std() > 0 else np.nan
    calmar = annual / abs(mdd) if (pd.notna(mdd) and mdd < 0) else np.nan
    beat = np.nan
    if bench_ret is not None:
        common = r.index.intersection(bench_ret.index)
        beat = (r.loc[common] > bench_ret.loc[common]).mean() * 100
    return {"交易日数": days,
            "总收益%": round(total * 100, 2),
            "年化%": round(annual * 100, 2),
            "最大回撤%": round(mdd * 100, 2),
            "Sharpe": round(sharpe, 3) if pd.notna(sharpe) else np.nan,
            "Calmar": round(calmar, 3) if pd.notna(calmar) else np.nan,
            "跑赢天数占比%": round(beat, 1) if pd.notna(beat) else np.nan,
            "_ret": r}


def main():
    # 引用已有汇总里的 OOS IC（每折三策略同值）
    old = pd.read_csv("output/wf_rank_summary_v2.csv", encoding="utf-8-sig")
    ic_map = {int(r["折"]): r["样本外IC"] for _, r in old.iterrows()}

    long_rows = []
    nav_bundle = {}   # i -> {strat: nav_series_normalized}
    recon_tail_check = []

    for f in FOLDS:
        i = f["n"]
        print(f"\n===== {f['label']} =====")
        nav_ai = read_nav(i, "AI")
        nav_mom = read_nav(i, "动量")
        nav_bench = rebuild_benchmark(f["ts"], f["te"])

        # 尾部对账：重建基准应与原(残缺)bench 文件的非 NaN 尾部逐点吻合
        old_bench = read_nav(i, "基准").dropna()
        common = nav_bench.index.intersection(old_bench.index)
        if len(common) > 5:
            diff = (nav_bench.loc[common] / old_bench.loc[common] - 1).abs().max() * 100
            recon_tail_check.append((i, len(common), round(diff, 4)))
            print(f"  基准重建尾部对账: 重叠{len(common)}日, 最大相对偏差={diff:.4f}%")

        # 对齐到统一交易日历（用 AI 的日历，它最完整）
        idx = nav_ai.index
        nav_ai, nav_mom = nav_ai.reindex(idx), nav_mom.reindex(idx)
        nav_bench = nav_bench.reindex(idx).ffill()   # 极少数日历差日用前值补

        bench_ret = nav_bench.pct_change().dropna()
        results = {s: perf(n, bench_ret if s != "基准" else None) for s, n in
                   (("AI", nav_ai), ("动量", nav_mom), ("基准", nav_bench))}

        for s in ("AI", "动量", "基准"):
            rr = results[s]
            long_rows.append({
                "折": i, "测试期": f"{f['ts']}~{f['te']}", "策略": STRAT_NAME[s],
                "总收益%": rr["总收益%"], "年化%": rr["年化%"],
                "最大回撤%": rr["最大回撤%"], "Sharpe": rr["Sharpe"],
                "Calmar": rr["Calmar"], "跑赢天数占比%": rr["跑赢天数占比%"],
                "样本外IC": ic_map[i], "交易日数": rr["交易日数"],
            })

        # 归一化画图用
        nav_bundle[i] = {s: n.dropna() / n.dropna().iloc[0] for s, n in
                         (("AI", nav_ai), ("动量", nav_mom), ("基准", nav_bench))}
        print(f"  AI  总收益={results['AI']['总收益%']:>7}%  年化={results['AI']['年化%']:>7}%  "
              f"MDD={results['AI']['最大回撤%']:>7}%  Sharpe={results['AI']['Sharpe']}")
        print(f"  动量 总收益={results['动量']['总收益%']:>7}%  年化={results['动量']['年化%']:>7}%  "
              f"MDD={results['动量']['最大回撤%']:>7}%  Sharpe={results['动量']['Sharpe']}")
        print(f"  基准 总收益={results['基准']['总收益%']:>7}%  年化={results['基准']['年化%']:>7}%  "
              f"MDD={results['基准']['最大回撤%']:>7}%  Sharpe={results['基准']['Sharpe']}")

    out = pd.DataFrame(long_rows)
    out.to_csv("output/oos_strategy_compare.csv", index=False, encoding="utf-8-sig")

    # ---- 与 wf_rank_summary_v2.csv 对账 ----
    print("\n===== 与 wf_rank_summary_v2.csv 对账 =====")
    recon = []
    for _, r in old.iterrows():
        port = r["组合"]                      # 旧名形如 "AI[rank_score]TopN组合"
        if not port.startswith(("AI", "动量")):
            continue
        mine = port[:-2] if port.endswith("组合") else port   # 去掉"组合"后缀对齐
        me = out[(out["折"] == int(r["折"])) & (out["策略"] == mine)]
        if me.empty:
            continue
        diff = me.iloc[0]["总收益%"] - float(r["总收益%"])
        recon.append((int(r["折"]), port, r["总收益%"], me.iloc[0]["总收益%"], round(diff, 3)))
        flag = "PASS" if abs(diff) < 0.5 else "CHECK"
        print(f"  折{int(r['折'])} {port:<22} 汇总={float(r['总收益%']):>7}%  重算={me.iloc[0]['总收益%']:>7}%  "
              f"差={diff:+.3f}pct [{flag}]")

    # ---- 净值对比图：3 面板 ----
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    colors = {"AI": "#d62728", "动量": "#1f77b4", "基准": "#7f7f7f"}
    for ax, f in zip(axes, FOLDS):
        i = f["n"]
        for s in ("AI", "动量", "基准"):
            ax.plot(nav_bundle[i][s].index, nav_bundle[i][s].values,
                    label=STRAT_NAME[s], color=colors[s], lw=1.6)
        ax.set_title(f["label"], fontsize=12)
        ax.grid(alpha=0.3)
        ax.axhline(1.0, color="k", lw=0.6, ls="--")
    axes[0].set_ylabel("归一净值 (起点=1.0)")
    axes[-1].legend(loc="best", fontsize=9)
    fig.suptitle("OOS 三折 × 三策略净值对比（归一到测试首日=1.0）", fontsize=14)
    fig.tight_layout()
    fig.savefig("output/oos_nav_compare.png", dpi=130)
    print("\n已保存: output/oos_strategy_compare.csv / .md / output/oos_nav_compare.png")

    # ---- 写 MD ----
    def row(i, s):
        r = out[(out["折"] == i) & (out["策略"] == STRAT_NAME[s])].iloc[0]
        return r

    lines = []
    lines.append("# OOS 同区间 模型/动量/基准 绩效对比（任务④）\n")
    lines.append("> 数据来源：`output/wf_f{1,2,3}_rank_v2_port_{ai,mom}.csv`（原样 NAV）；"
                 "基准净值因原 `_bench.csv` 前 87/117 日 NaN（run_benchmark 并集首日 asof 污染），"
                 "按同一口径重建，未上市票权重计现金。OOS IC 引用 `wf_rank_summary_v2.csv`。\n")
    lines.append("## 一、核心数字表\n")
    def fmt(v):
        return "—" if pd.isna(v) else v

    lines.append("| 折 | 策略 | 总收益% | 年化% | 最大回撤% | Sharpe | Calmar | 跑赢基准天数占比% | 样本外IC |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for f in FOLDS:
        i = f["n"]
        for s in ("AI", "动量", "基准"):
            r = row(i, s)
            lines.append(f"| {i} | {r['策略']} | {r['总收益%']} | {r['年化%']} | {r['最大回撤%']} | "
                         f"{r['Sharpe']} | {r['Calmar']} | {fmt(r['跑赢天数占比%'])} | {r['样本外IC']} |")
    lines.append("")

    lines.append("## 二、每折一句话解读\n")
    for f in FOLDS:
        i = f["n"]
        a, m, b = row(i, "AI"), row(i, "动量"), row(i, "基准")
        best = max([("AI", a["总收益%"]), ("动量", m["总收益%"]), ("基准", b["总收益%"])], key=lambda x: x[1])
        lines.append(f"- **折{i}（{f['label']}）**：AI {a['总收益%']}% vs 动量 {m['总收益%']}% vs 基准 {b['总收益%']}%，"
                     f"本折总收益最高为 **{best[0]}**；AI 跑赢基准天数 {a['跑赢天数占比%']}%、"
                     f"动量跑赢基准 {m['跑赢天数占比%']}%；OOS IC={ic_map[i]:.4f}。")
    lines.append("")

    ai_beats = out[out["策略"].str.startswith("AI")]["跑赢天数占比%"].mean()
    mom_beats = out[out["策略"].str.startswith("动量")]["跑赢天数占比%"].mean()
    ai_wins = sum(1 for f in FOLDS
                  if row(f["n"], "AI")["总收益%"] >= max(row(f["n"], "动量")["总收益%"],
                                                        row(f["n"], "基准")["总收益%"]))
    lines.append("## 三、结论\n")
    lines.append(f"- 三折中 **AI 总收益最高的折数：{ai_wins}/3**；"
                 f"AI 对基准平均跑赢天数占比 {ai_beats:.1f}%，动量 {mom_beats:.1f}%。")
    lines.append(f"- 模型 vs 动量同 OOS 区间是否成立：见上表逐折对比"
                 f"（折1 AI 大幅跑赢动量；折2 动量深跌、AI 抗跌；折3 动量反转居前）。")
    lines.append("- 基准行收益已补出非空数值（原汇总 CSV 基准行 总收益/年化 为空）。\n")

    lines.append("## 四、对账记录\n")
    lines.append("| 折 | 策略 | 汇总CSV总收益% | 本脚本重算% | 差(pct) |")
    lines.append("|---|---|---:|---:|---:|")
    for t in recon:
        lines.append(f"| {t[0]} | {t[1]} | {t[2]} | {t[3]} | {t[4]} |")
    lines.append("")
    lines.append("基准重建尾部与原残缺 `_bench.csv` 非 NaN 段逐点对账（最大相对偏差）：")
    for i, n, d in recon_tail_check:
        lines.append(f"- 折{i}: 重叠 {n} 日, 最大相对偏差 {d}%（≈0 即口径一致）。")
    lines.append("")
    lines.append("## 五、净值对比图说明\n")
    lines.append("`oos_nav_compare.png`：1 行 3 列，每列一个 OOS 折，三条线分别为 AI(红)、动量(蓝)、"
                 "基准(灰)，全部归一到测试首日=1.0；可直观看到折1 AI 单边上行并跑赢基准、"
                 "折2 基准(灰)上行而 AI/动量(红/蓝)回撤（动量跌得更深）、"
                 "折3 动量反转弹性最大、AI 次之，两者均大幅跑赢基准。")

    with open("output/oos_strategy_compare.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
