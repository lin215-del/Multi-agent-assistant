"""retriever.py 的测试。TDD：先写测试定义 parse_chunks + retriever_node 的期望行为。

真实 RAGFlow 调用是 IO 边界，用 monkeypatch 换成假函数。
字段名按真实返回（content / document_keyword / similarity）定型，靠手动冒烟验证。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.retriever import parse_chunks, retriever_node


# 真实 RAGFlow 返回的 chunk 字段子集（冒烟测抓到的）
_FAKE_CHUNK = {
    "content": "推免生条件...",
    "document_keyword": "通知-860093.md",
    "similarity": 0.31,
    "vector_similarity": 0.78,
    "positions": [[2, 1, 1, 1, 1]],
}
_FAKE_RESPONSE = {"code": 0, "data": {"chunks": [_FAKE_CHUNK, _FAKE_CHUNK]}}


# ---------- parse_chunks：把 RAGFlow 原始 JSON 抽成干净 chunks ----------
def test_parse_extracts_content_source_score():
    out = parse_chunks(_FAKE_RESPONSE)
    assert len(out) == 2
    c = out[0]
    assert c["content"] == "推免生条件..."
    assert c["source"] == "通知-860093.md"
    assert c["score"] == 0.31


def test_parse_handles_missing_fields():
    """chunk 没有 document_keyword / similarity 时给默认值，不崩。"""
    out = parse_chunks({"data": {"chunks": [{"content": "仅正文"}]}})
    assert out == [{"content": "仅正文", "source": "", "score": 0.0}]


def test_parse_empty_or_broken_response():
    """各种异常输入都返回空列表，不抛。"""
    assert parse_chunks(None) == []
    assert parse_chunks({}) == []
    assert parse_chunks({"data": None}) == []
    assert parse_chunks({"data": {}}) == []
    assert parse_chunks({"data": {"chunks": None}}) == []


# ---------- retriever_node：把捞到的 chunks 写进 State ----------
def test_retriever_node_writes_retrieved(monkeypatch):
    monkeypatch.setattr(
        "agents.retriever.retrieve_chunks",
        lambda q, did=None, top_k=6: parse_chunks(_FAKE_RESPONSE),
    )
    out = retriever_node({"query": "国家奖学金条件"})
    assert len(out["retrieved"]) == 2
    assert out["retrieved"][0]["source"] == "通知-860093.md"


def test_retriever_node_falls_back_to_question_when_no_query(monkeypatch):
    """query 没写（比如反思还没改写）时，退回用 question 检索。"""
    seen = {}
    def fake(q, did=None, top_k=6):
        seen["q"] = q
        return []
    monkeypatch.setattr("agents.retriever.retrieve_chunks", fake)
    retriever_node({"question": "奖学金条件", "query": None})
    assert seen["q"] == "奖学金条件"


# ---------- retrieve_chunks 参数：三个 PDF 对齐的环境变量默认值 ----------
def test_retrieve_chunks_passes_vector_similarity_weight(monkeypatch):
    """JSON payload 应包含 vector_similarity_weight 字段。"""
    payload = {}
    def fake_post(url, **kw):
        payload.update(kw.get("json", {}))
        import requests as _r
        resp = type("R", (), {"json": lambda self: {"data": {"chunks": []}}, "raise_for_status": lambda self: None})()
        return resp
    monkeypatch.setattr("agents.retriever.requests.post", fake_post)
    monkeypatch.setitem(os.environ, "RAGFLOW_BASE_URL", "http://localhost")
    monkeypatch.setitem(os.environ, "RAGFLOW_API_KEY", "sk-test")
    from agents.retriever import retrieve_chunks
    retrieve_chunks("测试")
    assert "vector_similarity_weight" in payload
    assert payload["vector_similarity_weight"] == 0.65


def test_retrieve_chunks_uses_env_similarity_threshold(monkeypatch):
    """设环境变量后 similarity_threshold 应从 env 读取。"""
    payload = {}
    def fake_post(url, **kw):
        payload.update(kw.get("json", {}))
        import requests as _r
        resp = type("R", (), {"json": lambda self: {"data": {"chunks": []}}, "raise_for_status": lambda self: None})()
        return resp
    monkeypatch.setattr("agents.retriever.requests.post", fake_post)
    monkeypatch.setitem(os.environ, "RAGFLOW_BASE_URL", "http://localhost")
    monkeypatch.setitem(os.environ, "RAGFLOW_API_KEY", "sk-test")
    monkeypatch.setitem(os.environ, "RAGFLOW_SIMILARITY_THRESHOLD", "0.5")
    from agents.retriever import retrieve_chunks
    retrieve_chunks("测试")
    assert payload["similarity_threshold"] == 0.5


def test_retrieve_chunks_uses_env_top_k(monkeypatch):
    """设 RAGFLOW_TOP_K 后 DEFAULT_TOP_K 应反映环境变量值。"""
    monkeypatch.setitem(os.environ, "RAGFLOW_TOP_K", "10")
    from importlib import reload
    import agents.retriever
    reload(agents.retriever)
    assert agents.retriever.DEFAULT_TOP_K == 10
    # 恢复默认值，避免污染后续测试
    monkeypatch.delenv("RAGFLOW_TOP_K")
    reload(agents.retriever)
