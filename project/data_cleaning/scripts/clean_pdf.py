"""
PDF 清洗（把 MineRU 串进清洗层）。
- clean_mineru_markdown: 纯函数，清洗 MineRU 输出的 markdown（抽表→JSON + 正文占位）
- run_mineru: subprocess 跑 mineru CLI 解析 PDF
- clean_pdf: 编排——跑 MineRU → 清洗 → 写正文 + tables/*.json + 复制图片
"""
import os, re, json, shutil, subprocess

from clean_tables import extract_tables_from_markdown

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))
MINERU_EXE = os.path.join(PROJECT_ROOT, ".venv-mineru", "Scripts", "mineru.exe")
TABLE_RE = re.compile(r"<table>.*?</table>", re.S)
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _first_sentence(text):
    """取首句：到第一个 。！？；!?; 截断，再限到 40 字。"""
    for stop in "。！？；!?;":
        idx = text.find(stop)
        if idx > 0:
            text = text[:idx + 1]
            break
    return text[:40].strip()


def _figure_caption(md, img_start):
    """在 md[:img_start] 里给图找 caption：标题优先，段落兜底。"""
    before = md[:img_start].rstrip()
    if not before:
        return ""
    lines = [ln.strip() for ln in before.split("\n")]
    for ln in reversed(lines):  # 先找最近的标题
        if ln.startswith("#"):
            return ln.lstrip("#").strip()
    for ln in reversed(lines):  # 再找最近的非空、非图片、非占位行
        if not ln or ln.startswith("![") or ln.startswith(("[图", "[表")):
            continue
        return _first_sentence(ln)
    return ""


def extract_figures_from_markdown(md):
    """抽 md 里所有图片 → [{n, path, caption, context}]，按出现顺序编号。
    caption 标题优先、段落兜底；context 是图片前 ~60 字片段，便于溯源。"""
    figures = []
    for i, m in enumerate(IMG_RE.finditer(md), 1):
        ctx_start = max(0, m.start() - 60)
        context = md[ctx_start:m.start()].strip().replace("\n", " ")[-60:]
        figures.append({
            "n": i,
            "path": m.group(1),
            "caption": _figure_caption(md, m.start()),
            "context": context,
        })
    return figures


def clean_mineru_markdown(md, source_url=""):
    """纯函数：清洗 MineRU 输出的 markdown。
    - 抽出所有 <table> → tables（JSON 列表），正文里表替换成 [表N] 占位
    - 抽出所有图片 → figures（含 caption 溯源），正文里图替换成 [图N] 占位
    返回 {markdown, tables, figures, source_url}。"""
    tables = extract_tables_from_markdown(md)
    figures = extract_figures_from_markdown(md)

    tcounter = {"i": 0}
    def _trep(_m):
        tcounter["i"] += 1
        return f"\n\n[表{tcounter['i']}]\n\n"

    fcounter = {"i": 0}
    def _frep(_m):
        fcounter["i"] += 1
        return f"\n\n[图{fcounter['i']}]\n\n"

    cleaned = TABLE_RE.sub(_trep, md)
    cleaned = IMG_RE.sub(_frep, cleaned).strip()
    return {"markdown": cleaned, "tables": tables, "figures": figures, "source_url": source_url}


def run_mineru(pdf_path, out_dir, backend="pipeline"):
    """subprocess 跑 mineru CLI 解析 PDF。成功返回 markdown 路径，失败 None。"""
    cmd = [MINERU_EXE, "-p", pdf_path, "-o", out_dir, "-b", backend, "-m", "auto", "-l", "ch"]
    subprocess.run(cmd, check=True, capture_output=True)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    md_path = os.path.join(out_dir, stem, "auto", f"{stem}.md")
    return md_path if os.path.exists(md_path) else None


def clean_pdf(pdf_path, out_dir, source_url=""):
    """完整清洗一份 PDF：跑 MineRU → 清洗 → 写正文 md + tables/*.json + 复制图片。"""
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    mineru_out = os.path.join(out_dir, "_mineru")  # 不带 name：MinerU 自己建 <stem>/auto/，避免双层 stem 撞 Windows 260 路径限制
    os.makedirs(mineru_out, exist_ok=True)
    md_path = run_mineru(pdf_path, mineru_out)
    if not md_path:
        return None
    md = open(md_path, encoding="utf-8").read()
    result = clean_mineru_markdown(md, source_url)

    os.makedirs(out_dir, exist_ok=True)
    header = f"# {name}\n\n" + (f"> 来源：{source_url}\n\n" if source_url else "")
    md_out = os.path.join(out_dir, f"{name}.md")
    open(md_out, "w", encoding="utf-8").write(header + result["markdown"])

    n_tables = 0
    if result["tables"]:
        tables_dir = os.path.join(out_dir, "tables")
        os.makedirs(tables_dir, exist_ok=True)
        for i, t in enumerate(result["tables"], 1):
            with open(os.path.join(tables_dir, f"{name}_table{i}.json"), "w", encoding="utf-8") as f:
                json.dump(t, f, ensure_ascii=False, indent=2)
        n_tables = len(result["tables"])

    n_figures = 0
    if result["figures"]:
        with open(os.path.join(out_dir, f"{name}_figures.json"), "w", encoding="utf-8") as f:
            json.dump(result["figures"], f, ensure_ascii=False, indent=2)
        n_figures = len(result["figures"])

    img_src = os.path.join(os.path.dirname(md_path), "images")
    if os.path.isdir(img_src):
        img_dst = os.path.join(out_dir, "images", name)
        os.makedirs(img_dst, exist_ok=True)
        for f in os.listdir(img_src):
            shutil.copy(os.path.join(img_src, f), os.path.join(img_dst, f))

    return {"markdown_path": md_out, "tables": n_tables, "figures": n_figures, "source_url": source_url}
