# -*- coding: utf-8 -*-
"""全盘预测：用全池模型对最新交易日截面打分，输出下周开盘 Top20 候选。

输入: output/symbols_full.txt (5225只) + output/quant.db + output/symbols_industry_full.csv
输出: output/paper/weekly_top20.csv / .json（纯 rank Top20 + 行业cap30% 分散版）
用法: python predict_weekly_top20.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
sys.path.insert(0, PROJ)

from data_engine.database import load_daily          # noqa: E402
from models.predict import add_rank_score            # noqa: E402
from paper_trade import pick_with_industry_cap       # noqa: E402

MODEL = "output/model_rank_h3p_full.joblib"
SYMBOLS_FILE = "output/symbols_full.txt"
IND_FILE = "output/symbols_industry_full.csv"
OUT_CSV = "output/paper/weekly_top20.csv"
OUT_JSON = "output/paper/weekly_top20.json"
TOP_N = 20
INDUSTRY_CAP = 0.30


def main():
    symbols = [s.strip() for s in open(SYMBOLS_FILE, encoding="utf-8") if s.strip()]
    print(f"加载 {len(symbols)} 只本地日线（全池模型打分，较慢，请等待）…", flush=True)
    panel = {}
    for sym in symbols:
        df = load_daily(sym)
        if df.empty or len(df) < 60:
            continue
        panel[sym] = df[["date", "open", "high", "low", "close", "volume"]]
    print(f"有效 {len(panel)} 只", flush=True)

    # 行业/名称映射：缺失/格式错误时 fail-closed，不生成可能不可交易的清单
    ind_map, name_map = {}, {}
    if not os.path.exists(IND_FILE):
        raise SystemExit(f"行业/名称映射不存在: {IND_FILE}；无法验证 ST 与 30% 行业 cap")
    im = pd.read_csv(IND_FILE, dtype={"code": str}, encoding="utf-8-sig").fillna("")
    if not {"code", "name", "industry"}.issubset(im.columns):
        raise SystemExit(f"行业映射列不完整（需要 code,name,industry）: {IND_FILE}")
    for _, r in im.iterrows():
        c = str(r["code"]).strip().zfill(6)
        ind_map[c] = str(r["industry"]).strip()
        name_map[c] = str(r["name"]).strip()

    scores, px_last, px_prev, chg = {}, {}, {}, {}
    all_dates = [pd.to_datetime(p["date"]).max() for p in panel.values()]
    last_date = max(all_dates) if all_dates else None
    n = 0
    for sym, p in panel.items():
        p = p.sort_values("date").reset_index(drop=True)
        p["date"] = pd.to_datetime(p["date"])
        # 与回测一致：只对最新交易日有成交的股票打分，停牌/陈旧数据不参与
        if last_date is None or p["date"].iloc[-1] != last_date:
            continue
        try:
            p = add_rank_score(p, model_path=MODEL, symbol=sym)
        except Exception as e:
            print(f"  打分失败 {sym}: {str(e)[:60]}", flush=True)
            continue
        row = p.iloc[-1]
        if pd.notna(row.get("rank_score")):
            scores[sym] = float(row["rank_score"])
            px_last[sym] = float(row["close"])
            if len(p) >= 2:
                px_prev[sym] = float(p["close"].iloc[-2])
                chg[sym] = (px_last[sym] / px_prev[sym] - 1) * 100 if px_prev[sym] else 0.0
        n += 1
        if n % 1000 == 0:
            print(f"  已打分 {n}/{len(panel)}…", flush=True)
    print(f"打分完成: {len(scores)} 只有分", flush=True)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    total = len(ranked)

    # ---- 可交易性过滤（生产口径：ST/退市 + 当日涨停 不可买，顺延选满） ----
    def limit_up(sym, chg):
        if chg != chg or chg <= 0:
            return False
        if sym.startswith(("300", "301", "688", "689")):
            return chg >= 19.5    # 创业板/科创板 20% 涨停
        return chg >= 9.5         # 主板 10% 涨停

    def tradable(sym):
        nm = str(name_map.get(sym, "") or "").strip()
        if not nm or "ST" in nm.upper() or "退" in nm:   # 名称缺失 → 无法确认，拒买
            return False
        ind = str(ind_map.get(sym, "") or "").strip()
        if not ind or ind == "未知":                     # 行业未知 → 无法验证 30% cap
            return False
        c = chg.get(sym, float("nan"))
        return not limit_up(sym, c)

    filtered = [(s, sc) for s, sc in ranked if tradable(s)]
    excluded = [(s, name_map.get(s, "-"), round(chg.get(s, 0.0), 2), sc)
                for s, sc in ranked if not tradable(s)]
    print(f"可交易过滤: 排除 {len(excluded)} 只（ST/退市/涨停）→ 剩余 {len(filtered)} 只", flush=True)
    for s, nm, c, sc in excluded[:8]:
        print(f"  排除 {s} {nm} chg={c:+.2f}% score={sc:.4f}", flush=True)

    def to_rows(picks):
        rows = []
        for i, sym in enumerate(picks, 1):
            rows.append({
                "rank": i,
                "symbol": sym,
                "name": name_map.get(sym, "-"),
                "industry": ind_map.get(sym, "未知"),
                "close": round(px_last.get(sym, 0.0), 2),
                "chg_pct": round(chg.get(sym, 0.0), 2),
                "rank_score": round(scores[sym], 4),
                "pool_pctile": round((1 - i / total) * 100, 1),
            })
        return rows

    rank_top = to_rows([s for s, _ in filtered[:TOP_N]])
    cap_picks, _ = pick_with_industry_cap(filtered, ind_map, TOP_N, INDUSTRY_CAP)
    cap_top = to_rows(cap_picks)

    as_of = str(pd.Timestamp(last_date).date())
    out = {
        "as_of": as_of,
        "total_scored": total,
        "industry_cap": INDUSTRY_CAP,
        "next_open_note": "基于收盘数据打分，供下周开盘参考；实盘以模拟盘cap30%分散为准",
        "rank_top20": rank_top,
        "cap_top20": cap_top,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    rdf = pd.DataFrame(rank_top)
    cdf = pd.DataFrame(cap_top)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    rdf.to_csv(OUT_CSV.replace(".csv", "_rank.csv"), index=False, encoding="utf-8-sig")
    cdf.to_csv(OUT_CSV.replace(".csv", "_cap.csv"), index=False, encoding="utf-8-sig")

    print(f"\n===== 全盘 Top{TOP_N} 预测（数据日 {as_of}，打分 {total} 只）=====")
    print(f"行业cap{INDUSTRY_CAP:.0%} 分散版（模拟盘口径）:")
    for r in cap_top:
        print(f"  #{r['rank']} {r['symbol']} {r['name']} [{r['industry']}] "
              f"收{r['close']:.2f} {r['chg_pct']:+.2f}% score={r['rank_score']}")
    print(f"\n纯rank Top20（未做行业分散）见 {OUT_CSV.replace('.csv', '_rank.csv')}")
    print(f"cap30% 分散版见 {OUT_CSV.replace('.csv', '_cap.csv')}")


if __name__ == "__main__":
    main()
