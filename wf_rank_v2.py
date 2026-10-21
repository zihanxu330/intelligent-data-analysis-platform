# -*- coding: utf-8 -*-
"""Walk-forward 评估 v3：全池、按折重训、可执行标签、统一交易口径。

每折只用 cut 之前的数据训练（train_rank --until cut --purge h），
在 cut 之后测试；IC 用可执行收益 open(t+1)->close(t+h)，组合回测用
portfolio.py 的次日开盘 + 成本 + 行业 cap + ST/涨跌停过滤。

用法:
  python wf_rank_v2.py --label-mode exec --timing --tag exec_h3_audit

输出（默认 output/audit_20261018/）:
  wf_<tag>_f{i}_port.csv / _nav.csv
  wf_<tag>_h3_summary.csv
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
PY = sys.executable
SYMS_FILE = "output/symbols_full.txt"
HORIZON = 3

FOLDS = [
    {"n": 1, "cut": "20241231", "test_start": "20250101", "test_end": "20250630"},
    {"n": 2, "cut": "20250630", "test_start": "20250701", "test_end": "20251231"},
    {"n": 3, "cut": "20251231", "test_start": "20260101", "test_end": "20261016"},
]


def oos_metrics(model_path, cut, test_start, test_end, label_mode, horizon=HORIZON, rebalance_days=5):
    """真样本外：每日截面 IC（与训练同标签）、Top5 超额、跑赢天数。"""
    from data_engine.database import load_daily
    from models.predict import add_rank_score
    from scipy.stats import spearmanr

    symbols = [s.strip() for s in open(SYMS_FILE, encoding="utf-8") if s.strip()]
    panels = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty or len(df) < 80:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])
        df = add_rank_score(df, model_path=model_path, symbol=sym)
        if label_mode == "exec_rebalance":
            df["fwd"] = df["open"].shift(-(rebalance_days + 1)) / df["open"].shift(-1) - 1
        elif label_mode in ("exec", "exec_3d"):
            df["fwd"] = df["close"].shift(-horizon) / df["open"].shift(-1) - 1
        else:
            df["fwd"] = df["close"].shift(-horizon) / df["close"] - 1
        df = df[(df["date"] > cut) & (df["date"] <= test_end)]
        if len(df) < 20:
            continue
        panels[sym] = df.set_index("date")[["rank_score", "fwd"]]

    ics, excs, beats = [], [], []
    all_dates = sorted(set().union(*[p.index for p in panels.values()])) if panels else []
    for d in all_dates:
        g = {s: p.loc[d] for s, p in panels.items()
             if d in p.index and pd.notna(p.loc[d, "rank_score"]) and pd.notna(p.loc[d, "fwd"])}
        if len(g) < 20:
            continue
        gdf = pd.DataFrame(g).T
        ic = spearmanr(gdf["rank_score"], gdf["fwd"]).correlation
        if pd.notna(ic):
            ics.append(ic)
        top = gdf.nlargest(5, "rank_score")["fwd"].mean()
        pool = gdf["fwd"].mean()
        excs.append(top - pool)
        beats.append(top > pool)
    if not ics:
        return dict(ic=np.nan, ic_std=np.nan, icir=np.nan, ic_pos=np.nan, exc=np.nan,
                    beat=np.nan, n_days=0)
    ic_arr = np.array(ics)
    return dict(ic=float(ic_arr.mean()), ic_std=float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else np.nan,
                icir=float(ic_arr.mean() / ic_arr.std(ddof=1)) if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0 else np.nan,
                ic_pos=float((ic_arr > 0).mean() * 100),
                exc=float(np.mean(excs)), beat=float(np.mean(beats) * 100), n_days=len(ic_arr))


def nav_sharpe(path):
    try:
        nav = pd.read_csv(path, parse_dates=[0], index_col=0)
        ai = nav.columns[-1]
        ret = nav[ai].pct_change().dropna()
        return float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else np.nan
    except Exception:
        return np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label-mode", choices=["close", "exec", "exec_3d", "exec_rebalance"], default="close")
    ap.add_argument("--rebalance-days", type=int, default=5)
    ap.add_argument("--timing", action="store_true", help="启用 MA60 择时（生产口径）")
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--out-dir", default="output/audit_20261018")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    mode = "exec_3d" if args.label_mode == "exec" else args.label_mode
    R = args.rebalance_days
    if mode == "exec_rebalance":
        horizon, offset = R, R + 1
    else:
        horizon, offset = HORIZON, HORIZON

    rows = []
    for f in FOLDS:
        i = f["n"]
        model = os.path.join(args.out_dir, f"wf_{args.tag}_f{i}_h{horizon}_{mode}.joblib")
        print(f"===== 折{i}: cut={f['cut']} test={f['test_start']}~{f['test_end']} "
              f"label={mode} timing={args.timing} =====", flush=True)
        subprocess.run([PY, "train_rank.py", "--until", f["cut"], "--horizon", str(horizon),
                        "--purge", str(offset), "--label-mode", mode,
                        "--rebalance-days", str(R), "--out", model],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        m = oos_metrics(model, f["cut"], f["test_start"], f["test_end"], mode, horizon, R)
        print(f"  OOS IC={m['ic']:.4f} ICIR={m['icir']:.2f} IC>0={m['ic_pos']:.1f}% "
              f"Top5超额={m['exc']*100:+.2f}pct/日 跑赢={m['beat']:.1f}% 截面={m['n_days']}", flush=True)

        out = os.path.join(args.out_dir, f"wf_{args.tag}_f{i}_port.csv")
        cmd = [PY, "backtest/portfolio.py", "--model", model, "--scorer", "rank_score",
               "--symbols-file", SYMS_FILE,
               "--start", f["test_start"], "--end", f["test_end"],
               "--top-n", "5", "--rebalance", "5", "--industry-cap", "0.30",
               "--industry-map", "output/symbols_industry_full.csv",
               "--exclude-st", "--out", out]
        if args.timing:
            cmd += ["--timing-mode", "mavg", "--timing-window", "60"]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

        df = pd.read_csv(out, encoding="utf-8-sig")
        nav_path = out.replace(".csv", "_nav.csv")
        sharpe = nav_sharpe(nav_path)
        years = max((pd.Timestamp(f["test_end"]) - pd.Timestamp(f["test_start"])).days / 365, 0.1)
        for _, r in df.iterrows():
            reb = r.get("调仓次数", np.nan)
            rebal_per_year = reb / years if pd.notna(reb) else np.nan
            rows.append({
                "折": i, "训练截止": f["cut"] + f" (purge{offset})",
                "测试期": f"{f['test_start']}~{f['test_end']}", "标签": mode,
                "择时": "MA60" if args.timing else "无",
                "组合": r["组合"], "总收益%": r["总收益%"], "年化%": r["年化%"],
                "最大回撤%": r["最大回撤%"], "Sharpe": round(sharpe, 2) if np.isfinite(sharpe) else "",
                "调仓次数": reb,
                "年化换手%": round(rebal_per_year * 100, 1) if pd.notna(rebal_per_year) else "",
                "费用估算年化%": round(rebal_per_year * 0.312, 2) if pd.notna(rebal_per_year) else "",
                "max_industry_pct": r.get("max_industry_pct", ""),
                "样本外IC": round(m["ic"], 4), "ICIR": round(m["icir"], 3) if np.isfinite(m["icir"]) else "",
                "IC>0占比%": round(m["ic_pos"], 1), "Top5日超额pct": round(m["exc"] * 100, 2),
                "跑赢天数%": round(m["beat"], 1),
            })

    summary = pd.DataFrame(rows)
    path = os.path.join(args.out_dir, f"wf_{args.tag}_h{horizon}_{mode}_summary.csv")
    summary.to_csv(path, index=False, encoding="utf-8-sig")
    print("\n===== Walk-forward 汇总 =====")
    print(summary.to_string(index=False))
    print("\n已保存:", path)


if __name__ == "__main__":
    main()
