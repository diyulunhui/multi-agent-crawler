# Repository Guidelines

## 项目结构与模块组织
- `src/`：核心业务代码，按领域拆分（如 `scraping/`、`scheduler/`、`workers/`、`storage/`、`services/`、`classification/`）。入口在 `main.py` 与 `src/app.py`。
- `tests/`：分层测试目录，`unit/`、`integration/`、`e2e/`（可选 `replay/`）。
- `scripts/`：运维与一次性脚本（如 `sync_hx_once.py`、`clean_dirty_data.py`、`run_test_pipeline.sh`）。
- `data/`：本地 SQLite 与抓取产物；`docs/testing-process.md` 记录测试门禁流程。

## 构建、测试与本地开发命令
- 建议先准备环境：`python3 -m venv .venv && source .venv/bin/activate`，然后安装项目实际依赖（按团队当前依赖清单）。
- 启动主循环抓取：`python3 main.py --discovery-url "https://www.hxguquan.com/" --interval 21600`
- 单次同步（含详情与分类）：`python3 scripts/sync_hx_once.py --entry-url "https://www.hxguquan.com/" --max-sessions 5`
- 全量测试流水线：`bash scripts/run_test_pipeline.sh`
- 分阶段执行（按门禁顺序）：`python3 -m unittest discover -s tests/unit -p "test_*.py"`、`python3 -m unittest discover -s tests/integration -p "test_*.py"`、`python3 -m unittest discover -s tests/e2e -p "test_*.py"`。
- 数据清洗预览：`python3 scripts/clean_dirty_data.py --db data/hx_auction.db`，正式执行时追加 `--apply`。

## 架构概览
- 主链路为 `发现专场 -> 发现拍品 -> 抓取详情/快照 -> 结果入库与报表`，由 `TaskScheduler + WorkerPool + Executors` 驱动。
- 存储层统一走 `src/storage/repositories/`，避免在执行器中直接拼接 SQL。
- 站点解析与规则变更优先收敛到 `src/scraping/` 与 `src/scraping/parsers/`，不要把 HTML 解析逻辑散落到业务层。

## 代码风格与命名约定
- Python 使用 4 空格缩进，保留类型注解与 `from __future__ import annotations` 风格。
- 建议在提交前执行一次 `python3 -m unittest discover -s tests/unit -p "test_*.py"` 作为快速自检。
- 命名规则：模块/函数/变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。
- 新增逻辑优先放入 `src/<domain>/` 对应层；避免在脚本中复制业务实现。

## 测试规范
- 测试框架为 `unittest`；测试文件命名必须为 `test_*.py`。
- 涉及调度、仓储、抓取解析改动时，至少补齐对应 `unit` 测试；跨模块流程改动需补 `integration` 或 `e2e`。
- 使用独立测试库（如 `data/test_*.db`），避免污染 `data/hx_auction.db`。
- 对解析器和 URL 规则改动，优先补样本驱动断言，确保字段映射与域名白名单行为可回归。

## 提交与 Pull Request 规范
- 当前目录未包含 `.git` 历史，无法提炼既有提交风格；建议采用 Conventional Commits：`feat: ...`、`fix: ...`、`test: ...`。
- PR 应包含：变更目的、核心改动点、执行过的测试命令与结果摘要、是否涉及数据结构或脚本行为变化。
- 若变更 `schema.sql`、调度策略或清洗脚本，PR 描述中需写明回滚方案与数据影响范围。

## 配置与数据安全
- 通过环境变量配置运行参数，参考 `src/config/settings.py`（如 `DB_URL`、`STORAGE_ROOT`、`APP_TIMEZONE`）。
- 禁止提交生产数据库、抓取原始快照或敏感数据；提交前确认 `data/` 下新增文件是否应纳入版本管理。

## Agent 协作说明
- 仓库协作默认使用简体中文沟通与文档说明，提交说明尽量给出可复现命令。
- 修改脚本或任务编排后，优先附一条最小复现命令与预期输出，便于后续代理或开发者快速验证。
