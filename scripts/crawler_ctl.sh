#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PID_FILE="${PID_FILE:-logs/crawler.pid}"
LOG_FILE="${LOG_FILE:-logs/main.log}"
DISCOVERY_URL="${DISCOVERY_URL:-https://www.hxguquan.com/}"
DISCOVERY_INTERVAL="${DISCOVERY_INTERVAL:-21600}"
TAIL_LINES="${TAIL_LINES:-120}"

is_running() {
  if [[ ! -f "${PID_FILE}" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  kill -0 "${pid}" 2>/dev/null
}

find_existing_pid() {
  local ps_output
  ps_output="$(ps aux 2>/dev/null || true)"
  if [[ -z "${ps_output}" ]]; then
    return 1
  fi
  local pid
  pid="$(printf '%s\n' "${ps_output}" | awk '/[Pp]ython .*main.py --discovery-url/ && $0 !~ /awk/ {print $2; exit}')"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  echo "${pid}"
}

start_crawler() {
  mkdir -p "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"
  if is_running; then
    local running_pid
    running_pid="$(cat "${PID_FILE}")"
    echo "crawler 已运行，PID=${running_pid}"
    return 0
  fi
  local existed_pid
  existed_pid="$(find_existing_pid || true)"
  if [[ -n "${existed_pid}" ]]; then
    echo "${existed_pid}" > "${PID_FILE}"
    echo "检测到已在运行的 crawler，PID=${existed_pid}，已补写 PID 文件"
    return 0
  fi

  nohup python3 main.py --discovery-url "${DISCOVERY_URL}" --interval "${DISCOVERY_INTERVAL}" >>"${LOG_FILE}" 2>&1 &
  local pid=$!
  echo "${pid}" > "${PID_FILE}"
  sleep 1

  if kill -0 "${pid}" 2>/dev/null; then
    echo "crawler 启动成功，PID=${pid}"
    return 0
  fi

  echo "crawler 启动失败，请检查日志：${LOG_FILE}"
  tail -n "${TAIL_LINES}" "${LOG_FILE}" || true
  return 1
}

stop_crawler() {
  if ! is_running; then
    local existed_pid
    existed_pid="$(find_existing_pid || true)"
    if [[ -z "${existed_pid}" ]]; then
      rm -f "${PID_FILE}"
      echo "crawler 未运行"
      return 0
    fi
    echo "${existed_pid}" > "${PID_FILE}"
  fi

  local pid
  pid="$(cat "${PID_FILE}")"
  kill -15 "${pid}" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${PID_FILE}"
      echo "crawler 已停止"
      return 0
    fi
    sleep 1
  done

  echo "crawler 停止超时，仍在运行 PID=${pid}"
  return 1
}

status_crawler() {
  if is_running; then
    local pid
    pid="$(cat "${PID_FILE}")"
    echo "crawler 运行中，PID=${pid}"
    return 0
  fi
  local existed_pid
  existed_pid="$(find_existing_pid || true)"
  if [[ -n "${existed_pid}" ]]; then
    echo "${existed_pid}" > "${PID_FILE}"
    echo "crawler 运行中，PID=${existed_pid}（PID 文件已修复）"
    return 0
  fi
  echo "crawler 未运行"
  return 1
}

show_logs() {
  if [[ ! -f "${LOG_FILE}" ]]; then
    echo "日志文件不存在：${LOG_FILE}"
    return 1
  fi
  tail -n "${TAIL_LINES}" "${LOG_FILE}"
}

case "${1:-}" in
  start)
    start_crawler
    ;;
  stop)
    stop_crawler
    ;;
  restart)
    stop_crawler || true
    start_crawler
    ;;
  status)
    status_crawler
    ;;
  logs)
    show_logs
    ;;
  *)
    echo "用法: bash scripts/crawler_ctl.sh {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
