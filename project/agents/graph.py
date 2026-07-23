"""LangGraph 编排：完整五节点图 + 条件路由 + 反思循环 + 拒答。

流程：
  START → router
  router --route--> retrieve / tool / both / reject
    retrieve → retriever → analyzer
    tool     → tool → analyzer
    both     → tool → retriever → analyzer
    reject   → reject_node → END
  analyzer → reflection
  reflection --ok?--> 通过→finalize；不通过且轮数<MAX→retry（重生成）；到上限→finalize（坦白）
"""
from langgraph.graph import START, END, StateGraph

from agents.analyzer import analyzer_node
from agents.reflection import reflection_node
from agents.retriever import retriever_node
from agents.router import router_node
from agents.state import AgentState
from agents.tools import tool_node

MAX_ROUNDS = 2  # 反思不通过时最多重试次数（初始 + 2 次重试 = 最多生成 3 次）


def reject_node(state: AgentState) -> dict:
    """礼貌拒答：超范围的问题引导回学生事务。"""
    return {"final": "这个问题超出了我的范围。我只负责暨南大学学生事务"
                     "（规章制度、申请流程、学分成绩、通知等）。"
                     "如果是这类问题，换个问法再问我；否则建议咨询辅导员或学校相关部门。"}


def finalize_node(state: AgentState) -> dict:
    """把 analysis 收为最终答案；反思没通过到上限时，坦白 + 附草稿。
    反思没跑（纯工具路径）视为通过——计算结果由代码产出，可直接交付。"""
    analysis = state.get("analysis", "")
    refl = state.get("reflection") or {}
    if not refl or refl.get("ok"):
        return {"final": analysis}
    return {"final": "这个问题我把握不大，建议咨询辅导员或查看教务处最新通知。"
                     "以下是我查到的相关内容供参考：\n\n" + analysis}


def retry_node(state: AgentState) -> dict:
    """重试前：用反思给的 rewritten_query 改写检索词 + 清空旧检索结果 + 轮数 +1。
    清空 retrieved 是为了让 retriever 用新 query 重新检索，不残留上一轮的旧 chunks。"""
    refl = state.get("reflection") or {}
    rq = refl.get("rewritten_query") or state.get("query") or state["question"]
    return {"round": (state.get("round") or 0) + 1,
            "query": rq,
            "retrieved": []}


def _after_router(state):
    route = state.get("route", "retrieve")
    if route == "reject":
        return "reject_node"
    if route in ("tool", "both"):
        return "tool"
    return "retriever"


def _after_tool(state):
    # both：tool 之后还要检索；tool-only：直接去分析
    return "retriever" if state.get("route") == "both" else "analyzer"


def _after_analyzer(state):
    # 纯工具计算路径：结果由代码算出，不需要反思质检，直接收尾
    if state.get("route") == "tool":
        return "finalize_node"
    return "reflection"


def _after_reflection(state):
    refl = state.get("reflection") or {}
    if refl.get("ok"):
        return "finalize_node"
    if (state.get("round") or 0) >= MAX_ROUNDS:
        return "finalize_node"
    return "retry_node"


def build_graph(router=None, retriever=None, analyzer=None, tool=None,
                reflection=None, reject=None, finalize=None, retry=None):
    """建完整五节点图。参数允许注入假节点（测试用），默认用真节点。"""
    g = StateGraph(AgentState)
    g.add_node("router", router or router_node)
    g.add_node("retriever", retriever or retriever_node)
    g.add_node("tool", tool or tool_node)
    g.add_node("analyzer", analyzer or analyzer_node)
    g.add_node("reflection", reflection or reflection_node)
    g.add_node("reject_node", reject or reject_node)
    g.add_node("finalize_node", finalize or finalize_node)
    g.add_node("retry_node", retry or retry_node)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", _after_router, {
        "retriever": "retriever", "tool": "tool", "reject_node": "reject_node"})
    g.add_conditional_edges("tool", _after_tool, {
        "retriever": "retriever", "analyzer": "analyzer"})
    g.add_edge("retriever", "analyzer")
    g.add_conditional_edges("analyzer", _after_analyzer, {
        "reflection": "reflection", "finalize_node": "finalize_node"})
    g.add_conditional_edges("reflection", _after_reflection, {
        "finalize_node": "finalize_node", "retry_node": "retry_node"})
    g.add_edge("retry_node", "retriever")
    g.add_edge("finalize_node", END)
    g.add_edge("reject_node", END)
    return g.compile()
