"""Intent agent: expand the user's question with semantic context."""

from .router import is_study_place_intent
from .state import AgentState


def expand_intent(state: AgentState) -> dict:
    """Expand the question with implied search terms."""
    q = state.question
    if "请假" in q:
        state.expanded_question = (
            f"{q}\n\n语义意图补全：检索暨南大学本科生请假申请表、请假办理流程、材料要求和官方下载入口。"
        )
        return {"status": "success", "detail": 'Intent Agent：已将简称补全为“本科生请假申请表/办理流程”'}
    if is_study_place_intent(q):
        state.expanded_question = (
            f"{q}\n\n语义意图补全：学生想找可以学习或自习的地方。"
            "请检索暨南大学图书馆、阅览室、开放时间、座位预约、空间预约等官方信息。"
        )
        return {"status": "success", "detail": 'Intent Agent：已将口语表达补全为"找学习/自习地点"'}
    if any(term in q for term in ["模板", "表格", "申请表", "证明", "下载", "材料"]):
        state.expanded_question = f"{q}\n\n语义意图补全：学生可能需要办理事项、表格模板或官方下载入口。"
        return {"status": "success", "detail": 'Intent Agent：已补全为"事项/材料下载"意图'}
    state.expanded_question = q
    return {"status": "success", "detail": "Intent Agent：无需补全，保留原问题"}
