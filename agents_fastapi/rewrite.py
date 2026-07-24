"""Rewrite agent: rewrite the retrieval query after quality failure.

Tries LLM-based rewrite first; falls back to hardcoded intent templates.
"""

import os

import requests

from .state import AgentState

_INTENT_FALLBACKS: list[tuple[list[str], str]] = [
    (["请假"], "暨南大学 本科生请假申请表 下载服务 学籍相关文件 审批"),
    (["学生证"], "暨南大学 学生证 补办 办理流程 负责部门 材料"),
    (["休学"], "暨南大学 本科生休学 申请 办理部门 受理时间"),
    (["复学"], "暨南大学 本科生复学申请 办理流程 材料"),
    (["退学"], "暨南大学 学生退学申请 审核 签字 流程"),
    (["转专业"], "暨南大学 本科生转专业 申请表 转出学院 转入学院"),
    (["图书馆", "自习"], "暨南大学 图书馆 开馆时间 座位预约 空间预约"),
]


def _llm_rewrite(question: str, issues: list[str], retry_count: int) -> str:
    llm_base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "")
    if not (llm_base and llm_key and llm_model):
        return ""
    prompt = (
        "学生问了这个问题，但知识库检索没找到足够资料。\n"
        f"原始问题：{question}\n"
        f"检索失败原因：{'；'.join(issues) if issues else '相似度不足或内容缺失'}\n"
        f"当前第 {retry_count} 次重试。\n\n"
        "请把问题改写成更精准的检索查询，用于搜索暨南大学知识库。要求：\n"
        '- 补充官方用语（如"申请表""办理流程""负责部门""下载入口"）\n'
        "- 如果问题有多个关键词，尽量同时覆盖\n"
        "- 不要编造答案，只改写查询词\n"
        "- 只输出改写后的一句话，不要任何解释"
    )
    try:
        resp = requests.post(
            f"{llm_base}/chat/completions",
            headers={"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
            json={"model": llm_model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 200},
            timeout=15,
        )
        result = str(resp.json()["choices"][0]["message"]["content"]).strip()
        return result[:500] if len(result) >= 4 else ""
    except Exception:
        return ""


def _template_rewrite(question: str, retry_count: int) -> str:
    for terms, text in _INTENT_FALLBACKS:
        if any(term in question for term in terms):
            if retry_count > 1:
                return f"{text} 事项名称 下载入口 联系方式"
            return text
    base = f"{question} 暨南大学 官方通知 办理流程 负责部门 所需材料"
    if retry_count > 1:
        base = f"{base} 事项名称 下载入口 联系方式"
    return base


def rewrite_query(state: AgentState) -> dict:
    """Rewrite the retrieval query. LLM first, template fallback."""
    state.retry_count += 1
    llm_result = _llm_rewrite(state.question, state.quality_issues, state.retry_count)
    if llm_result:
        state.retrieval_query = llm_result
        method = "llm"
    else:
        state.retrieval_query = _template_rewrite(state.question, state.retry_count)
        method = "template"
    state.ok = True
    state.answer = ""
    state.document_name = ""
    state.source_url = ""
    state.similarity = 0.0
    state.matches = []
    state.retrieved = []
    return {"status": "success", "detail": f"第 {state.retry_count} 次查询改写", "method": method}
