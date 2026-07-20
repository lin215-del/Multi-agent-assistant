"""清洗产物 → RAGFlow top-k 友好 md 包装（课件第三步）。

把 clean_pdf 的产物（正文 md + tables JSON + figures.json）包装成单个 md：
正文（含 [表N]/[图N] 占位）+ 表格附录（markdown 表格）+ 图说明附录（caption）。
RAGFlow 上传这个 md，切块后检索能命中表格内容 / 图 caption。
"""
import os
import json
import glob

import requests

DATASET_NAME = "暨大学生助手-多模态清洗"
DEFAULT_BASE = "http://localhost"


def table_to_markdown(table):
    """{caption, headers, rows} → markdown 表格字符串。无表头返回空。"""
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    if not headers:
        return ""
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def package_for_ragflow(name, markdown, tables, figures, source_url=""):
    """把清洗产物包装成 RAGFlow top-k 友好的单个 md。
    - 标题 + 来源
    - 正文（含 [表N]/[图N] 占位）
    - 表格附录：每张表 caption + markdown 表格（RAGFlow 切块后可命中表格内容）
    - 图说明附录：每张图 [图N] + caption（让图的语义可被检索）
    无表 / 无图时省略对应附录。"""
    parts = ["# " + name]
    if source_url:
        parts.append("> 来源：" + source_url)
    parts += ["", markdown.strip(), ""]

    if tables:
        parts += ["---", "## 表格内容", ""]
        for i, t in enumerate(tables, 1):
            cap = t.get("caption", "")
            parts.append("### [表" + str(i) + "] " + cap if cap else "### [表" + str(i) + "]")
            parts += ["", table_to_markdown(t), ""]

    if figures:
        parts += ["---", "## 图表说明", ""]
        for fig in figures:
            parts.append("[图" + str(fig.get("n", "")) + "] " + fig.get("caption", ""))

    return "\n".join(parts).rstrip() + "\n"


# ---------- RAGFlow API（IO 函数，端点已手动验证）----------
def load_env():
    """从 project/.env 读 RAGFLOW_API_KEY + RAGFLOW_BASE_URL，返回 (key, base)。
    .env 优先于环境变量；UTF-8 读，避开 Windows GBK 默认编码坑。"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    vals = {}
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    key = vals.get("RAGFLOW_API_KEY") or os.environ.get("RAGFLOW_API_KEY", "")
    base = vals.get("RAGFLOW_BASE_URL") or os.environ.get("RAGFLOW_BASE_URL", DEFAULT_BASE)
    return key, base


def _headers(key):
    return {"Authorization": "Bearer " + key}


def get_or_create_dataset(name=DATASET_NAME, description="MinerU 多模态清洗产物（正文 + 表格附录 + 图说明）"):
    """找或建 RAGFlow dataset，返回 dataset_id。已存在则复用。"""
    key, base = load_env()
    r = requests.get(base + "/api/v1/datasets", headers=_headers(key),
                     params={"page": 1, "page_size": 100}, timeout=15)
    r.raise_for_status()
    for d in r.json().get("data", []):
        if d.get("name") == name:
            return d["id"]
    r = requests.post(base + "/api/v1/datasets", headers=_headers(key),
                      json={"name": name, "description": description, "chunk_method": "naive"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["id"]


def upload_markdown(dataset_id, doc_name, md_content):
    """上传一个 md 文档到 dataset，返回 doc_id。重名会作为新版本/重复上传。"""
    key, base = load_env()
    r = requests.post(base + "/api/v1/datasets/" + dataset_id + "/documents",
                      headers=_headers(key),
                      files={"file": (doc_name + ".md", md_content.encode("utf-8"), "text/markdown")},
                      timeout=120)
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def parse_documents(dataset_id, doc_ids):
    """触发文档解析（切块 + 向量化）。RAGFlow 异步处理，调用后要轮询 chunk_count 确认完成。"""
    key, base = load_env()
    r = requests.post(base + "/api/v1/datasets/" + dataset_id + "/chunks",
                      headers=_headers(key), json={"document_ids": list(doc_ids)}, timeout=300)
    r.raise_for_status()
    return r.json()


def main():
    """批量上传清洗产物到 RAGFlow。
    - HTML md（cleaned/*/*.md）：直接上传（无表/图）
    - PDF（mineru_output/**/auto/*.md）：clean_mineru_markdown + package_for_ragflow 包装后上传
    按文件名去重（yingzai/yingzai_v2/diag_yingzai 同 PDF 只传一次），已有同名跳过。
    上传后批量 parse。
    """
    from clean_pdf import clean_mineru_markdown  # 延迟 import，避免顶部循环依赖

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cleaned_dir = os.path.join(project_root, "data_cleaning", "cleaned")
    mineru_dir = os.path.join(project_root, "data_cleaning", "mineru_output")

    ds = get_or_create_dataset()
    print("dataset_id:", ds, flush=True)

    # 已有文档名（重名跳过，避免重复上传）
    key, base = load_env()
    r = requests.get(base + "/api/v1/datasets/" + ds + "/documents",
                     headers=_headers(key), params={"page": 1, "page_size": 100}, timeout=15)
    existing = {d.get("name", "") for d in r.json().get("data", {}).get("docs", [])}
    print("dataset 现有", len(existing), "个文档（同名将跳过）", flush=True)

    doc_ids = []

    # HTML md：直接上传
    html_count = 0
    for md_path in sorted(glob.glob(os.path.join(cleaned_dir, "*", "*.md"))):
        section = os.path.basename(os.path.dirname(md_path))
        aid = os.path.splitext(os.path.basename(md_path))[0]
        doc_name = section + "-" + aid
        if doc_name + ".md" in existing:
            continue
        md_content = open(md_path, encoding="utf-8").read()
        if len(md_content.strip()) < 50:
            continue
        did = upload_markdown(ds, doc_name, md_content)
        if did:
            doc_ids.append(did)
            html_count += 1
            print("[HTML]", doc_name, flush=True)

    # PDF：clean + package + 上传，按 stem 去重
    pdf_count = 0
    seen = set()
    for raw_md in sorted(glob.glob(os.path.join(mineru_dir, "**", "auto", "*.md"), recursive=True)):
        stem = os.path.splitext(os.path.basename(raw_md))[0]
        if stem in seen:
            continue
        seen.add(stem)
        name = stem[:40]
        if name + ".md" in existing:
            print("[SKIP-PDF]", name, flush=True)
            continue
        md_text = open(raw_md, encoding="utf-8").read()
        result = clean_mineru_markdown(md_text)
        # figures 优先用 enrich 后的（VLM caption），没有则用 clean 出的粗 caption
        figures = result["figures"]
        rel = os.path.relpath(raw_md, mineru_dir)
        verify_dir = os.path.join(mineru_dir, rel.split(os.sep)[0])
        fig_json = os.path.join(verify_dir, stem + "_figures.json")
        if os.path.exists(fig_json):
            figures = json.load(open(fig_json, encoding="utf-8"))
        pkg = package_for_ragflow(name, result["markdown"], result["tables"], figures)
        did = upload_markdown(ds, name, pkg)
        if did:
            doc_ids.append(did)
            pdf_count += 1
            print("[PDF]", name, "| tables=" + str(len(result["tables"])),
                  "figures=" + str(len(result["figures"])), flush=True)

    print("上传完成：HTML", html_count, "+ PDF", pdf_count, "= 本次新传", len(doc_ids), "个文档", flush=True)
    if doc_ids:
        print("开始 parse（RAGFlow 异步切块 + 向量化）...", flush=True)
        parse_documents(ds, doc_ids)
        print("parse 已触发，稍后查 chunk_count 确认完成。", flush=True)
    else:
        print("无新文档，跳过 parse。", flush=True)


if __name__ == "__main__":
    main()
