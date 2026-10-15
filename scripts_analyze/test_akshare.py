# -*- coding: utf-8 -*-
"""测试 AkShare 连通性：拉取上证指数近期日线，确认今天(2026-10-15)数据可获取"""
import akshare as ak
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

# 1) 上证指数日线
try:
    idx = ak.stock_zh_index_daily(symbol="sh000001")
    print("=== sh000001 上证指数 ===")
    print(idx.tail(8).to_string())
except Exception as e:
    print("stock_zh_index_daily failed:", repr(e))

# 2) 单只股票日线（AkShare 标准接口）
try:
    df = ak.stock_zh_a_hist(symbol="600519", period="daily",
                            start_date="20260915", end_date="20261015", adjust="qfq")
    print("=== 600519 贵州茅台 最近5日 ===")
    print(df.tail(5).to_string())
except Exception as e:
    print("stock_zh_a_hist failed:", repr(e))
