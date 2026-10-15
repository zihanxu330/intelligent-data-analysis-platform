# -*- coding: utf-8 -*-
import akshare as ak, warnings
warnings.filterwarnings("ignore")
def probe(name, fn):
    try:
        df = fn()
        print(f"[OK] {name}: {len(df)}行, 列={list(df.columns)[:8]}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__} {str(e)[:80]}")
# 同花顺财务摘要（东财替代源）
probe("同花顺财务摘要 stock_financial_abstract_ths", lambda: ak.stock_financial_abstract_ths(symbol="000001", indicator="按报告期"))
# 同花顺业绩报表
probe("同花顺业绩报表 stock_yjbb_ths", lambda: ak.stock_yjbb_ths(date="20251231"))
# 乐咕 沪深300 PE
probe("乐咕PE stock_a_pe", lambda: ak.stock_a_pe(market="沪深京", indicator="市盈率"))
# 乐咕 大盘资金流
probe("乐咕资金流 stock_market_fund_flow", lambda: ak.stock_market_fund_flow())
# 新浪 个股资金流
probe("新浪资金流 stock_individual_fund_flow_rank", lambda: ak.stock_individual_fund_flow_rank(indicator="今日"))
# 乐咕 全市场情绪（此前用过stock_market_activity_legu）
probe("乐咕情绪 stock_market_activity_legu", lambda: ak.stock_market_activity_legu())
