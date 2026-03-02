# hxguquan_snapshot_skill

## 目标
执行 PRE5/PRE1/FINAL/NEXTDAY_FIX 快照，落证据并更新结果表。

## 输入
- `task_id`
- `event_type`
- `lot_id` / `session_id`
- `url`

## 输出
- `lot_snapshot` 写入结果
- `lot_result` 更新结果
- 质量评分与异常标记

## 执行流程
1. 根据 `event_type` 分支：
   - PRE5/PRE1：单次抓取并保存快照
   - FINAL：进入低频轮询直到 closed 或超时
   - SESSION_FINAL_SCRAPE：批量补抓
2. 调用 `storage_tool.save_raw` 保存原始 HTML 证据。
3. 调用 `db_tool.upsert_snapshot` 写入 `lot_snapshot`。
4. 调用 `db_tool.upsert_result` 更新 `lot_result`。
5. 调用 `quality_tool.evaluate_snapshot` 回写质量分。

## 失败回退
- 抓取失败：按指数退避重试。
- 监控超时：写入“未确认终态”并次日补抓。
- 入库失败：记录 dead-letter 并触发人工复核。

## 重跑策略
- 支持按 `lot_id` 和 `snapshot_type` 定向重跑。
- 重跑默认覆盖同幂等键记录，不追加脏数据。
