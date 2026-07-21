"""graph_service.py 的测试。TDD：用 monkeypatch 把 build_graph 替换成假图，
不真连 RAGFlow/SiliconFlow；只验 invoke 契约（输入 state 形状 + 输出解构 + 异常兜底）。

真联通性冒烟放 D2 用 FastAPI TestClient + 真 .env 跑一次。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

from web.backend import graph_service


def _patch_graph(monkeypatch, fake_invoke):
    """把 graph_service 内部的 _APP.invoke 替换成假函数（不真编译图）。"""
    monkeypatch.setattr(graph_service, "_APP", type("F", (), {"invoke": staticmethod(fake_invoke)})())


def test_ask_returns_full_trace_for_retrieve_route(monkeypatch):
    """retrieve 路径：invoke 返回 final + route + retrieved + reflection。"""
    fake_result = {
        "final": "国奖申请条件如下…（来源：通知-857469）",
        "route": "retrieve",
        "retrieved": [{"content": "国奖…", "source": "通知-857469", "score": 0.85}],
        "tool_output": None,
        "analysis": "草稿…",
        "reflection": {"ok": True, "reason": "引用了来源"},
        "round": 0,
    }
    _patch_graph(monkeypatch, lambda state, **kw: fake_result)

    out = graph_service.ask("国奖申请条件是什么")
    assert out["answer"] == "国奖申请条件如下…（来源：通知-857469）"
    assert out["route"] == "retrieve"
    assert len(out["matches"]) == 1
    assert out["matches"][0]["source"] == "通知-857469"
    assert out["reflection"] == {"ok": True, "reason": "引用了来源"}
    assert out["latency_ms"] >= 0


def test_ask_returns_reject_answer_for_reject_route(monkeypatch):
    """reject 路径：final 直接是拒答文案。"""
    fake_result = {
        "final": "这个问题超出了我的范围…",
        "route": "reject",
        "retrieved": [],
        "tool_output": None,
        "analysis": "",
        "reflection": None,
        "round": 0,
    }
    _patch_graph(monkeypatch, lambda state, **kw: fake_result)

    out = graph_service.ask("今天天气")
    assert out["route"] == "reject"
    assert "超出了我的范围" in out["answer"]
    assert out["matches"] == []


def test_ask_swallows_invoke_exception(monkeypatch):
    """invoke 抛异常时，兜底返回 '服务暂时不可用' + 错误信息，不抛给前端。"""
    def boom(state, **kw):
        raise RuntimeError("RAGFlow down")
    _patch_graph(monkeypatch, boom)

    out = graph_service.ask("随便问")
    assert "暂时不可用" in out["answer"]
    assert "RAGFlow down" in out["error"]
    assert out["route"] is None
    assert out["matches"] == []


def test_ask_initializes_full_state_shape(monkeypatch):
    """传给 invoke 的 state 必须满足 AgentState 所有字段（否则 LangGraph 报 missing keys）。"""
    captured = {}

    def spy(state, **kw):
        captured.update(state)
        return {"final": "x", "route": "retrieve", "retrieved": [], "tool_output": None,
                "analysis": "", "reflection": None, "round": 0}
    _patch_graph(monkeypatch, spy)

    graph_service.ask("hello")
    assert captured["question"] == "hello"
    assert captured["retrieved"] == []
    assert captured["analysis"] == ""
    assert captured["final"] == ""
    assert captured["round"] == 0


def test_ask_returns_trace_with_tool_output_for_both_route(monkeypatch):
    """both 路径：tool_output 不为空，matches 同时有检索结果。"""
    fake_result = {
        "final": "GPA 3.6 加权平均分 87.2，够国奖线（85）。",
        "route": "both",
        "retrieved": [{"content": "国奖线 85", "source": "通知-xxx", "score": 0.9}],
        "tool_output": "加权平均分：87.2（共 5 门课，16 学分）",
        "analysis": "草稿",
        "reflection": {"ok": True, "reason": "ok"},
        "round": 0,
    }
    _patch_graph(monkeypatch, lambda state, **kw: fake_result)

    out = graph_service.ask("GPA 3.6 够国奖线吗")
    assert out["route"] == "both"
    assert out["tool_output"] == "加权平均分：87.2（共 5 门课，16 学分）"
    assert len(out["matches"]) == 1