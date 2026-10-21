# 研究阶段索引

只读扫描 `output/research_stage*` 生成；结论摘要取各阶段 `final_assessment.md` 或 `README.md` 首段，完整语义以原文为准。

状态列为基于报告结论的关键词判定；生产代码/数据库/模型列只在报告有明确证据时填写，否则为“未核实”。

| Stage 目录 | 主要产物 | 结论摘要 | 状态 | 复核 | 生产代码 | 生产DB | 模型 |
|---|---|---|---|---|---|---|---|
| `research_stage3_20261019` | final_assessment.md, README.md | **存在局部信号，但稳定性不足；PIT 不完整，所有结论仅供诊断。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage4_recheck_20261019` | final_assessment.md, README.md, frozen_inputs.json | **存在局部信号，但稳定性不足；不能称为稳定 Alpha。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage4_20261019` | final_assessment.md, README.md, frozen_inputs.json | **全部。** 退市股、历史 ST、历史行业、停复牌、复权、财务公告日均非 PIT；2015–2021 无数据。所有结果只能作为诊断，不是严格 OOS。 | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未变更（报告明确未覆盖DB） | 未变更（报告明确未改生产模型） |
| `research_stage5_20261019` | final_assessment.md, README.md | **在“同一回测引擎的净/毛收益”层面，支持；在“稳定跑赢基准”层面，不支持。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage6_1_20261019` | README.md, frozen_inputs.json | - 修正 Stage6 的 ALL bootstrap 跨折分层错误； | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未变更（frozen quant.db 哈希与当前一致） | 未变更（报告明确不训练模型） |
| `research_stage6_20261019` | final_assessment.md, README.md, frozen_inputs.json | **20 日相对 5 日的净收益改善，在配对批次和修正统计后仍存在点估计，但稳定性不足、统计证据不足。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未变更（frozen quant.db 哈希与当前一致） | 未变更（报告明确不训练模型） |
| `research_stage7_20261019` | final_assessment.md, README.md, frozen_inputs.json | **50 事件试点通过预登记门槛；但只够证明“当前存续、现金/送转”的账本机制，不足以直接接入全池回测。** | 部分完成/试点 | 人工复核（结论层） | 未变更（仅研究模块） | 未核实 | 未核实 |
| `research_stage8_20261019` | final_assessment.md, README.md, frozen_inputs.json | **未达到预登记验收条件。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_1_20261019` | final_assessment.md, README.md, frozen_inputs.json | **普通有效事件达到 30 个，但多源字段对齐未通过；301150 仍未解释，因此不能进入当前存续股票池事件表建设，更不能接入回测。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_2_20261019` | final_assessment.md, README.md, frozen_inputs.json | **未通过。CNInfo 覆盖性无法在 100 只随机样本上完成；无记录漏报率无法估计；生命周期字段仍有明显缺口。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_2b_20261019` | final_assessment.md, README.md | **是，100/100 全部有请求状态**（0 not_attempted、0 request_failed）。 | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_3_20261019` | final_assessment.md, README.md, frozen_inputs.json | **未通过。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_4_20261019` | final_assessment.md, README.md, frozen_inputs.json | **仅维持现金分红数据试点，不能进入全量事件表建设。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_4b_20261019` | final_assessment.md, README.md, frozen_inputs.json | **全部补完（265/265 → 0 not_checked）**。45 只证券的 `source_request_log.csv`：45/45 ok、attempts 全 1、0 timeout、0 重试。无卡点——子进程硬超时 25s 机制在 45 只中 0 次触发。唯一遗留 request_failed 17 属 002282（Stage9.4 已存在：同花顺该股分红页面异常），不是本次缺口。 | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_4c_20261019` | final_assessment.md, README.md, frozen_inputs.json | **Stage9.4b 的“双源 100% 完成”需要降级为：96 只双源成功、1 只 THS 失败、3 只无事件。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_5_20261019` | final_assessment.md, README.md, frozen_inputs.json | **现金分红事件表达到“研究试点”标准；仍未达到“可接入回测/NAV”标准。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_5b_20261019` | final_assessment.md, README.md, frozen_inputs.json | **总判定：未通过；仅现金分红数据试点。** | 阻塞/未通过 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_6_20261019` | final_assessment.md, README.md, frozen_inputs.json | **适合作为“已发现事件”的主发现源，不适合作为完整性证明。** | 未核实 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_6b_20261019` | final_assessment.md, README.md, frozen_inputs.json | 原始 Stage9.6 将事件存在、辅助源查询失败和字段对齐混在状态汇总里，容易把重叠指标误读为互斥分类。本修正版将三者拆开，未改动 Stage9.6 原目录，也未联网、接入 NAV 或回测。 | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage9_20261019` | final_assessment.md, README.md, frozen_inputs.json | **普通现金/送转的账本机制在小样本上可靠；但 50 事件试点没有达到“全池事件表可接入”的条件。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage10_cash_readonly_20261019` | final_assessment.md, README.md | **只读候选表通过基础完整性校验；可进入“现金分红只读研究数据层”试点，但不能作为完整事件表、不能接回测/NAV、不能称 PIT。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage10b_readonly_layer_20261019` | final_assessment.md, README.md | **只读查询层通过确定性校验，可进入“研究数据层试点”，但仍不是完整事件表、PIT 或回测输入。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage10c_mcp_layer_20261019` | final_assessment.md, README.md | **MCP 工具层通过协议与确定性测试，可作为后续 Nexent/Agent 的只读数据访问层；仍不是完整事件表、PIT 或回测输入。** | 完成 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage10d_skill_agent_20261019` | final_assessment.md, README.md | **规则型 Skill/Agent 原型通过 12/12 确定性测试，可作为 Nexent Agent 的编排骨架；仍不是 LLM Agent、完整事件表、PIT 或回测输入。** | 完成 | 人工复核（结论层） | 未核实 | 未变更（仅只读查询层） | 未核实 |
| `research_stage10e_nexent_package_20261019` | final_assessment.md, README.md | **3 个工作流达到可接入 Nexent 的交付形态，9/9 确定性测试通过；但仍未实际注册 Nexent/LLM，也不是完整事件表或回测输入。** | 完成 | 人工复核（结论层） | 未变更（不修改生产） | 未核实 | 未核实 |
| `research_stage10f_demo_api_20261019` | final_assessment.md, README.md | **本地只读 Demo 通过 10/10 测试，可用来演示“问题 → 工作流 → 证据 → 边界”；仍不是 Nexent 部署、LLM Agent、完整事件表或回测系统。** | 完成 | 人工复核（结论层） | 未核实 | 未变更（不访问生产库） | 未核实 |
| `research_stage10_1_provenance_20261020` | final_assessment.md, README.md | **来源追溯修正通过：781/781 条现金候选可定位到 CNInfo 原始 JSON 记录，且字段一致；无真实字段冲突。** | 完成 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage10_2_cash_exposure_20261020` | final_assessment.md, README.md, frozen_inputs.json | **已完成“已发现现金事件集合 × 冻结持仓”的可观测暴露审计；可匹配暴露只有 2 个事件、5 个 lot，不能外推，也不能校正收益。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage11_holdings_exposure_20261019` | final_assessment.md, README.md | **当前事件数据不足以校正 Stage4 的 20 日 vs 5 日收益。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage11b_held_event_collection_20261019` | — | 报告缺失/未核实 | 未核实 | 报告缺失 | 未核实 | 未核实 | 未核实 |
| `research_stage11c_holdings_exposure_completed_20261019` | final_assessment.md, README.md | **补全持仓事件后，现金分红暴露不足以解释 20 日 vs 5 日的收益差。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage12_decomposition_20261019` | final_assessment.md, README.md | **20 日的优势主要不是成本/换手；持有期有正向毛收益，但宽度和批次依赖使其仍不是稳定 Alpha。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage13_batch_dependence_20261019` | final_assessment.md, README.md | **20 日优势高度依赖少数批次；批次敏感性使“稳定 Alpha”不成立。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage14_batch_reconcile_20261019` | final_assessment.md, README.md | **修正：20 日没有在“剔除最佳批次”后反转。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage15_width_risk_20261020` | final_assessment.md, README.md, frozen_inputs.json | **判定：支持有限风险改善，但统计功效不足，不是稳定优势。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage16_execution_audit_20261020` | final_assessment.md, README.md, frozen_inputs.json | **选择：支持有限的可执行性改善（点估计），但执行成本证据不足。** | 部分完成/试点 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |
| `research_stage17_forward_paper_20261020` | final_assessment.md, README.md, frozen_config.json, order_intents.csv, daily_nav.csv | **一句话：跟踪器已就绪，初始信号已冻结；但没有任何前瞻成交或绩效，当前不能判断 Top20/Top50 谁更优。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage17_run1_20261020` | final_assessment.md, README.md, daily_nav.csv | **一句话：首批订单因缺少 2026-10-19 行情而全部未成交；现金仍 100%，没有绩效，跟踪尚未真正开始。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage18_market_data_freshness_20261020` | final_assessment.md, README.md | **已定位问题，但需要外部网络/数据源条件才能修复。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage19_market_pipeline_fix_20261020` | final_assessment.md, README.md, frozen_inputs.json | **代码修复完成，临时库验证通过；生产数据库未改、未联网、未补数。** | 完成 | 人工复核（结论层） | 是（pipeline/data_engine 修复） | 否 | 否 |
| `research_stage20_backfill_validation_20261020` | final_assessment.md, README.md, frozen_inputs.json | **补数包通过核心验收，可作为 staging 候选；暂不直接写生产库。** | 完成 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20b_staging_import_20261020` | final_assessment.md, README.md, frozen_inputs.json | **staging 导入成功，但生产库不具备写入条件。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20c_corporate_action_review_20261020` | final_assessment.md, README.md | **688610 的 -27.88% 跳空已解释为 2026-10-19 的 10 转 4 + 10 派 2，不是数据错误。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20d_adjustment_ledger_20261020` | final_assessment.md, README.md | **688610 跳空已解释为 10 转 4 + 10 派 2；10-19/20 已知 4 个除权事件已建账本。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20e_adjusted_return_preview_20261020` | final_assessment.md, README.md | **除权事件调整预览完成；raw 价格会产生明显假收益。** | 完成 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20f_source_attribution_20261020` | final_assessment.md, README.md | **160 行 source 缺失已补齐；来源字段不再是 blocker。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20g_import_candidate_20261020` | final_assessment.md, README.md | **一句话：候选已经准备好，但生产库仍未写；需要明确批准、备份和事务。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20h_preimport_audit_20261020` | final_assessment.md, README.md, frozen_inputs.json | **技术导入安全且幂等；价格口径/单位/partial 状态仍有 blocker，生产库未写。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20i_price_basis_source_20261020` | final_assessment.md, README.md, frozen_inputs.json | **一句话：技术导入不是问题；价格锚点、候选单位、partial 状态三个语义问题未解决，生产库不能写。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage20j_anchor_reconciliation_20261020` | final_assessment.md, README.md, frozen_inputs.json | **一句话：A 方案只能“追加当日价格 + 事件调整”，不能称为完整复权；生产导入仍被锚点、单位、partial 和事件覆盖阻塞。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage21_forward_market_20261020` | final_assessment.md, README.md, frozen_config.json | **一句话：独立 raw 层的 schema 和验证已就绪，但没有可追溯 raw 源；跟踪只能准备，不能启动。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage22_raw_source_pilot_20261020` | final_assessment.md, README.md, frozen_inputs.json | **找到了历史 raw 本地文件，但没有当前/前瞻 raw 源。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage23_source_readiness_20261020` | final_assessment.md, README.md, frozen_inputs.json | **有 pilot 级来源，但未达全池级"持续提供"标准。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage24_raw_universe_20261020` | final_assessment.md, README.md, frozen_inputs.json, daily_status.csv | **有 pilot 级源，但全池供给仍未通过。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage25_raw_evidence_repair_20261020` | final_assessment.md, README.md, frozen_inputs.json | **不是解析失败，而是源侧无目标行。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage26_source_crosscheck_20261020` | final_assessment.md, README.md, frozen_inputs.json | **20 只独立源交叉通过；但只覆盖 20 只、东财有间歇断连，不能外推全池。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage27_500_sample_20261021` | final_assessment.md, README.md, frozen_inputs.json, daily_status.csv | **500 只样本：498 只有效，2 只未解决；全池前瞻仍不能启动。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage28_status_closure_20261021` | final_assessment.md, README.md, frozen_inputs.json | **500 只样本状态已全部分类；但仍不能启动全池。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage29_unit_cross_20261021` | final_assessment.md, README.md, frozen_inputs.json | **独立源交叉后，amount 498/498、turnover 496/498、完整单位 496/498；仍不是全池。** | 未核实 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage30_edge_policy_20261021` | final_assessment.md, README.md, frozen_inputs.json | **turnover 例外已解释，但 000016/002731 状态仍未确认；全池不能启动。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage31_full_supply_20261021` | final_assessment.md, README.md, frozen_inputs.json | **全池 5,225 只 KLC-only 试运行：5,216 ok、9 无目标行、0 请求失败、0 解析失败；覆盖率 99.83%。仍不能启动 Stage17。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage32_full_amount_20261021` | — | 报告缺失/未核实 | 未核实 | 报告缺失 | 否（研究脚本） | 否 | 否 |
| `research_stage33_full_cross_20261021` | — | 报告缺失/未核实 | 未核实 | 报告缺失 | 否（研究脚本） | 否 | 否 |
| `research_stage34_forward_finalize_20261021` | final_assessment.md, README.md, frozen_inputs.json | **raw 可用，但仍有 22 单位例外、9 无目标日；不是全池 100% 清洗。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage35_daily_forward_20261021` | final_assessment.md, README.md, frozen_config.json, daily_status.csv, raw_daily.csv | **部分完成 / 受阻。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage36_anchor_conversion_20261021` | final_assessment.md, README.md, frozen_inputs.json | **部分完成 / 特征口径仍有边界。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage37_eligible_pool_20261021` | final_assessment.md, README.md, frozen_config.json, signal_log.csv, order_intents.csv, daily_nav.csv | **方案 A 可评分池已建立，新纸面 run 已启动；执行日 2026-10-22 无数据，因此无成交、无 NAV 变动。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage37_feature_recovery_20261021` | final_assessment.md, README.md, frozen_inputs.json | **部分完成 / 特征仍不完整。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage38_execution_20261022` | final_assessment.md, README.md, frozen_inputs.json, daily_status.csv, daily_nav.csv | **目标日 2026-10-22 尚未到达，执行行情不可用；本阶段只完成数据审计，未生成成交、持仓或 NAV 变动。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage38_history_window_20261021` | final_assessment.md, README.md, frozen_inputs.json | **部分完成 / 特征仍不完整。** | 部分完成/试点 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage39_execution_20261022` | final_assessment.md, README.md, frozen_inputs.json, daily_status.csv, daily_nav.csv | **2026-10-22 尚未开始，目标日行情不可用；未结算，70 条订单保持 pending/blocked。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |
| `research_stage39_feature_blocker_20261021` | final_assessment.md, README.md, frozen_inputs.json | **部分完成 / 外部数据阻塞。** | 阻塞/未通过 | 人工复核（结论层） | 否（研究脚本） | 否 | 否 |


## 人工复核记录

复核范围（逐条回看源报告）：

- Stage3：结论为“存在局部信号但 PIT 不完整”，状态从“未核实”改为“部分完成/试点”。
- Stage7：50 事件试点通过，但不能全池接入，保留“部分完成/试点”。
- Stage9.2b：100/100 有请求状态，但仍有 field_incomplete/no_record_unverified，状态改为“部分完成/试点”。
- Stage10.1：来源追溯 781/781 通过，保留“完成”。
- Stage17/run1：跟踪器就绪但 0 成交；run1 状态改为“阻塞/未通过”。
- Stage20i：锚点/单位/partial 三个问题未解决，生产库不能写，状态改为“阻塞/未通过”。
- Stage20j：锚点只能部分统一，生产导入被阻塞，保留“阻塞/未通过”。
- Stage21：无可追溯 raw 源，跟踪不能启动，保留“阻塞/未通过”。
- Stage26：20 只独立源交叉通过，但不是全池，状态改为“部分完成/试点”。
- Stage31：全池 KLC-only 5,216/5,225，仍不能启动 Stage17，保留“阻塞/未通过”。
- Stage34：raw 可用但仍有 22 单位例外、9 无目标，状态从“完成”改为“部分完成/试点”。
- Stage36：96 事件、5,215 行转换、5,188 特征完整，但 37 只不满足，保留“部分完成/试点”。
- Stage37 eligible：5,190 可评分、70 pending、0 成交，保留“部分完成/试点”。
- Stage38/39 execution：10-22 行情未到，0 成交，保留“阻塞/未通过”。

未逐条做全量数字重算：本轮对所有有报告的目录做了“结论层”复核（首段结论、状态、关键验收表）；生产代码/DB/模型变更字段仍以报告明确文字为准，未明确的保持“未核实”。

## 复核统计

- 总条目：72
- 人工复核（结论层）：69
- 报告缺失：3
- 自动摘要：0（本轮已对全部有报告的目录做结论层复核）
- 生产代码/DB/模型变更：仅在报告明确时填写，否则“未核实”

方法：逐目录读取 `final_assessment.md`/`README.md` 的首段结论与关键验收表；生产变更字段做保守标注；不把关键词判断当作完整语义审计。

## 说明

- 未读取到报告的阶段标为“报告缺失/未核实”。
- `output/` 被 `.gitignore` 忽略；索引只描述现状，不移动任何文件。
- 研究结论、纸面跟踪和生产配置是三层不同对象，不能互相替代。
