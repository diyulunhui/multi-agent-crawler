# Requirements Document

## Introduction

本规范定义“DeerFlow 多智能体编排 + Scrapling 采集”的落地需求，用于支持两类拍卖数据获取模式：

1. 专场（限时竞买专场）：结标后延迟批量抓取最终成交信息。
2. 普通拍卖（单品限时）：在截标前 5 分钟抓取临截标报价快照。

该功能的核心价值是同时满足“时效性（准点快照）”与“完整性（可回放、可补抓、可审计）”，并将页面变更和异常处理纳入可持续运营流程。

## Alignment with Product Vision

当前项目尚未提供 `.spec-workflow/steering/product.md`，本需求按以下产品目标对齐：

1. 以稳定采集为第一目标，保障关键时点数据可获取。
2. 以低运维成本为目标，将规则修复与质量巡检流程化。
3. 以数据可信为底线，保存原始快照并支持回放审计。

## Requirements

### Requirement 1

**User Story:** 作为数据运营人员，我希望系统能自动发现专场和标的增量，这样我不需要手工逐页盯盘。

#### Acceptance Criteria

1. WHEN 发现任务按计划触发 THEN 系统 SHALL 抓取公开入口中的专场列表与普通拍卖列表，并解析 `session_id/source_url/session_type/title` 等基础字段。
2. WHEN 发现任务处理专场详情或列表页 THEN 系统 SHALL 解析并增量写入 `lot_id/session_id/title_raw/end_time/status`。
3. IF 已存在标的字段发生变化 THEN 系统 SHALL 更新标的记录并刷新 `last_seen_at`，同时保留变化轨迹所需的时间戳信息。

### Requirement 2

**User Story:** 作为平台工程师，我希望任务调度在高并发时仍可控可恢复，这样系统不会因为峰值任务导致丢数。

#### Acceptance Criteria

1. WHEN 调度器创建任务 THEN 系统 SHALL 使用 Python 标准库实现任务队列（如 `queue.PriorityQueue` + `threading`/`asyncio`）并禁止依赖 Redis、RabbitMQ、Kafka 等外部队列中间件。
2. WHEN 多个任务在同一时间窗口爆发 THEN 系统 SHALL 基于任务优先级（`PRE5 > 发现 > 次日补抓`）和并发上限分发执行。
3. IF 任务执行失败 THEN 系统 SHALL 按任务类型执行有限次重试、指数退避，并在超过重试上限后写入失败记录以供人工处理。
4. WHEN 进程重启 THEN 系统 SHALL 从数据库中恢复未完成任务，避免仅内存队列导致的任务丢失。

### Requirement 3

**User Story:** 作为成交数据使用方，我希望专场在结标后能分阶段补抓，这样可以兼顾时效和准确率。

#### Acceptance Criteria

1. WHEN 专场进入结标后阶段 THEN 系统 SHALL 至少调度一次“结标后 30-90 分钟”抓取任务。
2. WHEN 专场达到次日固定时刻（默认 10:00，可配置） THEN 系统 SHALL 再次抓取并覆盖修正最终结果。
3. IF 启用 D+3 补抓策略 THEN 系统 SHALL 在结标后第 3 天追加一次可选补抓任务。

### Requirement 4

**User Story:** 作为行情观察者，我希望普通拍卖能在临截标时保留快照，并可扩展到顺延后的最终结果确认。

#### Acceptance Criteria

1. WHEN 普通拍卖标的存在有效 `end_time` THEN 系统 SHALL 在 `end_time - 5 分钟` 触发 `PRE5` 快照抓取。
2. IF 开启高精度快照开关 THEN 系统 SHALL 在 `end_time - 1 分钟` 额外触发 `PRE1` 快照。
3. IF 启用最终成交确认模式 AND 检测到顺延迹象 THEN 系统 SHALL 进入低频轮询监控，直到页面状态为已结标/成交价稳定后结束。
4. IF 仅启用 `PRE5` 模式 THEN 系统 SHALL 明确将结果标记为“临截标快照”，不冒充最终成交价。

### Requirement 5

**User Story:** 作为数据治理负责人，我希望系统保留结构化结果与原始证据链，这样后续规则变更时可回放重算。

#### Acceptance Criteria

1. WHEN 任意快照抓取成功 THEN 系统 SHALL 写入 `lot_snapshot` 并保存原始 HTML/JSON 到对象存储路径 `/{site}/{date}/{session_id}/{lot_id}/{snapshot_type}.html`。
2. IF 同一 `lot_id + snapshot_type + time_bucket` 已存在 THEN 系统 SHALL 以幂等方式更新记录，避免重复入库。
3. WHEN 标的进入终态（成交/流拍/撤拍） THEN 系统 SHALL 写入或更新 `lot_result`，包含 `final_price/final_end_time/is_unsold/is_withdrawn/confidence_score`。

### Requirement 6

**User Story:** 作为维护工程师，我希望系统能自动识别解析异常和页面变更，这样可以快速修复采集规则。

#### Acceptance Criteria

1. WHEN 某站点解析失败率在滑动窗口内超过阈值 THEN 系统 SHALL 触发页面变更告警并创建规则修复任务。
2. IF 同一标的在不同入口出现冲突字段 THEN 系统 SHALL 按可信源优先级决策并记录冲突明细。
3. WHEN 数据质量校验失败 THEN 系统 SHALL 下调 `confidence_score`，并将记录加入人工复核清单。

### Requirement 7

**User Story:** 作为业务分析人员，我希望系统能自动输出成交统计报表，这样可以快速判断品类热度和价格区间。

#### Acceptance Criteria

1. WHEN 日报任务触发 THEN 系统 SHALL 生成按站点、专场、品类聚合的成交统计（含中位数、分位区间、异常值计数）。
2. IF 用户请求导出 THEN 系统 SHALL 提供 CSV 导出能力，字段与数据库主模型一致。
3. WHEN 生成报表 THEN 系统 SHALL 标注数据窗口、快照类型覆盖范围和质量评分摘要。

## 测试流程与验收门禁

1. 开发阶段必须执行单元测试，覆盖调度规则、原生队列优先级、幂等与重试策略。
2. 合并前必须执行集成测试，覆盖 `task_state -> queue -> worker -> snapshot/result` 全链路。
3. 发布前必须执行端到端测试，覆盖“发现 -> PRE5 -> 入库 -> 报表”主流程与顺延异常流程。
4. 每次解析规则调整后必须执行回放测试，使用已保存 `raw_ref` 快照验证结果一致性。
5. 任一测试阶段失败时 SHALL 阻断发布，并输出失败摘要与修复责任人。
6. 验收通过标准 SHALL 满足：
   - 单元测试通过率 100%
   - 集成测试关键场景通过率 100%
   - 端到端主流程通过率 100%
   - 无 P0/P1 严重缺陷遗留

## Non-Functional Requirements

### Code Architecture and Modularity
- **Single Responsibility Principle**: 采集、调度、解析、质量、报表职责分离，每个模块只处理单一领域。
- **Modular Design**: DeerFlow 控制面与采集数据面解耦，调度器、执行器、解析器可独立替换。
- **Dependency Management**: 队列层仅依赖 Python 标准库，不引入队列中间件；外部依赖集中在采集与存储适配层。
- **Clear Interfaces**: 统一任务结构（事件类型、优先级、重试策略、幂等键）与统一快照输出结构。

### Performance
- `PRE5` 任务触发准确性在稳定负载下达到 P95 误差不超过 30 秒。
- 单进程 Worker 支持可配置并发，保证高峰时段任务可被限流且不阻塞关键优先级。
- 专场批量抓取采用分页聚合策略，避免逐标的单页请求导致请求风暴。

### Security
- 仅采集公开可访问或合法授权的数据入口，遵守目标站点协议与频率限制。
- 不实现绕过验证码、风控或其他反爬机制的对抗逻辑。
- 凭据与敏感配置通过环境变量或密钥管理注入，不明文写入代码仓库。

### Reliability
- 任务执行必须具备重试、失败落库、幂等写入与重启恢复能力。
- 快照保存失败不得阻断结构化数据记录，结构化写入失败必须触发重试与告警。
- 关键链路（发现、PRE5、专场补抓）需提供健康检查与运行指标。

### Usability
- 任务策略（PRE5/PRE1、专场补抓时刻、顺延监控开关）可通过配置文件调整。
- 每日输出可读的采集摘要与异常清单，便于非开发人员复核。
- 报表输出支持固定字段模板，减少下游分析对接成本。
