"""LangGraph 编排的薄封装。

启动时 `compile_app()` 调一次 `agents.graph.build_graph()` 把图编译好塞到 `_APP`；
之后每次 `ask(question)` 复用这个编译图（无状态，可安全并发）。

state 形状按 agents/state.py AgentState 补齐所有字段，否则 LangGraph 报 missing keys。
异常兜底：invoke 抛异常时返回 `{answer: '服务暂时不可用…', error: ...}`，
不让上游 FastAPI 500 把前端搞白屏。
"""
import time
from typing import Any

from agents.graph import build_graph

_APP: Any = None


def compile_app() -> None:
    """编译 LangGraph 图，进程启动时调一次。"""
    global _APP
    _APP = build_graph()


def ask(question: str) -> dict:
    """跑一遍图，返回前端需要的精简 trace。

    返回字段：
      answer        — final 答案（reject 时直接是拒答文案）
      route         — 调度决策（retrieve/tool/both/reject/None）
      matches       — 检索 chunks（[{content, source, score}]，前端自己 classify 加 type）
      tool_output   — 工具结果（str 或 None）
      analysis      — 草稿（反思重试前的版本，前端历史页可看）
      reflection    — 质检结果（{ok, reason} 或 None）
      round         — 反思循环轮数
      latency_ms    — 本次总耗时
      error         — invoke 异常时的错误信息（成功时为 None）
    """
    initial = {
        "question": question,
        "route": None,
        "query": None,
        "retrieved": [],
        "tool_output": None,
        "analysis": "",
        "reflection": None,
        "final": "",
        "round": 0,
        "node_trace": [],
    }
    t0 = time.time()
    try:
        result = _APP.invoke(initial)
        elapsed = int((time.time() - t0) * 1000)
        return _trace_from_result(result, elapsed)
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        return {
            "answer": f"服务暂时不可用：{exc.__class__.__name__}。请稍后再试或联系管理员。",
            "route": None,
            "matches": [],
            "tool_output": None,
            "analysis": "",
            "reflection": None,
            "round": 0,
            "latency_ms": elapsed,
            "error": str(exc),
            "node_trace": [],
        }


def _trace_from_result(result: dict, elapsed_ms: int) -> dict:
    """把 LangGraph 完整 state 抽成前端 trace。"""
    return {
        "answer": result.get("final") or "",
        "route": result.get("route"),
        "matches": result.get("retrieved") or [],
        "tool_output": result.get("tool_output"),
        "analysis": result.get("analysis") or "",
        "reflection": result.get("reflection"),
        "round": int(result.get("round") or 0),
        "latency_ms": elapsed_ms,
        "error": None,
        "node_trace": result.get("node_trace") or [],
    }