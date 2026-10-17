# -*- coding: utf-8 -*-
"""
生成 AI 量化系统前端看板（自包含 HTML）。

数据来源（全部为项目真实产物，数据保真）：
  - output/paper/paper_state.json            模拟盘账户状态
  - output/paper/paper_report_2026-10-15.csv 今日下单日报
  - output/portfolio_rank_r5_nav.csv         rank Top5/5日 无择时净值
  - output/portfolio_rank_r5_mavg60_nav.csv  rank Top5/5日 + MA60择时净值
  - output/portfolio_v2_summary.csv          组合/成本/择时对比汇总
  - output/wf_rank_summary.csv               walk-forward 3折对比
  - output/rule_vs_ai_oos_20260101_20261015.csv 300只样本外对比

用法：cd quant && python frontend/gen_dashboard.py
输出：frontend/AI量化系统看板.html（自包含，双击即开）
"""
import csv
import json
import os

QUANT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(QUANT, "output")


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def read_csv_dicts(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_f(v):
    """字符串转 float；空/非法返回 None。"""
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


# ============ 1. 模拟盘 ============
with open(os.path.join(OUT, "paper", "paper_state.json"), encoding="utf-8") as f:
    paper = json.load(f)

paper_orders = paper.get("orders", [])
paper_nav_history = paper.get("nav_history", [])
paper_holdings = paper.get("holdings", {})
paper_last_rebal = paper.get("last_rebal", "-")
paper_total_rebals = paper.get("total_rebals", 0)
paper_cash = paper.get("cash", 0)
paper_timing = paper_nav_history[-1].get("timing", "-") if paper_nav_history else "-"
paper_nav = paper_nav_history[-1].get("nav", 0) if paper_nav_history else 0

# 今日日报
report_path = None
for fn in os.listdir(os.path.join(OUT, "paper")):
    if fn.startswith("paper_report_") and fn.endswith(".csv"):
        report_path = os.path.join(OUT, "paper", fn)
report_rows = read_csv_rows(report_path) if report_path else [["action", "symbol", "shares", "ref_price", "cost_pct", "note"]]
report_date = os.path.basename(report_path).replace("paper_report_", "").replace(".csv", "") if report_path else "-"

# ============ 2. 净值曲线（择时 vs 无择时）============
def read_nav(path):
    rows = read_csv_dicts(path)
    dates, ai, mom, bench = [], [], [], []
    for r in rows:
        d = r.get("", r.get("日期", "")).strip() or (list(r.values())[0].strip() if r else "")
        # 第一列无表头名，用列值顺序取
        vals = list(r.values())
        dates.append(vals[0].strip())
        ai.append(to_f(vals[3]) if len(vals) > 3 else None)     # AI[rank_score]组合
        mom.append(to_f(vals[1]) if len(vals) > 1 else None)    # 动量组合
        bench.append(to_f(vals[2]) if len(vals) > 2 else None)  # 全池基准
    return dates, ai, mom, bench

nav_dates_plain, ai_plain, mom_plain, bench_plain = read_nav(os.path.join(OUT, "portfolio_rank_r5_nav.csv"))
nav_dates_timed, ai_timed, mom_timed, _ = read_nav(os.path.join(OUT, "portfolio_rank_r5_mavg60_nav.csv"))

# 统一时间轴：以无择时文件为准（两者日期序列一致），择时文件按日期补齐
timed_map = dict(zip(nav_dates_timed, ai_timed))
dates = nav_dates_plain
ai_t = [timed_map.get(d) for d in dates]

# ============ 3. 组合/成本/择时对比 ============
cost_rows = []    # A 组：成本对比
timing_rows = []  # C 组：择时模式
for r in read_csv_dicts(os.path.join(OUT, "portfolio_v2_summary.csv")):
    grp = (r.get("组") or "").strip()
    name = (r.get("场景") or "").strip()
    cfg = (r.get("配置") or "").strip()
    ret = to_f(r.get("总收益%"))
    dd = to_f(r.get("最大回撤%"))
    if grp.startswith("A."):
        cost_rows.append({"name": name, "cfg": cfg, "ret": ret, "dd": dd})
    elif grp.startswith("C."):
        timing_rows.append({"name": cfg, "ret": ret, "dd": dd})

# walk-forward（wf_rank_summary.csv 去重：每折每组合取一条）
wf = {}
for r in read_csv_dicts(os.path.join(OUT, "wf_rank_summary.csv")):
    fold = (r.get("折") or "").strip()
    combo = (r.get("组合") or "").strip()
    ret = to_f(r.get("总收益%"))
    dd = to_f(r.get("最大回撤%"))
    if fold and combo:
        key = (fold, combo)
        if key not in wf:
            wf[key] = {"ret": ret, "dd": dd}

wf_folds = ["1", "2", "3"]
def wf_series(prefix):
    out = []
    for fold in wf_folds:
        v = wf.get((fold, prefix), {})
        out.append(v.get("ret"))
    return out

wf_rank = wf_series("AI[rank_score]TopN组合")
wf_cls = wf_series("AI[ai_prob]TopN组合")
wf_mom = wf_series("动量TopN组合")
wf_bench_dd = []
for fold in wf_folds:
    v = wf.get((fold, "全池等权基准"), {})
    wf_bench_dd.append(v.get("dd"))
wf_labels = ["折1\n2025H1", "折2\n2025H2", "折3\n2026H1"]

# ============ 4. 300只样本外（holdout）============
oos_rows = read_csv_dicts(os.path.join(OUT, "rule_vs_ai_oos_20260101_20261015.csv"))
ai_win = 0
total = 0
for r in oos_rows:
    code = (r.get("代码") or "").strip()
    if not code or code == "平均":
        continue
    total += 1
    diff = to_f(r.get("AI-规则差%"))
    if diff is not None and diff > 0:
        ai_win += 1
holdout_avg_rule = -3.65   # CSV 平均行：规则 -3.65 / AI -0.15 / 差 +3.5
holdout_avg_ai = -0.15

# ============ 4.5 模型 Top 候选 ============
cand_file = os.path.join(OUT, "frontend_candidates.json")
if os.path.exists(cand_file):
    with open(cand_file, encoding="utf-8") as f:
        candidates = json.load(f)
else:
    candidates = {"as_of": "-", "total_scored": 0, "candidates": []}

# ============ 4.7 每日 IC 滚动检验 ============
ic_data = {"dates": [], "ic": [], "ma20": [], "months": [], "m_ic": [],
           "stats": {}, "today": None}
ic_file = os.path.join(OUT, "paper", "daily_ic_log.csv")
if os.path.exists(ic_file):
    ic_rows = read_csv_dicts(ic_file)
    ic_dates = [str(r["date"])[:10] for r in ic_rows]
    ic_vals = [to_f(r["ic"]) for r in ic_rows]
    t20_vals = [to_f(r["top20_avg"]) for r in ic_rows]
    pool_vals = [to_f(r["pool_avg"]) for r in ic_rows]
    ma_vals = []
    for i in range(len(ic_vals)):
        seg = [v for v in ic_vals[max(0, i - 19):i + 1] if v is not None]
        ma_vals.append(round(sum(seg) / len(seg), 4) if seg else None)
    n = len(ic_vals)
    avg_ic = sum(v for v in ic_vals if v is not None) / n if n else None
    pos_ic = sum(1 for v in ic_vals if v is not None and v > 0) / n * 100 if n else None
    beat_tp = sum(1 for a, p in zip(t20_vals, pool_vals)
                  if a is not None and p is not None and a > p) / n * 100 if n else None
    recent = ic_rows[-250:]
    r_beat = 0
    r_cnt = 0
    for r in recent:
        a, p = to_f(r.get("top20_avg")), to_f(r.get("pool_avg"))
        if a is not None and p is not None:
            r_cnt += 1
            if a > p:
                r_beat += 1
    r_beat_pct = r_beat / r_cnt * 100 if r_cnt else None
    # 月度聚合（近12个月）
    months, m_ic = [], []
    m_map = {}
    for r in ic_rows:
        ym = str(r["date"])[:7]
        v = to_f(r["ic"])
        if v is None:
            continue
        m_map.setdefault(ym, []).append(v)
    for ym in sorted(m_map)[-12:]:
        months.append(ym)
        m_ic.append(round(sum(m_map[ym]) / len(m_map[ym]), 4))
    ic_data = {
        "dates": ic_dates, "ic": [round(v, 4) if v is not None else None for v in ic_vals],
        "ma20": ma_vals, "months": months, "m_ic": m_ic,
        "stats": {
            "n": n,
            "avg": round(avg_ic, 4) if avg_ic is not None else None,
            "pos": round(pos_ic) if pos_ic is not None else None,
            "beat": round(beat_tp) if beat_tp is not None else None,
            "r_beat": round(r_beat_pct) if r_beat_pct is not None else None,
        },
    }

# 今日盘中偏差（10-16 实时：昨日打分 vs 今日涨跌）
dev_file = os.path.join(OUT, "paper", "deviation_20261016.csv")
if os.path.exists(dev_file):
    try:
        from scipy.stats import spearmanr
        d_rows = read_csv_dicts(dev_file)
        xs, ys = [], []
        for r in d_rows:
            x = to_f(r.get("rank_score"))
            y = to_f(r.get("pct"))
            if x is not None and y is not None:
                xs.append(x)
                ys.append(y)
        if len(xs) > 20:
            rho, _ = spearmanr(xs, ys)
            arr = sorted(zip(xs, ys), key=lambda t: -t[0])
            t20v = sum(t[1] for t in arr[:20]) / 20
            poolv = sum(ys) / len(ys)
            hit = sum(1 for t in arr[:20] if t[1] > 0)
            ic_data["today"] = {"n": len(xs), "ic": round(rho, 3),
                                "top20": round(t20v, 2), "pool": round(poolv, 2),
                                "hit": hit}
    except Exception:
        pass

# ============ 5. 组装数据 ============
DATA = {
    "generated": "2026-10-15",
    "paper": {
        "nav": round(paper_nav, 2),
        "cash": round(paper_cash, 2),
        "holdings_count": len(paper_holdings),
        "timing": paper_timing,
        "last_rebal": paper_last_rebal,
        "total_rebals": paper_total_rebals,
        "orders": paper_orders,
    },
    "report": {
        "date": report_date,
        "rows": report_rows,
    },
    "nav": {
        "dates": dates,
        "ai_timed": [round(v, 2) if v is not None else None for v in ai_t],
        "ai_plain": [round(v, 2) if v is not None else None for v in ai_plain],
        "mom_plain": [round(v, 2) if v is not None else None for v in mom_plain],
        "bench": [round(v, 2) if v is not None else None for v in bench_plain],
    },
    "cost": cost_rows,
    "timing": timing_rows,
    "wf": {
        "labels": wf_labels,
        "rank": wf_rank,
        "cls": wf_cls,
        "mom": wf_mom,
        "bench_dd": wf_bench_dd,
    },
    "holdout": {
        "total": total,
        "ai_win": ai_win,
        "avg_rule": holdout_avg_rule,
        "avg_ai": holdout_avg_ai,
    },
    "candidates": candidates,
    "ic": ic_data,
}

# ============ 6. HTML 模板 ============
HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI量化系统看板</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='6' fill='%230b1220'/%3E%3Cpath d='M4 16l5-6 4 4 7-9' stroke='%23f0524d' stroke-width='2.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='18' cy='6' r='1.8' fill='%23f5a524'/%3E%3C/svg%3E">
<style>
:root{
  --bg:#0a0f1a; --panel:#101a2e; --panel2:#0d1524; --line:#1d2a42;
  --tx:#e6edf7; --tx2:#8b98ad; --tx3:#5c6b82;
  --up:#f0524d; --down:#2fbf71; --blue:#5b8cff; --amber:#f5a524; --gray:#64748b;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:auto}
body{background:var(--bg);color:var(--tx);font-family:"Segoe UI","Microsoft YaHei","PingFang SC",system-ui,sans-serif;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:20px 18px 8px}
header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:6px 2px 18px}
.brand{display:flex;align-items:center;gap:12px}
.brand svg{flex:none}
.brand h1{font-size:22px;font-weight:700;letter-spacing:.5px}
.brand .sub{font-size:12px;color:var(--tx2);margin-top:2px}
.meta{font-size:12px;color:var(--tx2);text-align:right}
.meta a{color:var(--blue);text-decoration:none}
.meta a:hover{text-decoration:underline}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;min-width:0}
.kpi .k{font-size:12px;color:var(--tx2);display:flex;align-items:center;gap:6px;white-space:nowrap}
.kpi .k svg{flex:none}
.kpi .v{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums;letter-spacing:.3px}
.kpi .d{font-size:11px;color:var(--tx3);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.up{color:var(--up)} .down{color:var(--down)} .blue{color:var(--blue)} .amber{color:var(--amber)}
.cards{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;min-width:0}
.card h2{font-size:14px;font-weight:600;color:var(--tx);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.card h2 .tag{font-size:10px;font-weight:400;color:var(--tx3);border:1px solid var(--line);border-radius:99px;padding:1px 8px}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th,td{text-align:left;padding:7px 8px;font-size:12.5px;border-bottom:1px solid var(--line)}
th{color:var(--tx2);font-weight:500;white-space:nowrap}
td{font-variant-numeric:tabular-nums;word-break:break-all}
td.num,th.num{text-align:right}
.flat-badge{display:inline-block;background:rgba(47,191,113,.12);color:var(--down);border:1px solid rgba(47,191,113,.35);border-radius:6px;padding:2px 10px;font-size:12px;font-weight:600}
.hold-badge{display:inline-block;background:rgba(245,165,36,.12);color:var(--amber);border:1px solid rgba(245,165,36,.35);border-radius:6px;padding:2px 10px;font-size:12px;font-weight:600}
.acct-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.acct-item{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.acct-item .k{font-size:11px;color:var(--tx2)}
.acct-item .v{font-size:18px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
.acct-item .s{font-size:11px;color:var(--tx3);margin-top:2px}
.chart-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.chart-card h2{font-size:14px;font-weight:600;margin-bottom:4px}
.chart-card .note{font-size:11.5px;color:var(--tx2);margin-bottom:10px}
.chart{width:100%;height:360px}
.chart.sm{height:300px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.model-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.model-item{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.model-item .n{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.model-item .k{font-size:11px;color:var(--tx2);margin-top:3px}
.model-item .s{font-size:11px;color:var(--tx3);margin-top:1px}
.cand-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.cand-card h2{font-size:14px;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:8px}
.cand-card .note{font-size:11.5px;color:var(--tx2);margin-bottom:10px}
.cand-table tbody tr{cursor:pointer;transition:background .15s}
.cand-table tbody tr:hover{background:var(--panel2)}
.cand-table td.sym{font-weight:600;color:var(--blue)}
.chg-up{color:var(--up)} .chg-dn{color:var(--down)}
.modal-mask{position:fixed;inset:0;background:rgba(4,8,15,.72);display:flex;align-items:center;justify-content:center;z-index:99;padding:16px}
.modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:520px;width:100%;padding:20px 22px;position:relative;box-shadow:0 12px 40px rgba(0,0,0,.5)}
.modal-close{position:absolute;top:10px;right:12px;background:none;border:none;color:var(--tx2);font-size:22px;cursor:pointer;line-height:1;padding:6px}
.modal-close:hover{color:var(--tx)}
.modal h3{font-size:18px;margin-bottom:12px}
.modal .row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px;gap:12px}
.modal .row:last-child{border-bottom:none}
.modal .row .k{color:var(--tx2);flex:none} .modal .row .v{font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.modal .warn{font-size:11.5px;color:var(--tx3);margin-top:12px;line-height:1.7}
@media (max-width:500px){.cand-table td,.cand-table th{font-size:11.5px;padding:6px 4px}}
footer{margin-top:18px;padding:14px 0 26px;border-top:1px solid var(--line);font-size:11.5px;color:var(--tx3);line-height:1.8}
code{background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:11.5px;font-family:Consolas,"Courier New",monospace;color:var(--amber)}
@media (max-width:860px){
  .kpis{grid-template-columns:repeat(2,1fr)}
  .cards{grid-template-columns:1fr}
  .two{grid-template-columns:1fr}
  .acct-grid{grid-template-columns:repeat(2,1fr)}
  .model-grid{grid-template-columns:repeat(2,1fr)}
  .chart{height:320px}
}
@media (max-width:500px){
  .kpis{grid-template-columns:1fr 1fr}
  .acct-grid{grid-template-columns:1fr 1fr}
  .model-grid{grid-template-columns:1fr 1fr}
  .kpi .v{font-size:22px}
}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="brand">
    <svg width="40" height="40" viewBox="0 0 40 40"><rect width="40" height="40" rx="10" fill="#0d1524"/><rect width="40" height="40" rx="10" fill="none" stroke="#1d2a42"/><path d="M8 26l7-9 6 5 10-13" stroke="#f0524d" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="31" cy="10" r="2.4" fill="#f5a524"/></svg>
    <div>
      <h1>AI 量化组合系统</h1>
      <div class="sub">A股 300 只池 · LGBMRanker 排序学习 · MA60 择时 · Paper Trading 模拟盘</div>
    </div>
  </div>
  <div class="meta">
    <div>数据截至 2026-10-15 收盘 · 含 10-16 盘中偏差</div>
    <div><a href="https://github.com/zihanxu330/intelligent-data-analysis-platform" target="_blank" rel="noopener">github.com/zihanxu330/intelligent-data-analysis-platform</a></div>
  </div>
</header>

<!-- ===== KPI ===== -->
<section class="kpis">
  <div class="kpi">
    <div class="k"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>模拟盘净值</div>
    <div class="v" id="kpi-nav"></div>
    <div class="d">初始资金 1,000,000 · 空仓避险中</div>
  </div>
  <div class="kpi">
    <div class="k"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>MA60 择时组合</div>
    <div class="v up" id="kpi-timing"></div>
    <div class="d">rank Top5/5日 · 真实成本 + 次日执行</div>
  </div>
  <div class="kpi">
    <div class="k"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19V5M4 19h16M8 15l3-4 3 2 5-7"/></svg>样本外 AI vs 规则</div>
    <div class="v blue" id="kpi-oos"></div>
    <div class="d" id="kpi-oos-d"></div>
  </div>
  <div class="kpi">
    <div class="k"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>模型预测准确率</div>
    <div class="v amber">52.0%</div>
    <div class="d">单日涨跌分类 · 超随机基线 0.7pct</div>
  </div>
</section>

<!-- ===== 模拟盘 + 日报 ===== -->
<section class="cards">
  <div class="card">
    <h2>Paper Trading 模拟盘 <span class="tag" id="acct-status"></span></h2>
    <div class="acct-grid">
      <div class="acct-item"><div class="k">账户净值</div><div class="v" id="acct-nav"></div><div class="s">NAV</div></div>
      <div class="acct-item"><div class="k">可用现金</div><div class="v" id="acct-cash"></div><div class="s">100% 现金</div></div>
      <div class="acct-item"><div class="k">持仓数量</div><div class="v" id="acct-hold"></div><div class="s">当前持仓只数</div></div>
      <div class="acct-item"><div class="k">择时信号</div><div class="v" id="acct-timing"></div><div class="s" id="acct-rebal"></div></div>
    </div>
  </div>
  <div class="card">
    <h2>下单日报 <span class="tag" id="report-date"></span></h2>
    <table id="report-table">
      <colgroup><col style="width:14%"><col style="width:13%"><col style="width:12%"><col style="width:17%"><col style="width:13%"><col style="width:31%"></colgroup>
      <thead><tr><th class="num">动作</th><th class="num">代码</th><th class="num">股数</th><th class="num">参考价</th><th class="num">成本</th><th>说明</th></tr></thead>
      <tbody></tbody>
    </table>
    <div style="font-size:11.5px;color:var(--tx3);margin-top:10px">
      口径：佣金万3 + 卖出印花税0.05% + 双边过户费 · 当日收盘价模拟成交（正式版 T+1 次日执行）·
      生成命令 <code>python paper_trade.py --report</code>
    </div>
  </div>
</section>

<!-- ===== 净值曲线 ===== -->
<section class="chart-card">
  <h2>组合净值曲线（2026 全段 · 真实成本 · 次日执行）</h2>
  <div class="note">AI[rank_score] Top5/5日：MA60 择时版把回撤从 -32.92% 压到 -9.47%，收益 42.83% → 46.26%</div>
  <div class="chart" id="chart-nav"></div>
</section>

<!-- ===== 成本 + 择时 ===== -->
<section class="two">
  <div class="chart-card">
    <h2>真实成本 vs 简化成本</h2>
    <div class="note">真实成本（佣金+印花税+过户费）与 T+1 次日执行，显著吃掉换手收益</div>
    <div class="chart sm" id="chart-cost"></div>
  </div>
  <div class="chart-card">
    <h2>MA60 择时模式对比</h2>
    <div class="note">固定/滚动阈值均差于均线择时；MA60 收益最高且回撤最小</div>
    <div class="chart sm" id="chart-timing"></div>
  </div>
</section>

<!-- ===== walk-forward ===== -->
<section class="chart-card">
  <h2>Walk-Forward 三折验证（rank vs 分类 vs 动量）</h2>
  <div class="note">折2（2025H2）三类组合同步失效——选股因子失效期，非市场下跌；全池基准回撤仅 -4.8%~-10.3%</div>
  <div class="chart" id="chart-wf"></div>
</section>

<!-- ===== 每日 IC 滚动检验 ===== -->
<section class="chart-card">
  <h2>每日 IC 滚动检验（模型打分 vs 次日实际）</h2>
  <div class="note" id="ic-note"></div>
  <div class="two">
    <div class="chart-card">
      <h2>每日 IC 曲线</h2>
      <div class="note">Spearman(当日 rank_score, 次日涨跌)，20 日滚动均值平滑</div>
      <div class="chart sm" id="chart-ic"></div>
    </div>
    <div class="chart-card">
      <h2>月度平均 IC（近 12 个月）</h2>
      <div class="note">红=当期排序有效，绿=当期失效（2026-07 明显失效月）</div>
      <div class="chart sm" id="chart-ic-m"></div>
    </div>
  </div>
  <div class="acct-grid" style="margin-top:14px">
    <div class="acct-item"><div class="k">全期平均 IC</div><div class="v" id="ic-avg"></div><div class="s" id="ic-pos"></div></div>
    <div class="acct-item"><div class="k">Top20 跑赢全池</div><div class="v" id="ic-beat"></div><div class="s" id="ic-beat-r"></div></div>
    <div class="acct-item"><div class="k">样本交易日</div><div class="v" id="ic-n"></div><div class="s">299 只池 · 次日涨跌口径</div></div>
    <div class="acct-item"><div class="k">今日盘中偏差</div><div class="v" id="ic-today"></div><div class="s" id="ic-today-s"></div></div>
  </div>
</section>

<!-- ===== 模型 Top 候选 ===== -->
<section class="cand-card">
  <h2>模型 Top 候选（LGBMRanker 排序） <span class="tag" id="cand-meta"></span></h2>
  <div class="note">最新交易日截面打分，仅展示模型排序结果，非买入建议；点击任意行查看详情</div>
  <div style="overflow-x:auto">
  <table class="cand-table" id="cand-table">
    <colgroup><col style="width:9%"><col style="width:13%"><col style="width:22%"><col style="width:16%"><col style="width:17%"><col style="width:23%"></colgroup>
    <thead><tr><th class="num">排名</th><th>代码</th><th class="num">rank_score</th><th class="num">收盘价</th><th class="num">当日涨跌</th><th class="num">全池百分位</th></tr></thead>
    <tbody></tbody>
  </table>
  </div>
</section>

<!-- 详情浮层 -->
<div class="modal-mask" id="cand-modal" style="display:none" role="dialog" aria-modal="true">
  <div class="modal">
    <button class="modal-close" id="modal-close" aria-label="关闭">×</button>
    <h3 id="modal-title"></h3>
    <div id="modal-body"></div>
    <div class="warn">rank_score 为 LGBMRanker 截面相对排序分（5 档标签），分数越高代表模型认为未来 5 日相对收益越靠前；当日涨跌为最近交易日行情，与排序信号无直接因果。仅供研究，不构成投资建议。</div>
  </div>
</div>

<!-- ===== 模型说明 ===== -->
<section class="card">
  <h2>模型与数据</h2>
  <div class="model-grid">
    <div class="model-item"><div class="n">300</div><div class="k">股票池</div><div class="s">5年日线 · SQLite 本地仓库</div></div>
    <div class="model-item"><div class="n">23</div><div class="k">特征维度</div><div class="s">19 技术 + 4 财务（同花顺）</div></div>
    <div class="model-item"><div class="n">5 档</div><div class="k">排序标签</div><div class="s">LGBMRanker · 未来5日收益分档</div></div>
    <div class="model-item"><div class="n" id="model-win"></div><div class="k">样本外 AI 胜场</div><div class="s" id="model-win-d"></div></div>
  </div>
</section>

<footer>
  仅供研究与学习，不构成投资建议。模拟盘为历史收盘数据仿真，非真实账户交易；实盘需券商 QMT 权限后接入。
  模型单日预测准确率约 52%，信号强度有限，组合收益主要来自截面排序的相对优势与 MA60 择时的回撤控制。
</footer>

</div>

<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>
var DATA = @@DATA@@;
var fmt = function(v, d){ if(v==null) return "-"; return Number(v).toLocaleString("zh-CN", {minimumFractionDigits:d||0, maximumFractionDigits:d||0}); };
var fmtPct = function(v, d){ if(v==null) return "-"; return (v>0?"+":"") + Number(v).toFixed(d==null?2:d) + "%"; };

/* ---- KPI 填充 ---- */
document.getElementById("kpi-nav").textContent = fmt(DATA.paper.nav, 0);
document.getElementById("kpi-timing").textContent = fmtPct(46.26);
document.getElementById("kpi-oos").textContent = "AI 胜 " + DATA.holdout.ai_win + "/" + DATA.holdout.total;
document.getElementById("kpi-oos-d").textContent = "AI 平均 " + fmtPct(DATA.holdout.avg_ai) + " vs 规则 " + fmtPct(DATA.holdout.avg_rule);

document.getElementById("acct-nav").textContent = fmt(DATA.paper.nav, 0);
document.getElementById("acct-cash").textContent = fmt(DATA.paper.cash, 0);
document.getElementById("acct-hold").textContent = DATA.paper.holdings_count;
document.getElementById("acct-timing").textContent = (DATA.paper.timing == "flat" ? "空仓" : DATA.paper.timing);
document.getElementById("acct-rebal").textContent = "最近调仓 " + DATA.paper.last_rebal + " · 共 " + DATA.paper.total_rebals + " 次";
var st = document.getElementById("acct-status");
if (DATA.paper.timing == "flat") { st.textContent = "空仓避险"; st.className = "tag flat-badge"; }
else { st.textContent = "持有中"; st.className = "tag hold-badge"; }

document.getElementById("report-date").textContent = DATA.report.date;
var tb = document.querySelector("#report-table tbody");
tb.innerHTML = "";
DATA.report.rows.forEach(function(r, i){
  if (i === 0) return; // 跳过表头
  var tr = document.createElement("tr");
  [r[0]||"", r[1]||"", r[2]||"", r[3]||"", r[4]||"", r[5]||""].forEach(function(c){
    var td = document.createElement("td");
    td.textContent = c || "-";
    if (["FLAT","BUY","SELL"].indexOf(c) >= 0) td.classList.add("num");
    tr.appendChild(td);
  });
  tb.appendChild(tr);
});
if (tb.children.length === 0){
  var tr = document.createElement("tr");
  var td = document.createElement("td");
  td.colSpan = 6; td.textContent = "当日无交易，系统按择时信号保持空仓";
  td.style.color = "var(--tx3)";
  tr.appendChild(td); tb.appendChild(tr);
}

document.getElementById("model-win").textContent = DATA.holdout.ai_win + "/" + DATA.holdout.total;
document.getElementById("model-win-d").textContent = "AI 平均 " + fmtPct(DATA.holdout.avg_ai) + " vs 规则 " + fmtPct(DATA.holdout.avg_rule);

/* ---- 图表：净值曲线 ---- */
var navChart = echarts.init(document.getElementById("chart-nav"));
var lastNonNull = function(arr){ for (var i = arr.length-1; i>=0; i--) if (arr[i]!=null) return arr[i]; return null; };
navChart.setOption({
  backgroundColor: "transparent",
  color: ["#f0524d", "#f5a524", "#5b8cff", "#64748b"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: function(v){ return v==null ? "-" : fmt(v, 0); } },
  legend: { data: ["AI rank + MA60择时", "AI rank 无择时", "动量 Top5", "全池等权基准"], top: 0, textStyle: { color: "#8b98ad", fontSize: 11 } },
  grid: { left: 8, right: 16, top: 30, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: DATA.nav.dates, axisLine: { lineStyle: { color: "#1d2a42" } }, axisLabel: { color: "#5c6b82", fontSize: 10, interval: 30 } },
  yAxis: { type: "value", scale: true, axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return (v/10000).toFixed(0) + "万"; } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [
    { name: "AI rank + MA60择时", type: "line", data: DATA.nav.ai_timed, showSymbol: false, lineStyle: { width: 2.4 }, endLabel: { show: true, formatter: function(p){ return fmtPct((p.value/1000000-1)*100, 1); }, color: "#f0524d", fontSize: 11 } },
    { name: "AI rank 无择时", type: "line", data: DATA.nav.ai_plain, showSymbol: false, lineStyle: { width: 1.8, type: "dashed" }, endLabel: { show: true, formatter: function(p){ return fmtPct((p.value/1000000-1)*100, 1); }, color: "#f5a524", fontSize: 11 } },
    { name: "动量 Top5", type: "line", data: DATA.nav.mom_plain, showSymbol: false, lineStyle: { width: 1.4 }, endLabel: { show: true, formatter: function(p){ return fmtPct((p.value/1000000-1)*100, 1); }, color: "#5b8cff", fontSize: 11 } },
    { name: "全池等权基准", type: "line", data: DATA.nav.bench, showSymbol: false, lineStyle: { width: 1.2, type: "dotted", color: "#64748b" }, endLabel: { show: true, formatter: function(p){ return fmtPct((p.value/1000000-1)*100, 1); }, color: "#64748b", fontSize: 11 } }
  ]
});

/* ---- 图表：真实成本 vs 简化成本 ---- */
var costChart = echarts.init(document.getElementById("chart-cost"));
costChart.setOption({
  backgroundColor: "transparent",
  color: ["#5b8cff", "#f0524d"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: function(v){ return v==null ? "-" : fmtPct(v, 1); } },
  legend: { data: ["简化成本+当日成交", "真实成本+次日执行"], top: 0, textStyle: { color: "#8b98ad", fontSize: 11 } },
  grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: ["rank Top5 · 5日", "动量 Top5 · 5日"], axisLabel: { color: "#8b98ad", fontSize: 11 }, axisLine: { lineStyle: { color: "#1d2a42" } } },
  yAxis: { type: "value", axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return v + "%"; } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [
    { name: "简化成本+当日成交", type: "bar", barWidth: 18, label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ return fmtPct(p.value, 1); } }, data: [53.66, 78.12] },
    { name: "真实成本+次日执行", type: "bar", barWidth: 18, label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ return fmtPct(p.value, 1); } }, data: [42.83, 48.58] }
  ]
});

/* ---- 图表：择时模式 ---- */
var timingChart = echarts.init(document.getElementById("chart-timing"));
var timingData = [
  { name: "无择时", v: 42.83, dd: -32.92 },
  { name: "固定阈值0.5", v: 25.04, dd: -12.46 },
  { name: "滚动均值20", v: -2.37, dd: -32.92 },
  { name: "均线MA20", v: 23.76, dd: -15.12 },
  { name: "均线MA60", v: 46.26, dd: -9.47 }
];
timingChart.setOption({
  backgroundColor: "transparent",
  color: ["#5b8cff"],
  tooltip: { trigger: "axis", confine: true, formatter: function(ps){ var d = timingData[ps[0].dataIndex]; return d.name + "<br/>总收益 " + fmtPct(d.v, 1) + "<br/>最大回撤 " + fmtPct(d.dd, 1); } },
  grid: { left: 8, right: 8, top: 20, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: timingData.map(function(d){ return d.name; }), axisLabel: { color: "#8b98ad", fontSize: 10, interval: 0 }, axisLine: { lineStyle: { color: "#1d2a42" } } },
  yAxis: { type: "value", axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return v + "%"; } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [{
    name: "总收益", type: "bar", barWidth: 20,
    itemStyle: { color: function(p){ return p.value < 0 ? "#2fbf71" : (p.dataIndex === 4 ? "#f0524d" : "#5b8cff"); } },
    label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ var d = timingData[p.dataIndex]; return fmtPct(d.v, 1) + " / 回撤" + fmtPct(d.dd, 0); } },
    data: timingData.map(function(d){ return d.v; })
  }]
});

/* ---- 图表：walk-forward ---- */
var wfChart = echarts.init(document.getElementById("chart-wf"));
wfChart.setOption({
  backgroundColor: "transparent",
  color: ["#f0524d", "#5b8cff", "#f5a524"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: function(v){ return v==null ? "-" : fmtPct(v, 1); } },
  legend: { data: ["AI[rank_score]", "AI[ai_prob] 分类", "动量 TopN"], top: 0, textStyle: { color: "#8b98ad", fontSize: 11 } },
  grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: DATA.wf.labels, axisLabel: { color: "#8b98ad", fontSize: 11 }, axisLine: { lineStyle: { color: "#1d2a42" } } },
  yAxis: { type: "value", axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return v + "%"; } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [
    { name: "AI[rank_score]", type: "bar", barWidth: 16, label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ return fmtPct(p.value, 1); } }, data: DATA.wf.rank },
    { name: "AI[ai_prob] 分类", type: "bar", barWidth: 16, label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ return fmtPct(p.value, 1); } }, data: DATA.wf.cls },
    { name: "动量 TopN", type: "bar", barWidth: 16, label: { show: true, position: "top", color: "#8b98ad", fontSize: 10, formatter: function(p){ return fmtPct(p.value, 1); } }, data: DATA.wf.mom }
  ]
});

/* ---- 图表：每日 IC ---- */
var icChart = echarts.init(document.getElementById("chart-ic"));
var icInterval = Math.floor((DATA.ic.dates.length - 1) / 8);
if (icInterval < 0) icInterval = 0;
icChart.setOption({
  backgroundColor: "transparent",
  color: ["#5b8cff", "#f5a524"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: function(v){ return v == null ? "-" : Number(v).toFixed(4); } },
  legend: { data: ["每日 IC", "20日均IC"], top: 0, textStyle: { color: "#8b98ad", fontSize: 11 } },
  grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: DATA.ic.dates, axisLine: { lineStyle: { color: "#1d2a42" } }, axisLabel: { color: "#5c6b82", fontSize: 10, interval: icInterval } },
  yAxis: { type: "value", axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return v.toFixed(2); } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [
    { name: "每日 IC", type: "line", data: DATA.ic.ic, showSymbol: false, lineStyle: { width: 1.2, color: "#5b8cff", opacity: .55 },
      markLine: { silent: true, symbol: "none", lineStyle: { color: "#2fbf71", type: "dashed", width: 1 }, data: [{ yAxis: 0 }], label: { show: false } } },
    { name: "20日均IC", type: "line", data: DATA.ic.ma20, showSymbol: false, lineStyle: { width: 2.2, color: "#f5a524" } }
  ]
});

/* ---- 图表：月度平均 IC ---- */
var icmChart = echarts.init(document.getElementById("chart-ic-m"));
icmChart.setOption({
  backgroundColor: "transparent",
  color: ["#f0524d", "#2fbf71"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: function(v){ return v == null ? "-" : Number(v).toFixed(4); } },
  grid: { left: 8, right: 8, top: 16, bottom: 6, containLabel: true },
  xAxis: { type: "category", data: DATA.ic.months, axisLabel: { color: "#8b98ad", fontSize: 10, interval: 0 }, axisLine: { lineStyle: { color: "#1d2a42" } } },
  yAxis: { type: "value", axisLabel: { color: "#5c6b82", fontSize: 10, formatter: function(v){ return v.toFixed(2); } }, splitLine: { lineStyle: { color: "#141f36" } } },
  series: [{
    name: "月度平均 IC", type: "bar", barWidth: 18,
    itemStyle: { color: function(p){ return p.value < 0 ? "#2fbf71" : "#f0524d"; } },
    label: { show: true, position: "top", color: "#8b98ad", fontSize: 9, formatter: function(p){ return p.value.toFixed(3); } },
    data: DATA.ic.m_ic
  }]
});

/* ---- IC 统计填充 ---- */
var icS = DATA.ic.stats || {};
document.getElementById("ic-avg").textContent = icS.avg == null ? "-" : (icS.avg > 0 ? "+" : "") + icS.avg.toFixed(4);
document.getElementById("ic-pos").textContent = "IC>0 占比 " + (icS.pos == null ? "-" : icS.pos + "%");
document.getElementById("ic-beat").textContent = icS.beat == null ? "-" : icS.beat + "%";
document.getElementById("ic-beat-r").textContent = "近一年 Top20 跑赢 " + (icS.r_beat == null ? "-" : icS.r_beat + "%");
document.getElementById("ic-n").textContent = icS.n == null ? "-" : icS.n;
var td = DATA.ic.today;
if (td) {
  document.getElementById("ic-today").textContent = (td.ic > 0 ? "+" : "") + td.ic.toFixed(3);
  document.getElementById("ic-today-s").textContent = "Top20 " + (td.top20 > 0 ? "+" : "") + td.top20.toFixed(2) + "% vs 全池 " + (td.pool > 0 ? "+" : "") + td.pool.toFixed(2) + "% · 涨 " + td.hit + "/20";
} else {
  document.getElementById("ic-today").textContent = "待收盘";
  document.getElementById("ic-today-s").textContent = "盘中 IC 收盘后滚动更新";
}
var icNote = "全期 " + (icS.n || "-") + " 个交易日平均 IC " + (icS.avg == null ? "-" : (icS.avg > 0 ? "+" : "") + icS.avg.toFixed(4)) + "，IC>0 占比 " + (icS.pos == null ? "-" : icS.pos + "%") + "；Top20 次日平均跑赢全池占比 " + (icS.beat == null ? "-" : icS.beat + "%") + "——排序优势集中在头部而非全截面。";
if (td) {
  icNote += "今日盘中偏差：昨日 Top20 今日平均 " + (td.top20 > 0 ? "+" : "") + td.top20.toFixed(2) + "% vs 全池 " + (td.pool > 0 ? "+" : "") + td.pool.toFixed(2) + "%（大盘普涨日模型偏好的小盘/科创板跑输），单日噪声大，以滚动 IC 为准。";
}
document.getElementById("ic-note").textContent = icNote;

/* ---- 模型 Top 候选 + 详情浮层 ---- */
var cands = DATA.candidates.candidates || [];
document.getElementById("cand-meta").textContent = "数据日 " + DATA.candidates.as_of + " · " + DATA.candidates.total_scored + " 只打分";
var ct = document.querySelector("#cand-table tbody");
ct.innerHTML = "";
cands.forEach(function(c){
  var tr = document.createElement("tr");
  tr.innerHTML = "<td class='num' style='color:var(--tx2)'>#" + c.rank + "</td>"
    + "<td class='sym'>" + c.symbol + "</td>"
    + "<td class='num'>" + Number(c.score).toFixed(4) + "</td>"
    + "<td class='num'>" + fmt(c.close, 2) + "</td>"
    + "<td class='num " + (c.chg >= 0 ? "chg-up" : "chg-dn") + "'>" + fmtPct(c.chg, 2) + "</td>"
    + "<td class='num' style='color:var(--tx2)'>前 " + Number(c.pctile).toFixed(1) + "%</td>";
  tr.addEventListener("click", function(){ openCand(c); });
  ct.appendChild(tr);
});
function openCand(c){
  var rows = [
    ["代码", c.symbol],
    ["rank_score", Number(c.score).toFixed(4)],
    ["全池排名", "#" + c.rank + " / " + DATA.candidates.total_scored],
    ["全池百分位", "前 " + Number(c.pctile).toFixed(1) + "%"],
    ["收盘价", fmt(c.close, 2)],
    ["当日涨跌", fmtPct(c.chg, 2)]
  ];
  var body = rows.map(function(r){
    return "<div class='row'><span class='k'>" + r[0] + "</span><span class='v'>" + r[1] + "</span></div>";
  }).join("");
  document.getElementById("modal-title").textContent = "股票 " + c.symbol;
  document.getElementById("modal-body").innerHTML = body;
  document.getElementById("cand-modal").style.display = "flex";
}
function closeCand(){
  document.getElementById("cand-modal").style.display = "none";
}
document.getElementById("modal-close").addEventListener("click", closeCand);
document.getElementById("cand-modal").addEventListener("click", function(e){
  if (e.target === this) closeCand();
});
document.addEventListener("keydown", function(e){
  if (e.key === "Escape") closeCand();
});

window.addEventListener("resize", function(){
  navChart.resize(); costChart.resize(); timingChart.resize(); wfChart.resize(); icChart.resize(); icmChart.resize();
});
</script>
</body>
</html>
"""

html_out = HTML.replace("@@DATA@@", json.dumps(DATA, ensure_ascii=False))
out_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(out_dir, "AI量化系统看板.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_out)
print("OK ->", out_path)
print("holdout:", total, "AI胜", ai_win, "胜率", round(ai_win / total * 100, 1) if total else "-")
print("nav 点数:", len(dates), "首", dates[0] if dates else "-", "末", dates[-1] if dates else "-")
