# FastAPI 本地运行说明

项目已统一为 FastAPI，不再需要 Node.js、npm、pnpm 或 Next.js。

## 一键启动

直接双击项目根目录的：

```text
start.bat
```

首次运行只需输入一次 RAGFlow API Key。脚本会自动创建虚拟环境、安装依赖、发现或恢复核心知识库、填写知识库 ID、生成 `.env.local` 并启动服务。

前提是本机 `http://localhost:8080` 上的 RAGFlow 已启动，并已配置 LLM 与 Embedding 模型。

命令行方式：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_fastapi.ps1
```

启动完成后访问 `http://127.0.0.1:8090`。

第一次访问会要求创建管理员；后续普通用户可从登录页注册。

管理员仍可在 `/settings` 中修改 RAGFlow、VLM 或 LLM 配置。配置会保存到 `.env.local` 并立即生效。

## 页面权限

- 普通用户：智能问答、图片提问、来源引用、历史记录
- 管理员：包含普通用户功能，并可访问 Agent 日志、数据看板、连接配置、用户管理

## 停止

在启动服务的 PowerShell 窗口按 `Ctrl+C`。
