# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.getcwd())
from train_model import build_dataset, load_fin_map
from data_engine.database import list_symbols
fin_map = load_fin_map()
full, fc = build_dataset(list_symbols()[:60], 5, until="20251231", fin_map=fin_map)
full["rank_label"] = full.groupby("date")["future_ret"].rank(method="first").astype(int)
print("rank_label max:", full["rank_label"].max(), "nunique:", full["rank_label"].nunique())
print("日期截面数:", full["date"].nunique())
print(full.groupby("date").size().describe())
print("未来收益范围:", full["future_ret"].min(), "~", full["future_ret"].max())
