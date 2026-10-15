# -*- coding: utf-8 -*-
"""单独测试新浪个股日线接口"""
import akshare as ak
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)

try:
    df = ak.stock_zh_a_daily(symbol="sh600519", start_date="20260601", end_date="20261015", adjust="qfq")
    print("type:", type(df))
    print("shape:", df.shape)
    print(df.tail(5).to_string())
except Exception as e:
    print("sh600519 failed:", type(e).__name__, repr(e))
