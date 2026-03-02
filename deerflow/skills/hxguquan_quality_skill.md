# hxguquan_quality_skill

## 目标
执行快照质量评分、冲突检测与页面漂移告警，输出可追踪异常工单。

## 输入
- `site`
- `window_minutes`
- `lot_ids`（可选）

## 输出
- 质量评分结果列表
- 冲突列表
- 漂移告警（如触发）
- 待人工复核工单

## 执行流程
1. 调用 `db_tool.query_recent_snapshots` 拉取样本。
2. 调用 `quality_tool.evaluate_snapshot` 计算质量分。
3. 调用 `quality_tool.detect_conflicts` 识别冲突。
4. 调用 `quality_tool.detect_parser_drift` 判断是否触发漂移告警。
5. 将低分或冲突记录写入 `review_queue`。

## 告警触发条件
- 快照缺失率 > 配置阈值
- 漂移窗口失败率 >= 30% 且样本数 >= 10
- 同一 lot 在关键字段上出现不可解释冲突

## 输出格式
- `issue_type`: `LOW_QUALITY` / `FIELD_CONFLICT` / `PARSER_DRIFT`
- `entity_id`: lot_id 或 site
- `severity`: P0/P1/P2
- `evidence`: 原始快照引用、冲突字段、时间窗口
- `action`: RETRY / FIX_RULE / MANUAL_REVIEW
