"""Quality agent: rule-based gate that validates retrieval sufficiency."""

import re

from .state import AgentState

MIN_GROUNDED_SCORE = 0.2


def required_intent_terms(question: str) -> list[str]:
    """Return the first keyword group that matches the question."""
    groups = [
        ["请假"],
        ["学生证"],
        ["休学"],
        ["复学"],
        ["退学"],
        ["转专业"],
        ["辅修"],
        ["校巴", "班车"],
        ["图书馆", "开馆"],
        ["校园网"],
    ]
    return next((group for group in groups if any(term in question for term in group)), [])


def question_bigrams(question: str) -> list[str]:
    """Extract deduplicated Chinese bigrams, filtering common stop words."""
    ignored = {
        "暨南", "南大", "大学", "学生", "学校", "请问", "怎么", "怎样", "如何", "哪里",
        "什么", "办理", "申请", "相关", "流程", "材料", "入口", "部门", "电话", "时间",
        "下载", "审批", "表格", "服务",
    }
    terms: list[str] = []
    for segment in re.findall(r"[一-鿿]{2,}", question):
        terms.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return [t for t in dict.fromkeys(terms) if t not in ignored][:24]


def check_quality(state: AgentState) -> dict:
    """Validate answer sufficiency. Sets state.quality_status and state.quality_issues."""
    issues: list[str] = []

    if state.route == "health":
        state.quality_status = "pass"
        state.quality_issues = []
        return {"status": "success", "detail": "医疗安全模板通过；知识库资料仅作服务入口补充"}

    if not state.ok:
        issues.append("回答状态未通过")
    if not state.retrieved and not state.matches:
        issues.append("没有召回知识分块")
    if state.similarity < MIN_GROUNDED_SCORE:
        issues.append(f"最高相似度 {state.similarity:.3f} 低于阈值 {MIN_GROUNDED_SCORE:.1f}")
    if not state.document_name:
        issues.append("缺少来源文档")

    evidence = " ".join([
        state.document_name,
        state.answer,
        *[str(m.get("document_name", "")) + " " + str(m.get("snippet", "")) for m in state.matches],
    ])
    req_terms = required_intent_terms(state.question)
    if req_terms and not any(t in evidence for t in req_terms):
        issues.append(f"召回内容未覆盖问题关键事项：{'/'.join(req_terms)}")
    elif not req_terms:
        lex = question_bigrams(state.question)
        if lex and not any(t in evidence for t in lex):
            issues.append("召回内容与原问题缺少有效关键词重合")

    state.quality_issues = issues
    if not issues:
        state.quality_status = "pass"
        return {"status": "success", "detail": "Harness 通过：分数、来源和关键事项均满足要求"}
    if state.retry_count < state.max_retries:
        state.quality_status = "retry"
        return {"status": "retry", "detail": f"Harness 要求重试：{'；'.join(issues)}"}
    state.quality_status = "reject"
    state.ok = False
    state.answer = "经过多轮检索仍未找到足以支撑答案的可靠资料。为避免误导，我无法确认，请联系对应业务部门或查看学校官方通知。"
    state.document_name = ""
    state.source_url = ""
    state.similarity = 0.0
    state.matches = []
    state.retrieved = []
    return {"status": "rejected", "detail": f"达到最大重试次数，拒答：{'；'.join(issues)}"}
