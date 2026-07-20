# AI 自讲 Demo

阶段 01 提供前后端分离的最小应用、集中配置校验、SQLite 连接、JSON 控制台日志和健康检查页面。

## 环境要求

- Python 3.11 或更高版本
- Node.js 20 或更高版本
- pnpm 10 或更高版本

## 安装

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
pnpm --dir frontend install
```

请在启动前替换 `.env` 中的示例模型配置。阶段 01 不调用 AI 或 ASR，但仍会校验全部已确认配置，避免后续阶段才发现配置缺失。

## 启动

同时启动 FastAPI 和 Vite：

```powershell
.\scripts\dev.ps1
```

也可以分别启动：

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
pnpm --dir frontend dev
```

前端地址为 `http://127.0.0.1:5173`，API 健康检查地址为 `http://127.0.0.1:8000/api/health`。Vite 从根目录 `.env` 读取 `BACKEND_PROXY_TARGET`，并将 `/api` 代理到 FastAPI。

## 检查

```powershell
python -m pytest backend/tests
python -m ruff check backend
python -m ruff format --check backend
pnpm --dir frontend test
pnpm --dir frontend typecheck
pnpm --dir frontend build
```
