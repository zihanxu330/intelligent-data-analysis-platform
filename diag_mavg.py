# -*- coding: utf-8 -*-
import sys, numpy as np, pandas as pd
sys.path.insert(0, r"C:\Users\22646\Desktop\项目\quant_ai_updated\quant")
from data_engine.database import load_daily
SYMS=[s.strip() for s in open("output/symbols_300.txt", encoding="utf-8") if s.strip()]
frames=[]
for sym in SYMS:
    df=load_daily(sym)
    if df.empty: continue
    df=df[(df["date"]>="20250701")&(df["date"]<="20251231")]
    if len(df)<30: continue
    frames.append(df.set_index("date")["close"])
idx=pd.concat(frames,axis=1).mean(axis=1)
idx=idx/idx.iloc[0]
lines=[]
for w in (10,20,60):
    ma=idx.rolling(w,min_periods=w//2).mean()
    below=(idx<ma)
    lines.append(f"MA{w}: 低于均线天数占比 {below.mean()*100:.0f}% (每5日样本 {below[::5].mean()*100:.0f}%)")
lines.append(f"指数: 首 {idx.iloc[0]:.3f} 尾 {idx.iloc[-1]:.3f} 低 {idx.min():.3f} 高 {idx.max():.3f}")
open("output/diag_mavg.txt","w",encoding="utf-8").write("\n".join(lines))
print("done")
