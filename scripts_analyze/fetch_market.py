# -*- coding: utf-8 -*-
"""拉取今日全市场统计 + 代表性个股日线（带重试）"""
import time
import akshare as ak
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 100)


def retry(fn, retries=4, wait=5):
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  重试 {i+1}/{retries}: {type(e).__name__} {e}")
            time.sleep(wait)
    raise last


# 1) 全市场实时快照（涨跌家数统计）
def fetch_spot():
    df = ak.stock_zh_a_spot_em()
    return df

try:
    spot = retry(fetch_spot)
    print("=== 全市场快照 (stock_zh_a_spot_em) ===")
    print("总股票数:", len(spot))
    # 涨跌幅列
    chg_col = "涨跌幅"
    if chg_col in spot.columns:
        up = (spot[chg_col] > 0).sum()
        down = (spot[chg_col] < 0).sum()
        flat = (spot[chg_col] == 0).sum()
        print(f"上涨: {up}  下跌: {down}  平盘: {flat}")
        print("今日涨跌幅分布:")
        print(spot[chg_col].describe().to_string())
        print("\n涨幅前5:")
        print(spot.nlargest(5, chg_col)[["代码", "名称", "最新价", "涨跌幅"]].to_string())
        print("\n跌幅前5:")
        print(spot.nsmallest(5, chg_col)[["代码", "名称", "最新价", "涨跌幅"]].to_string())
except Exception as e:
    print("spot failed:", repr(e))

# 2) 代表性个股日线（东财接口，带重试）
symbols = ["600519", "000001", "300750"]
for sym in symbols:
    def fetch_hist(s=sym):
        return ak.stock_zh_a_hist(symbol=s, period="daily",
                                  start_date="20260601", end_date="20261015", adjust="qfq")
    try:
        df = retry(fetch_hist)
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                "最高": "high", "最低": "low", "成交量": "volume",
                                "成交额": "amount", "换手率": "turnover"})
        df["date"] = pd.to_datetime(df["date"])
        print(f"\n=== {sym} 最近5日 ===")
        print(df.tail(5)[["date", "open", "high", "low", "close", "volume", "turnover"]].to_string())
    except Exception as e:
        print(f"{sym} failed:", repr(e))
