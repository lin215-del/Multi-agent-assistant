"""Router agent: classify the student's question into one of 4 routes."""

import re

from .state import AgentState, Route


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def is_study_place_intent(question: str) -> bool:
    """Pure predicate: does this question indicate study-place intent?"""
    q = _clean(question)
    patterns = [
        "想学习", "学习地方", "地方学习", "没找到地方", "找地方学", "哪里学", "哪里学习",
        "自习", "复习", "备考", "看书", "写作业", "图书馆", "阅览室", "座位预约", "空间预约",
    ]
    return any(p in q for p in patterns)


def route_question(state: AgentState) -> dict:
    """Classify the question and set state.route + state.route_reason."""
    q = _clean(state.expanded_question)
    if any(term in q for term in ["感冒", "发烧", "发热", "咳嗽", "校医", "门诊", "医保", "公费医疗", "看病", "不舒服"]):
        state.route = "health"
        state.route_reason = "健康或校内医疗服务问题，进入 Health Agent"
    elif re.search(r"(gpa|绩点|加权平均|平均分|学分).*(算|计算|多少)|怎么算.*(gpa|绩点|平均分)", state.expanded_question, re.I):
        state.route = "tool"
        state.route_reason = "成绩、绩点或学分计算问题，进入 Tool Agent"
    elif any(term in q for term in ["账号密码", "验证码", "身份证号码", "私人手机", "家庭住址", "未公开", "保证录取"]):
        state.route = "reject"
        state.route_reason = "涉及隐私、安全或未公开信息"
    else:
        state.route = "retrieve"
        state.route_reason = "学生事务问题，进入检索增强回答链路"
    return {"status": "success" if state.route != "reject" else "rejected",
            "detail": state.route_reason, "route": state.route}
