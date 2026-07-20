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
        lambda q, did=None, top_k=8: parse_chunks(_FAKE_RESPONSE),
    )
    out = retriever_node({"query": "国家奖学金条件"})
    assert len(out["retrieved"]) == 2
    assert out["retrieved"][0]["source"] == "通知-860093.md"


def test_retriever_node_falls_back_to_question_when_no_query(monkeypatch):
    """query 没写（比如反思还没改写）时，退回用 question 检索。"""
    seen = {}
    def fake(q, did=None, top_k=8):
        seen["q"] = q
        return []
    monkeypatch.setattr("agents.retriever.retrieve_chunks", fake)
    retriever_node({"question": "奖学金条件", "query": None})
    assert seen["q"] == "奖学金条件"
