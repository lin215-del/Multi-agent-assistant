"""analyzer.py 的测试。TDD：先写测试定义 build_prompt + analyzer_node 的期望行为。

真实 LLM 调用是 IO 边界，用 monkeypatch 换成假函数。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.analyzer import build_prompt, analyzer_node


# ---------- build_prompt：把问题/资料/工具结果组装成 LLM prompt ----------
def test_prompt_includes_question():
    p = build_prompt("奖学金条件", [])
    assert "奖学金条件" in p


def test_prompt_includes_each_chunk_content_and_source():
    chunks = [
        {"content": "推免生要 GPA3.5 以上", "source": "通知-A.md", "score": 0.3},
        {"content": "创新学分需 4 分", "source": "办法-B.md", "score": 0.25},
    ]
    p = build_prompt("问", chunks)
    assert "推免生要 GPA3.5 以上" in p
    assert "通知-A.md" in p
    assert "创新学分需 4 分" in p
    assert "办法-B.md" in p


def test_prompt_includes_tool_output_when_present():
    p = build_prompt("问", [], tool_output="加权平均分=85.2")
    assert "加权平均分=85.2" in p


def test_prompt_omits_tool_section_when_absent():
    """没工具结果时，prompt 里不该出现'工具计算结果'这一节。"""
    p = build_prompt("问", [])
    assert "工具计算结果" not in p


def test_prompt_forbids_fabrication_and_requires_citation():
    """prompt 必须含'不要编造'+'来源'要求（反思 agent 的质检基础）。"""
    p = build_prompt("问", [])
    assert "不要编造" in p
    assert "来源" in p


# ---------- analyzer_node：把草稿写进 State ----------
def test_analyzer_node_writes_analysis(monkeypatch):
    monkeypatch.setattr("agents.analyzer.generate_with_llm", lambda q, c, t=None: "这是草稿答案")
    out = analyzer_node({"question": "奖学金条件", "retrieved": [{"content": "x", "source": "s.md"}]})
    assert out["analysis"] == "这是草稿答案"


def test_analyzer_node_passes_state_fields_to_llm(monkeypatch):
    """确认节点正确抽出 question/retrieved/tool_output 传给 LLM。"""
    captured = {}
    def fake(q, c, t=None):
        captured["q"], captured["c"], captured["t"] = q, c, t
        return "草稿"
    monkeypatch.setattr("agents.analyzer.generate_with_llm", fake)
    analyzer_node({
        "question": "我的GPA够吗",
        "retrieved": [{"content": "条件...", "source": "a.md"}],
        "tool_output": {"gpa": 3.6},
    })
    assert captured["q"] == "我的GPA够吗"
    assert captured["c"][0]["source"] == "a.md"
    assert captured["t"] == {"gpa": 3.6}
