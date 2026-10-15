# -*- coding: utf-8 -*-
"""把新浪缓存数据写入项目本地SQLite仓库，供回测/策略走本地链路"""
import os
import sys
import pandas as pd

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from data_engine.database import save_daily

CACHE = os.path.join(PROJ, "output", "cache_sina")
total = 0
for f in sorted(os.listdir(CACHE)):
    if not f.endswith(".csv"):
        continue
    sym = f.replace(".csv", "")
    df = pd.read_csv(os.path.join(CACHE, f), parse_dates=["date"])
    # 统一列名（新浪源有 outstanding_share 额外列，只需标准列）
    df = df[["date", "open", "high", "low", "close", "volume"]]
    n = save_daily(sym, df)
    total += n
    print(f"{sym}: 写入 {n} 行")
print("总计:", total)
