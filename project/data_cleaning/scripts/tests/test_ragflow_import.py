"""ragflow_import 包装函数测试。
TDD：先定义'清洗产物 → RAGFlow top-k 友好 md'的期望行为。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/

from ragflow_import import package_for_ragflow, table_to_markdown, load_env


# ---------- load_env：手动解析 → load_dotenv（去重 + 修 edge case）----------
def test_load_env_reads_from_os_environ(monkeypatch):
    """改用 load_dotenv 后，load_env 直接从 os.environ 取值。"""
    monkeypatch.setenv("RAGFLOW_API_KEY", "rk-abc=123")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://localhost:9380")
    key, base = load_env()
    assert key == "rk-abc=123"
    assert base == "http://localhost:9380"


def test_load_env_handles_equals_in_value(monkeypatch):
    """值里含等号（如 rk-abc=123）要完整保留。os.environ 原生支持。"""
    monkeypatch.setenv("RAGFLOW_API_KEY", "rk-abc=123")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://localhost")
    key, base = load_env()
    assert key == "rk-abc=123"


def test_load_dotenv_strips_inline_comments(tmp_path, monkeypatch):
    """load_dotenv 真把 .env 里的 inline 注释剥掉。测的是 load_dotenv 行为，
    不是 load_env——确保我们不依赖手动解析的残留逻辑。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RAGFLOW_API_KEY=rk-abc=123\n"
        "RAGFLOW_BASE_URL=http://localhost:9380  # 这是注释\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(env_file), override=True)
    assert os.environ["RAGFLOW_API_KEY"] == "rk-abc=123"
    assert os.environ["RAGFLOW_BASE_URL"] == "http://localhost:9380"


def test_load_env_falls_back_to_defaults(monkeypatch):
    """env var 没设时，base 退回到 DEFAULT_BASE。"""
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.setenv("RAGFLOW_API_KEY", "k")
    key, base = load_env()
    assert key == "k"
    assert base == "http://localhost"


def test_table_to_markdown_basic():
    table = {"caption": "学分表", "headers": ["类别", "学分"], "rows": [{"类别": "A1", "学分": "2"}], "quality": "ok"}
    md = table_to_markdown(table)
    assert "| 类别 | 学分 |" in md
    assert "| ---" in md
    assert "| A1 | 2 |" in md


def test_package_includes_title_source_body_and_appendices():
    md = "正文开头 [表1] 中间 [图1] 结尾"
    tables = [{"caption": "学分表", "headers": ["类别", "学分"], "rows": [{"类别": "A1", "学分": "2"}], "quality": "ok"}]
    figures = [{"n": 1, "path": "images/x.jpg", "caption": "登录界面", "context": "..."}]
    out = package_for_ragflow("创新学分办法", md, tables, figures, source_url="https://jwc.jnu.edu.cn/x")
    # 标题 + 来源
    assert "# 创新学分办法" in out
    assert "https://jwc.jnu.edu.cn/x" in out
    # 正文保留（含占位）
    assert "正文开头" in out
    assert "结尾" in out
    # 表格附录：caption + markdown 表
    assert "学分表" in out
    assert "| 类别 | 学分 |" in out
    assert "| A1 | 2 |" in out
    # 图说明附录：序号 + caption
    assert "[图1]" in out
    assert "登录界面" in out


def test_package_without_tables_or_figures_has_no_appendix():
    out = package_for_ragflow("纯文本文档", "只有正文", [], [], source_url="")
    assert "只有正文" in out
    assert "表格内容" not in out
    assert "图表说明" not in out
