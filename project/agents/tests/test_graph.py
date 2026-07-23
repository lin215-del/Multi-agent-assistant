"""graph.py 完整版的测试：验条件路由 + 反思循环 + 拒答分支走对路。

用假节点（不连真 LLM/RAGFlow），靠假 router/reflection 驱动各种分支。
finalize/reject/retry 用真节点（纯函数，无 IO）。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.graph import build_graph, MAX_ROUNDS


def _make_app(route, reflection_seq, call_log):
    """造一组假节点 + 编译图。route 控制路由，reflection_seq 控制每次反思的 ok。"""
    refl_i = [0]

    def router(state):
        call_log.append("router")
        return {"route": route, "query": state["question"]}

    def tool(state):
        call_log.append("tool")
        return {"tool_output": "TOOL"}

    def retriever(state):
        call_log.append("retriever")
        return {"retrieved": [{"content": "c", "source": "s.md", "score": 0.85}]}

    def analyzer(state):
        call_log.append("analyzer")
        return {"analysis": "ANS"}

    def reflection(state):
        call_log.append("reflection")
        i = refl_i[0]
        refl_i[0] += 1
        if i < len(reflection_seq):
            ok = reflection_seq[i]
        elif reflection_seq:
            ok = reflection_seq[-1]
        else:
            ok = True
        result = {"ok": ok, "reason": "r"}
        if not ok:
            result["rewritten_query"] = state["question"] + " 改写"
        return {"reflection": result}

    return build_graph(router=router, tool=tool, retriever=retriever,
                       analyzer=analyzer, reflection=reflection)


# ---------- 各路由分支 ----------
def test_retrieve_path_passes():
    log = []
    app = _make_app("retrieve", [True], log)
    result = app.invoke({"question": "q"})
    assert result["final"] == "ANS"
    assert "tool" not in log          # retrieve 不调工具
    assert log.count("analyzer") == 1


def test_reject_path_skips_work_nodes():
    log = []
    app = _make_app("reject", [], log)
    result = app.invoke({"question": "q"})
    assert "范围" in result["final"]   # 礼貌拒答
    assert "retriever" not in log
    assert "analyzer" not in log
    assert "tool" not in log


def test_tool_only_path_skips_retriever_and_reflection():
    """纯工具计算：不检索、不反思，工具算完直接收尾。"""
    log = []
    app = _make_app("tool", [True], log)
    result = app.invoke({"question": "q"})
    assert "tool" in log
    assert "retriever" not in log
    assert "reflection" not in log
    assert result["final"] == "ANS"


def test_both_path_runs_tool_then_retriever():
    log = []
    app = _make_app("both", [True], log)
    app.invoke({"question": "q"})
    assert "tool" in log
    assert "retriever" in log
    assert log.index("tool") < log.index("retriever")  # 工具在前


# ---------- 反思循环 ----------
def test_reflection_retry_then_pass():
    """第一次不通过、第二次通过 → 每次重试重新检索 + 重新分析。"""
    log = []
    app = _make_app("retrieve", [False, True], log)
    result = app.invoke({"question": "q"})
    assert log.count("retriever") == 2  # 初次 + 重试各一次检索
    assert log.count("analyzer") == 2
    assert log.count("reflection") == 2
    assert result["final"] == "ANS"


def test_retry_rewrites_query(monkeypatch):
    """retry_node 从 reflection 取 rewritten_query 写进 query，并清空 retrieved
    触发重新检索。"""
    from agents.graph import retry_node
    state = {
        "question": "原始问题",
        "query": "原始检索词",
        "retrieved": [{"content": "旧资料"}],
        "reflection": {"ok": False, "reason": "不够好", "rewritten_query": "改写后的检索词"},
        "round": 0,
    }
    out = retry_node(state)
    assert out["query"] == "改写后的检索词"
    assert out["retrieved"] == []  # 清空旧资料，触发重新检索
    assert out["round"] == 1


def test_max_rounds_gives_up():
    """一直不通过 → 分析跑 MAX_ROUNDS+1 次后坦白收尾。"""
    log = []
    app = _make_app("retrieve", [False, False, False], log)
    result = app.invoke({"question": "q"})
    assert log.count("analyzer") == MAX_ROUNDS + 1
    assert log.count("retriever") == MAX_ROUNDS + 1  # 每次分析前都重新检索
    assert "把握不大" in result["final"]


# ---------- 检索后相关度闸门 ----------
def test_retriever_low_score_rejects():
    """纯检索路径 score 不够阈值 → 直接拒答，不进 analyzer。"""
    log = []
    def retriever(state):
        log.append("retriever")
        return {"retrieved": [{"content": "c", "source": "s.md", "score": 0.3}]}
    app = build_graph(
        router=lambda s: (log.append("router"), {"route": "retrieve", "query": s["question"]})[1],
        retriever=retriever,
        analyzer=lambda s: (log.append("analyzer"), {"analysis": "ANS"})[1],
        reflection=lambda s: (log.append("reflection"), {"reflection": {"ok": True, "reason": "ok"}})[1],
    )
    result = app.invoke({"question": "q"})
    assert "范围" in result["final"] or "超出" in result["final"]
    assert "analyzer" not in log


def test_retriever_low_score_both_still_analyzes():
    """both 路径 score 不够但有 tool_output → 仍进 analyzer（不浪费工具计算结果）。"""
    log = []
    def retriever(state):
        log.append("retriever")
        return {"retrieved": [{"content": "c", "source": "s.md", "score": 0.3}]}
    app = build_graph(
        router=lambda s: (log.append("router"), {"route": "both", "query": s["question"]})[1],
        tool=lambda s: (log.append("tool"), {"tool_output": "TOOL"})[1],
        retriever=retriever,
        analyzer=lambda s: (log.append("analyzer"), {"analysis": "ANS"})[1],
        reflection=lambda s: (log.append("reflection"), {"reflection": {"ok": True, "reason": "ok"}})[1],
    )
    result = app.invoke({"question": "q"})
    assert "analyzer" in log
    assert result["final"] == "ANS"
