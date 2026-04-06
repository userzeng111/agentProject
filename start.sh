#!/bin/bash
# ============================================
# 一键启动前后端项目
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/apps/agent-runtime"
FRONTEND_DIR="$SCRIPT_DIR/apps/web"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="3000"

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

PM=$(detect_pm)
PYTHON=$(detect_python)

log "检测到包管理器: $PM"
log "检测到 Python: $($PYTHON --version)"

# 启动后端
start_backend() {
    log "启动后端服务 (FastAPI)..."
    cd "$BACKEND_DIR"
    $PYTHON -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
}

# 启动前端
start_frontend() {
    log "启动前端服务 (Next.js)..."
    cd "$FRONTEND_DIR"
    $PM run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
}

# 并行启动
log "========================================="
log "  小说 Agent - 一键启动"
log "========================================="
echo ""

# 启动后端（后台运行）
start_backend &
BACKEND_PID=$!

if ! wait_http_ready "http://$BACKEND_HOST:$BACKEND_PORT/api/health" 20; then
    error "后端健康检查失败：http://$BACKEND_HOST:$BACKEND_PORT/api/health"
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
fi
success "后端已启动 (PID: $BACKEND_PID, http://$BACKEND_HOST:$BACKEND_PORT)"

# 启动前端（后台运行）
start_frontend &
FRONTEND_PID=$!

if ! wait_http_ready "http://$FRONTEND_HOST:$FRONTEND_PORT" 30; then
    error "前端就绪检查失败：http://$FRONTEND_HOST:$FRONTEND_PORT"
    kill "$FRONTEND_PID" 2>/dev/null || true
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
fi
success "前端已启动 (PID: $FRONTEND_PID, http://$FRONTEND_HOST:$FRONTEND_PORT)"
echo ""
log "按 Ctrl+C 停止所有服务"
echo ""

# 捕获 Ctrl+C，统一终止
cleanup() {
    echo ""
    warn "正在停止服务..."
    kill "$BACKEND_PID" 2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    success "已停止所有服务"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 等待所有后台进程
wait
