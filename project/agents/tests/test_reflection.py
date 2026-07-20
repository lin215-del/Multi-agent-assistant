"""reflection.py 的测试。TDD：parse_check + build_check_prompt + reflection_node。

LLM 质检是 IO 边界，用 monkeypatch；解析和 prompt 组装是纯函数测全。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.reflection import parse_check, build_check_prompt, reflection_node


# ---------- parse_check：把 LLM 质检输出解析成 {ok, reason} ----------
def test_parse_ok_true():
    r = parse_check('{"ok": true, "reason": "有引用来源"}')
    assert r["ok"] is True
    assert r["reason"] == "有引用来源"


def test_parse_ok_false():
    r = parse_check('{"ok": false, "reason": "没标注来源"}')
    assert r["ok"] is False
    assert r["reason"] == "没标注来源"


def test_parse_ok_as_string():
    """LLM 可能把 true 写成字符串。"""
    r = parse_check('{"ok": "true", "reason": "x"}')
    assert r["ok"] is True


def test_parse_in_code_fence():
    raw = '```json\n{"ok": true, "reason": "通过"}\n```'
    assert parse_check(raw)["ok"] is True


def test_parse_surrounding_text():
    raw = '判断结果：{"ok": false, "reason": "跑题"}，就这样'
    r = parse_check(raw)
    assert r["ok"] is False
    assert r["reason"] == "跑题"


def test_parse_empty_or_garbage_defaults_pass():
    """解析不出来默认通过（不因解析故障卡住流程）。"""
    assert parse_check("")["ok"] is True
    assert parse_check("乱七八糟")["ok"] is True
    assert parse_check(None)["ok"] is True


def test_parse_missing_ok_defaults_pass():
    """JSON 里没 ok 字段，默认通过。"""
    assert parse_check('{"reason": "x"}')["ok"] is True


# ---------- build_check_prompt ----------
def test_prompt_includes_question_analysis_and_sources():
    chunks = [{"content": "资料A", "source": "通知-1.md"}, {"content": "资料B", "source": "办法-2.md"}]
    p = build_check_prompt("奖学金条件", chunks, "这是草稿答案")
    assert "奖学金条件" in p
    assert "这是草稿答案" in p
    assert "通知-1.md" in p
    assert "办法-2.md" in p


def test_prompt_lists_criteria():
    p = build_check_prompt("问", [], "答")
    assert "来源" in p
    assert "跑题" in p


# ---------- reflection_node ----------
def test_reflection_node_writes_parsed_result(monkeypatch):
    monkeypatch.setattr("agents.reflection.check_with_llm",
                        lambda q, r, a: '{"ok": false, "reason": "没引用"}')
    out = reflection_node({"question": "问", "retrieved": [], "analysis": "答"})
    assert out["reflection"]["ok"] is False
    assert out["reflection"]["reason"] == "没引用"


def test_reflection_node_passes_state_fields(monkeypatch):
    captured = {}

    def fake(q, r, a):
        captured["q"], captured["r"], captured["a"] = q, r, a
        return '{"ok": true, "reason": "ok"}'

    monkeypatch.setattr("agents.reflection.check_with_llm", fake)
    reflection_node({"question": "Q", "retrieved": [{"content": "c", "source": "s.md"}], "analysis": "A"})
    assert captured["q"] == "Q"
    assert captured["a"] == "A"
    assert captured["r"][0]["source"] == "s.md"
