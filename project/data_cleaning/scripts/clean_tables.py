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


def _is_caption_row(cells, n_cols):
    """caption = 单个 cell 占满整行（典型表标题）。
    多 cell 行即使 colspan 占满（多级表头合并列名）也不是 caption。"""
    return len(cells) == 1 and cells[0][2] >= n_cols


def _detect_quality(rows):
    """行宽不齐且无 rowspan 标记 → 'unaligned'（MineRU 漏标 rowspan 的层级表），
    否则 'ok'。"""
    if any(rs > 1 for r in rows for (_, rs, _) in r):
        return "ok"
    widths = {sum(cs for _, _, cs in r) for r in rows}
    return "unaligned" if len(widths) > 1 else "ok"


def table_to_json(html):
    """HTML <table> 片段 → {caption, headers, rows, quality}。
    - 展开 rowspan（向下填充）/ colspan（横向填充），避免合并单元格错位
    - caption：只把 colspan 占满整行的标题行当 caption；表头取其后第一个内容行
    - 表头 cell 数不足列数时，空位用 '列N' 补，避免丢数据
    - quality：无 rowspan 标记但行宽不齐的层级表标 'unaligned'，提醒下游结构不可信
    - 空表返回空结构（quality='empty'）。"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    empty = {"caption": "", "headers": [], "rows": [], "quality": "empty"}
    if table is None:
        return empty
    rows = _parse_rows(table)
    if not rows:
        return empty
    n_cols = max(sum(cs for _, _, cs in r) for r in rows)
    if n_cols == 0:
        return empty
    grid = _expand_rows(rows, n_cols)
    header_idx = next((i for i, r in enumerate(rows) if not _is_caption_row(r, n_cols)), 0)
    caption = " ".join(text for r in rows[:header_idx] for (text, _, _) in r if text)
    raw = [h if h else f"列{i}" for i, h in enumerate(grid[header_idx])]
    seen = {}
    headers = []
    for h in raw:  # 去重：表头 colspan 展开会有重复列名，加序号避免 dict 键冲突丢数据
        c = seen.get(h, 0)
        headers.append(h if c == 0 else f"{h}.{c}")
        seen[h] = c + 1
    data_rows = [{headers[i]: gr[i] for i in range(len(headers))}
                 for gr in grid[header_idx + 1:]]
    return {
        "caption": caption,
        "headers": headers,
        "rows": data_rows,
        "quality": _detect_quality(rows),
    }


def extract_tables_from_markdown(md):
    """从 markdown 里揪出所有 <table>...</table>，逐个转 JSON，返回列表。
    MineRU 把 PDF 表格输出成 HTML <table> 嵌在 markdown 里，这里统一抽取。"""
    return [table_to_json(m.group(0)) for m in re.finditer(r"<table>.*?</table>", md, re.S)]
