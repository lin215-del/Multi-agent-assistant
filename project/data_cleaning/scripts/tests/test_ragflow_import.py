"""ragflow_import 包装函数测试。
TDD：先定义'清洗产物 → RAGFlow top-k 友好 md'的期望行为。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/

from ragflow_import import package_for_ragflow, table_to_markdown


def test_table_to_markdown_basic():
    table = {"caption": "学分表", "headers": ["类别", "学分"], "rows": [{"类别": "A1", "学分": "2"}], "quality": "ok"}
    md = table_to_markdown(table)
    assert "| 类别 | 学分 |" in md
    assert "| ---" in md
    assert "| A1 | 2 |" in md


def test_package_includes_title_source_body_and_appendices():
    md = "正文开头 [表1] 中间 [图1] 结尾"
    tables = [{"caption": "学分表", "headers": ["类别", "学分"], "rows": [{"类别": "A1", "学分": "2"}], "quality": "ok"}]
    figures = [{"n": 1, "path": "images/x.jpg", "caption": "登录界面", "context": "..."}]
    out = package_for_ragflow("创新学分办法", md, tables, figures, source_url="https://jwc.jnu.edu.cn/x")
    # 标题 + 来源
    assert "# 创新学分办法" in out
    assert "https://jwc.jnu.edu.cn/x" in out
    # 正文保留（含占位）
    assert "正文开头" in out
    assert "结尾" in out
    # 表格附录：caption + markdown 表
    assert "学分表" in out
    assert "| 类别 | 学分 |" in out
    assert "| A1 | 2 |" in out
    # 图说明附录：序号 + caption
    assert "[图1]" in out
    assert "登录界面" in out


def test_package_without_tables_or_figures_has_no_appendix():
    out = package_for_ragflow("纯文本文档", "只有正文", [], [], source_url="")
    assert "只有正文" in out
    assert "表格内容" not in out
    assert "图表说明" not in out
