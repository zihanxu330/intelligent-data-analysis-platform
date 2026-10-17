# -*- coding: utf-8 -*-
"""排序模型 walk-forward 验证：3折滚动训练+组合回测对照。

每折：用折前数据训练 rank 模型与分类模型（同一切割点），
      在折后 6 个月测试期跑 5日调仓 Top5 组合（真实成本+次日执行），
      与动量、全池基准对照。输出 output/wf_rank_summary.csv。
"""
import os
import subprocess
import sys

import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
PY = sys.executable
SYMS_FILE = "output/symbols_300.txt"

HORIZON = 5   # change to 1 or 3 when comparing horizons

FOLDS = [
    {"n": 1, "cut": "20241231", "test_start": "20250101", "test_end": "20250630"},
    {"n": 2, "cut": "20250630", "test_start": "20250701", "test_end": "20251231"},
    {"n": 3, "cut": "20251231", "test_start": "20260101", "test_end": "20260630"},
]

rows = []
for f in FOLDS:
    i = f["n"]
    rank_model = f"output/wf_f{i}_rank_h{HORIZON}.joblib"
    cls_model = f"output/wf_f{i}_cls.joblib"
    print(f"===== 折{i}: 训练截止 {f['cut']}, 测试 {f['test_start']}~{f['test_end']} =====")
    subprocess.run([PY, "train_rank.py", "--until", f["cut"], "--horizon", str(HORIZON), "--out", rank_model], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([PY, "train_model.py", "--model", "lgb", "--until", f["cut"], "--out", cls_model],
                   check=True, stdout=subprocess.DEVNULL)
    for tag, model, scorer in [("rank", rank_model, "rank_score"), ("cls", cls_model, "ai_prob")]:
        out = f"output/wf_f{i}_{tag}_port.csv"
        subprocess.run([PY, "backtest/portfolio.py", "--model", model, "--scorer", scorer,
                        "--symbols-file", SYMS_FILE,
                        "--start", f["test_start"], "--end", f["test_end"],
                        "--top-n", "5", "--rebalance", "5", "--out", out],
                       check=True, stdout=subprocess.DEVNULL)
        df = pd.read_csv(out, encoding="utf-8-sig")
        for _, r in df.iterrows():
            rows.append({"折": i, "训练截止": f["cut"], "测试期": f"{f['test_start']}~{f['test_end']}",
                         "组合": r["组合"], "总收益%": r["总收益%"], "年化%": r["年化%"],
                         "最大回撤%": r["最大回撤%"], "调仓次数": r.get("调仓次数", "")})

summary_df = pd.DataFrame(rows)
summary_df.to_csv("output/wf_rank_summary.csv", index=False, encoding="utf-8-sig")
print("\n===== Walk-Forward 汇总 =====")
print(summary_df.to_string(index=False))
print("\n已保存: output/wf_rank_summary.csv")
