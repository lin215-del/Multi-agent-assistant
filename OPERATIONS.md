# 运行与维护

## 本机启动

1. 在 RAGFlow 中重新创建 API Token，不要继续使用曾经发送到聊天或截图中的密钥。
2. 将 `.env.example` 另存为本机 `.env`，只在 `.env` 中填写新 Token。
3. 启动 RAGFlow 后运行 `python web_app.py`。
4. 访问 `http://127.0.0.1:8090/healthz`，返回 `{"status":"ok"}` 表示 Web 服务正常。

## Docker 启动

```powershell
docker compose build
docker compose up -d
docker compose ps
```

容器通过 `host.docker.internal:8080` 访问宿主机 RAGFlow。`data` 目录只读挂载，`outputs` 用于质量和调优报告。公网部署前必须在反向代理中配置 HTTPS、访问日志脱敏和可信来源限制。

## 数据更新

执行一次平衡采集、清洗、质量检查并同步 RAGFlow：

```powershell
python scripts\update_pipeline.py --max-pages 200 --depth 1 --max-pages-per-seed 12 --sync-ragflow
```

采集器为每个种子分配独立页数上限，避免单个部门占满全部额度。同步时会删除已被清洗规则淘汰的知识库文档，并替换内容哈希发生变化的文档。

只补充或验证 RAGFlow 原生图片块：

```powershell
python ragflow\sync_native_images.py --datasets A --datasets B --datasets C
```

同步器将 MinerU 视觉单元交给 RAGFlow 自行写入对象存储并生成 `image_id`，随后逐一读取验证。运行结果显示在数据看板的“多模态资源”区域。

安装登录后常驻的每日 03:00 自动更新守护进程：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_maintenance_task.ps1
```

守护进程会在电脑错过 03:00 时于下次登录后补跑。移除自动启动项：

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\JNU Student Assistant Auto Refresh.lnk"
```

## 质量与检索验收

```powershell
python scripts\quality_gate.py --check-links
python ragflow\tune_core_retrieval.py --reuse-results
python ragflow\tune_retrieval_parameters.py --datasets C --workers 8 --notice-only --apply
python visualize_pipeline.py
```

质量门禁检查官方链接、旧通知、多模态图注、空表格和稀疏表格。正式助手的高风险拒答规则独立于相似度，包括凭据、个人隐私、医疗用药和录取保证。

照片提问默认限制为 6 MB，仅接受 JPG、PNG 和 WebP。照片在内存中缩放，不保存到本地；部署到公网时应在隐私说明中明确照片会发送给配置的视觉模型服务，并建议用户先遮挡个人信息。

## 密钥轮换

上线前必须在各自平台完成以下外部操作：

- 作废并重建 SiliconFlow API Key。
- 作废并重建百度 OCR API Key/Secret Key。
- 作废并重建 RAGFlow API Token。
- 确认新密钥只存在于 `.env` 或部署平台的 Secret 管理中。
- 运行 `git grep -n -I -E "sk-|API_KEY=.+|SECRET_KEY=.+"`，确认仓库没有真实密钥。

密钥轮换属于平台账户操作，不能由仓库脚本代替。

## 备份

发布前备份 `data/cleaned`、RAGFlow 数据卷和 `config`。Git 标签保存代码与配置历史，但不会保存被 `.gitignore` 排除的原始数据、附件、密钥和运行报告。

导出可提交 GitHub 的知识库内容快照：

```powershell
python ragflow\export_knowledge_bases.py --workers 8
```

导出结果位于 `knowledge_base/`，包含文档、分块、图片、公开配置和校验和，但主动排除账号、凭据、反馈与聊天数据。发布前检查 `knowledge_base/manifest.json` 中所有知识库的 `errors` 均为空。
