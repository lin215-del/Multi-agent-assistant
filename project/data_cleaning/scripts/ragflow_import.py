"""清洗产物 → RAGFlow top-k 友好 md 包装（课件第三步）。

把 clean_pdf 的产物（正文 md + tables JSON + figures.json）包装成单个 md：
正文（含 [表N]/[图N] 占位）+ 表格附录（markdown 表格）+ 图说明附录（caption）。
RAGFlow 上传这个 md，切块后检索能命中表格内容 / 图 caption。
"""
import os


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
