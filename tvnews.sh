#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
NEWS_LOG="$LOG_DIR/news.log"
WEB_LOG="$LOG_DIR/web.log"
NEWS_PID="$LOG_DIR/news.pid"
WEB_PID="$LOG_DIR/web.pid"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STOP_TIMEOUT="${STOP_TIMEOUT:-20}"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' < "$pid_file"
  fi
}

is_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

service_pid() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file" || true)"

  if is_running "$pid"; then
    printf '%s\n' "$pid"
    return 0
  fi

  if [[ -n "${pid:-}" ]]; then
    rm -f "$pid_file"
  fi
}

start_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  local existing_pid
  existing_pid="$(service_pid "$pid_file")"
  if [[ -n "$existing_pid" ]]; then
    log "$name already running (pid $existing_pid)"
    return 0
  fi

  log "Starting $name..."
  (
    cd "$ROOT_DIR"
    nohup "$@" >> "$log_file" 2>&1 &
    printf '%s\n' "$!" > "$pid_file"
  )

  sleep 1
  local pid
  pid="$(read_pid "$pid_file")"

  if is_running "$pid"; then
    log "$name started (pid $pid)"
    return 0
  fi

  rm -f "$pid_file"
  log "$name failed to start. Check $log_file"
  tail -n 20 "$log_file" 2>/dev/null || true
  return 1
}

stop_service() {
  local name="$1"
  local pid_file="$2"

  local pid
  pid="$(service_pid "$pid_file")"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    log "$name not running"
    return 0
  fi

  log "Stopping $name..."
  kill "$pid" 2>/dev/null || true
  local waited=0
  while [[ "$waited" -lt "$STOP_TIMEOUT" ]]; do
    if ! is_running "$pid"; then
      rm -f "$pid_file"
      log "$name stopped"
      return 0
    fi

    sleep 1
    waited=$((waited + 1))
  done

  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  log "$name stopped forcefully after ${STOP_TIMEOUT}s"
}

status_service() {
  local name="$1"
  local pid_file="$2"

  local pid
  pid="$(service_pid "$pid_file")"
  if [[ -n "$pid" ]]; then
    log "$name running (pid $pid)"
  else
    log "$name stopped"
  fi
}

start_all() {
  local failed=0
  start_service "News" "$NEWS_PID" "$NEWS_LOG" "$PYTHON_BIN" -u run.py || failed=1
  start_service "Web" "$WEB_PID" "$WEB_LOG" "$PYTHON_BIN" -u web/server.py || failed=1
  return "$failed"
}

stop_all() {
  stop_service "Web" "$WEB_PID"
  stop_service "News" "$NEWS_PID"
}

status_all() {
  status_service "News" "$NEWS_PID"
  status_service "Web" "$WEB_PID"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [start|stop|status|restart]

Commands:
  start    Start news downloader and web server
  stop     Stop news downloader and web server
  status   Show current service status
  restart  Stop and then start both services

If no command is given, start is used.
EOF
}

main() {
  local cmd="${1:-start}"

  case "$cmd" in
    start)
      start_all
      ;;
    stop)
      stop_all
      ;;
    status)
      status_all
      ;;
    restart)
      stop_all
      start_all
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      return 1
      ;;
  esac
}

main "$@"
