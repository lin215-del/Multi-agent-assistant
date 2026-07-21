"""chunk_classifier：把 RAGFlow 拿到的 chunk 按内容启发式分到 table / figure / text。

这是答辩"多模态差异化"的钩子——RAGFlow 的 retrieval 返回不带 type 字段（agents/retriever.py:22
只抽 content/source/score），但清洗层把 PDF 的表格转 JSON、图用 VLM 生成文字描述时插了
[表N]/[图N] 占位和 "##表格内容" 章节标题。本模块从 content 启发式识别出来，
前端据此在答案旁打不同色徽章，让"这一段引用自表格 / 这一段是图描述"可见。

启发式：
- figure: 含 "[图" 或 "图片描述：" → figure（VLM caption 附录用）
- table: 含管道行 "| --- |" 或 "##表格内容" 或 "##表格 " → table
- text: 其他
"""
from web.backend.chunk_classifier import classify_chunk


def test_classify_markdown_pipe_table_is_table():
    """Markdown 管道表行（| --- |）→ table。"""
    content = "| 学分 | 课程 |\n| --- | --- |\n| 4 | 高数 |\n| 3 | 英语 |"
    assert classify_chunk(content) == "table"


def test_classify_table_header_is_table():
    """清洗层的 '##表格内容' 章节标题 → table。"""
    content = "##表格内容\n\n以下是某通知的课程学分表…"
    assert classify_chunk(content) == "table"


def test_classify_figure_placeholder_is_figure():
    """正文里的 [图N] 占位 → figure。"""
    content = "申请流程如下图所示：[图2]。请按图操作。"
    assert classify_chunk(content) == "figure"


def test_classify_vlm_caption_is_figure():
    """VLM 生成的图描述开头 '图片描述：' → figure。"""
    content = "图片描述：流程图展示了从注册到毕业的 5 个步骤，箭头从左到右…"
    assert classify_chunk(content) == "figure"


def test_classify_plain_text_is_text():
    """普通正文段落 → text。"""
    content = "国家奖学金申请条件如下：1. 学习成绩优异；2. 综合素质突出…"
    assert classify_chunk(content) == "text"


def test_classify_empty_is_text():
    """空字符串兜底为 text。"""
    assert classify_chunk("") == "text"


def test_classify_table_takes_priority_over_figure_marker_in_long_table():
    """管道表里若有 [图X] 字样（如表内说明），仍判 table（先看表再看图）。"""
    content = "如图1所示：\n\n| 项目 | 说明 |\n| --- | --- |\n| A | 详见[图1] |"
    assert classify_chunk(content) == "table"