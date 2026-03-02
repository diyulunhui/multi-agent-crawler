#!/usr/bin/env bash
set -euo pipefail

# 统一测试流水线入口：任何阶段失败立即退出。
run_stage() {
  local stage="$1"
  local cmd="$2"
  echo "[TEST] START ${stage}"
  eval "${cmd}"
  echo "[TEST] PASS  ${stage}"
}

run_stage "UNIT" "python3 -m unittest discover -s tests/unit -p 'test_*.py'"
run_stage "INTEGRATION" "python3 -m unittest discover -s tests/integration -p 'test_*.py'"
run_stage "E2E" "python3 -m unittest discover -s tests/e2e -p 'test_*.py'"

# replay 阶段可选：目录存在时执行。
if [[ -d "tests/replay" ]]; then
  run_stage "REPLAY" "python3 -m unittest discover -s tests/replay -p 'test_*.py'"
else
  echo "[TEST] SKIP REPLAY (tests/replay not found)"
fi

echo "[TEST] ALL PASSED"
