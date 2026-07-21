"""chunk_type 启发式分类：table / figure / text。

RAGFlow retrieval 返回不带 type（agents/retriever.py:22），但清洗层在 PDF 产物里
插入 [表N]/[图N] 占位 + "##表格内容" 章节 + VLM caption 附录。本模块从 content
启发式识别出来，供前端打"表格/图/正文"徽章——这是答辫"多模态差异化"的可见钩子。
"""


def classify_chunk(content: str) -> str:
    """按内容启发式判定 chunk 类型。空串兜底 text。"""
    if not content:
        return "text"
    if _looks_like_table(content):
        return "table"
    if _looks_like_figure(content):
        return "figure"
    return "text"


def _looks_like_table(content: str) -> bool:
    """表格特征：Markdown 管道行（| --- |）或 '##表格' 章节标题。"""
    if "##表格" in content:
        return True
    if "| --- |" in content or "|---|" in content:
        return True
    return False


def _looks_like_figure(content: str) -> bool:
    """图特征：正文 [图N] 占位，或 VLM caption 附录的 '图片描述：' 开头。"""
    if "[图" in content:
        return True
    if "图片描述：" in content:
        return True
    return False