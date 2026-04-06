# 小说 Agent Demo

基于 LangChain + LangGraph 的 AI 辅助小说创作系统。

## 环境要求

- Python 3.11+
- Node.js 18+
- pnpm（前端包管理）

## 快速启动

### 1. 后端

```bash
cd apps/agent-runtime

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
# 或
pip install -e .

# 配置环境变量（复制示例文件并填写 API Key）
cp .env.example .env
# 编辑 .env，填写 OPENAI_API_KEY

# 启动后端
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证后端启动：

```bash
curl http://127.0.0.1:8000/api/health
# 预期返回：{"status":"ok"}
```

### 2. 前端

```bash
cd apps/web

# 安装依赖
npm install

# 配置前端 API 地址（如需修改）
# 当前默认会连接 http://127.0.0.1:8000
# 如需修改，编辑 .env.local 并设置 NEXT_PUBLIC_API_BASE_URL

# 启动前端开发服务器
npm run dev
```

浏览器访问 `http://localhost:3000`（或终端显示的端口）。

### 2.1 前端构建校验

```bash
npm run build
```

说明：
- 当前仓库执行 `npm run lint` 时会进入 Next.js ESLint 初始化交互，不适合作为现成校验命令。
- 需要做前端基础校验时，优先使用 `npm run build`。

### 2.2 一键启动后端 + Tunnel

如果只需要启动后端与 Cloudflare Tunnel，可在仓库根目录运行：

```bash
./start-backend-tunnel.sh
```

默认行为：
- 后端启动到 `127.0.0.1:8000`
- 使用 `~/.cloudflared/config.yml`
- 自动读取其中的 `tunnel` ID 并执行 `cloudflared tunnel run`

如需只检查命令而不真正启动：

```bash
./start-backend-tunnel.sh --dry-run
```

### 3. 验证接口

```bash
# 健康检查
curl http://127.0.0.1:8000/api/health

# 查看模型列表（14 个模型）
curl http://127.0.0.1:8000/api/models | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'模型数量: {len(d[\"data\"])}')
for m in d['data']:
    print(f'  {m[\"id\"]} ({m.get(\"display_name\",\"\")})')
"

# 查看 Dashboard
curl http://127.0.0.1:8000/api/dashboard | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'默认模型: {d[\"model_summary\"][\"default_model\"]}')
print(f'待处理: {d[\"continue_total\"]}, 运行中: {d[\"running_total\"]}, 失败: {d[\"failed_total\"]}')
"

# 切换默认模型
curl -X PATCH http://127.0.0.1:8000/api/settings/default-model \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"gpt-5.3-codex"}'

# 归档列表（分页）
curl "http://127.0.0.1:8000/api/archive?page=1&page_size=5" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'总数: {d[\"total\"]}, 当前页: {d[\"page\"]}, 每页: {d[\"page_size\"]}, 总页数: {d[\"total_pages\"]}')
"
```

## 项目结构

```
apps/
├── agent-runtime/        # FastAPI 后端
│   ├── app/
│   │   ├── api/          # 路由层
│   │   ├── application/  # 业务服务层
│   │   ├── domain/       # 领域模型
│   │   ├── graph/        # LangGraph 工作流
│   │   ├── llm/          # LLM 引擎 & 模型目录
│   │   ├── context/      # 上下文管理 & 压缩 & 缓存
│   │   ├── storage/      # 任务持久化
│   │   └── settings/     # 配置
│   ├── tests/            # 后端测试
│   └── .env              # 环境变量（需自行创建）
│
└── web/                  # Next.js 前端
    └── src/
        ├── app/          # 页面路由
        ├── features/     # 功能组件
        ├── components/   # 通用组件
        └── lib/          # API & 类型
```

## 核心功能

- **首页双栏布局**：Tab 分组任务列表 + 侧边栏统计 & 模型切换
- **默认模型切换**：首页侧边栏下拉选择，运行时生效，持久化到配置文件
- **归档分页**：后端分页查询，前端 Pagination 组件
- **工作流**：LangGraph 驱动（创建 → 规划 → 审核 → 生成 → 归档）
- **上下文管理**：预算分配、参考素材压缩、模型响应缓存
