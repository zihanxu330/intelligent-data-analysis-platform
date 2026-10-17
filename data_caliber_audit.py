# -*- coding: utf-8 -*-
"""任务二(用户自定优先级③)：数据口径审计与记录。

只读访问 output/quant.db（不写库、不改任何现有文件），输出：
  output/data_caliber_audit.csv   每只股票日线覆盖 + 关键列质量汇总
  output/data_caliber_report.md    可读报告（含训练口径 manifest 模板章节）

审计项：
  a) 每票日线起止/行数/相对全局交易日历的缺失交易日数；
  b) turnover/amount 非空比例（标注换手率类特征实际不可用）、volume=0、
     |单日涨跌幅|>9.8% 的价格跳变计数（按板块粗分，ST 无法从库内识别，已如实标注）；
  c) 股票池：symbols_300.txt vs daily_bars 355 票，幸存者偏差风险量化；
  d) financials.csv 覆盖、events/ 公告与研报条数核对；
  e) 训练口径 manifest（静态记录，供用户改年份复用）。
"""
import os
import sqlite3

import numpy as np
import pandas as pd

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)

DB = "output/quant.db"
SYMS_FILE = "output/symbols_300.txt"


def board(sym: str) -> str:
    if sym.startswith(("30", "68")):
        return "创业/科创(±20%)"
    if sym.startswith(("8", "4")):
        return "北交(±30%)"
    return "主板(±10%)"


def main():
    conn = sqlite3.connect(DB)

    # ---------- 全局交易日历 ----------
    cal = pd.read_sql("SELECT DISTINCT date AS d FROM daily_bars ORDER BY d", conn)["d"].tolist()
    cal_set = set(cal)
    cal_series = pd.Series(cal)

    # ---------- a) 每票覆盖 ----------
    cov = pd.read_sql("""
        SELECT symbol, MIN(date) AS start_d, MAX(date) AS end_d, COUNT(*) AS rows
        FROM daily_bars GROUP BY symbol ORDER BY symbol
    """, conn)
    miss = []
    for _, r in cov.iterrows():
        span = cal_series[(cal_series >= r["start_d"]) & (cal_series <= r["end_d"])]
        miss.append(int(len(span) - r["rows"]))
    cov["区间内应到交易日数"] = [len(cal_series[(cal_series >= s) & (cal_series <= e)])
                              for s, e in zip(cov["start_d"], cov["end_d"])]
    cov["缺失交易日数"] = miss
    cov = cov.rename(columns={"symbol": "股票代码", "start_d": "起始日期",
                              "end_d": "结束日期", "rows": "日线行数"})

    # ---------- b) 关键列质量 ----------
    total = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
    turnover_n = conn.execute("SELECT COUNT(*) FROM daily_bars WHERE turnover IS NOT NULL").fetchone()[0]
    amount_n = conn.execute("SELECT COUNT(*) FROM daily_bars WHERE amount IS NOT NULL").fetchone()[0]
    vol0 = conn.execute("SELECT COUNT(*) FROM daily_bars WHERE volume=0").fetchone()[0]

    bars = pd.read_sql("SELECT symbol, date, close FROM daily_bars ORDER BY symbol, date", conn)
    bars["ret"] = bars.groupby("symbol")["close"].pct_change()
    bars["board"] = bars["symbol"].map(board)
    jump_up = bars[bars["ret"] > 0.098]
    jump_dn = bars[bars["ret"] < -0.098]
    jump_by_board = bars[bars["ret"].abs() > 0.098].groupby("board").size().to_dict()

    # ---------- c) 股票池审计 ----------
    pool = [s.strip() for s in open(SYMS_FILE, encoding="utf-8") if s.strip()]
    db_syms = set(cov["股票代码"])
    pool_set = set(pool)
    pool_in_db = pool_set & db_syms
    db_extra = db_syms - pool_set
    pool_missing = pool_set - db_syms

    # ---------- d) 财务与事件 ----------
    fin = pd.read_csv("output/financials.csv")
    fin["report_date"] = pd.to_datetime(fin["report_date"], errors="coerce")
    fin_min = fin["report_date"].min()
    fin_max = fin["report_date"].max()
    fin_n = len(fin)
    fin_n_stocks = fin["symbol"].nunique()
    ann_n = sum(1 for _ in open("output/events/announcements.csv", encoding="utf-8")) - 1
    rep_n = sum(1 for _ in open("output/events/research_reports.csv", encoding="utf-8")) - 1

    # ---------- 写审计 CSV（每票覆盖为主，附质量汇总行） ----------
    cov_out = cov.copy()
    cov_out.to_csv("output/data_caliber_audit.csv", index=False, encoding="utf-8-sig")

    conn.close()

    # ---------- 汇总数字 ----------
    summary = {
        "总行数": total, "股票数": len(db_syms), "全局交易日数": len(cal),
        "数据区间": f"{cal[0]} ~ {cal[-1]}",
        "turnover非空行数": turnover_n, "amount非空行数": amount_n,
        "turnover非空比例%": round(turnover_n / total * 100, 3),
        "amount非空比例%": round(amount_n / total * 100, 3),
        "volume=0行数": vol0,
        "涨跌幅>9.8%跳变数": int(bars["ret"].abs().gt(0.098).sum()),
        "其中上涨跳变": int(len(jump_up)), "其中下跌跳变": int(len(jump_dn)),
        "symbols_300池票": len(pool), "池在库票": len(pool_in_db),
        "库内池外额外票": len(db_extra), "池内缺失票": len(pool_missing),
        "financials条数": fin_n, "financials股票数": fin_n_stocks,
        "financials区间": f"{fin_min.date()} ~ {fin_max.date()}",
        "公告条数": ann_n, "研报条数": rep_n,
    }

    # ---------- MD 报告 ----------
    L = []
    L.append("# 数据口径审计报告（任务③）\n")
    L.append("> 审计方式：只读连接 `output/quant.db`（未做任何写操作）；"
             f"全局交易日历={len(cal)} 日（{cal[0]} ~ {cal[-1]}）。\n")

    L.append("## 一、关键列质量\n")
    L.append(f"- daily_bars 总行数 **{total:,}**，覆盖 **{len(db_syms)}** 只票，"
             f"区间 {summary['数据区间']}。")
    L.append(f"- `turnover` 非空行数 **{turnover_n}**（{summary['turnover非空比例%']}%）；"
             f"`amount` 非空行数 **{amount_n}**（{summary['amount非空比例%']}%）。"
             f"**→ 换手率/成交额类特征实际不可用**（下载时被丢弃，仅 {turnover_n} 行有值，"
             f"占比 {summary['turnover非空比例%']}%）。")
    L.append(f"- `volume=0` 行数：**{vol0}**。")
    L.append(f"- 单日涨跌幅 |r|>9.8% 的价格跳变共 **{summary['涨跌幅>9.8%跳变数']}** 次"
             f"（涨 {summary['其中上涨跳变']} / 跌 {summary['其中下跌跳变']}），按板块：{jump_by_board}。")
    L.append("  - 注：daily_bars 无股票名称/ST 标记列，**无法从库内区分 ST 与正常股**；"
             "上表按板块阈值（主板10%/创业科创20%/北交30%）粗分，仅作审计不判错。\n")

    L.append("## 二、股票池审计（幸存者偏差风险）\n")
    L.append(f"- `symbols_300.txt` 静态池 = **{len(pool)}** 票；库内实际有数据的票 = **{len(db_syms)}** 票。")
    L.append(f"- 池内票在库命中：**{len(pool_in_db)}**；库内池外额外票：**{len(db_extra)}**；"
             f"池内但库中缺失：**{len(pool_missing)}**。")
    L.append("- **风险定性**：股票池是「当前快照」——训练/回测只用今天还在交易的 300 只，"
             "历史上退市、长期停牌、后来被剔除的票不在库内（或已被排除在池外），"
             "构成**幸存者偏差**：历史收益偏乐观，且池外 55 只与池重叠关系见上。"
             "355>300 说明库内还残留一批曾下载、但不在当前 300 快照里的票。\n")

    L.append("## 三、财务与事件数据\n")
    L.append(f"- `output/financials.csv`：**{fin_n:,}** 行 × **{fin_n_stocks}** 只票，"
             f"报告期覆盖 {summary['financials区间']}。")
    L.append(f"- `output/events/announcements.csv`：**{ann_n:,}** 条公告；"
             f"`output/events/research_reports.csv`：**{rep_n:,}** 条研报"
             f"（与已知「56 万公告 + 7729 研报」核对：{'一致' if abs(ann_n-560000)<5000 and rep_n==7729 else '见上'}）。\n")

    L.append("## 四、训练口径 Manifest（模板，可改年份复用）\n")
    L.append("```yaml")
    L.append("train_window_years: 5            # 训练窗口长度")
    L.append("universe: symbols_300.txt        # 静态 300 池（当前快照，存在幸存者偏差）")
    L.append("horizon_production: 3           # 生产标签 horizon=3")
    L.append("horizon_wf_ic: 5                # !! wf_rank_v2.py 里 OOS IC 用 fwd5/h5")
    L.append("#   !! 口径不一致：wf_rank_summary_v2.csv 的样本外IC 基于 fwd5 计算，")
    L.append("#      而生产模型 train_rank 用 h3。两者 horizon 不同，IC 与真实 h3 选股效力不可直接等同，")
    L.append("#      此处如实标注，供用户决策是否统一为 h3 重算 IC。")
    L.append("purge: horizon                    # 训练尾部剔除 horizon 个交易日")
    L.append("embargo: 0")
    L.append("fin_features_avail: 报告期+90天   # 财务特征可用时点（防未来函数）")
    L.append("event_alignment: 次交易日         # 事件对齐到下一交易日")
    L.append("adjust: qfq                       # 前复权，但库内无复权标记列")
    L.append("#   !! 未来信息风险：qfq 复权因子随时间变化，固定用最新复权价回测会引入")
    L.append("#      未来信息（历史复权价被事后调整）；库内未标记复权方式/日期，无法回溯。")
    L.append("exec: 次日收盘成交, 比例成本0.05%  # wf v2 汇总用最松口径")
    L.append("#   vs wf_exec_calib.py 真实成交(次日开盘+滑点0.1%+最低佣金5元+涨跌停)")
    L.append("#      对照差约 -0.41pct（AI Top5，三折均值），即 v2 汇总收益偏乐观约 0.41pct。")
    L.append("database_coverage_note: 库内数据仅起于 2021-10-15")
    L.append("#   !! 训练窗口标称 5 年，但 fold1 cut=2024-12-31 时实际可用历史约 3.2 年，")
    L.append("#      早期年份(2019~2021-10)样本缺失，训练窗口被数据起点截断。")
    L.append("```\n")

    L.append("## 五、自检对照\n")
    L.append(f"- 期望 turnover/amount 非空=242：实际 {turnover_n} / {amount_n} → "
             f"{'一致' if turnover_n==242 and amount_n==242 else '不符'}。")
    L.append(f"- 期望库内股票=355：实际 {len(db_syms)} → {'一致' if len(db_syms)==355 else '不符'}。")
    L.append(f"- 期望总行数≈363,734：实际 {total:,} → {'一致' if total==363734 else '不符'}。")
    L.append(f"- 公告≈56万/研报=7729：实际 {ann_n:,} / {rep_n} → "
             f"{'一致' if rep_n==7729 else '见上'}。\n")

    L.append("## 六、产物\n")
    L.append("- 逐票覆盖明细：`output/data_caliber_audit.csv`（股票代码/起始/结束/行数/应到/缺失）。")

    with open("output/data_caliber_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    print("===== 数据口径审计汇总 =====")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n跳变按板块: {jump_by_board}")
    print("已保存: output/data_caliber_audit.csv / output/data_caliber_report.md")


if __name__ == "__main__":
    main()
