# hxguquan_discovery_skill

## 目标
发现公开入口中的专场增量，并把 `DISCOVER_LOTS` 任务派发到任务系统。

## 输入
- `entry_url`: 发现入口 URL
- `site`: 站点标识（默认 `hxguquan`）
- `trigger_time`: 触发时间

## 输出
- 新增/更新的 `auction_session` 记录数
- 派发的 `DISCOVER_LOTS` 任务数
- 失败列表与重试建议

## 执行流程
1. 调用 `scrape_tool.fetch_page(entry_url)` 获取原始页面。
2. 调用 `scrape_tool.parse_sessions(raw)` 提取 session 列表。
3. 调用 `db_tool.upsert_session(batch)` 执行幂等入库。
4. 按 session 逐条调用 `queue_tool.enqueue(DISCOVER_LOTS)`。
5. 记录运行摘要到 `db_tool.insert_job_log`。

## 失败回退
- 抓取失败：按重试策略退避重试，超过上限记录 dead-letter。
- 解析失败：保存原始页面并触发 `hxguquan_quality_skill` 漂移检测。
- 入库冲突：按主键幂等覆盖，不中断批次。

## 重跑策略
- 支持按 `trigger_time` 窗口重跑。
- 重跑前先基于 `dedupe_key` 去重，避免重复派发。
