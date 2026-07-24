"""LangGraph orchestration — 11 agent nodes, conditional routing, retry loop.

Each node is a thin wrapper that delegates to a dedicated agent module under
agents_fastapi/.  The graph itself carries no business logic.
"""

from __future__ import annotations

import time
import uuid
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import answer as _answer
from . import health as _health
from . import intent as _intent
from . import quality as _quality
from . import reflection as _reflection
from . import retriever as _retriever
from . import rewrite as _rewrite
from . import router as _router
from . import study_place as _study_place
from . import tools as _tools
from .state import AgentState
from .tracing import trace

MAX_RETRIEVAL_RETRIES = 2


class GraphState(TypedDict):
    state: AgentState


class StudentAssistantGraph:
    """LangGraph multi-agent orchestration for the Jinan University student assistant."""

    def __init__(self):
        graph = StateGraph(GraphState)
        graph.add_node("intent_agent", self.intent_agent)
        graph.add_node("router_agent", self.router_agent)
        graph.add_node("reject_agent", self.reject_agent)
        graph.add_node("tool_agent", self.tool_agent)
        graph.add_node("health_agent", self.health_agent)
        graph.add_node("study_place_agent", self.study_place_agent)
        graph.add_node("retriever_agent", self.retriever_agent)
        graph.add_node("quality_agent", self.quality_agent)
        graph.add_node("rewrite_agent", self.rewrite_agent)
        graph.add_node("reflection_agent", self.reflection_agent)
        graph.add_node("answer_agent", self.answer_agent)

        graph.add_edge(START, "intent_agent")
        graph.add_edge("intent_agent", "router_agent")
        graph.add_conditional_edges(
            "router_agent",
            self.route_after_router,
            {
                "reject": "reject_agent",
                "tool": "tool_agent",
                "health": "health_agent",
                "study": "study_place_agent",
                "retrieve": "retriever_agent",
            },
        )
        graph.add_edge("reject_agent", "reflection_agent")
        graph.add_edge("tool_agent", "reflection_agent")
        graph.add_edge("health_agent", "retriever_agent")
        graph.add_conditional_edges(
            "study_place_agent",
            lambda v: "quality" if v["state"].answer else "retrieve",
            {"quality": "quality_agent", "retrieve": "retriever_agent"},
        )
        graph.add_edge("retriever_agent", "quality_agent")
        graph.add_conditional_edges(
            "quality_agent",
            self.route_after_quality,
            {
                "pass": "reflection_agent",
                "retry": "rewrite_agent",
                "reject": "reflection_agent",
            },
        )
        graph.add_edge("rewrite_agent", "retriever_agent")
        graph.add_edge("reflection_agent", "answer_agent")
        graph.add_edge("answer_agent", END)

        self.compiled = graph.compile(checkpointer=MemorySaver())

    def run(self, state: AgentState, thread_id: str | None = None) -> AgentState:
        config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
        return self.compiled.invoke({"state": state}, config=config)["state"]

    # ── nodes ──────────────────────────────────────────────────────────

    def intent_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        started = time.perf_counter()
        result = _intent.expand_intent(state)
        state.retrieval_query = state.expanded_question
        state.max_retries = MAX_RETRIEVAL_RETRIES
        state.trace.append(trace("intent_agent", result["status"], result["detail"],
                                 state.expanded_question, start=started))
        return value

    def router_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        started = time.perf_counter()
        result = _router.route_question(state)
        state.trace.append(trace("router_agent", result["status"], result["detail"],
                                 state.expanded_question, start=started))
        return value

    def route_after_router(self, value: GraphState) -> str:
        state = value["state"]
        if state.route == "retrieve" and _router.is_study_place_intent(state.expanded_question):
            return "study"
        return state.route

    def reject_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        state.ok = False
        state.answer = "这个问题涉及隐私、安全或未公开信息，我不能提供相关内容。"
        state.trace.append(trace("reject_agent", "rejected", "安全规则拒答", state.expanded_question))
        return value

    def tool_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _tools.calculate_gpa(state)
        state.trace.append(trace("tool_agent", result["status"], result["detail"], state.expanded_question))
        return value

    def health_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _health.health_answer(state)
        state.trace.append(trace("health_agent", result["status"], result["detail"], state.expanded_question))
        return value

    def study_place_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _study_place.local_study_answer(state)
        status = "success" if result["status"] == "success" else "error"
        state.trace.append(trace("study_place_agent", status, result["detail"],
                                 state.expanded_question, state.similarity))
        return value

    def retriever_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        started = time.perf_counter()
        try:
            state.retrieval_query = state.retrieval_query or state.expanded_question
            retrieve_result = _retriever.ragflow_retrieve(state)
            state.trace.append(trace(
                "retriever_agent", retrieve_result["status"],
                f"第 {state.retry_count + 1} 轮{retrieve_result['detail']}",
                state.retrieval_query, retrieve_result.get("top_score"), started,
            ))
            if state.route != "health":
                _retriever.make_grounded_answer(state)
            elif state.retrieved:
                top = state.retrieved[0]
                state.document_name = str(top.get("document_keyword") or top.get("document_name") or "")
                content = str(top.get("content") or top.get("content_with_weight") or "")
                state.source_url = _retriever.extract_source_url(content)
                state.similarity = float(top.get("similarity") or 0)
                state.matches = [{
                    "document_name": state.document_name,
                    "similarity": state.similarity,
                    "snippet": content[:260],
                }]
        except Exception as exc:
            state.retrieved = []
            state.trace.append(trace("retriever_agent", "error", str(exc)[:220],
                                     state.retrieval_query, start=started))
            if state.route != "health":
                state.ok = False
                state.answer = "当前知识库检索失败。为避免误导，我不会猜测答案，请检查 RAGFlow 配置和运行状态。"
        return value

    def quality_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        started = time.perf_counter()
        if state.route == "health":
            state.quality_status = "pass"
            state.quality_issues = []
            state.trace.append(trace("quality_agent", "success",
                                     "医疗安全模板通过；知识库资料仅作服务入口补充",
                                     state.retrieval_query, state.similarity, started))
            return value
        result = _quality.check_quality(state)
        state.trace.append(trace("quality_agent", result["status"], result["detail"],
                                 state.retrieval_query, state.similarity, started))
        return value

    def route_after_quality(self, value: GraphState) -> str:
        return value["state"].quality_status

    def rewrite_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _rewrite.rewrite_query(state)
        state.trace.append(trace("rewrite_agent", result["status"], result["detail"],
                                 state.retrieval_query))
        return value

    def reflection_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _reflection.reflect(state)
        state.trace.append(trace("reflection_agent", result["status"], result["detail"],
                                 state.expanded_question, state.similarity))
        return value

    def answer_agent(self, value: GraphState) -> GraphState:
        state = value["state"]
        result = _answer.polish_answer(state)
        state.trace.append(trace("answer_agent", result["status"], result["detail"],
                                 state.expanded_question))
        return value
