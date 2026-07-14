#!/bin/bash
# ============================================
# 一键启动前后端项目
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/apps/agent-runtime"
FRONTEND_DIR="$SCRIPT_DIR/apps/web"
BACKEND_HOST="${BACKEND_HOST:-localhost}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
RUNTIME_DIR="${RUNTIME_DIR:-$SCRIPT_DIR/.run}"
DETACH_MODE="false"
BACKEND_PID=""
FRONTEND_PID=""
BACKEND_PID_FILE=""
FRONTEND_PID_FILE=""
BACKEND_LOG_FILE=""
FRONTEND_LOG_FILE=""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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
    echo -e "${RED}[错误]${NC} $1"
}

usage() {
    cat <<EOF
用法：
  ./start.sh [--detach]

参数：
  --detach    以后台模式启动前后端，健康检查通过后退出脚本

可选环境变量：
  BACKEND_HOST   后端监听地址，默认 localhost
  BACKEND_PORT   后端端口，默认 8000
  FRONTEND_HOST  前端监听地址，默认 localhost
  FRONTEND_PORT  前端端口，默认 3000
  RUNTIME_DIR    pid 与日志目录，默认 ./.run
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --detach)
            DETACH_MODE="true"
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

# 检测包管理器
detect_pm() {
    if [[ -f "$FRONTEND_DIR/package-lock.json" ]] && command -v npm &>/dev/null; then
        echo "npm"
    elif [[ -f "$FRONTEND_DIR/pnpm-lock.yaml" ]] && command -v pnpm &>/dev/null; then
        echo "pnpm"
    elif [[ -f "$FRONTEND_DIR/yarn.lock" ]] && command -v yarn &>/dev/null; then
        echo "yarn"
    elif command -v npm &>/dev/null; then
        echo "npm"
    else
        error "未找到 Node.js 包管理器 (pnpm/yarn/npm)"
        exit 1
    fi
}

# 检测 Python
detect_python() {
    local venv_python="$BACKEND_DIR/.venv/bin/python"

    if [[ -x "$venv_python" ]]; then
        echo "$venv_python"
    elif command -v python3 &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null; then
        echo "python"
    else
        error "未找到 Python"
        exit 1
    fi
}

wait_http_ready() {
    local url="$1"
    local retries="$2"
    local i

    for ((i = 1; i <= retries; i++)); do
        if curl -sf "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

kill_if_running() {
    local pid="${1:-}"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
    fi
}

start_backend_foreground() {
    log "启动后端服务 (FastAPI)..."
    cd "$BACKEND_DIR"
    exec "$PYTHON" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
}

start_frontend_foreground() {
    log "启动前端服务 (Next.js)..."
    cd "$FRONTEND_DIR"
    exec "$PM" run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
}

start_backend_detached() {
    log "启动后端服务 (FastAPI, 后台模式)..."
    mkdir -p "$RUNTIME_DIR"
    BACKEND_PID_FILE="$RUNTIME_DIR/backend-${BACKEND_PORT}.pid"
    BACKEND_LOG_FILE="$RUNTIME_DIR/backend-${BACKEND_PORT}.log"
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid "$PYTHON" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
            >"$BACKEND_LOG_FILE" 2>&1 < /dev/null &
    else
        nohup "$PYTHON" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
            >"$BACKEND_LOG_FILE" 2>&1 < /dev/null &
    fi
    BACKEND_PID=$!
    echo "$BACKEND_PID" > "$BACKEND_PID_FILE"
}

start_frontend_detached() {
    log "启动前端服务 (Next.js, 后台模式)..."
    mkdir -p "$RUNTIME_DIR"
    FRONTEND_PID_FILE="$RUNTIME_DIR/frontend-${FRONTEND_PORT}.pid"
    FRONTEND_LOG_FILE="$RUNTIME_DIR/frontend-${FRONTEND_PORT}.log"
    local frontend_cmd
    frontend_cmd="cd \"$FRONTEND_DIR\" && exec $PM run dev -- --hostname \"$FRONTEND_HOST\" --port \"$FRONTEND_PORT\""
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid bash -lc "$frontend_cmd" >"$FRONTEND_LOG_FILE" 2>&1 < /dev/null &
    else
        nohup bash -lc "$frontend_cmd" >"$FRONTEND_LOG_FILE" 2>&1 < /dev/null &
    fi
    FRONTEND_PID=$!
    echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
}

PM=$(detect_pm)
PYTHON=$(detect_python)

log "检测到包管理器: $PM"
log "检测到 Python: $($PYTHON --version)"

# 并行启动
log "========================================="
log "  小说 Agent - 一键启动"
log "========================================="
echo ""

if [[ "$DETACH_MODE" == "true" ]]; then
    start_backend_detached
    if ! wait_http_ready "http://$BACKEND_HOST:$BACKEND_PORT/api/health" 20; then
        error "后端健康检查失败：http://$BACKEND_HOST:$BACKEND_PORT/api/health"
        warn "后端日志：$BACKEND_LOG_FILE"
        [[ -f "$BACKEND_LOG_FILE" ]] && tail -n 40 "$BACKEND_LOG_FILE" || true
        kill_if_running "$BACKEND_PID"
        exit 1
    fi
    success "后端已启动 (PID: $BACKEND_PID, http://$BACKEND_HOST:$BACKEND_PORT)"

    start_frontend_detached
    if ! wait_http_ready "http://$FRONTEND_HOST:$FRONTEND_PORT" 30; then
        error "前端就绪检查失败：http://$FRONTEND_HOST:$FRONTEND_PORT"
        warn "前端日志：$FRONTEND_LOG_FILE"
        [[ -f "$FRONTEND_LOG_FILE" ]] && tail -n 60 "$FRONTEND_LOG_FILE" || true
        kill_if_running "$FRONTEND_PID"
        kill_if_running "$BACKEND_PID"
        exit 1
    fi
    success "前端已启动 (PID: $FRONTEND_PID, http://$FRONTEND_HOST:$FRONTEND_PORT)"
    echo ""
    log "后台模式启动完成"
    log "后端日志：$BACKEND_LOG_FILE"
    log "前端日志：$FRONTEND_LOG_FILE"
    log "后端 PID 文件：$BACKEND_PID_FILE"
    log "前端 PID 文件：$FRONTEND_PID_FILE"
    exit 0
fi

start_backend_foreground &
BACKEND_PID=$!

if ! wait_http_ready "http://$BACKEND_HOST:$BACKEND_PORT/api/health" 20; then
    error "后端健康检查失败：http://$BACKEND_HOST:$BACKEND_PORT/api/health"
    kill_if_running "$BACKEND_PID"
    exit 1
fi
success "后端已启动 (PID: $BACKEND_PID, http://$BACKEND_HOST:$BACKEND_PORT)"

start_frontend_foreground &
FRONTEND_PID=$!

if ! wait_http_ready "http://$FRONTEND_HOST:$FRONTEND_PORT" 30; then
    error "前端就绪检查失败：http://$FRONTEND_HOST:$FRONTEND_PORT"
    kill_if_running "$FRONTEND_PID"
    kill_if_running "$BACKEND_PID"
    exit 1
fi
success "前端已启动 (PID: $FRONTEND_PID, http://$FRONTEND_HOST:$FRONTEND_PORT)"
echo ""
log "按 Ctrl+C 停止所有服务"
echo ""

cleanup() {
    echo ""
    warn "正在停止服务..."
    kill_if_running "$BACKEND_PID"
    kill_if_running "$FRONTEND_PID"
    success "已停止所有服务"
    exit 0
}
trap cleanup SIGINT SIGTERM

wait
