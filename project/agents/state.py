"""LangGraph 共享状态。

5 个 agent 不直接互相传参，每个人都只跟 AgentState 这个"工作台"打交道——
读它、往里写新东西。这是 LangGraph 的核心约定，也是节点能互相解耦的关键。
"""
from typing import Any, Literal, Optional, TypedDict

# 调度 Agent 的路由决策，4 选 1
Route = Literal["retrieve", "tool", "both", "reject"]


class AgentState(TypedDict):
    """5 个 agent 共享的工作台，每个字段是流程里的一个中间结果。"""

    question: str
    """学生原始问题，入口写入，全程不变。"""

    route: Optional[Route]
    """调度 Agent 的决策：retrieve / tool / both / reject。"""

    query: Optional[str]
    """送进检索的查询词；反思重试时可能被改写，所以跟 question 分开存。"""

    retrieved: list[dict]
    """检索 Agent 从 RAGFlow 捞回来的 chunks（正文 / 表格 / 图 VLM 描述）。"""

    tool_output: Optional[Any]
    """工具 Agent 的执行结果；没用工具就是 None。"""

    analysis: str
    """分析 Agent 写的草稿答案。"""

    reflection: Optional[dict]
    """反思 Agent 的质检结果：{"ok": bool, "reason": str}。"""

    final: str
    """最终交付给学生的答案。"""

    round: int
    """反思循环当前第几轮，用来限制最大重试次数。"""

    node_trace: list[dict]
    """逐节点执行耗时记录：[{node: str, elapsed_ms: int}, ...]，调试 & 答辩用。"""
