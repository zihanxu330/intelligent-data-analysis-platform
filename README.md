# quant_ai —— A股量化回测最小可用系统

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

## 重要提醒

- 本项目中的策略（双均线交叉）只是用来验证回测链路是否work的示例，
  **没有做过严谨的有效性验证，不构成任何投资建议**。
- 回测结果不代表未来实盘表现，历史数据存在过拟合、幸存者偏差等风险。
- 如果之后要接入实盘交易，需要额外考虑：滑点、真实的涨跌停限制、
  T+1交易制度、印花税（卖出0.05%）、券商接口对接、异常情况熔断机制等，
  这些在当前的回测框架里都还没有覆盖。
