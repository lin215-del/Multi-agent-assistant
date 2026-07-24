# RAGFlow 知识库快照

本目录由 `ragflow/export_knowledge_bases.py` 从本机 RAGFlow REST API 导出，用于团队审阅、版本归档和离线备份。

包含 `manifest.json`、各知识库的配置/文档/分块、按 SHA-256 去重的文档原件与原生图片，以及 `SHA256SUMS.txt`。

不包含 RAGFlow API Token、模型 API Key、数据库密码、账号、昵称、创建者 ID、反馈日志和聊天记录。

重新导出：

```powershell
python ragflow\export_knowledge_bases.py --workers 8
```
