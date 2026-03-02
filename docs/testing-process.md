# 测试流程与发布门禁

## 流程总览
统一执行顺序：`unit -> integration -> e2e -> replay`。

## 1. Unit
- 目标：验证调度、队列、重试、解析等核心单模块逻辑。
- 执行命令：`python3 -m unittest discover -s tests/unit -p "test_*.py"`
- 门禁：失败即阻断后续阶段。

## 2. Integration
- 目标：验证仓储、调度、执行器、服务层协作。
- 执行命令：`python3 -m unittest discover -s tests/integration -p "test_*.py"`
- 门禁：失败即阻断后续阶段。

## 3. E2E
- 目标：验证“发现 -> 快照 -> 入库 -> 报表”主链路。
- 执行命令：`python3 -m unittest discover -s tests/e2e -p "test_*.py"`
- 门禁：失败即阻断发布。

## 4. Replay
- 目标：解析规则变更后，使用历史样本回放验证一致性。
- 执行命令：`python3 -m unittest discover -s tests/replay -p "test_*.py"`（如目录存在）
- 门禁：失败即阻断发布。

## 发布门禁
- 四阶段全部通过才允许发布。
- 任一阶段失败，必须附带失败摘要与修复责任人。
- 合并请求需附测试执行摘要（命令、结果、时间）。
