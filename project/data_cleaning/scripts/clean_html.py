"""
HTML 清洗（课件"Python 第二步"）。
把爬虫存的 raw HTML 清洗成可读 markdown：抽正文、去导航/页脚、合并 <br> 碎行。
MineRU 留给 PDF/表格/公式；HTML 这条路 Python 一步到位。
"""
import os, re, csv, glob
from bs4 import BeautifulSoup

BODY_SELECTORS = ["#vsb_content", ".v_news_content", ".wp_articlecontent",
                  ".article-content", "article", ".content"]
TITLE_SELECTORS = ["h1", ".Article_Title", ".art-title", ".title"]
BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]
JUNK_SELECTORS = ["script", "style", ".position", ".breadcrumb", ".nav", ".footer",
                  ".share", ".pagination"]


def extract_body(html):
    """找正文容器。返回 bs4 Tag 或 None。"""
    soup = BeautifulSoup(html, "lxml")
    for sel in BODY_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 0:
            return el
    return None


def clean_markdown(html):
    """抽正文 → 删干扰元素 → 每个 block 一行（行内 <br> 合并）→ 返回干净文本。"""
    body = extract_body(html)
    if body is None:
        return ""
    for sel in JUNK_SELECTORS:
        for el in body.select(sel):
            el.decompose()
    lines = []
    for el in body.find_all(BLOCK_TAGS):
        text = el.get_text(strip=True)  # 行内 <br> 不产生换行，自然合并
        if text:
            lines.append(text)
    md = "\n".join(lines)
    if not md:
        md = body.get_text("\n", strip=True)
    return md


def clean_page(html, source_url=None):
    """清洗一页：返回 {title, markdown, source_url, char_count}。带 source_url 供溯源。"""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    for sel in TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    md = clean_markdown(html)
    return {
        "title": title,
        "markdown": md,
        "source_url": source_url or "",
        "char_count": len(md),
    }


def clean_directory(raw_dir, out_dir):
    """批量：读 raw_dir/html/*.html + raw_dir/manifest.csv → 清洗 → 写 out_dir/*.md + cleaned_index.csv。
    manifest 提供 id→url 映射，用于溯源。返回结果列表。"""
    os.makedirs(out_dir, exist_ok=True)
    url_map = {}
    manifest = os.path.join(raw_dir, "manifest.csv")
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                url_map[row["id"]] = row.get("url", "")
    results = []
    for hf in sorted(glob.glob(os.path.join(raw_dir, "html", "*.html"))):
        aid = os.path.splitext(os.path.basename(hf))[0]
        with open(hf, encoding="utf-8") as f:
            html = f.read()
        result = clean_page(html, source_url=url_map.get(aid, ""))
        result["id"] = aid
        header = f"# {result['title']}\n\n"
        if result["source_url"]:
            header += f"> 来源：{result['source_url']}\n\n"
        md_path = os.path.join(out_dir, f"{aid}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(header + result["markdown"])
        result["md_path"] = md_path
        results.append(result)
    index_path = os.path.join(out_dir, "cleaned_index.csv")
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "source_url", "char_count", "md_path"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    return results


def main():
    import argparse
    ap = argparse.ArgumentParser(description="批量清洗 raw HTML → cleaned markdown")
    ap.add_argument("--section", default="学生办事指南")
    args = ap.parse_args()
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    raw_dir = os.path.join(project_root, "data_cleaning", "raw", args.section)
    out_dir = os.path.join(project_root, "data_cleaning", "cleaned", args.section)
    print(f"清洗: {raw_dir} -> {out_dir}")
    results = clean_directory(raw_dir, out_dir)
    print(f"完成 {len(results)} 篇，总字数 {sum(r['char_count'] for r in results)}")
    print(f"  cleaned: {out_dir}")
    print(f"  index:   {os.path.join(out_dir, 'cleaned_index.csv')}")


if __name__ == "__main__":
    main()
