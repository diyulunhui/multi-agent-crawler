# Tasks Document

- [x] 1. 建立配置与领域基础模型
  - File: src/config/settings.py
  - File: src/domain/models.py
  - File: src/domain/events.py
  - 定义系统配置、拍卖实体、任务事件与优先级枚举
  - 明确 `SPECIAL/NORMAL`、`PRE5/PRE1/FINAL/NEXTDAY_FIX`、`DISCOVER_*` 等核心类型
  - Purpose: 为调度、执行、入库提供统一数据契约
  - _Leverage: requirements.md, design.md_
  - _Requirements: 1, 2, 3, 4, 5_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 架构工程师 | Task: 在 `src/config` 与 `src/domain` 下创建配置与领域模型，确保后续模块共享统一类型定义 | Restrictions: 不引入队列中间件依赖，不把业务常量散落到执行器中，不使用未定义枚举字符串 | _Leverage: requirements.md, design.md 数据模型章节 | _Requirements: 1,2,3,4,5 | Success: 类型可被导入复用，运行静态检查无循环依赖，事件/快照枚举覆盖完整 | Instructions: 开始前将本任务在 tasks.md 从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录 artifacts；最后将 `[-]` 改为 `[x]`。

- [x] 2. 搭建数据库连接与基础表结构
  - File: src/storage/db.py
  - File: src/storage/schema.sql
  - File: src/storage/repositories/base_repo.py
  - 创建数据库连接管理、建表 SQL 与基础仓储抽象
  - 覆盖 `auction_session/lot/lot_snapshot/lot_result/task_state`
  - Purpose: 提供稳定持久层和后续仓储扩展底座
  - _Leverage: design.md Data Models_
  - _Requirements: 1, 2, 5_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 后端工程师（数据层） | Task: 完成数据库底座与核心表结构，保证幂等键、唯一约束和索引到位 | Restrictions: 不把业务逻辑写入 SQL 初始化脚本，不省略 `task_state` 表，不做破坏性 DDL | _Leverage: design.md 的 5 张模型定义 | _Requirements: 1,2,5 | Success: 本地初始化可一次建表成功，关键唯一键存在，仓储层可复用连接 | Instructions: 开始前将本任务改为 `[-]`；完成后调用 `log-implementation`；然后改为 `[x]`。

- [x] 3. 实现任务仓储与幂等写入接口
  - File: src/storage/repositories/task_repo.py
  - File: src/storage/repositories/session_repo.py
  - File: src/storage/repositories/lot_repo.py
  - 提供任务入库、状态更新、失败落库、去重查询接口
  - 提供专场与标的增量写入接口，支持变更时间刷新
  - Purpose: 支撑调度恢复、幂等执行与增量发现
  - _Leverage: src/storage/db.py, src/storage/repositories/base_repo.py_
  - _Requirements: 1, 2, 5_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 数据访问工程师 | Task: 实现 task/session/lot 仓储，保证去重、幂等和状态迁移接口完整 | Restrictions: 不绕过基础仓储直接拼接重复 SQL，不把重试策略硬编码在仓储层，不忽略异常日志 | _Leverage: base_repo 与 schema.sql | _Requirements: 1,2,5 | Success: 仓储接口覆盖调度和执行场景，重复写入可幂等，失败信息可追踪 | Instructions: 先把任务标记 `[-]`，完成后记录 `log-implementation`，再标记 `[x]`。

- [x] 4. 实现 Python 原生优先队列封装
  - File: src/queue/priority_queue.py
  - File: src/queue/task_item.py
  - 基于 `queue.PriorityQueue` 封装任务入队/出队/确认完成
  - 支持优先级、到期时间排序、线程安全消费
  - Purpose: 在不使用中间件前提下承载高峰任务分发
  - _Leverage: src/domain/events.py_
  - _Requirements: 2_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 并发工程师 | Task: 封装原生优先队列并定义任务排序项，满足 PRE5 高优先级抢占 | Restrictions: 禁止引入 Redis/RabbitMQ/Kafka 客户端，不写不可控忙轮询，不省略线程安全保护 | _Leverage: Python queue/threading 标准库, domain events | _Requirements: 2 | Success: 多线程下出队稳定、优先级正确、接口可用于 WorkerPool | Instructions: 将该任务置为 `[-]` 后开发；完成后调用 `log-implementation`；再改为 `[x]`。

- [x] 5. 实现任务调度规则引擎
  - File: src/scheduler/policies.py
  - File: src/scheduler/task_scheduler.py
  - 实现发现任务、PRE5/PRE1、专场三段式补抓任务生成
  - 将业务规则转换为统一任务事件并写入任务仓储
  - Purpose: 固化两类拍卖核心时序策略
  - _Leverage: src/storage/repositories/task_repo.py, src/domain/models.py_
  - _Requirements: 2, 3, 4_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 调度系统工程师 | Task: 按规则生成各类任务（专场补抓、PRE5/PRE1、可选 FINAL 监控）并落库入队 | Restrictions: 不将规则硬编码到主程序入口，不遗漏可配置开关，不忽略时区处理 | _Leverage: design.md Architecture + Error Handling | _Requirements: 2,3,4 | Success: 输入 lot/session 后可稳定产出正确 run_at 与优先级任务集合 | Instructions: 开始前改 `[-]`，完成后 `log-implementation`，最后改 `[x]`。

- [x] 6. 实现重启恢复与重试退避机制
  - File: src/scheduler/recovery_service.py
  - File: src/workers/retry_policy.py
  - 启动时回收未完成任务并重新入队
  - 为失败任务提供有限次重试与指数退避
  - Purpose: 防止重启与临时故障导致任务丢失
  - _Leverage: src/storage/repositories/task_repo.py, src/queue/priority_queue.py_
  - _Requirements: 2, 6_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 可靠性工程师 | Task: 构建任务恢复与重试策略，保证失败可追踪、可补偿、可终止 | Restrictions: 不做无限重试，不在失败时吞异常，不破坏任务幂等键 | _Leverage: task_state 表结构与队列封装 | _Requirements: 2,6 | Success: 重启后 pending/running 任务可恢复，重试次数/退避间隔按策略生效 | Instructions: 先标记 `[-]`；完成后 `log-implementation`；再标记 `[x]`。

- [x] 7. 封装 Scrapling 采集适配与解析标准化
  - File: src/scraping/adapter.py
  - File: src/scraping/parsers/hx_parser.py
  - File: src/scraping/normalizers.py
  - 封装页面抓取、专场/标的解析、字段标准化
  - 输出统一结构供执行器与存储层消费
  - Purpose: 形成稳定可维护的采集入口
  - _Leverage: src/domain/models.py, design.md Components and Interfaces_
  - _Requirements: 1, 4, 5_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 爬虫工程师 | Task: 使用 Scrapling 适配公开入口采集并完成解析标准化，输出统一对象 | Restrictions: 不实现绕过风控/验证码逻辑，不把解析规则散落在执行器中，不忽略空字段与异常字段处理 | _Leverage: design.md 的 ScraplingAdapter 设计 | _Requirements: 1,4,5 | Success: 可从入口页面解析 session 与 lot，字段规范化一致，异常页面可返回结构化错误 | Instructions: 开始前设为 `[-]`；完成后写 `log-implementation`；再设为 `[x]`。

- [x] 8. 实现发现任务执行器
  - File: src/workers/executors/discovery_executor.py
  - File: src/workers/executors/lot_executor.py
  - 执行 `DISCOVER_SESSIONS` 与 `DISCOVER_LOTS` 任务
  - 将解析结果写入 session/lot 仓储并触发后续调度
  - Purpose: 打通入口发现到任务派发闭环
  - _Leverage: src/scraping/adapter.py, src/scheduler/task_scheduler.py_
  - _Requirements: 1, 2_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 任务执行器开发工程师 | Task: 实现发现类执行器，完成采集、解析、入库、后续任务触发链路 | Restrictions: 不在执行器中直接操作低级 SQL，不跳过幂等判断，不混入报表逻辑 | _Leverage: repositories + scheduler | _Requirements: 1,2 | Success: 发现任务可端到端执行，重复运行不产生脏重复数据，异常会回写 task_state | Instructions: 将 `[ ]` 改 `[-]` 后实施；完成后 `log-implementation`；改 `[x]`。

- [x] 9. 实现快照执行器与顺延监控流程
  - File: src/workers/executors/snapshot_executor.py
  - File: src/workers/monitor/extension_monitor.py
  - 执行 `SNAPSHOT_PRE5/PRE1/FINAL_MONITOR/SESSION_FINAL_SCRAPE`
  - 支持顺延场景下低频轮询并按终态退出
  - Purpose: 满足临截标快照和最终成交确认扩展
  - _Leverage: src/scraping/adapter.py, src/workers/retry_policy.py_
  - _Requirements: 3, 4_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 时序任务工程师 | Task: 实现 PRE5 与可选 FINAL 监控执行逻辑，处理顺延直到 closed/稳定成交 | Restrictions: 不做高频无节制轮询，不把 FINAL 结果误标为 PRE5，不忽略监控超时退出 | _Leverage: design.md Error Scenarios 1/4 | _Requirements: 3,4 | Success: PRE5 准点抓取可执行，顺延监控可结束并写入明确状态标记 | Instructions: 先置 `[-]`，完成后记录 `log-implementation`，再置 `[x]`。

- [x] 10. 实现快照持久化与结果聚合服务
  - File: src/storage/object_store.py
  - File: src/services/snapshot_service.py
  - File: src/services/result_service.py
  - 保存原始 HTML/JSON 到对象存储并写入 `lot_snapshot`
  - 聚合生成/更新 `lot_result` 与置信度字段
  - Purpose: 建立证据链与最终数据出口
  - _Leverage: src/storage/repositories/lot_repo.py, src/storage/repositories/task_repo.py_
  - _Requirements: 5_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 数据持久化工程师 | Task: 完成快照与结果服务，保证对象存储路径规范、数据库写入幂等、终态可追踪 | Restrictions: 不跳过 raw_ref 保存，不让快照失败静默吞掉，不破坏 lot_result 主键唯一性 | _Leverage: design.md Data Models (lot_snapshot, lot_result) | _Requirements: 5 | Success: 同一幂等键重复写入不重复，raw_ref 可追溯，result 更新策略可配置 | Instructions: 先改 `[-]`，完成后 `log-implementation`，最后改 `[x]`。

- [x] 11. 实现质量校验与页面漂移检测
  - File: src/quality/quality_service.py
  - File: src/quality/drift_detector.py
  - 实现价格缺失/异常、时间跳变、跨入口冲突校验
  - 解析失败率超阈值时触发 drift 告警任务
  - Purpose: 降低页面改版带来的数据质量风险
  - _Leverage: src/services/snapshot_service.py, src/storage/repositories/task_repo.py_
  - _Requirements: 6_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 数据质量工程师 | Task: 落地质量打分与漂移检测机制，并输出待人工复核清单 | Restrictions: 不把业务阈值写死在代码中，不忽略冲突记录明细，不让告警无法追踪来源 | _Leverage: design.md QualityService 设计 | _Requirements: 6 | Success: 质量分可复现，drift 告警可触发，冲突数据可审计 | Instructions: 开发前设为 `[-]`；完成后调用 `log-implementation`；再置为 `[x]`。

- [x] 12. 实现报表与 CSV 导出能力
  - File: src/reporting/report_service.py
  - File: src/reporting/csv_exporter.py
  - 生成按站点/专场/品类聚合的日报统计
  - 导出标准字段 CSV 并标注数据窗口与质量摘要
  - Purpose: 给业务侧提供可消费的结果输出
  - _Leverage: src/storage/repositories/lot_repo.py, src/quality/quality_service.py_
  - _Requirements: 7_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 数据分析后端工程师 | Task: 实现统计报表与 CSV 导出，确保指标口径与数据模型一致 | Restrictions: 不写死输出路径，不混淆快照与最终成交口径，不忽略质量评分展示 | _Leverage: design.md Reporting Agent 目标 | _Requirements: 7 | Success: 日报可按配置窗口生成，CSV 字段稳定，报表附带质量摘要 | Instructions: 先标记 `[-]`；完成后 `log-implementation`；最后标记 `[x]`。

- [x] 13. 定义 DeerFlow 技能文档（发现/标的/快照）
  - File: deerflow/skills/hxguquan_discovery_skill.md
  - File: deerflow/skills/hxguquan_lot_skill.md
  - File: deerflow/skills/hxguquan_snapshot_skill.md
  - 定义技能输入输出、调用顺序、失败回退和重跑策略
  - Purpose: 让控制面可重复编排并降低人工介入频率
  - _Leverage: design.md Architecture, src/scheduler/task_scheduler.py_
  - _Requirements: 1, 2, 3, 4_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: DeerFlow 编排工程师 | Task: 编写 3 个技能文档，明确发现/标的/快照工作流与工具调用契约 | Restrictions: 不写模糊描述，不省略失败重试与人工介入条件，不脱离现有任务事件命名 | _Leverage: 现有任务模型与执行器接口 | _Requirements: 1,2,3,4 | Success: 技能文档可指导自动化执行，输入输出契约清晰且与代码一致 | Instructions: 开始前改为 `[-]`，完成后 `log-implementation`，再改为 `[x]`。

- [x] 14. 定义 DeerFlow 质量技能与工具契约
  - File: deerflow/skills/hxguquan_quality_skill.md
  - File: deerflow/tools/tool_contracts.md
  - 定义 `db_tool/queue_tool/storage_tool/scrape_tool` 调用协议
  - 定义质量代理触发条件与异常工单输出格式
  - Purpose: 统一控制面与数据面接口，避免集成歧义
  - _Leverage: design.md Components and Interfaces_
  - _Requirements: 2, 5, 6, 7_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 平台集成工程师 | Task: 制定质量技能与工具契约文档，确保 DeerFlow 与 Python 服务接口一致 | Restrictions: 不定义与实现不一致的字段，不遗漏错误码和重试语义，不忽略版本兼容说明 | _Leverage: design.md Integration Points | _Requirements: 2,5,6,7 | Success: 工具契约可直接驱动集成开发，质量技能输出可被任务系统消费 | Instructions: 先置 `[-]`，完成后写 `log-implementation`，再置 `[x]`。

- [x] 15. 实现应用启动入口与 WorkerPool 运行时
  - File: src/workers/pool.py
  - File: src/app.py
  - File: main.py
  - 装配配置、仓储、调度器、队列、执行器并启动主循环
  - 提供优雅停机、健康检查和基础运行日志
  - Purpose: 形成可运行的端到端采集服务
  - _Leverage: src/queue/priority_queue.py, src/scheduler/recovery_service.py_
  - _Requirements: 2, 3, 4, 5, 6_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 平台工程师 | Task: 完成应用装配与 WorkerPool 运行时，打通调度到执行全链路 | Restrictions: 不将配置硬编码在 main，不忽略关闭信号处理，不把监控日志与业务日志混淆 | _Leverage: 已实现的 queue/scheduler/executor 模块 | _Requirements: 2,3,4,5,6 | Success: 本地可一键启动服务，任务可流转执行，停机时不丢正在处理状态 | Instructions: 开始前改为 `[-]`；完成后调用 `log-implementation`；最后改为 `[x]`。

- [x] 16. 建立测试流程与发布门禁
  - File: docs/testing-process.md
  - File: scripts/run_test_pipeline.sh
  - 定义 `unit -> integration -> e2e -> replay` 测试阶段与执行顺序
  - 提供统一测试入口脚本并约定失败即阻断发布
  - Purpose: 固化团队测试流程，避免“有测试任务但无统一流程”的执行偏差
  - _Leverage: requirements.md 测试流程与验收门禁, design.md 测试流程_
  - _Requirements: 2, 5, 6, 7_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 测试平台工程师 | Task: 建立文档化测试流程和可执行测试门禁脚本，统一所有阶段测试入口 | Restrictions: 不只写文档不落脚本，不允许发布前跳过任一测试阶段，不依赖线上环境执行 | _Leverage: Testing Strategy + 当前任务清单中的测试任务 | _Requirements: 2,5,6,7 | Success: 团队可按单一脚本执行完整测试流程，失败阶段可定位并阻断发布 | Instructions: 开始前置 `[-]`，完成后 `log-implementation`，再置 `[x]`。

- [x] 17. 补充关键单元测试（调度与队列）
  - File: tests/unit/test_task_scheduler.py
  - File: tests/unit/test_priority_queue.py
  - 覆盖 PRE5/PRE1/专场补抓规则、优先级排序、并发消费
  - Purpose: 防止核心时序与并发逻辑回归
  - _Leverage: src/scheduler/task_scheduler.py, src/queue/priority_queue.py_
  - _Requirements: 2, 3, 4_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: Python 测试工程师 | Task: 编写调度与队列单元测试，验证关键时序规则与优先级行为 | Restrictions: 不依赖外部网络，不写脆弱的时间睡眠测试，不忽略边界条件（跨日、无 end_time） | _Leverage: Testing Strategy Unit Testing | _Requirements: 2,3,4 | Success: 单测覆盖关键规则分支并稳定通过，失败信息可定位 | Instructions: 开始前置 `[-]`，完成后 `log-implementation`，再置 `[x]`。

- [x] 18. 补充集成与端到端测试（快照全链路）
  - File: tests/integration/test_snapshot_pipeline.py
  - File: tests/e2e/test_hx_pipeline.py
  - 覆盖“发现 -> 调度 -> PRE5 快照 -> 入库 -> 报表”的主流程
  - 覆盖顺延监控超时与次日补抓修正流程
  - Purpose: 验证系统在真实任务编排下的稳定性
  - _Leverage: src/app.py, src/services/snapshot_service.py, src/reporting/report_service.py_
  - _Requirements: 1, 2, 3, 4, 5, 6, 7_
  - _Prompt: Implement the task for spec hx-auction-data-pipeline, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 集成测试工程师 | Task: 编写主链路集成与 E2E 测试，覆盖关键成功路径与异常路径 | Restrictions: 不依赖真实线上站点，不省略断言质量分和状态迁移，不忽略失败重试场景 | _Leverage: Testing Strategy Integration/E2E | _Requirements: 1,2,3,4,5,6,7 | Success: 主链路可在测试环境稳定跑通，异常路径可复现且可断言 | Instructions: 先把任务改 `[-]`；完成后调用 `log-implementation`；最后改 `[x]`。
