"""
HTML 表 → JSON 清洗（课件"表转 JSON"硬要求）。
MineRU 把 PDF 里的表格解析成 HTML <table>，这里负责把它转成结构化 JSON：
  {"headers": [...], "rows": [{列名: 值, ...}, ...]}
"""
import re
from bs4 import BeautifulSoup


def _parse_rows(table):
    """<table> 的每个 <tr> → [[(text, rowspan, colspan), ...], ...]。空行丢弃。"""
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for c in tr.find_all(["td", "th"]):
            try:
                rs = max(int(c.get("rowspan", 1) or 1), 1)
                cs = max(int(c.get("colspan", 1) or 1), 1)
            except (ValueError, TypeError):
                rs = cs = 1
            cells.append((c.get_text(strip=True), rs, cs))
        if cells:
            rows.append(cells)
    return rows


def _expand_rows(rows, n_cols):
    """展开 rowspan/colspan 成 n_cols 宽的二维表。
    rowspan>1 的值向下填充到被合并的后续行；colspan>1 横向占多列。
    pending[col] = [剩余 rowspan 数, 值]，记录某列接下来还要被上面哪个值占几行。"""
    grid = []
    pending = {}
    for cells in rows:
        row = [""] * n_cols
        ci = 0
        col = 0
        while col < n_cols:
            if col in pending:
                row[col] = pending[col][1]
                pending[col][0] -= 1
                if pending[col][0] == 0:
                    del pending[col]
                col += 1
            elif ci < len(cells):
                text, rs, cs = cells[ci]
                ci += 1
                for k in range(cs):
                    if col + k < n_cols:
                        row[col + k] = text
                        if rs > 1:
                            pending[col + k] = [rs - 1, text]
                col += cs
            else:
                col += 1
        grid.append(row)
    return grid


def table_to_json(html):
    """HTML <table> 片段 → {"caption": ..., "headers": [...], "rows": [...]}。
    - 展开 rowspan（向下填充）/ colspan（横向填充），避免合并单元格错位
    - 表头行 = cell 数最多的那行；之前的行（常是 colspan 占满的标题）合并成 caption
    - 其余行按表头转成 dict。空表返回空结构。"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    empty = {"caption": "", "headers": [], "rows": []}
    if table is None:
        return empty
    rows = _parse_rows(table)
    if not rows:
        return empty
    n_cols = max(sum(cs for _, _, cs in r) for r in rows)
    if n_cols == 0:
        return empty
    grid = _expand_rows(rows, n_cols)
    cell_counts = [len(r) for r in rows]
    max_cells = max(cell_counts)
    header_idx = next(i for i, n in enumerate(cell_counts) if n == max_cells)
    caption = " ".join(text for r in rows[:header_idx] for (text, _, _) in r if text)
    headers = grid[header_idx]
    data_rows = [{headers[i]: gr[i] for i in range(len(headers))}
                 for gr in grid[header_idx + 1:]]
    return {"caption": caption, "headers": headers, "rows": data_rows}


def extract_tables_from_markdown(md):
    """从 markdown 里揪出所有 <table>...</table>，逐个转 JSON，返回列表。
    MineRU 把 PDF 表格输出成 HTML <table> 嵌在 markdown 里，这里统一抽取。"""
    return [table_to_json(m.group(0)) for m in re.finditer(r"<table>.*?</table>", md, re.S)]
