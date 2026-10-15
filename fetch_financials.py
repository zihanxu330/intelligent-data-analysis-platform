# -*- coding: utf-8 -*-
"""拉取股票财务摘要（同花顺源，东财替代），存 output/financials.csv。
列: symbol, report_date, net_profit_yoy, revenue_yoy, roe, debt_ratio
注意：report_date 是报告期；下游使用时按 "report_date + 90天" 作为可用日（近似披露延迟，防未来函数）。
"""
import sys
import os
import time
import pandas as pd
import akshare as ak
import warnings

warnings.filterwarnings("ignore")

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)
from pipeline import sample_symbols

OUT = os.path.join(PROJ, "output", "financials.csv")


def clean(x):
    """把 '64.75%' / False / 数值 统一清洗成 float；% 转小数。"""
    if x is None or x is False:
        return float("nan")
    if isinstance(x, str):
        s = x.strip()
        if s.endswith("%"):
            try:
                return float(s.rstrip("%")) / 100.0
            except ValueError:
                return float("nan")
        try:
            return float(s)
        except ValueError:
            return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def fetch_one(sym: str):
    df = ak.stock_financial_abstract_ths(symbol=sym, indicator="按报告期")
    if df is None or df.empty:
        return None
    keep = ["报告期", "净利润同比增长率", "营业总收入同比增长率", "净资产收益率", "资产负债率"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df.columns = ["report_date", "net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    for c in ["net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]:
        df[c] = df[c].apply(clean)
    df["symbol"] = sym
    return df[["symbol", "report_date", "net_profit_yoy", "revenue_yoy", "roe", "debt_ratio"]]


def main():
    symbols = sample_symbols(300)
    frames, fails = [], []
    for i, sym in enumerate(symbols, 1):
        got = False
        for attempt in range(3):
            try:
                df = fetch_one(sym)
                if df is not None:
                    frames.append(df)
                    print(f"[OK {i}/{len(symbols)}] {sym} {len(df)}期")
                else:
                    print(f"[EMPTY {i}/{len(symbols)}] {sym}")
                got = True
                break
            except Exception as e:
                print(f"[RETRY {attempt + 1}/3] {sym}: {type(e).__name__} {str(e)[:60]}")
                time.sleep(1.0 * (attempt + 1))
        if not got:
            fails.append(sym)
        time.sleep(0.3)
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"完成: 成功 {len(frames)} 只, 失败 {len(fails)} 只: {fails[:20]}")
    print("保存:", OUT)


if __name__ == "__main__":
    main()
