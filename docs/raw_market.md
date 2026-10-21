# raw 行情抓取与清洗模块

模块：`data_engine/raw_market.py`

目标：把 Stage23–31 中临时脚本里的重复逻辑收拢成一个可复用、可测试、默认不碰生产库的模块。

## 边界

- 只接收 `price_basis=raw`；
- 原始响应必须落盘 + SHA-256；
- 解析失败、请求失败、无目标行分开；
- amount/turnover 缺失保留 `NULL`；
- 独立 SQLite 只追加，冲突写 `raw_daily_conflicts`；
- 不写 `output/quant.db`；
- 不生成信号、订单、成交。

## 结构

| 对象 | 作用 |
|---|---|
| `SinaRawSource` | 新浪 KLC/amount 抓取，保存原始 body |
| `parse_klc_bytes` | 用冻结 AkShare JS 解码 KLC |
| `parse_amount_jsonp` | 解析 amount JSONP；`(null)` 返回 None |
| `pick_target` | 精确目标日，否则返回最后日期 |
| `build_bar` | 构造并校验 `RawBar`；turnover 仅在股本可用时派生 |
| `RawBar.validate` | 6 位代码、日期、OHLC、非负、raw 口径、哈希 |
| `RawStore` | 建表、只追加、冲突保留、状态旁路 |
| `fetch_universe` | 顺序抓取并写库；失败不伪造行情 |

## CLI

```bash
python -m data_engine.raw_market init --db output/forward_raw.db

python -m data_engine.raw_market parse \
  --klc output/.../689009_klc.js \
  --symbol 689009 --date 2026-10-20

python -m data_engine.raw_market fetch \
  --symbols 600000,000001 \
  --date 2026-10-20 \
  --raw-dir output/raw \
  --db output/forward_raw.db
```

## 状态

- `ok`：目标日有行；
- `no_data`：源有历史但目标日无行；
- `parse_failed`：payload 不能解码；
- `request_failed`：网络失败；
- `http_error`：非 200；
- `source_status` 保留具体原因。

## 单位

- KLC `volume`：股；
- KLC `amount`：元（源字段）；
- `turnover`：只有 amount JSONP 的股本可用时才计算，标记 `derived`；
- 独立验证仍需第二来源；模块不自动宣称 `verified`。

## 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：

- raw/qfq 拒绝；
- OHLC 关系；
- amount JSONP `null`；
- 目标日缺失；
- 追加幂等；
- 冲突不覆盖；
- 状态可区分；
- 无 amount 时 turnover=NULL。
