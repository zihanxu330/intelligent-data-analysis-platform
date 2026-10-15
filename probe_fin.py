# -*- coding: utf-8 -*-
import akshare as ak, warnings
warnings.filterwarnings("ignore")
df = ak.stock_financial_abstract_ths(symbol="000001", indicator="按报告期")
print("全部列:", list(df.columns))
print(df.head(2).to_string())
df2 = ak.stock_financial_abstract_ths(symbol="000001", indicator="按单季度")
print("\n按单季度列:", list(df2.columns)[:12])
