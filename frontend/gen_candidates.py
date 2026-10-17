# -*- coding: utf-8 -*-
"""
生成前端看板用的"模型 Top 候选"数据（只读，不写模拟盘状态）。

与 paper_trade.py 的打分逻辑同源：本地库 300 只 → LGBMRanker 排序打分
→ 输出最新交易日 Top20 候选（rank_score / 收盘价 / 涨跌幅 / 全池百分位）。

用法：cd quant && python frontend/gen_candidates.py
输出：output/frontend_candidates.json
"""
import json
import os
import sys

import pandas as pd

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # quant/
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import load_daily          # noqa: E402
from models.predict import add_rank_score            # noqa: E402

MODEL = "output/model_rank_h3p.joblib"
SYMBOLS_FILE = "output/symbols_300.txt"
OUT_FILE = "output/frontend_candidates.json"
TOP_N = 20


def main():
    symbols = [s.strip() for s in open(SYMBOLS_FILE, encoding="utf-8") if s.strip()]
    print(f"加载 {len(symbols)} 只本地日线…")
    panel = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty:
            continue
        panel[sym] = df[["date", "open", "high", "low", "close", "volume"]]
    print(f"有效 {len(panel)} 只")

    scores, px_last, px_prev, chg, last_date = {}, {}, {}, {}, None
    for sym, p in panel.items():
        p = p.sort_values("date").reset_index(drop=True)
        p["date"] = pd.to_datetime(p["date"])
        p = add_rank_score(p, model_path=MODEL, symbol=sym)
        if last_date is None:
            last_date = p["date"].iloc[-1]
        row = p.iloc[-1]
        if pd.notna(row.get("rank_score")):
            scores[sym] = float(row["rank_score"])
            px_last[sym] = float(row["close"])
            if len(p) >= 2:
                px_prev[sym] = float(p["close"].iloc[-2])
                chg[sym] = (px_last[sym] / px_prev[sym] - 1) * 100 if px_prev[sym] else 0.0

    ranked = sorted(scores, key=scores.get, reverse=True)
    top = []
    for i, sym in enumerate(ranked[:TOP_N], 1):
        top.append({
            "rank": i,
            "symbol": sym,
            "score": round(scores[sym], 4),
            "close": round(px_last.get(sym, 0.0), 2),
            "chg": round(chg.get(sym, 0.0), 2),
            "pctile": round((1 - i / len(ranked)) * 100, 1),
        })
    out = {
        "as_of": str(pd.Timestamp(last_date).date()) if last_date is not None else "-",
        "total_scored": len(ranked),
        "candidates": top,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"OK 数据日 {out['as_of']} | 打分 {len(ranked)} 只 | Top{TOP_N} 已写入 {OUT_FILE}")
    for c in top[:5]:
        print(f"  #{c['rank']} {c['symbol']} score={c['score']} chg={c['chg']:+.2f}%")


if __name__ == "__main__":
    main()
