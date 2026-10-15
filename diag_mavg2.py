# -*- coding: utf-8 -*-
import sys, pandas as pd, numpy as np
sys.path.insert(0, os.getcwd())
from data_engine.database import load_daily
SYMS=[s.strip() for s in open("output/symbols_300.txt", encoding="utf-8") if s.strip()]
frames=[]
for sym in SYMS:
    df=load_daily(sym)
    if df.empty: continue
    df=df[(df["date"]>="20260101")&(df["date"]<="20261015")]
    if len(df)<30: continue
    frames.append(df.set_index("date")["close"])
idx=pd.concat(frames,axis=1).mean(axis=1)
idx=idx/idx.iloc[0]
ma=idx.rolling(20,min_periods=10).mean()
below=idx<ma
# 每月低于均线的占比
m=pd.DataFrame({"idx":idx,"below":below}).resample("ME").agg({"idx":"last","below":"mean"})
print(m.to_string())
