"""clean_tables.py 的测试。TDD：先写测试定义 HTML 表 → JSON 的期望行为。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/ 加进 path

from clean_tables import table_to_json, extract_tables_from_markdown


def test_simple_table_with_th_headers():
    html = """<table>
      <tr><th>序号</th><th>名称</th></tr>
      <tr><td>1</td><td>互联网+</td></tr>
      <tr><td>2</td><td>挑战杯</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["headers"] == ["序号", "名称"]
    assert result["rows"] == [
        {"序号": "1", "名称": "互联网+"},
        {"序号": "2", "名称": "挑战杯"},
    ]


def test_table_all_td_first_row_as_header():
    """MineRU 输出的表常常全是 <td>（没 <th>），第一行当表头"""
    html = """<table>
      <tr><td>序号</td><td>名称</td></tr>
      <tr><td>1</td><td>互联网+</td></tr>
      <tr><td>2</td><td>挑战杯</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["headers"] == ["序号", "名称"]
    assert result["rows"] == [
        {"序号": "1", "名称": "互联网+"},
        {"序号": "2", "名称": "挑战杯"},
    ]


def test_empty_table_returns_empty():
    result = table_to_json("<table></table>")
    assert result["headers"] == []
    assert result["rows"] == []


def test_mineru_style_table_with_colspan_title():
    """MineRU 常把表的第一行弄成占满整行的标题（colspan），真表头在第二行。
    标题行要识别成 caption，不当表头。"""
    html = """<table>
      <tr><td colspan="4">2024年全国普通高校学科竞赛排行榜榜单</td></tr>
      <tr><td>序号</td><td>竞赛名称</td><td>子赛</td><td>分类</td></tr>
      <tr><td>1</td><td>互联网+</td><td>互联网+</td><td>综合类</td></tr>
      <tr><td>2</td><td>挑战杯</td><td>挑战杯</td><td>综合类</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["caption"] == "2024年全国普通高校学科竞赛排行榜榜单"
    assert result["headers"] == ["序号", "竞赛名称", "子赛", "分类"]
    assert result["rows"] == [
        {"序号": "1", "竞赛名称": "互联网+", "子赛": "互联网+", "分类": "综合类"},
        {"序号": "2", "竞赛名称": "挑战杯", "子赛": "挑战杯", "分类": "综合类"},
    ]


# ---------- extract_tables_from_markdown ----------
def test_extract_finds_multiple_tables():
    md = """一些说明文字
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
中间又有文字
<table><tr><th>B</th></tr><tr><td>2</td></tr></table>
结尾"""
    tables = extract_tables_from_markdown(md)
    assert len(tables) == 2
    assert tables[0]["headers"] == ["A"]
    assert tables[0]["rows"] == [{"A": "1"}]
    assert tables[1]["headers"] == ["B"]
    assert tables[1]["rows"] == [{"B": "2"}]


def test_extract_returns_empty_when_no_table():
    assert extract_tables_from_markdown("纯文字，没有表") == []


# ---------- rowspan / colspan 展开 ----------
def test_rowspan_value_filled_downward():
    """rowspan>1 的单元格，其值要向下填充到被合并的后续行。
    不展开的话，后续行 cell 数 < 表头，列会错位。"""
    html = """<table>
      <tr><th>序号</th><th>名称</th><th>子项</th><th>分类</th></tr>
      <tr><td rowspan="2">1</td><td rowspan="2">外研社</td><td>演讲</td><td>语言</td></tr>
      <tr><td>辩论</td><td>语言</td></tr>
      <tr><td>2</td><td>数学建模</td><td>数学建模</td><td>理学</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["headers"] == ["序号", "名称", "子项", "分类"]
    assert result["rows"] == [
        {"序号": "1", "名称": "外研社", "子项": "演讲", "分类": "语言"},
        {"序号": "1", "名称": "外研社", "子项": "辩论", "分类": "语言"},
        {"序号": "2", "名称": "数学建模", "子项": "数学建模", "分类": "理学"},
    ]


def test_rowspan_mineru_redundant_attrs():
    """MineRU 真实输出：每个 td 都带 colspan/rowspan 属性（哪怕是 1），
    且相邻多列可能同时 rowspan（如'序号'+'竞赛名称'一起跨行）。
    复刻 test_ranking.pdf 序号15 那段的真实 HTML 结构。"""
    html = """<table>
      <tr><td colspan="1" rowspan="1">序号</td><td colspan="1" rowspan="1">竞赛名称（总）</td><td colspan="1" rowspan="1">竞赛名称（子赛）</td><td colspan="1" rowspan="1">竞赛分类</td></tr>
      <tr><td colspan="1" rowspan="2">15</td><td colspan="1" rowspan="2">外研社全国大学生英语系列赛</td><td colspan="1" rowspan="1">英语演讲赛</td><td colspan="1" rowspan="1">语言类</td></tr>
      <tr><td colspan="1" rowspan="1">英语辩论赛</td><td colspan="1" rowspan="1">语言类</td></tr>
      <tr><td colspan="1" rowspan="1">16</td><td colspan="1" rowspan="1">全国职业院校技能大赛</td><td colspan="1" rowspan="1">全国职业院校技能大赛</td><td colspan="1" rowspan="1">职业技能类</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["headers"] == ["序号", "竞赛名称（总）", "竞赛名称（子赛）", "竞赛分类"]
    assert result["rows"] == [
        {"序号": "15", "竞赛名称（总）": "外研社全国大学生英语系列赛", "竞赛名称（子赛）": "英语演讲赛", "竞赛分类": "语言类"},
        {"序号": "15", "竞赛名称（总）": "外研社全国大学生英语系列赛", "竞赛名称（子赛）": "英语辩论赛", "竞赛分类": "语言类"},
        {"序号": "16", "竞赛名称（总）": "全国职业院校技能大赛", "竞赛名称（子赛）": "全国职业院校技能大赛", "竞赛分类": "职业技能类"},
    ]


def test_colspan_horizontal_fill():
    """colspan>1 的单元格横向占据多列（数据区，非标题）。"""
    html = """<table>
      <tr><th>A</th><th>B</th><th>C</th></tr>
      <tr><td colspan="2">合并</td><td>x</td></tr>
    </table>"""
    result = table_to_json(html)
    assert result["rows"] == [{"A": "合并", "B": "合并", "C": "x"}]
