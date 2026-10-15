# -*- coding: utf-8 -*-
import akshare as ak, warnings
warnings.filterwarnings("ignore")
def probe(name, fn):
    try:
        df = fn()
        print(f"[OK] {name}: {len(df)}行, 列={list(df.columns)[:8]}")
        if len(df):
            print("     日期范围:", str(df.iloc[0,0])[:19], "~", str(df.iloc[-1,0])[:19])
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__} {str(e)[:80]}")
probe("新浪30分钟 stock_zh_a_minute", lambda: ak.stock_zh_a_minute(symbol="sz000001", period="30", adjust="qfq"))
probe("新浪60分钟 stock_zh_a_minute60", lambda: ak.stock_zh_a_minute(symbol="sz000001", period="60", adjust="qfq"))
