#!/bin/bash
# ============================================
# 一键启动后端服务 + Cloudflare Tunnel
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/apps/agent-runtime"

DEFAULT_BACKEND_HOST="localhost"
DEFAULT_BACKEND_PORT="8000"
DEFAULT_TUNNEL_CONFIG="$HOME/.cloudflared/config.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
  echo -e "${BLUE}[启动]${NC} $1"
}

success() {
  echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
  echo -e "${YELLOW}[警告]${NC} $1"
}

error() {
  echo -e "${RED}[错误]${NC} $1" >&2
}

usage() {
  cat <<EOF
用法：
  ./start-backend-tunnel.sh [选项]

选项：
  --backend-host HOST        后端监听地址，默认 ${DEFAULT_BACKEND_HOST}
  --backend-port PORT        后端监听端口，默认 ${DEFAULT_BACKEND_PORT}
  --tunnel-config PATH       cloudflared 配置文件，默认 ${DEFAULT_TUNNEL_CONFIG}
  --dry-run                  只打印将执行的动作，不真正启动
  -h, --help                 显示帮助
EOF
}

detect_python() {
  local backend_dir="$1"
  local venv_python="$backend_dir/.venv/bin/python"

  if [[ -x "$venv_python" ]]; then
    echo "$venv_python"
  elif command -v python3 >/dev/null 2>&1; then
    echo "python3"
  elif command -v python >/dev/null 2>&1; then
    echo "python"
  else
    error "未找到 Python"
    exit 1
  fi
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    error "未找到命令：$cmd"
    exit 1
  fi
}

extract_tunnel_id() {
  local config_file="$1"
  awk -F': ' '$1 == "tunnel" {print $2}' "$config_file" | head -n 1
}

wait_backend_ready() {
  local health_url="$1"
  local retries=20
  local i
  for ((i = 1; i <= retries; i++)); do
    if curl -sf "$health_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

BACKEND_HOST="$DEFAULT_BACKEND_HOST"
BACKEND_PORT="$DEFAULT_BACKEND_PORT"
TUNNEL_CONFIG="$DEFAULT_TUNNEL_CONFIG"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-host)
      BACKEND_HOST="$2"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    --tunnel-config)
      TUNNEL_CONFIG="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      error "未知参数：$1"
      usage
      exit 1
      ;;
  esac
done

require_command cloudflared
require_command curl
PYTHON="$(detect_python "$BACKEND_DIR")"

if [[ ! -f "$TUNNEL_CONFIG" ]]; then
  error "cloudflared 配置文件不存在：$TUNNEL_CONFIG"
  exit 1
fi

TUNNEL_ID="$(extract_tunnel_id "$TUNNEL_CONFIG")"
if [[ -z "$TUNNEL_ID" ]]; then
  error "无法从配置文件中读取 tunnel ID：$TUNNEL_CONFIG"
  exit 1
fi

BACKEND_CMD="$PYTHON -m uvicorn app.main:app --host $BACKEND_HOST --port $BACKEND_PORT --reload"
TUNNEL_CMD="cloudflared tunnel --config $TUNNEL_CONFIG run $TUNNEL_ID"
HEALTH_URL="http://$BACKEND_HOST:$BACKEND_PORT/api/health"

log "Python: $($PYTHON --version 2>&1)"
log "Tunnel 配置: $TUNNEL_CONFIG"
log "Tunnel ID: $TUNNEL_ID"
log "后端命令: $BACKEND_CMD"
log "隧道命令: $TUNNEL_CMD"

if [[ "$DRY_RUN" == "true" ]]; then
  success "dry-run 完成，未真正启动进程"
  exit 0
fi

cleanup() {
  echo ""
  warn "正在停止后端与隧道..."
  if [[ -n "${TUNNEL_PID:-}" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  success "已停止所有进程"
  exit 0
}

trap cleanup SIGINT SIGTERM

log "启动后端服务..."
cd "$BACKEND_DIR"
$PYTHON -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

if ! wait_backend_ready "$HEALTH_URL"; then
  error "后端健康检查失败：$HEALTH_URL"
  kill "$BACKEND_PID" 2>/dev/null || true
  exit 1
fi
success "后端已就绪：$HEALTH_URL (PID: $BACKEND_PID)"

log "启动 Cloudflare Tunnel..."
cloudflared tunnel --config "$TUNNEL_CONFIG" run "$TUNNEL_ID" &
TUNNEL_PID=$!
success "Tunnel 已启动 (PID: $TUNNEL_PID)"

echo ""
log "按 Ctrl+C 停止后端与隧道"
echo ""

wait
