"""chunk_audit.py 的测试。纯函数（assess_chunk / format_report_markdown）不依赖外部服务。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, ROOT)

from scripts.chunk_audit import assess_chunk, format_report_markdown, _looks_truncated


def test_assess_chunk_with_title():
    a = assess_chunk({"content": "## 申请条件\n1. 品德优良"})
    assert a["has_title"]
    assert a["quality_score"] > 0.5


def test_assess_chunk_with_table():
    a = assess_chunk({"content": "##表格 成绩对照\n|---|\n| 优 | 4.0 |"})
    assert a["has_table_structure"]
    assert a["has_title"]


def test_assess_chunk_with_html_table():
    a = assess_chunk({"content": "##表格 成绩对照\n<table>\n<thead>\n<tr>\n<th>优</th>\n</tr>\n</table>"})
    assert a["has_table_structure"]


def test_assess_chunk_truncated_ellipsis():
    a = assess_chunk({"content": "申请条件包括品德优良、成绩..."})
    assert a["is_truncated"]


def test_assess_chunk_truncated_no_punctuation():
    a = assess_chunk({"content": "申请条件包括品德优良、成绩优异、" * 10 + "最后一句没有句号"})
    assert a["is_truncated"]


def test_assess_chunk_complete():
    a = assess_chunk({"content": "申请条件包括品德优良。成绩需在年级前30%。"})
    assert not a["is_truncated"]


def test_assess_chunk_figure():
    a = assess_chunk({"content": "[图1] 图片描述：校园地图"})
    assert a["is_figure"]


def test_quality_score_range():
    """所有 chunk 的质量分在 0-1 之间。"""
    contents = [
        "## 标题\n正文内容。",
        "纯正文无标题无结构",
        "|---|\n| a | b |",
        "",
        "[图1] 图片描述",
    ]
    for c in contents:
        a = assess_chunk({"content": c})
        assert 0.0 <= a["quality_score"] <= 1.0


def test_empty_chunk_handled():
    for val in [None, {}, {"content": ""}]:
        a = assess_chunk(val)
        assert a["quality_score"] == 0.0
        assert a["content_length"] == 0


def test_format_report_markdown():
    report = {
        "meta": {"total_queries": 1, "total_chunks": 2, "top_k": 5},
        "summary": {"avg_quality_score": 0.6, "truncation_rate": 0.5,
                    "table_rate": 0.0, "figure_rate": 0.5},
        "per_query": [{
            "query": "测试",
            "chunk_count": 2,
            "avg_score": 0.6,
            "chunks": [{
                "source": "doc.md", "score": 0.85,
                "content_preview": "正文预览",
                "assessment": {"has_title": True, "has_table_structure": False,
                               "is_truncated": False, "is_figure": True,
                               "content_length": 100, "quality_score": 0.8},
            }],
        }],
    }
    md = format_report_markdown(report)
    assert "Chunk 审计报告" in md
    assert "概览" in md
    assert "汇总统计" in md
    assert "逐查询详情" in md
    assert "测试" in md


def test_looks_truncated_ellipsis():
    assert _looks_truncated("内容...")


def test_looks_truncated_no_sentence_end():
    assert _looks_truncated("内容很长" + ("，" * 40))


def test_looks_truncated_complete():
    assert not _looks_truncated("完整句子。")
    assert not _looks_truncated("完整句子！")
    assert not _looks_truncated("GPA 计算公式：加权平均分。")
