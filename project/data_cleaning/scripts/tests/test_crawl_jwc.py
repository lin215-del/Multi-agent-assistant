"""crawl_jwc.py 的测试。TDD：先写测试定义期望行为，再改实现到全绿。"""
import os, sys, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 把 scripts/ 加进 path，好 import crawl_jwc
FIX = os.path.join(HERE, "fixtures")

from crawl_jwc import (is_login, is_internal, safe_name, article_id,
                       parse_list_html, parse_detail_html, find_section_url_html)

LIST_URL = "https://jwc.jnu.edu.cn/xsbszn/list.htm"
DETAIL_URL = "https://jwc.jnu.edu.cn/2019/0419/c11805a310286/page.htm"


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


# ---------- 登录系统识别 ----------
def test_is_login_catches_login_systems():
    assert is_login("https://jw.jnu.edu.cn/")
    assert is_login("https://jwxk.jnu.edu.cn/")
    assert is_login("https://jwxt.jnu.edu.cn/")


def test_is_login_not_flag_public():
    assert not is_login("https://jwc.jnu.edu.cn/xsbszn/list.htm")


def test_is_internal():
    assert is_internal("https://jwc.jnu.edu.cn/anything")
    assert not is_internal("https://example.com/")


# ---------- safe_name ----------
def test_safe_name_strips_path_chars():
    out = safe_name("a/b\\c?d*e")
    for ch in ["/", "\\", "?", "*"]:
        assert ch not in out


def test_safe_name_empty():
    assert safe_name("") == "untitled"


# ---------- article_id ----------
def test_article_id_from_sudy_url():
    url = "https://jwc.jnu.edu.cn/2021/0317/c11805a602515/page.htm"
    assert article_id(url) == "602515"


# ---------- find_section_url_html（栏目入口要选 list 页，别误选 detail 页）----------
def test_find_section_url_prefers_list_page():
    """主页里"通知"既出现在 widget（详情页链接）又出现在导航（list 页），
    必须返回 list 页，不能返回详情页。"""
    main_html = """<html><body>
      <div class="widget"><a href="/2026/0717/c6765a860438/page.htm">关于某事的通知</a></div>
      <nav><a href="/6765/list.htm">通知</a></nav>
    </body></html>"""
    url = find_section_url_html(main_html, "通知", base="https://jwc.jnu.edu.cn")
    assert url == "https://jwc.jnu.edu.cn/6765/list.htm"


# ---------- parse_list_html（核心）----------
def test_parse_list_html_extracts_items():
    items = parse_list_html(_read("xsbszn_list.html"), LIST_URL)
    assert len(items) == 9


def test_parse_list_html_urls_are_detail_pages():
    items = parse_list_html(_read("xsbszn_list.html"), LIST_URL)
    for title, url in items:
        assert re.search(r"/c\d+a\d+/page\.htm", url), f"不是详情页 URL: {url}"


def test_parse_list_html_includes_known_titles():
    items = parse_list_html(_read("xsbszn_list.html"), LIST_URL)
    titles = " ".join(t for t, _ in items)
    assert "选课" in titles
    assert "成绩单" in titles


# ---------- parse_detail_html ----------
def test_parse_detail_html_title_and_text():
    d = parse_detail_html(_read("detail_xk.html"), DETAIL_URL)
    assert "选课" in d["title"]
    assert len(d["text"]) > 100


def test_parse_detail_html_date_from_url():
    d = parse_detail_html(_read("detail_xk.html"), DETAIL_URL)
    assert d["date"] == "2019-04-19"


def test_parse_detail_html_attachments_is_list():
    d = parse_detail_html(_read("detail_xk.html"), DETAIL_URL)
    assert isinstance(d["attachments"], list)
