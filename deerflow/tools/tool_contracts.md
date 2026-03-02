# tool_contracts

## db_tool

### upsert_session
- Input: `{ sessions: Session[] }`
- Output: `{ upserted: number, updated: number }`
- Error: `DB_CONNECTION_ERROR`, `DB_CONSTRAINT_ERROR`

### upsert_lot
- Input: `{ lots: Lot[] }`
- Output: `{ upserted: number, updated: number }`
- Error: `DB_CONNECTION_ERROR`, `DB_CONSTRAINT_ERROR`

### upsert_snapshot
- Input: `{ snapshots: Snapshot[] }`
- Output: `{ upserted: number, updated: number }`
- Error: `DB_CONNECTION_ERROR`, `DB_CONSTRAINT_ERROR`

### upsert_result
- Input: `{ results: Result[] }`
- Output: `{ upserted: number, updated: number }`
- Error: `DB_CONNECTION_ERROR`, `DB_CONSTRAINT_ERROR`

## queue_tool

### enqueue
- Input: `{ tasks: TaskEvent[] }`
- Output: `{ accepted: number, rejected: number }`
- Retry: network/temporary 失败按指数退避自动重试
- Error: `QUEUE_FULL`, `INVALID_TASK`, `QUEUE_INTERNAL_ERROR`

## storage_tool

### save_raw
- Input: `{ site, snapshot_time, session_id, lot_id, snapshot_type, html }`
- Output: `{ raw_ref }`
- Error: `STORAGE_WRITE_ERROR`, `INVALID_PATH`

## scrape_tool

### fetch_page
- Input: `{ url, headers?, timeout_seconds? }`
- Output: `{ status_code, text, headers, fetched_at }`
- Error: `NETWORK_ERROR`, `HTTP_ERROR`, `TIMEOUT`

### parse_sessions
- Input: `{ text, source_url }`
- Output: `{ sessions: ParsedSession[] }`
- Error: `PARSER_ERROR`

### parse_lots
- Input: `{ text }`
- Output: `{ lots: ParsedLot[] }`
- Error: `PARSER_ERROR`

## 版本兼容约定
- 契约版本字段：`contract_version`，当前 `1.0.0`
- 向后兼容规则：新增字段必须为可选
- 破坏性变更：必须升级主版本并发布迁移说明
