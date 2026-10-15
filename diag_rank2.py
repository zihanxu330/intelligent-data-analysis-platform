# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.getcwd())
from train_model import build_dataset, load_fin_map
from data_engine.database import list_symbols
from lightgbm import LGBMRanker
fin_map = load_fin_map()
full, fc = build_dataset(list_symbols()[:60], 5, until="20251231", fin_map=fin_map)
full["rank_label"] = full.groupby("date")["future_ret"].rank(method="first").astype(int)
full = full.sort_values("date")
tr = full.iloc[: int(len(full)*0.8)]
print("train rows:", len(tr), "groups:", tr["date"].nunique())
print("rank_label 唯一值前20:", sorted(tr["rank_label"].unique())[:20])
print("rank_label max:", tr["rank_label"].max(), "nunique:", tr["rank_label"].nunique())
try:
    m = LGBMRanker(n_estimators=20, max_depth=4, min_child_samples=10, verbose=-1)
    m.fit(tr[fc], tr["rank_label"], group=tr.groupby("date").size().tolist())
    print("[OK] 训练成功")
except Exception as e:
    print("[FAIL]", str(e)[:120])
