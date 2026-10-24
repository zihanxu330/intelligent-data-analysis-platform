# Quant Research & Backtesting · 量化研究与回测

**用 Python 演示行情处理、因子计算、回测和数据质量检查。** 提供不依赖真实行情或训练模型的合成数据演示，以及可选的 React 可视化面板。

A research-oriented Python project for market data, factor engineering and backtesting. Start with the offline synthetic example; historical research results are kept separate from the reproducible demo.

[离线运行](#quick-start) · [Web 面板](webapp/README.md) · [环境说明](docs/environment.md) · [历史研究记录](docs/research-history.md)

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
