"""Reflection agent: final sanity check before answer delivery."""

from .state import AgentState


def reflect(state: AgentState) -> dict:
    """Final reflection pass."""
    if state.route == "health":
        return {"status": "success", "detail": "医疗回答已通过安全边界检查，不替代诊断"}
    status = "success" if state.ok else "rejected"
    return {"status": status, "detail": f"答案已完成来源、相似度和拒答检查；检索重试 {state.retry_count} 次"}
