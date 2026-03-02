#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

LABEL="${LABEL:-com.local.crawler.main}"
UID_VALUE="$(id -u)"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
PY_BIN="${PY_BIN:-$(command -v python3)}"
DISCOVERY_URL="${DISCOVERY_URL:-https://www.hxguquan.com/}"
DISCOVERY_INTERVAL="${DISCOVERY_INTERVAL:-21600}"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/logs}"
OUT_LOG="${OUT_LOG:-${LOG_DIR}/launchd.out.log}"
ERR_LOG="${ERR_LOG:-${LOG_DIR}/launchd.err.log}"

write_plist() {
  mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIR}"
  cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY_BIN}</string>
    <string>${ROOT_DIR}/main.py</string>
    <string>--discovery-url</string>
    <string>${DISCOVERY_URL}</string>
    <string>--interval</string>
    <string>${DISCOVERY_INTERVAL}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
</dict>
</plist>
EOF
}

is_loaded() {
  launchctl print "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1
}

start_service() {
  write_plist
  if is_loaded; then
    launchctl kickstart -k "gui/${UID_VALUE}/${LABEL}"
  else
    launchctl bootstrap "gui/${UID_VALUE}" "${PLIST_PATH}"
  fi
  launchctl enable "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1 || true
  echo "服务已启动: ${LABEL}"
}

stop_service() {
  if is_loaded; then
    launchctl bootout "gui/${UID_VALUE}/${LABEL}"
    echo "服务已停止: ${LABEL}"
    return 0
  fi
  echo "服务未加载: ${LABEL}"
}

status_service() {
  if is_loaded; then
    launchctl print "gui/${UID_VALUE}/${LABEL}" | sed -n '1,80p'
    return 0
  fi
  echo "服务未加载: ${LABEL}"
  return 1
}

uninstall_service() {
  stop_service || true
  rm -f "${PLIST_PATH}"
  echo "服务定义已删除: ${PLIST_PATH}"
}

show_logs() {
  mkdir -p "${LOG_DIR}"
  echo "--- ${OUT_LOG} ---"
  tail -n 80 "${OUT_LOG}" 2>/dev/null || true
  echo "--- ${ERR_LOG} ---"
  tail -n 80 "${ERR_LOG}" 2>/dev/null || true
}

case "${1:-}" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  restart)
    stop_service || true
    start_service
    ;;
  status)
    status_service
    ;;
  uninstall)
    uninstall_service
    ;;
  logs)
    show_logs
    ;;
  *)
    echo "用法: bash scripts/crawler_launchd.sh {start|stop|restart|status|uninstall|logs}"
    exit 1
    ;;
esac
