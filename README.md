# 暨南大学学生助手

项目一现已统一为 **FastAPI + LangGraph + RAGFlow** 架构，不再包含或依赖 Next.js。

## 已实现功能

- 普通用户注册、登录、退出和历史对话
- 管理员/普通用户角色权限
- 自然语言学生事务问答
- RAGFlow 知识库检索、Top-K 召回、来源文档和相似度展示
- 检索不足时主动拒答
- 拒答时清空无关来源、相似度和网页按钮
- 真实 LangGraph 多智能体编排
- 对话历史回填和 LangGraph 运行检查点
- GPA/加权平均分工具调用
- 健康问题安全边界
- JPG、PNG、WebP 截图识别后再检索知识库
- Agent 执行日志
- 本地知识库快照数据看板
- 图片语义、可见文字、页码及结构化表格的多模态索引
- 可选文本模型只在证据通过质量门禁后整理答案
- RAGFlow 配置持久化到 `.env.local`
- Docker Compose 部署

## 快速启动（Windows）

使用前只需要准备：

1. Python 3.11 或 3.12。
2. 已启动的本机 RAGFlow（默认 `http://localhost:8080`），并在 RAGFlow 中配置好 LLM 与 Embedding 模型。
3. 一个有效的 RAGFlow API Key。

下载或克隆项目后，直接双击根目录的：

```text
start.bat
```

首次运行只会隐藏询问一次 RAGFlow API Key。脚本会自动：

- 创建项目专用 `.venv`
- 安装/更新 Python 依赖
- 验证 RAGFlow 连接
- 自动发现核心知识库
- 缺少知识库时从项目快照恢复“核心服务卡片”和“第一阶段”
- 自动填写主知识库与补充知识库 ID
- 将配置保存到不会上传 GitHub 的 `.env.local`
- 启动 FastAPI 服务

首次恢复知识库需要上传并解析文档，耗时取决于本机 RAGFlow 和模型速度；解析完成前，问答可能暂时拒答。

也可以在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_fastapi.ps1
```

浏览器打开：

```text
http://127.0.0.1:8090
```

首次打开会进入管理员初始化页面。请创建自己的管理员账号和至少 8 位密码，项目不再内置明文演示密码。

## 手动启动

```powershell
cd "C:\Users\Andy\Desktop\最新\student-assistant-main"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app_fastapi:app --host 127.0.0.1 --port 8090
```

## RAGFlow 配置

管理员登录后打开：

```text
http://127.0.0.1:8090/settings
```

填写：

- RAGFlow API Key
- RAGFlow 地址（本机默认值不需要修改）
- 问答知识库 ID（使用一键启动时自动填写）
- 可选的通知补充知识库 ID
- 可选的重排模型 ID
- 可选的文本模型地址、Key 和模型名

点击保存后立即生效，并写入本机 `.env.local`。页面不会回显 API Key，刷新和重启后不需要重新填写。

需要手动部署时，也可以复制 `.env.example`：

```powershell
Copy-Item .env.example .env.local
```

除 RAGFlow API Key 外，其余 Key 均为可选：

- `VLM_API_KEY`：启用截图识别。
- `LLM_API_KEY`：启用检索证据通过后的语言整理。
- 不配置 VLM/LLM Key 时，普通文字问答仍可使用规则路由和 RAGFlow 原文摘要。

不要将 `.env.local`、API Key 或真实密码提交到代码仓库。

## 页面

- `/`：普通用户与管理员的学生事务问答、截图提问、来源和历史
- `/agent-logs`：管理员查看 Agent 节点、耗时和结果
- `/pipeline`：管理员查看 RAGFlow 在线状态及本地知识库快照
- `/settings`：管理员持久化 RAGFlow 配置
- `/admin/users`：管理员维护用户角色

## 多智能体流程

```text
Intent Agent
  → Router Agent
      → Retriever Agent
      → Study Place Agent
      → Tool Agent
      → Health Agent
      → Reject Agent
  → Reflection Agent
  → Answer Agent
```

检索节点后包含 Quality Harness；不合格结果会改写查询并最多重试两次。编排使用
Python `langgraph.graph.StateGraph` 与 `MemorySaver` 检查点，运行轨迹会写入：

```text
data/feedback/agent_traces.jsonl
```

用户、会话和历史记录保存在：

```text
data/feedback/assistant.sqlite3
```

密码使用 PBKDF2-SHA256 哈希保存，旧版明文密码在首次启动时自动迁移。

## 图片提问

图片不会保存到项目目录。服务只接受 JPG、PNG、WebP，最大 6 MB，并将图片发送到 `.env.local` 配置的视觉模型服务。视觉模型只生成脱敏后的检索问题，最终答案仍必须由 RAGFlow 官方资料支撑。

所需环境变量：

```text
VLM_BASE_URL=https://api.siliconflow.cn/v1
VLM_API_KEY=你的视觉模型Key
VLM_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
```

## 数据看板

看板会直接读取 `knowledge_base/datasets/*/summary.json`，所以即使 RAGFlow 暂时离线，也能显示项目自带快照中的知识库数、文档数、文本分块和图片分块，不会再出现已导入但看板全为 0 的情况。

## 多模态清洗与关联

`multimodal/build_snapshot_index.py` 会读取知识库快照中的 MinerU/视觉模型结果，按图片
SHA-256 和表格内容去重，并保留：

- 来源文档、页码、视觉类型和上下文
- 图片说明、可见文字、检索关键词和建议问题
- 图片文件的可访问路径
- HTML 表格转换后的 JSON 行列数据

重建和质量检查：

```powershell
.\.venv\Scripts\python.exe .\multimodal\build_snapshot_index.py
.\.venv\Scripts\python.exe .\scripts\quality_gate.py --strict
```

问答命中相关文档后，页面会在答案下方展示真实图片或可滚动的结构化表格。质量门禁会检查
断图、缺少说明、空表格和稀疏表格。

完整的核心检索评测配置可离线生成，不会访问 RAGFlow：

```powershell
.\.venv\Scripts\python.exe .\ragflow\tune_core_retrieval.py --variants 4 --generate-only
```

## 项目报告

- [第三部分：多模态清洗与关联学术报告（PDF）](docs/reports/第三部分_多模态清洗与关联_学术报告.pdf)
- [第三部分：多模态清洗与关联学术报告（Word）](docs/reports/第三部分_多模态清洗与关联_学术报告.docx)

报告可直接从 GitHub 下载。源文件由 `scripts/build_third_part_academic_report.py` 生成。

## Docker

```powershell
docker compose up --build
```

打开 `http://127.0.0.1:8090`。如果 RAGFlow 运行在 Windows 宿主机，请在容器配置中使用：

```text
RAGFLOW_BASE_URL=http://host.docker.internal:8080
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m py_compile app_fastapi.py agents_fastapi\graph.py agents_fastapi\state.py
.\.venv\Scripts\python.exe scripts\quality_gate.py --strict
.\.venv\Scripts\python.exe tests\fastapi_smoke.py
```

## 目录说明

- `app_fastapi.py`：FastAPI API、页面、认证和管理后台
- `agents_fastapi/`：LangGraph 多智能体状态和编排
- `crawler/`：官网网页与附件采集
- `cleaner/`：清洗和服务卡片生成
- `multimodal/`：图片、表格和视觉识别
- `ragflow/`：导入、检索、参数实验和知识库导出
- `knowledge_base/`：可迁移的知识库快照
- `config/`：分块与召回实验配置
- `docs/reports/`：项目学术报告 PDF 与 Word
- `tests/`：FastAPI 与 RAGFlow 相关测试
