# 团队知识库一键恢复

组员可以从 GitHub Release 下载项目源码，在自己的电脑上将同一份知识库快照恢复到本地 RAGFlow。快照已经过 SHA-256 校验并去除 API Key、账号和聊天记录。

## 前置条件

1. Docker 和 RAGFlow 已启动，浏览器能够打开 `http://localhost:8080`。
2. 已在 RAGFlow 配置快照所需的 LLM 和 Embedding 模型。
3. 已在 RAGFlow 的 API 页面创建个人 API Key。
4. 已安装 Python 3.10 或更高版本。

## 一键恢复

在项目目录打开 PowerShell：

```powershell
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\restore_team_ragflow.ps1
```

脚本默认恢复全部 5 个知识库，共 692 条知识库记录。重复运行不会重复上传同名文档。

只恢复正式使用的核心库和第一阶段综合库：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore_team_ragflow.ps1 -Scope recommended
```

仅检查下载的数据是否完整，不连接 RAGFlow：

```powershell
python scripts\restore_team_ragflow.py --dry-run
```

## 恢复结果

脚本会：

- 校验 GitHub 快照中的全部文件。
- 按名称创建或复用知识库。
- 重建 A/B/C 的 500、800、1200 tokens 分块流水线。
- 按批上传文档，同名文档自动跳过。
- 只对原快照中有检索分块的文档触发解析，保留仅供下载的附件。
- 在 `outputs/team_restore.json` 生成不含 API Key 的恢复报告。

API Key 只存在于当前 PowerShell 进程，脚本结束后立即清除。

## 使用边界

Vercel 上的学生助手无法访问组员电脑的 `localhost`。恢复后的知识库可以直接在组员本机 RAGFlow 中查看和检索；若要让线上学生助手查询某台电脑的本地知识库，仍需 Cloudflare Tunnel 等公网 HTTPS 通道。

RAGFlow 的 `image_id` 属于每个实例自己的对象存储。重新解析可能生成新的图片 ID，因此 ID 不会与原快照完全相同，但原始文档和图片文件仍保存在 GitHub 快照中。
