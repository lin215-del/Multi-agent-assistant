"""clean_pdf.py 的测试。重点测纯函数 clean_mineru_markdown。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/

from clean_pdf import clean_mineru_markdown


def test_extracts_tables_and_replaces_with_placeholder():
    md = """# 学科竞赛榜单

榜单说明文字。

<table><tr><th>序号</th><th>名称</th></tr><tr><td>1</td><td>互联网+</td></tr></table>

后面还有文字。
"""
    result = clean_mineru_markdown(md, source_url="https://jwc.jnu.edu.cn/x/page.htm")
    # 抽出 1 张表
    assert len(result["tables"]) == 1
    assert result["tables"][0]["headers"] == ["序号", "名称"]
    assert result["tables"][0]["rows"] == [{"序号": "1", "名称": "互联网+"}]
    # 正文里 HTML 表被替换成 [表1] 占位
    assert "<table>" not in result["markdown"]
    assert "[表1]" in result["markdown"]
    # 非表格文字保留
    assert "榜单说明文字" in result["markdown"]
    assert "后面还有文字" in result["markdown"]
    # 溯源
    assert result["source_url"] == "https://jwc.jnu.edu.cn/x/page.htm"


def test_multiple_tables_numbered_sequentially():
    md = """<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
中间
<table><tr><th>B</th></tr><tr><td>2</td></tr></table>"""
    result = clean_mineru_markdown(md)
    assert len(result["tables"]) == 2
    assert "[表1]" in result["markdown"]
    assert "[表2]" in result["markdown"]


def test_no_tables_returns_clean_text():
    md = "纯文字，没表\n\n另一段"
    result = clean_mineru_markdown(md)
    assert result["tables"] == []
    assert "<table>" not in result["markdown"]
    assert "纯文字" in result["markdown"]


# ---------- 图表溯源 ----------
def test_figure_caption_from_nearest_title():
    md = """前面的引子。

## 步骤二：进入申请界面

![](images/abc.jpg)

后续文字。
"""
    result = clean_mineru_markdown(md)
    assert len(result["figures"]) == 1
    fig = result["figures"][0]
    assert fig["n"] == 1
    assert fig["path"] == "images/abc.jpg"
    assert fig["caption"] == "步骤二：进入申请界面"
    # 正文里图片被替换成 [图N] 占位
    assert "[图1]" in result["markdown"]
    assert "![]" not in result["markdown"]
    # 非图片文字保留
    assert "后续文字" in result["markdown"]


def test_figure_caption_falls_back_to_paragraph():
    """图上文没标题时，caption 取最近段落的首句。"""
    md = """首先在输入框输入"创新学分认定"，然后再点击查询。

![](images/def.jpg)
"""
    result = clean_mineru_markdown(md)
    assert len(result["figures"]) == 1
    assert "创新学分认定" in result["figures"][0]["caption"]


def test_multiple_figures_numbered_sequentially():
    md = """## 一

![](images/a.jpg)

正文。

## 二

![](images/b.jpg)
"""
    result = clean_mineru_markdown(md)
    assert len(result["figures"]) == 2
    assert result["figures"][0]["n"] == 1
    assert result["figures"][1]["n"] == 2
    assert result["figures"][1]["caption"] == "二"
    assert "[图1]" in result["markdown"]
    assert "[图2]" in result["markdown"]


def test_no_figures_returns_empty_list():
    md = "纯文字，没图\n\n另一段"
    result = clean_mineru_markdown(md)
    assert result["figures"] == []
