# -*- coding: utf-8 -*-
"""生成最终交付CSV：合并因子诊断 + 回测绩效汇总"""
import os
import json
import pandas as pd

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 因子诊断（已有）
diag = pd.read_csv(os.path.join(PROJ, "output", "strategy_diagnosis_20261015.csv"),
                   encoding="utf-8-sig", dtype={"代码": str})
diag["代码"] = diag["代码"].astype(str).str.zfill(6)

# 回测汇总（从 api_runs 结果读取）
SYMBOLS = {
    "600519": "贵州茅台", "601318": "中国平安", "300750": "宁德时代",
    "600036": "招商银行", "000858": "五粮液", "601899": "紫金矿业",
    "000001": "平安银行", "002594": "比亚迪",
}
bt_rows = []
for sym, name in SYMBOLS.items():
    fp = os.path.join(PROJ, "output", "api_runs", f"{sym}_result.json")
    with open(fp, "r", encoding="utf-8") as f:
        res = json.load(f)
    m = res["metrics"]
    trades = res["trades"]
    # 修正回撤口径：backtrader drawdown 单位已是 %，engine 未除100
    dd = m["max_drawdown_pct"] if m["max_drawdown_pct"] is not None else 0.0
    trade_desc = ""
    if trades:
        parts = [f"{t['date']} {'买' if t['action']=='buy' else '卖'}@{t['price']}" for t in trades]
        trade_desc = "; ".join(parts)
    bt_rows.append({
        "代码": sym, "名称": name,
        "区间总收益%": round(m["total_return"] * 100, 2),
        "期末资金": m["final_value"],
        "最大回撤%": round(dd, 2),
        "交易次数": m["total_trades"],
        "胜率%": round(m["win_rate"] * 100, 2) if m["win_rate"] is not None else None,
        "交易明细": trade_desc or "空仓(未建仓)",
    })

bt = pd.DataFrame(bt_rows)
merged = diag.merge(bt[["代码", "区间总收益%", "最大回撤%", "交易次数", "交易明细"]],
                    on="代码", how="left")
out_path = os.path.join(PROJ, "output", "market_analysis_20261015.csv")
merged.to_csv(out_path, index=False, encoding="utf-8-sig")
print("已保存:", out_path)
print("行数:", len(merged))
print(merged[["代码", "名称", "今日涨跌%", "买入信号", "区间总收益%", "最大回撤%", "交易次数"]].to_string(index=False))
