# Quant Research & Backtesting · 量化研究与回测

**用 Python 演示行情处理、因子计算、回测和数据质量检查。** 提供不依赖真实行情或训练模型的合成数据演示，以及可选的 React 可视化面板。

A research-oriented Python project for market data, factor engineering and backtesting. Start with the offline synthetic example; historical research results are kept separate from the reproducible demo.

[离线运行](#quick-start) · [Web 面板](webapp/README.md) · [环境说明](docs/environment.md) · [历史研究记录](docs/research-history.md)

## Does the Amihud signal add value beyond low trading value?

I tested a simple explanation for an A-share signal: stocks with a high Amihud score might owe their returns to low trading value alone. The score averages the absolute daily return divided by daily traded value over 20 sessions. To test the extra information in that ratio, I compared its top 20 stocks with a portfolio selected solely for low average traded value, matching the two portfolios by listing board, size decile within board, and industry.

Both simulated accounts started with CNY 1 million and rebalanced every five sessions at the next open. The replay included lot sizes, price-limit checks, commissions, transfer fees, sell-side stamp duty and slippage. Here is the same 37-period comparison from January 5 to October 16, 2026, with only the slippage assumption changed.

| Slippage per side | Amihud net return | Matched control | Difference |
| --- | ---: | ---: | ---: |
| 10 basis points | 20.20% | 21.47% | −1.27 pp |
| 40 basis points | 13.69% | 12.71% | +0.98 pp |

**Why could Amihud win 21 of 37 periods and still finish behind?** At base cost, its average lead in winning periods was 0.42 percentage points, while its average deficit in losing periods was 0.60. A stock-by-stock reconciliation showed that Amihud saved about CNY 9,139 in fees and simulated slippage, but lost CNY 21,817 relative to the control on price moves. I kept the simpler control in the prospective comparison. The ranking of the two strategies depends on what it costs to trade them.

These figures come from a historical research replay on daily bars. Industry classifications use a snapshot, historical stock eligibility is incomplete, and daily opens approximate execution. The private market dataset is required to reproduce the figures. The [offline quick start](#quick-start) exercises the public backtesting pipeline using synthetic data.

## Trace a backtest

The offline example generates 800 synthetic daily bars. To inspect one run, follow the prices from the generator through the rule strategy to the backtest result. The same command-line entry point also accepts local A-share data.

1. [Run the example](#quick-start) and open `output/demo.json`.
2. Read the [price generator](data/fetcher.py) and the [rule strategy](strategy/ma_cross.py) to see what the strategy observes.
3. Follow the [backtest engine](backtest/engine.py) to see how the strategy produces the reported result.

For a small experiment, change the fast and slow periods and rerun the example with a different output filename. Differences on synthetic prices illustrate how the rules behave. Historical research has its own [data assumptions and limitations](docs/research-history.md).

## What is included

| 模块 | 内容 |
| --- | --- |
| 数据处理 | pandas、SQLite、本地优先读取与可选行情下载 |
| 因子 | 均线、动量、波动、RSI、ATR 等 |
| 回测 | backtrader 单标的回测与组合研究工具 |
| 模型研究 | 分类和排序模型的训练、加载与评分脚本 |
| 可视化 | React 看板展示 K 线、资金曲线、指标与交易记录 |
| 数据质量 | 独立 raw 行情层、只读健康检查与测试 |

## Quick start

需要 Python 3.11+。从仓库根目录执行：

```bash
git clone https://github.com/zihanxu330/intelligent-data-analysis-platform.git
cd intelligent-data-analysis-platform
python -m venv .venv
```

激活虚拟环境后安装离线演示依赖：

```bash
python -m pip install -r requirements-demo.txt
python main.py --mode synthetic --no-plot --json-out output/demo.json
```

这条命令生成合成行情并运行默认规则策略，输出指标与 `output/demo.json`，不下载真实行情、不训练模型，也不调用 LLM。结果只用于验证工程流程。

需要资金曲线图时：

```bash
python main.py --mode synthetic
```

完整的数据采集与机器学习环境使用 `requirements.txt`；Python 3.11 的历史锁定记录见 `requirements-lock-py311.txt`。安装细节见 [环境说明](docs/environment.md)。

## Web dashboard

[webapp/README.md](webapp/README.md) 包含 Node 服务与 React 客户端的启动步骤。Web 面板默认使用合成数据；切换到真实行情后可能联网并写入本地数据。

## Project map

```text
main.py            CLI / Web 调用的回测入口
data/              合成数据生成与行情读取
data_engine/       SQLite、下载与 raw 行情校验
factors/           因子与特征工程
strategy/          示例策略
backtest/          回测引擎、费用与组合约束
models/            模型加载与评分
tools/             健康检查、研究索引与纸面结算工具
tests/             离线工程测试
webapp/            React + Node.js 可视化面板
docs/              环境、数据口径与历史研究说明
```

## Verification

```bash
python -m unittest discover -s tests -v
```

测试覆盖临时数据库、raw 行情解析、索引检查及路径可移植性等工程行为。运行完整测试前请安装 `requirements.txt` 中的完整依赖（包括 AkShare 与 mini-racer）；演示依赖仅覆盖离线回测。详见 [raw 行情文档](docs/raw_market.md)。

`python tools/project_healthcheck.py` 和 `python tools/research_index_check.py` 用于检查你本地的数据与研究产物。全新克隆不包含这些产物，缺失项应如实报告，不能据此宣称数据就绪。

## Data and model boundaries

- 仓库不附带 `output/quant.db`、训练模型、全市场行情或冻结研究产物。
- `real` 模式可能联网并写入本地数据库；`pipeline.py`、训练脚本和纸面交易脚本会写运行产物。运行前请阅读对应说明。
- 历史 300 池、全池、不同日期和价格口径的结果不能混用。
- 部分交易规则和数据口径仍有近似或缺口；研究记录没有证明稳定 Alpha。
- 纸面跟踪脚本缺少配套 ST/退市过滤函数和可选预警评分函数，目前会在读取数据或写状态前明确拒绝运行；CLI 帮助仍可使用。此模块尚未达到可执行状态。
- 项目用于学习与研究，历史回测或合成数据结果不代表未来收益。

## Further reading

- [环境与依赖](docs/environment.md)
- [raw 行情层](docs/raw_market.md)
- [历史 README 与研究边界](docs/research-history.md)
- [研究阶段索引（原始产物不随仓库提供）](docs/research-index.md)
- [研究结论修正记录](docs/research-corrections.md)

欢迎提交可复现的问题、离线测试或数据校验改进。许可证见 [LICENSE](LICENSE)。
