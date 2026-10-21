# -*- coding: utf-8 -*-
"""抓取季度业绩报表（含公告日期字段），供 monthly_multifactor.py 使用。

数据源：AkShare `stock_yjbb_em`（东财业绩报表）。
注意：返回的“最新公告日期”是**最新**公告日（可能包含后续更正），不能直接当
point-in-time 可用日；monthly_multifactor.py 使用法定披露截止日（Q1/H1/Q3/年报）
作为可用日，属于保守口径。

用法:
    python fetch_fundamentals.py
输出:
    output/fundamentals/yjbb_2021_2026.csv
"""
import os
import time

import akshare as ak
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(PROJ, "output", "fundamentals")


def main():
    os.makedirs(OUT, exist_ok=True)
    quarters = []
    for y in range(2021, 2027):
        for md in ("0331", "0630", "0930", "1231"):
            d = f"{y}{md}"
            if d > "20260630":
                continue
            quarters.append(d)

    frames = []
    for q in quarters:
        try:
            df = ak.stock_yjbb_em(date=q)
        except Exception as exc:
            print(q, "FAILED", type(exc).__name__, exc, flush=True)
            continue
        if df is None or df.empty:
            print(q, "empty", flush=True)
            continue
        df["quarter"] = q
        frames.append(df)
        print(q, df.shape, flush=True)
        time.sleep(0.5)

    if not frames:
        raise SystemExit("没有抓到任何季度数据")
    full = pd.concat(frames, ignore_index=True)
    path = os.path.join(OUT, "yjbb_2021_2026.csv")
    full.to_csv(path, index=False, encoding="utf-8-sig")
    print("saved", full.shape, path)


if __name__ == "__main__":
    main()
