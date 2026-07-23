# 暨大学生助手 · Multi-Agent Student Assistant

> 基于 LangGraph 多智能体编排 + RAGFlow 检索增强的暨大学生事务问答系统。
> 给学生问的每一个问题，答案都**带原文出处**——没把握就直说"把握不大"。

**项目代码全部在 [`project/`](project/) 子目录内。** 下面所有路径都相对仓根，往里走先 `cd project`。

---

## ✨ 核心特性

- **5 大智能体 + 3 辅助节点**：分类 → 检索 → 工具 → 生成 → 反思，循环自检
- **RAGFlow 检索增强**：所有回答可追溯到原始文档片段
- **自纠错循环**：反思失败最多 2 次重试，配合查询重写
- **学生 GPA 加权计算**：自然语言"这几门课多少分？平均多少？" → 自动结构化提取 → 加权平均
- **认证 + 历史**：PBKDF2 哈希 + SQLite 持久化问答历史

---

## 🏗️ 架构

```
                    ┌──────────────── retry (≤2) ──────────────┐
                    │                                          │
                    ▼                                          │
[学生提问] → Router → Retriever → Analyzer → Reflection      │
                            │            ▲           │          │
                            ▼            │           │ ok       │
                          Tools ─────────┘           ▼          │
                                                  Finalize ──→ [带引用的回答]
                                                            │
                                                            │ !ok & 满 MAX_ROUNDS
                                                            ▼
                                                  [拒答或带"把握不大"前缀]
```

---

## 🧩 五智能体

| 智能体 | 角色 |
|---|---|
| **Router** | 4 类路由：检索 / 工具 / 双开 / 拒答 |
| **Retriever** | RAGFlow top-k 召回 |
| **Tool** | 自然语言 → 结构化课程 → 加权平均分 |
| **Analyzer** | 起草答案，强制引用来源，拒答在找不到时 |
| **Reflection** | 三检：引用、对题、坦诚；失败则产出 `rewritten_query` |

辅助节点：`reject`（出域拒答）、`finalize`（出答案）、`retry`（套用 `rewritten_query` 重来）。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 智能体编排 | LangGraph（StateGraph + 条件边 + 反思循环） |
| LLM | SiliconFlow API（Qwen2.5 系列） |
| 检索 | RAGFlow（自部署，Docker） |
| 数据清洗 | MinerU（PDF→MD）+ PaddleOCR（图→文/VLM 描述） |
| 后端 | Flask + SQLite（问答历史） |
| 鉴权 | PBKDF2-HMAC-SHA256 + 内存 token 字典 |
| 前端 | 单页 HTML（CSS/JS 全内联，无构建步骤） |
| 测试 | pytest |

---

## 🚀 快速开始

```bash
# 0. 先进项目子目录
cd project

# 1. 起 RAGFlow 容器（外部依赖；本仓库不含）
#    按官网 compose 启动，导入 data_cleaning/output/ 下的 md

# 2. Python 环境（两个 venv 对应两个阶段）
python -m venv .venv                # agents + web
python -m venv .venv-mineru         # data_cleaning（PaddleOCR 链路）

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple langgraph langchain-openai flask

.\.venv-mineru\Scripts\Activate.ps1
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 3. 配环境变量
cp .env.example .env
# 编辑 .env，填 SILICONFLOW_API_KEY / RAGFLOW_API_KEY / RAGFLOW_BASE_URL

# 4. 起服务
python web/backend/app.py    # 默认 http://127.0.0.1:5000
```

---

## 📁 目录结构

仓库布局：

```
.
├── README.md                      # 你正在看的这个文件
├── .gitignore
└── project/                       # ★ 全部代码与文档
    ├── agents/                    # 多智能体核心
    │   ├── state.py               # 共享状态 TypedDict
    │   ├── router.py              # 入口分类
    │   ├── retriever.py           # RAGFlow 召回
    │   ├── tools.py               # GPA 加权平均 + JSON 抽取
    │   ├── analyzer.py            # 起草答案
    │   ├── reflection.py          # 自检 + 查询重写
    │   ├── graph.py               # LangGraph 编排（含 MAX_ROUNDS=2）
    │   └── tests/                 # 单元 + 图集成测试（mock LLM / RAGFlow）
    ├── web/                       # 收银台层
    │   ├── backend/               # Flask + SQLite + auth
    │   └── frontend/              # 单页 SPA（index.html）
    ├── data_cleaning/             # 知识库原始加工
    │   ├── raw/                   # 爬虫抓下来的 HTML/PDF
    │   ├── scripts/               # 清洗 + VLM + RAGFlow 导入
    │   └── mineru_output/         # MinerU 中间产物（gitignore）
    ├── docs/                      # 演示与答辩材料
    │   ├── 演示指南.md            # 8 题演示清单
    │   └── 答辩脚本.md            # 5 分钟讲稿 + 评委追问准备
    └── requirements.txt           # 仅 .venv-mineru 用；agents/web 依赖见上方
```

---

## 🧪 测试

```bash
cd project

.\.venv\Scripts\Activate.ps1
pytest agents/tests/ -v                # mock LLM 的单元 + 图集成测试
pytest web/backend/tests/ -v           # API 层测试

.\.venv-mineru\Scripts\Activate.ps1
pytest data_cleaning/scripts/tests/ -v # 清洗脚本测试
```

---

## 🎬 演示

详见 [`project/docs/演示指南.md`](project/docs/演示指南.md) —— 8 个递进的演示场景，覆盖路由、检索、循环、工具调用、出域拒答。

---

## ⚠️ 已知限制

- Token 存进程内存（`project/web/backend/auth.py`），重启会失效，需重新登录
- 反思重试上限 2 次（再拒答或带"把握不大"前缀）
- 课程列表很长时 GPT 偶发漏抽结构化字段（32B 模型限制）
- `.venv/` 与 `.venv-mineru/` 不入库，请按"快速开始"重建
- 默认管理员凭据 `admin / admin123` 仅供本地开发，上线请通过 `.env` 覆盖

---

## 🤝 致谢

暨南大学 实训项目 · 多智能体方向自选选题
