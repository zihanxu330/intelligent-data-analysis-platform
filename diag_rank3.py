# -*- coding: utf-8 -*-
import sys, os, numpy as np
sys.path.insert(0, os.getcwd())
from train_model import build_dataset, load_fin_map
from data_engine.database import list_symbols
from lightgbm import LGBMRanker
fin_map = load_fin_map()
full, fc = build_dataset(list_symbols()[:60], 5, until="20251231", fin_map=fin_map)
full["rank_label"] = full.groupby("date")["future_ret"].rank(method="first").astype(int)
full = full.sort_values("date")
# 与 train_rank.py 完全一致的日期切分
dates = np.array(sorted(full["date"].unique()))
cut = int(len(dates) * 0.8)
tr = full[full["date"].isin(set(dates[:cut]))]
print("train rows:", len(tr), "groups:", tr["date"].nunique())
try:
    m = LGBMRanker(n_estimators=20, max_depth=4, min_child_samples=10, verbose=-1)
    m.fit(tr[fc], tr["rank_label"], group=tr.groupby("date").size().tolist())
    print("[OK] 日期切分+连续组: 训练成功")
except Exception as e:
    print("[FAIL]", str(e)[:120])
