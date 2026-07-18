"""clean_html.py 的测试。TDD：先写测试定义期望行为，再实现到全绿。"""
import os, sys, csv

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/ 加进 path
FIX = os.path.join(HERE, "fixtures")

from clean_html import extract_body, clean_markdown, clean_page, clean_directory


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


DETAIL = _read("detail_xk.html")  # 学生选课流程


# ---------- extract_body ----------
def test_extract_body_finds_content():
    body = extract_body(DETAIL)
    assert body is not None
    assert len(body.get_text(strip=True)) > 50


# ---------- clean_markdown ----------
def test_clean_markdown_returns_body_content():
    md = clean_markdown(DETAIL)
    assert len(md) > 50


def test_clean_removes_nav_and_footer_junk():
    """5段式之'删'：当前位置/页脚/导航这类干扰 RAG 的无用信息要去掉"""
    html = """<html><body>
      <div class="position">当前位置：首页 &gt; 学生办事指南</div>
      <div class="wp_articlecontent"><p>这是真正的正文内容。</p></div>
      <div class="footer">版权所有 暨南大学教务处</div>
    </body></html>"""
    md = clean_markdown(html)
    assert "当前位置" not in md
    assert "版权所有" not in md
    assert "这是真正的正文内容" in md


def test_clean_merges_br_fragmented_lines():
    """碎行合并：被 <br> 切断的 '行政办公楼 / 827 / 扫码缴费' 要合到一行"""
    html = """<html><body><div class="wp_articlecontent">
      <p>到石牌校区行政办公楼<br>827<br>扫码缴费</p>
    </div></body></html>"""
    md = clean_markdown(html)
    lines = [l for l in md.split("\n") if l.strip()]
    assert any("行政办公楼" in l and "827" in l and "扫码缴费" in l for l in lines), \
        f"碎行没合并:\n{md}"


# ---------- clean_page ----------
def test_clean_page_title_and_markdown():
    result = clean_page(DETAIL)
    assert "选课" in result["title"]
    assert len(result["markdown"]) > 50


def test_clean_page_includes_source_url():
    """可溯源：清洗结果要带上来源 URL"""
    url = "https://jwc.jnu.edu.cn/2019/0419/c11805a310286/page.htm"
    result = clean_page(DETAIL, source_url=url)
    assert result["source_url"] == url


def test_clean_page_char_count_matches():
    result = clean_page(DETAIL)
    assert result["char_count"] == len(result["markdown"])


# ---------- clean_directory（批量：读 raw → 写 cleaned + 索引）----------
def test_clean_directory_writes_markdown_and_index(tmp_path):
    raw = tmp_path / "raw"
    html_dir = raw / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "123.html").write_text(
        "<html><head><title>测试标题</title></head><body>"
        "<h1>测试标题</h1>"
        '<div class="wp_articlecontent"><p>这是正文内容，足够长的正文。</p></div>'
        "</body></html>", encoding="utf-8")
    with open(raw / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "date", "section", "url", "html_path", "attachments", "attachments_count"])
        w.writerow(["123", "测试标题", "2021-03-17", "学生办事指南",
                    "https://jwc.jnu.edu.cn/2021/0317/c11805a123/page.htm",
                    "raw/html/123.html", "", 0])
    out = tmp_path / "cleaned"
    results = clean_directory(str(raw), str(out))
    assert (out / "123.md").exists()
    md = (out / "123.md").read_text(encoding="utf-8")
    assert "这是正文内容" in md
    idx = (out / "cleaned_index.csv").read_text(encoding="utf-8-sig")
    assert "c11805a123/page.htm" in idx  # 溯源 URL 进了索引
    assert len(results) == 1
