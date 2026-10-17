# -*- coding: utf-8 -*-
"""成交校准对比：同一批 wf v2 模型（已训练），旧成交 vs 真实成交。

old_exec : 次日收盘 + 比例成本（无滑点/最低佣金/涨跌停）  == v2 已交付结果
real_exec: 次日开盘 + 滑点0.1% + 最低佣金5元 + 涨跌停不可成交

输出 output/paper/exec_calib_compare.csv（每折两组 + 差异）。
"""
import os
import subprocess
import sys

import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
PY = sys.executable
SYMS_FILE = "output/symbols_300.txt"
HORIZON = 5

FOLDS = [
    {"n": 1, "cut": "20241231", "ts": "20250101", "te": "20250630"},
    {"n": 2, "cut": "20250630", "ts": "20250701", "te": "20251231"},
    {"n": 3, "cut": "20251231", "ts": "20260101", "te": "20260630"},
]

rows = []
for f in FOLDS:
    i = f["n"]
    model = f"output/wf_f{i}_rank_h{HORIZON}_v2.joblib"
    common = [PY, "backtest/portfolio.py", "--model", model, "--scorer", "rank_score",
              "--symbols-file", SYMS_FILE, "--start", f["ts"], "--end", f["te"],
              "--top-n", "5", "--rebalance", str(HORIZON)]
    # 旧口径（等价 v2；显式关闭新默认开启的涨跌停/整手，保持对照纯净）
    out_old = f"output/paper/exec_old_f{i}.csv"
    subprocess.run(common + ["--out", out_old,
                             "--no-limit-check", "--no-lot100"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 真实成交（显式声明全部口径，避免默认翻转漂移）
    out_real = f"output/paper/exec_real_f{i}.csv"
    subprocess.run(common + ["--out", out_real,
                             "--fill", "next_open", "--slippage", "0.001",
                             "--min-commission", "5", "--limit-check", "--lot100"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    old = pd.read_csv(out_old, encoding="utf-8-sig")
    real = pd.read_csv(out_real, encoding="utf-8-sig")
    o = old[old["组合"].str.startswith("AI")].iloc[0]
    r = real[real["组合"].str.startswith("AI")].iloc[0]
    rows.append({
        "折": i, "测试期": f"{f['ts']}~{f['te']}",
        "旧口径总收益%": o["总收益%"], "真实成交总收益%": r["总收益%"],
        "收益差pct": round(r["总收益%"] - o["总收益%"], 2),
        "旧年化%": o["年化%"], "真年化%": r["年化%"],
        "旧回撤%": o["最大回撤%"], "真回撤%": r["最大回撤%"],
    })

df = pd.DataFrame(rows)
df.to_csv("output/paper/exec_calib_compare.csv", index=False, encoding="utf-8-sig")
print("===== 成交校准对比（AI[rank_score]Top5，wf v2 同一批模型） =====")
print(df.to_string(index=False))
avg = df["收益差pct"].mean()
print(f"\n平均收益差: {avg:+.2f} pct（真实成交相对旧口径）")
with open("output/paper/exec_calib_compare.txt", "w", encoding="utf-8") as fh:
    fh.write(df.to_string(index=False) + "\n")
    fh.write(f"\n平均收益差: {avg:+.2f} pct\n")
    fh.write("口径: 旧=次日收盘+比例成本; 真实=次日开盘+滑点0.1%+最低佣金5元+涨跌停不可成交(主板10%)\n")
print("已保存: output/paper/exec_calib_compare.csv / .txt")
