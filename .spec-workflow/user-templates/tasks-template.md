# Tasks Document

- [ ] 1. 定义核心接口与数据模型
  - File: [文件路径]
  - Purpose: [目的]
  - _Leverage: [复用点]_
  - _Requirements: [需求编号]_
  - _Prompt: Implement the task for spec {spec-name}, first run spec-workflow-guide to get the workflow guide then implement the task: Role: [角色] | Task: [任务] | Restrictions: [约束] | _Leverage: [杠杆文件] | _Requirements: [需求编号] | Success: [完成标准] | Instructions: 开始前将任务从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录实现；最后改为 `[x]`。

- [ ] 2. 实现业务主流程
  - File: [文件路径]
  - Purpose: [目的]
  - _Leverage: [复用点]_
  - _Requirements: [需求编号]_
  - _Prompt: Implement the task for spec {spec-name}, first run spec-workflow-guide to get the workflow guide then implement the task: Role: [角色] | Task: [任务] | Restrictions: [约束] | _Leverage: [杠杆文件] | _Requirements: [需求编号] | Success: [完成标准] | Instructions: 开始前将任务从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录实现；最后改为 `[x]`。

- [ ] 3. 建立测试流程与发布门禁
  - File: docs/testing-process.md
  - File: scripts/run_test_pipeline.sh
  - 定义 `unit -> integration -> e2e -> replay` 测试阶段与顺序
  - Purpose: 固化统一测试流程，保证失败可阻断
  - _Leverage: design.md 测试流程章节_
  - _Requirements: [需求编号]_
  - _Prompt: Implement the task for spec {spec-name}, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 测试平台工程师 | Task: 建立测试流程文档与统一执行脚本，确保可在 CI 或本地一键执行 | Restrictions: 不跳过任何测试阶段，不依赖线上环境，不允许失败后继续发布 | _Leverage: 现有测试用例与 CI 配置 | _Requirements: [需求编号] | Success: 脚本可执行完整流程，失败阶段可定位并中断 | Instructions: 开始前将任务从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录实现；最后改为 `[x]`。

- [ ] 4. 补充单元测试
  - File: [测试文件路径]
  - Purpose: 覆盖核心逻辑与边界条件
  - _Leverage: [业务模块文件]_
  - _Requirements: [需求编号]_
  - _Prompt: Implement the task for spec {spec-name}, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 测试工程师 | Task: 编写单元测试覆盖核心分支和边界条件 | Restrictions: 不依赖外部网络，不使用脆弱的 sleep 断言，不遗漏失败场景 | _Leverage: 目标模块与测试工具 | _Requirements: [需求编号] | Success: 单元测试稳定通过并可定位失败原因 | Instructions: 开始前将任务从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录实现；最后改为 `[x]`。

- [ ] 5. 补充集成与端到端测试
  - File: [集成/E2E 测试文件路径]
  - Purpose: 验证模块协作与完整业务路径
  - _Leverage: [应用入口/服务层]_
  - _Requirements: [需求编号]_
  - _Prompt: Implement the task for spec {spec-name}, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 集成测试工程师 | Task: 编写集成与端到端测试，覆盖主路径与关键异常路径 | Restrictions: 不依赖真实生产环境，不忽略状态迁移断言，不省略错误路径验证 | _Leverage: 测试策略章节与现有测试夹具 | _Requirements: [需求编号] | Success: 主流程和异常流程均可复现并稳定通过 | Instructions: 开始前将任务从 `[ ]` 改为 `[-]`；完成后调用 `log-implementation` 记录实现；最后改为 `[x]`。
