# 历史研究记录

以下内容保留自 2026-10-24 整理前的 README，用于追踪研究过程，不是当前运行状态或可复现绩效承诺。

- 文中日期与阶段描述是当时的快照。
- 涉及的行情库、训练模型、审计报告和 `output/research_stage*` 不随本仓库分发。
- 文中的历史收益数字缺少随仓库发布的完整输入与冻结产物，不能作为当前版本的验证结果。
- 当前可运行入口请见 [仓库 README](../README.md)。

---

# quant_ai —— A股量化回测最小可用系统

> **2026-10-19 审计提示**：当前生产口径是**全池 5,225 只**（`output/symbols_full.txt`，实际有日线 5,224），生产模型 `output/model_rank_h3p_full.joblib` 的 `train_until=20261015`。本文下方“300 只股票池 / 23 特征 / walk-forward 平均 +28.07%”等数字是**历史 300 池记录**，不可作为当前全池结论。最新审计见 `output/audit_20261019/AUDIT_REPORT_20261019.md`，全池 walk-forward 与数据口径以该报告为准。


## 当前阶段与工程入口（2026-10-21）

当前处于 **Stage39 执行日等待**：

- 生产 `output/quant.db` 仍停在 **2026-10-16**；
- Stage37 已建立 5,190 只 eligible pool 的纸面 run；
- Stage38/39 核实 2026-10-22 行情未到，70 条订单保持 pending/blocked；
- 没有成交、持仓或前瞻 NAV 绩效；
- 本阶段未改生产库、生产模型和 `paper_trade.py`；工作区已有未提交的 `paper_trade.py`/`pipeline.py`/`requirements.txt` 修改，需另行 review，本阶段未处理。

### 快速开始

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/project_healthcheck.py
python tools/project_healthcheck.py --json
python tools/project_healthcheck.py --as-of 2026-10-21 --expected-date 2026-10-21
python tools/research_index_check.py --json
```

健康检查默认只读、不联网；`--json` 输出机器可读报告；不传 `--expected-date` 时行情新鲜度为 `unknown`，不猜交易日。

### 关键目录

| 路径 | 用途 |
|---|---|
| `main.py` / `pipeline.py` | 主回测入口 / 行情更新入口 |
| `data_engine/` | 本地数据库、增量行情、raw 行情层 |
| `factors/` | 因子与特征工程 |
| `models/` | 模型加载与打分 |
| `backtest/` | 回测与组合约束 |
| `strategy/` | 策略 |
| `tools/project_healthcheck.py` | 只读健康检查 |
| `tools/research_index_check.py` | 只读研究索引一致性检查 |
| `output/quant.db` | 生产行情库（只读检查，不随意写） |
| `output/research_stage*` | 冻结研究产物 |
| `docs/research-index.md` | Stage 研究产物索引 |

### 常用命令与副作用

| 命令 | 作用 | 联网 | 写数据库/模型 | 备注 |
|---|---|---|---|---|
| `python main.py --mode synthetic` | 离线合成回测 | 否 | 否 | 安全 |
| `python main.py --mode real --symbol 600519` | 真实行情回测 | 是 | 写运行产物/缓存 | 可能写 `output/cache` |
| `python pipeline.py` | 行情更新 | 是 | 写 `output/quant.db` | 生产数据入口，谨慎运行 |
| `python research/stage37_eligible_pool.py` | 重建 eligible pool 纸面信号 | 否 | 只写 Stage37 研究目录 | 会重算模型评分 |
| `python research/stage39_execution.py` | 执行日数据审计 | 是 | 只写 Stage39 研究目录 | 目标日未到则保持 pending |
| `python paper_trade.py` | 生产纸面跟踪 | 是 | 写 `output/paper` | 不是研究脚本，谨慎运行 |
| `python train_rank.py` | 训练排序模型 | 否 | 写模型 | 本阶段不执行 |
| `python predict_weekly_top20.py` | 生成 Top20 预测 | 否 | 写 `output` 预测文件 | 不等于前瞻成交 |

### 研究、纸面、生产三层

- **研究结论**：`output/research_stage*/final_assessment.md`，可能部分完成/受阻，不等于可交易。
- **纸面跟踪**：Stage37 的 5,190 eligible pool；有 pending 订单不等于成交，无 10-22 数据就没有 fills/NAV。
- **生产配置**：`output/quant.db`、`output/model_rank_h3p_full.joblib`、`paper_trade.py`。研究脚本不得写这些对象。

### 已知限制

- 生产库仍是 stale-qfq，锚点推断 2026-10-16；
- 5,225 只中 35 只不可评分（25 只上市不足 60 日、10 只无 10-21 行情）；
- 纸面 run 只覆盖 5,190 只 eligible pool，不是全池；
- 2026-10-22 执行数据尚未到达；
- 尚无稳定 Alpha 的证据。

详细阶段索引见 [`docs/research-index.md`](research-index.md)。

## raw 行情层（独立于生产库）

`data_engine/raw_market.py` 是新浪 KLC raw 日线的抓取、离线解码、校验和独立存储模块：

- 只接受 `price_basis=raw`；
- 原始 body 落盘 + SHA-256；
- 目标日、无数据、解析失败、请求失败分开；
- amount/turnover 缺失保留 NULL；
- `RawStore` 只追加，冲突写 `raw_daily_conflicts`；
- 不写 `output/quant.db`，不生成信号/订单。

```bash
python -m data_engine.raw_market init --db output/forward_raw.db
python -m data_engine.raw_market parse --klc fixture.js --symbol 600000 --date 2026-10-20
python -m unittest discover -s tests -v
```

详见 `docs/raw_market.md`。

## 目录结构

```
quant_ai/
├── data/
│   └── fetcher.py         # 真实A股数据（AkShare）+ 合成数据生成器（离线测试用）
├── factors/
│   └── factor_lib.py      # 均线/动量/波动率/RSI/布林带等因子计算
├── strategy/
│   ├── ma_cross.py        # 多因子规则趋势策略（默认策略）
│   └── ai_decision.py     # 纯AI决策策略（买卖全由模型预测概率驱动）
├── models/
│   └── predict.py         # 加载训练模型给行情打 ai_prob（未来上涨概率）
├── backtest/
│   └── engine.py          # backtrader回测封装，输出绩效指标+资金曲线图
├── train_model.py         # 训练"未来N日涨跌"分类模型（随机森林）
├── main.py                # 入口脚本
├── requirements.txt
└── output/                # 回测结果、图表、数据缓存输出目录
```

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 离线验证（不需要网络，用合成数据跑通整条链路）

```bash
python main.py --mode synthetic
```

### 2. 真实A股数据回测

```bash
python main.py --mode real --symbol 600519 --start 20230101 --end 20241231
```

`--symbol` 是不带交易所前缀的6位代码，例如贵州茅台是 `600519`，平安银行是 `000001`。

首次拉取会自动缓存到 `output/cache/`，重复运行同一区间不会重复请求接口。

### 3. 输出结果

运行后会在终端打印：
- 初始/期末资金、总收益率
- 夏普比率、最大回撤
- 总交易次数、胜率

同时会在 `output/equity_curve.png` 生成资金曲线图。

## 接下来可以怎么扩展

1. **换策略**：在 `strategy/` 下新建文件，继承 `bt.Strategy`，参考 `ma_cross.py` 的结构，
   在 `main.py` 里替换 `strategy_cls` 即可。

2. **加因子驱动的选股**：用 `factors/factor_lib.py` 里的 `build_full_factor_table()`
   对多只股票批量计算因子，做横截面打分排序，构建多因子选股策略。

3. **接入机器学习**：
   - 用因子表当特征（X），未来N日收益率或涨跌方向当标签（y）
   - 先用 `sklearn` 的逻辑回归/随机森林跑通训练→预测→回测的闭环
   - 注意时间序列数据不能随机切分train/test，要按时间顺序切分，
     并且预测用的特征在预测时点必须是"已经发生"的信息，避免未来函数（look-ahead bias）

4. **多标的组合回测**：目前是单只股票，可以扩展成多只股票的组合，
   加入仓位分配、行业分散、最大持仓数限制等风控规则。

5. **参数优化时注意过拟合**：backtrader自带 `optstrategy` 可以做参数网格搜索，
   但要用样本外数据（out-of-sample）验证，不要只看训练区间表现最好的参数组合。

## 可视化前端（Web界面）

`webapp/` 目录下有一套 Node.js + React 的可视化面板，可以在浏览器里选股票、
调参数、点击运行回测，看K线图、资金曲线、绩效指标和逐笔交易记录，不用再敲命令行。
用法见 `webapp/README.md`。

## 策略说明（V2 多因子版）

`strategy/ma_cross.py` 现在是多因子趋势策略（类名仍叫 `MACrossStrategy`，保持对外接口不变）：
- **买入条件**：MA10 > MA30 > MA60（趋势多头排列）+ 20日动量为正 + RSI处于40~70（避免追高）
- **卖出条件**：ATR动态止损 / 移动止盈回撤12% / 快慢线死叉（趋势反转）
- 仓位管理：单次最多用70%资金（`max_position`参数）

`factors/factor_lib.py` 新增了 `add_atr()`（ATR真实波幅）和 `add_trend_strength()`（趋势强度，基于MA20与MA60的偏离度）。

当前 `main.py` 和 Web前端只暴露了 `fast_period`/`slow_period` 两个可调参数，
`trend_period`、`atr_stop`、`trailing_stop`、`rsi`区间等新参数目前是策略里的固定值，
如果需要在前端也能调这些参数，可以照着 `main.py` 里 `--fast-period`/`--slow-period` 的写法加对应的CLI参数，
再在 `webapp/server/server.js` 和 `webapp/client/src/components/ParamForm.jsx` 里透传。

## 策略说明（AI 决策版）

`strategy/ai_decision.py`（`AIDecisionStrategy`）是纯 AI 决策策略：**买卖时机完全由机器学习模型决定，不含均线/动量/RSI 等规则条件**。

- **决策流程**：`train_model.py` 训练的"未来N日涨跌"分类模型，对每根K线输出上涨概率 `ai_prob`；
  空仓且 `ai_prob >= buy_threshold`（默认0.55）→ 买入；持仓且 `ai_prob < sell_threshold`（默认0.45）→ 卖出
- **兜底风控**：可选的 ATR 止损（`use_atr_stop=True` 时生效），仅在模型失效/价格极端下兜底，不参与交易决策，可关闭
- **使用方式**：`python main.py --mode real --strategy ai --symbol 600519 --start 20260601 --end 20261015`
- **对比**：`rule`（多因子规则，默认）与 `ai` 两种决策方式可通过 `--strategy` 一键切换；
  批量对比结果见 `output/rule_vs_ai_20261015.csv`

> 注意：模型预测精度取决于训练数据量。当前主线已升级为 **300 只股票 × 5 年日线** +
> 23 特征 + 排序学习（见下方「近期升级」章节），旧版单票示例仅供跑通闭环；
> 用于真实决策前请先做样本外 / walk-forward 验证，不要直接拿历史回测结果当实盘预期。

## 近期升级（2026-10）：AI 决策 → 排序学习 → 组合框架 → Paper Trading

从"单票 AI 策略"演进为"多标的 AI 组合 + 模拟盘"的完整流水线：

- **一键流水线** `pipeline.py`：下载 → 训练 → 样本外对比，一条命令跑完
- **股票池扩展**：300 只 A 股 × 5 年日线（`output/symbols_300.txt`），23 特征（19 技术 + 4 财务，`factors/factor_lib.py::add_extended_features`）
- **样本外验证**：holdout 300 只（2026 年）规则 -3.65% vs AI -0.15%，AI 胜 194/300；walk-forward 3 折 rank 平均 +28.07%
- **排序学习** `train_rank.py`：LGBMRanker 直接优化截面排名（5 档相关度标签），`models/predict.py::add_rank_score` 打分
- **组合框架** `backtest/portfolio.py`：默认次日开盘成交、双边 0.1% 滑点、最低佣金 5 元、100 股整手及涨跌停约束；卖出印花税按历史费率分档（2023-08-28 起 0.05%），停牌保留至复牌估值，支持择时（fixed/rolling/MA60）。板块涨跌停比例仍为近似值，未区分 ST 和新股无涨跌幅限制期。
- **择时验证**：rank Top5/5 日，MA60 择时 +46.26%（回撤 -9.47% vs 无择时 -32.92%）
- **Paper Trading** `paper_trade.py`：排序模型 + MA60 择时，每日收盘后运行，状态持久化；`--report` 生成下单日报（CSV+MD）供手工实盘下单过渡

## 个股涨跌归因（analyze_move.py）

给定股票和区间，把"为什么涨/跌"拆成可复现的事实链，输出 Markdown 报告 + JSON 事实包 + 图表：

```bash
python analyze_move.py --symbol 603986 --start 20260101 --end 20261016
python analyze_move.py --symbol 600519 --start 20260101 --end 20260630 --top-days 8
```

输出到 `output/analysis/<code>_<start>_<end>.{md,json,png}`：

- **收益拆解**：市场（全市场等权）+ 行业超额（行业等权 - 市场）+ 个股特质（个股 - 行业），对数贡献可加
- **CAPM**：β、α、R²；**关键交易日**：涨跌停、跳空、量比、当日行业超额、±N 日公告/研报
- **事件时间线**：重大公告、研报评级、财报（按 +90 天披露滞后对齐）
- **因子画像**：动量、波动、RSI、价格位置、量比，给自身 3 年分位
- **规则化结论**：只引用报告里的数字，不做因果断言

数据边界：公告只覆盖 2025-10 之后；研报只覆盖 250 只老池；价格为不复权收盘价；市场基准是当前存续 5225 只的等权，存在幸存者偏差（早期年份市场收益可能偏高）。报告末尾会自动列出这些警告。

### 可选的 LLM 解读（事实约束）

```bash
# 任意 OpenAI 兼容端点；PowerShell 用 $env:LLM_API_KEY="..."
set LLM_API_KEY=sk-xxx
set LLM_BASE_URL=https://api.deepseek.com/v1
set LLM_MODEL=deepseek-chat

python analyze_move.py --symbol 603986 --start 20260101 --end 20261016 --llm
python analyze_move.py --symbol 603986 --start 20260101 --end 20261016 --llm-dry-run
```

- `--llm-dry-run` 只生成 `_llm_prompt.txt`，不调用 API，方便先检查事实包。
- `--llm` 输出 `_llm.md`，并追加到报告末尾的“AI 解读（事实约束）”。
- prompt 强制模型只能引用 JSON 事实、每条结论带日期/数字、不得编造公告；归因不等于因果。

## 重要提醒

- 本项目中的策略（双均线交叉）只是用来验证回测链路是否work的示例，
  **没有做过严谨的有效性验证，不构成任何投资建议**。
- 回测结果不代表未来实盘表现，历史数据存在过拟合、幸存者偏差等风险。
- 如果之后要接入实盘交易，需要额外考虑：滑点、真实的涨跌停限制、
  T+1交易制度、印花税（卖出0.05%）、券商接口对接、异常情况熔断机制等，
  这些在当前的回测框架里都还没有覆盖。
