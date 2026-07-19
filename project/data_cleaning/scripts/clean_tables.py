"""
HTML 表 → JSON 清洗（课件"表转 JSON"硬要求）。
MineRU 把 PDF 里的表格解析成 HTML <table>，这里负责把它转成结构化 JSON：
  {"headers": [...], "rows": [{列名: 值, ...}, ...]}
"""
import re
from bs4 import BeautifulSoup


def table_to_json(html):
    """HTML <table> 片段 → {"caption": ..., "headers": [...], "rows": [...]}。
    - 表头行 = cell 数最多的那行（通常是真正的列头）
    - 表头之前的行（cell 少、常是 colspan 占满的标题）合并成 caption
    - 其余行按表头转成 dict。空表返回空结构。"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    empty = {"caption": "", "headers": [], "rows": []}
    if table is None:
        return empty
    rows = table.find_all("tr")
    if not rows:
        return empty
    parsed = [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])] for tr in rows]
    parsed = [p for p in parsed if p]
    if not parsed:
        return empty
    max_cells = max(len(p) for p in parsed)
    header_idx = next(i for i, p in enumerate(parsed) if len(p) == max_cells)
    caption = " ".join(c[0] for c in parsed[:header_idx] if c)
    headers = parsed[header_idx]
    data_rows = []
    for cells in parsed[header_idx + 1:]:
        n = min(len(headers), len(cells))
        data_rows.append({headers[i]: cells[i] for i in range(n)})
    return {"caption": caption, "headers": headers, "rows": data_rows}


def extract_tables_from_markdown(md):
    """从 markdown 里揪出所有 <table>...</table>，逐个转 JSON，返回列表。
    MineRU 把 PDF 表格输出成 HTML <table> 嵌在 markdown 里，这里统一抽取。"""
    return [table_to_json(m.group(0)) for m in re.finditer(r"<table>.*?</table>", md, re.S)]
