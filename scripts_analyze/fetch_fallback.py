# -*- coding: utf-8 -*-
"""备用数据源测试：新浪个股接口 + 全市场涨跌统计"""
import time
import akshare as ak
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def retry(fn, retries=3, wait=4):
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  重试 {i+1}/{retries}: {type(e).__name__} {e}")
            time.sleep(wait)
    raise last


# 1) 新浪个股日线接口
def fetch_sina(sym):
    return ak.stock_zh_a_daily(symbol=sym, start_date="20260601", end_date="20261015", adjust="qfq")

for sym in ["sh600519", "sz000001", "sz300750"]:
    try:
        df = retry(lambda s=sym: fetch_sina(s))
        print(f"\n=== {sym} 新浪日线 最近5日 ===")
        print(df.tail(5).to_string())
    except Exception as e:
        print(f"{sym} failed:", repr(e))

# 2) 市场活跃度（乐咕乐股：含上涨/下跌家数）
def fetch_activity():
    return ak.stock_market_activity_legu()

try:
    act = retry(fetch_activity)
    print("\n=== 乐咕市场活跃度 ===")
    print(act.to_string())
except Exception as e:
    print("activity failed:", repr(e))
