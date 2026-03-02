# hxguquan_lot_skill

## 目标
发现专场下标的增量，并根据规则派发 PRE5/PRE1/FINAL 任务。

## 输入
- `session_id`
- `session_url`
- `trigger_time`

## 输出
- 新增/更新的 `lot` 记录数
- 派发的快照任务数
- 无效 `end_time` 标的清单

## 执行流程
1. 调用 `scrape_tool.fetch_page(session_url)` 抓取专场页面。
2. 调用 `scrape_tool.parse_lots(raw)` 提取 lot 列表。
3. 调用 `db_tool.upsert_lot(batch)` 幂等入库。
4. 依据规则生成任务：
   - `SNAPSHOT_PRE5`
   - `SNAPSHOT_PRE1`（可选）
   - `SNAPSHOT_FINAL_MONITOR`（可选）
5. 调用 `queue_tool.enqueue(batch_tasks)` 投递任务。

## 失败回退
- lot 解析为空：保存原始页面并触发质量检测。
- 任务投递失败：批量重试并记录失败原因。

## 重跑策略
- 支持按 `session_id` 全量重跑。
- 对同一 lot 使用 `lot_id + snapshot_type + minute_bucket` 幂等键。
