# 跨阶段结论修正清单

本清单只记录源报告中明确的“后续修正/限定前序”的关系；不修改前序报告原文。

| 后续 Stage | 被修正/限定的前序 | 修正内容 | 证据 |
|---|---|---|---|
| Stage14 | Stage12 / Stage13 | Stage12/13 将 20 日 `cum_ex_top1` 与 5 日 `total` 比较，导致“剔除最佳批次后反转”的错误结论；按 Stage4 官方 `batch_returns` 重算 18/18 后，20 日没有反转。 | `output/research_stage14_batch_reconcile_20261019/final_assessment.md` |
| Stage9.4c | Stage9.4b | Stage9.4b 的“双源 100% 完成”降级为：96 只双源成功、1 只 THS 失败、3 只无事件；002282 的 17 条 THS 是 `request_failed`。 | `output/research_stage9_4c_20261019/final_assessment.md` |
| Stage20c / Stage20d | Stage20b（688610 跳空） | 688610 的 -27.88% 不是脏数据，而是 10 转 4 + 10 派 2；理论除权 80.5714。 | `output/research_stage20c_corporate_action_review_20261020/final_assessment.md`; `output/research_stage20d_adjustment_ledger_20261020/final_assessment.md` |
| Stage20i / Stage20j | Stage20g 候选可直接拼接的假设 | DB 是 stale-qfq，候选是 current-qfq；直接拼接会产生假跳空，必须先做锚点转换/事件调整。 | `output/research_stage20i_price_basis_source_20261020/final_assessment.md`; `output/research_stage20j_anchor_reconciliation_20261020/final_assessment.md` |
| Stage29 修正版 | Stage29 初版 | 20 亿成交额下用 0.01 元绝对容差过严，123 行 amount 误报；改相对容差 1e-6 后 amount 498/498。 | `output/research_stage29_unit_cross_20261021/README.md`; `final_assessment.md` |
| Stage30 | Stage28 | 000016/002731 只有长窗口最后交易日证据，不能升级为确认停牌；保留 inferred/unverified。 | `output/research_stage28_status_closure_20261021/final_assessment.md`; `output/research_stage30_edge_policy_20261021/final_assessment.md` |
| Stage35 / Stage36 / Stage37 / Stage38 / Stage39 | Stage34 的单日“全池可用”印象 | 后续依次限定为：10-21 增量、锚点转换、5,190 eligible pool、10-22 无执行数据；不是 5,225 全池可交易。 | `output/research_stage35_daily_forward_20261021/final_assessment.md`; `output/research_stage36_anchor_conversion_20261021/final_assessment.md`; `output/research_stage37_eligible_pool_20261021/final_assessment.md`; `output/research_stage38_execution_20261022/final_assessment.md`; `output/research_stage39_execution_20261022/final_assessment.md` |

## 检查范围

已核对 Stage9.4b/9.4c、Stage12/13/14、Stage20b/c/d/i/j、Stage28/29/30、Stage31、Stage34–39 的 `final_assessment.md`/README 与关键数字。  
未声称对所有历史 Stage 的每个数字做了全量重算；只记录报告中有明确文字支持的修正关系。
