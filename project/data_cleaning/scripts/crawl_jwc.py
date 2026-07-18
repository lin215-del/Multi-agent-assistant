"""
jwc.jnu.edu.cn 公开栏目爬虫（暨大教务处）
- 只爬公开页面，遇登录系统(jw/jwxk/jwxt)自动跳过
- 礼貌延时，可限条数，断点不续（v1 简单版，重跑会覆盖 html/覆写 manifest，附件按文件名去重）
用法:
    python data_cleaning/scripts/crawl_jwc.py                       # 默认：学生办事指南，最多 20 条
    python data_cleaning/scripts/crawl_jwc.py --section 学生办事指南 --max 10
    python data_cleaning/scripts/crawl_jwc.py --section 教务管理 --max 30
"""
import os, sys, time, csv, re, argparse
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE = "https://jwc.jnu.edu.cn"
DELAY = 1.5
TIMEOUT = 15
HEADERS = {"User-Agent": "JNU-Training-Bot/0.1 (JNU student training project)"}
ATT_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".wps", ".zip", ".rar")
SKIP_HOSTS = ("jw.jnu", "jwxk", "jwxt", "thesis", "cet")

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))  # project/


def get(url, retries=1):
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.encoding = r.apparent_encoding
            return r
        except Exception as e:
            print(f"  [warn] 请求失败({i+1}): {type(e).__name__} {e}")
            time.sleep(2)
    return None


def is_internal(u): return "jwc.jnu.edu.cn" in u
def is_login(u): return any(s in u for s in SKIP_HOSTS)


def safe_name(s, n=60):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", s or "").strip()
    return (s[:n]).strip() or "untitled"


def article_id(url):
    nums = re.findall(r"\d+", urlparse(url).path)
    return nums[-1] if nums else None


def find_section_url_html(html, name, base):
    """纯函数：从主页 HTML 找栏目入口。
    优先返回 /list.htm（栏目列表页），避免误选主页 widget 里的详情页链接。"""
    soup = BeautifulSoup(html, "lxml")
    matches = []
    for a in soup.select("a[href]"):
        if name not in a.get_text():
            continue
        u = urljoin(base, a.get("href", ""))
        if is_internal(u) and not is_login(u):
            matches.append(u)
    list_urls = [u for u in matches if "/list.htm" in u]
    if list_urls:
        return list_urls[0]
    return matches[0] if matches else None


def find_section_url(name):
    print(f"[1/4] 主页找栏目: {name}")
    r = get(BASE + "/")
    if not r:
        sys.exit("[error] 主页打不开，检查网络/VPN")
    url = find_section_url_html(r.text, name, BASE)
    if not url:
        sys.exit(f"[error] 主页没找到 '{name}' 的列表页，改名或看导航")
    print(f"  入口: {url}")
    return url


DETAIL_RE = re.compile(r"/c\d+a\d+/page\.htm")


def parse_list_html(html, base_url, max_items=None):
    """纯函数：从列表页 HTML 抽 [(title, detail_url), ...]。不发请求，方便单测。"""
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.select("a[href]"):
        u = urljoin(base_url, a.get("href", ""))
        if not is_internal(u) or is_login(u) or u in seen:
            continue
        if not DETAIL_RE.search(u):
            continue
        title = " ".join(a.get_text().split())
        if not title or len(title) < 4:
            continue
        seen.add(u)
        items.append((title, u))
    if max_items:
        items = items[:max_items]
    return items


def parse_list(list_url, max_items):
    print("[2/4] 解析列表页...")
    r = get(list_url)
    if not r:
        return []
    items = parse_list_html(r.text, list_url, max_items)
    print(f"  抽出 {len(items)} 条（上限 {max_items}）")
    return items


def parse_detail_html(html, url):
    """纯函数：从详情页 HTML 抽 {url,title,text,date,attachments}。不发请求。"""
    soup = BeautifulSoup(html, "lxml")
    title = None
    for sel in ["h1", ".Article_Title", ".art-title", ".title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title:
        title = soup.title.get_text(strip=True) if soup.title else url
    body = None
    for sel in ["#vsb_content", ".v_news_content", ".wp_articlecontent", ".article-content", "article", ".content"]:
        el = soup.select_one(sel)
        if el:
            body = el
            break
    scope = body if body else soup
    text = scope.get_text("\n", strip=True)
    date = ""
    mu = re.search(r"/(20\d{2})/(\d{2})(\d{2})/", url)
    if mu:
        date = f"{mu.group(1)}-{mu.group(2)}-{mu.group(3)}"
    if not date:
        m = re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", text)
        if m:
            date = m.group(0)
    attachments = []
    for a in scope.select("a[href]"):
        u = urljoin(url, a.get("href", ""))
        if is_login(u):
            continue
        low = u.lower().split("?")[0]
        if low.endswith(ATT_EXT) or "/_upload/" in u:
            fname = a.get_text(strip=True) or os.path.basename(urlparse(u).path)
            attachments.append((fname, u))
    return {"url": url, "title": title, "text": text,
            "date": date, "attachments": attachments}


def parse_detail(url):
    r = get(url)
    if not r:
        return None
    item = parse_detail_html(r.text, url)
    item["html"] = r.text
    return item


def save_item(item, idx, out_root):
    aid = article_id(item["url"]) or f"{idx:03d}"
    html_dir = os.path.join(out_root, "html")
    att_dir = os.path.join(out_root, "attachments")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(att_dir, exist_ok=True)
    html_path = os.path.join(html_dir, f"{aid}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(item["html"])
    saved = []
    for fname, u in item["attachments"]:
        fname = safe_name(fname)
        apath = os.path.join(att_dir, fname)
        if os.path.exists(apath):
            saved.append(apath); continue
        print(f"    附件: {fname}")
        ar = get(u)
        if ar and ar.status_code == 200:
            with open(apath, "wb") as f:
                f.write(ar.content)
            saved.append(apath)
            time.sleep(DELAY)
    return aid, html_path, saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", default="学生办事指南", help="栏目名（主页导航里匹配）")
    ap.add_argument("--max", type=int, default=20, help="最多抓多少条")
    args = ap.parse_args()

    out_root = os.path.join(PROJECT_ROOT, "data_cleaning", "raw", safe_name(args.section))
    print("=" * 60)
    print(f"jwc 爬虫 | 栏目={args.section} | 上限={args.max} | 延时={DELAY}s")
    print(f"输出: {out_root}")
    print("=" * 60)

    rb = get(BASE + "/robots.txt")
    if rb and rb.status_code == 200 and re.search(r"Disallow:\s*/\s*$", rb.text):
        sys.exit("[abort] robots.txt 禁止爬根目录")

    section_url = find_section_url(args.section)
    time.sleep(DELAY)
    items = parse_list(section_url, args.max)
    if not items:
        print("[warn] 列表没抽出，可能 selector 要调（把一条详情页发我看看）"); return

    rows = []
    for i, (title, url) in enumerate(items, 1):
        print(f"[3/4] ({i}/{len(items)}) {title[:42]}")
        item = parse_detail(url)
        time.sleep(DELAY)
        if not item:
            continue
        aid, html_path, atts = save_item(item, i, out_root)
        rows.append({"id": aid, "title": item["title"], "date": item["date"],
                     "section": args.section, "url": item["url"],
                     "html_path": os.path.relpath(html_path, PROJECT_ROOT),
                     "attachments": ";".join(os.path.relpath(a, PROJECT_ROOT) for a in atts),
                     "attachments_count": len(atts)})

    manifest = os.path.join(out_root, "manifest.csv")
    with open(manifest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "date", "section", "url",
                                          "html_path", "attachments", "attachments_count"])
        w.writeheader(); w.writerows(rows)
    print(f"\n[4/4] 完成。抓 {len(rows)} 条，附件 {sum(r['attachments_count'] for r in rows)} 个")
    print(f"  manifest: {manifest}")
    print(f"  raw 目录: {out_root}")


if __name__ == "__main__":
    main()
