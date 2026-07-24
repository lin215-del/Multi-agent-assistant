"""Tool agent: compute GPA / weighted average score from student questions."""

import re

from .state import AgentState


def calculate_gpa(state: AgentState) -> dict:
    """Parse 'score credit' pairs and compute weighted average."""
    pairs = re.findall(r"(\d+(?:\.\d+)?)\s*分?[，,、\s]*(\d+(?:\.\d+)?)\s*学分", state.question)
    if pairs:
        weighted = sum(float(score) * float(credit) for score, credit in pairs)
        credits = sum(float(credit) for _, credit in pairs)
        state.answer = f"按成绩×学分计算：总学分 {credits:g}，加权平均分 {weighted / credits:.2f}。"
        return {"status": "success", "detail": "执行加权平均分计算工具"}
    state.ok = False
    state.answer = '请按"高数 85分 4学分，英语 90分 3学分"的格式输入，我会计算加权平均分。'
    return {"status": "rejected", "detail": "未能从问题中解析出课程成绩"}
