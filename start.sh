#!/bin/bash
# ============================================
# 一键启动前后端项目
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/apps/agent-runtime"
FRONTEND_DIR="$SCRIPT_DIR/apps/web"

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
    if command -v pnpm &>/dev/null; then
        echo "pnpm"
    elif command -v yarn &>/dev/null; then
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
    if command -v python3 &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null; then
        echo "python"
    else
        error "未找到 Python"
        exit 1
    fi
}

PM=$(detect_pm)
PYTHON=$(detect_python)

log "检测到包管理器: $PM"
log "检测到 Python: $($PYTHON --version)"

# 启动后端
start_backend() {
    log "启动后端服务 (FastAPI)..."
    cd "$BACKEND_DIR"
    $PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
}

# 启动前端
start_frontend() {
    log "启动前端服务 (Next.js)..."
    cd "$FRONTEND_DIR"
    $PM run dev
}

# 并行启动
log "========================================="
log "  小说 Agent - 一键启动"
log "========================================="
echo ""

# 启动后端（后台运行）
start_backend &
BACKEND_PID=$!

# 等待后端启动
sleep 2

# 启动前端（后台运行）
start_frontend &
FRONTEND_PID=$!

success "后端已启动 (PID: $BACKEND_PID, http://localhost:8000)"
success "前端已启动 (PID: $FRONTEND_PID, http://localhost:3000)"
echo ""
log "按 Ctrl+C 停止所有服务"
echo ""

# 捕获 Ctrl+C，统一终止
cleanup() {
    echo ""
    warn "正在停止服务..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    success "已停止所有服务"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 等待所有后台进程
wait
