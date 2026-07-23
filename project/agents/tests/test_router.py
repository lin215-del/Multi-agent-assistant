"""router.py 的测试。TDD：先写测试定义 parse_route + router_node 的期望行为。

LLM 调用是 IO 边界，这里用 monkeypatch 换成假函数，不真连 SiliconFlow；
真实联通性放最后手动冒烟测一次。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.router import parse_route, router_node


# ---------- parse_route：把 LLM 文本解析成合法 Route ----------
def test_parse_exact_words():
    assert parse_route("retrieve") == "retrieve"
    assert parse_route("tool") == "tool"
    assert parse_route("both") == "both"
    assert parse_route("reject") == "reject"


def test_parse_strips_whitespace_and_case():
    assert parse_route("  Retrieve\n") == "retrieve"
    assert parse_route("REJECT") == "reject"
    assert parse_route("\tboth ") == "both"


def test_parse_extracts_word_from_sentence():
    """LLM 有时不乖乖只吐类别名，会带前缀或解释；要能从中抠出类别词。"""
    assert parse_route("类别：retrieve") == "retrieve"
    assert parse_route("我认为走 tool") == "tool"
    assert parse_route("answer: both") == "both"


def test_parse_empty_or_garbage_defaults_retrieve():
    """解析不出来兜底 retrieve（交给检索+反思兜底，不轻易拒答）。"""
    assert parse_route("") == "retrieve"
    assert parse_route("乱七八糟") == "retrieve"
    assert parse_route("不知道") == "retrieve"


def test_parse_does_not_match_substring():
    """'reject' 里不含 'tool' 子串——但 LLM 输出 'reject because tool' 时
    'tool' 也在字符串里。要按 LLM 真正意图（优先级或最早出现）判，不能子串误判。
    具体：'reject' 出现在文本更早位置时，应判 reject 而非 tool。"""
    assert parse_route("reject because tool not available") == "reject"
    assert parse_route("类别：reject，原因：不是学生事务") == "reject"
    assert parse_route("this is a tool question") == "tool"
    assert parse_route("need both retrieve and tool") == "both"


# ---------- router_node：把 LLM 分类结果写进 State ----------
def test_router_node_writes_route_and_query(monkeypatch):
    """读 question → 调 LLM → 把 route + query 写回工作台。"""
    monkeypatch.setattr("agents.router.classify_with_llm", lambda q: "retrieve")
    out = router_node({"question": "国家奖学金申请条件"})
    assert out["route"] == "retrieve"
    assert out["query"] == "国家奖学金申请条件"


def test_router_node_fallback_on_garbage_llm_output(monkeypatch):
    monkeypatch.setattr("agents.router.classify_with_llm", lambda q: "一堆乱码")
    out = router_node({"question": "随便问"})
    assert out["route"] == "retrieve"
