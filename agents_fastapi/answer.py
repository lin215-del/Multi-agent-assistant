"""Answer agent: optionally polish the final answer via LLM."""

import os

import requests

from .state import AgentState


def _llm_polish(
    question: str,
    answer: str,
    matches: list[dict],
    messages: list[dict],
) -> tuple[str, str]:
    llm_base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "")
    if not (llm_base and llm_key and llm_model):
        return answer, "可选文本模型未配置；保留通过质量门禁的规则摘要"

    evidence = "\n\n".join(
        f"[资料 {i}] {m.get('document_name', '')}\n{m.get('snippet', '')}"
        for i, m in enumerate(matches[:5], 1)
    )
    history = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content', ''))[:300]}"
        for m in messages[-6:]
    )
    prompt = (
        "你是暨南大学学生事务问答助手。只能根据下方资料改写现有答案，"
        "不得补充资料中没有的日期、金额、网址、电话、流程或结论。"
        "若资料不足，原样返回现有答案。回答应简洁、分点、使用中文，"
        "不要编造来源编号或链接。\n\n"
        f"近期对话：\n{history or '无'}\n\n"
        f"当前问题：{question}\n\n"
        f"现有答案：{answer}\n\n"
        f"检索资料：\n{evidence}"
    )
    try:
        resp = requests.post(
            f"{llm_base}/chat/completions",
            headers={"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
            json={
                "model": llm_model,
                "messages": [
                    {"role": "system", "content": "严格执行有依据回答和拒绝臆测规则。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 700,
            },
            timeout=35,
        )
        resp.raise_for_status()
        polished = str(resp.json()["choices"][0]["message"]["content"]).strip()
        if 8 <= len(polished) <= 4000:
            return polished, "文本模型仅对已通过质量门禁的证据摘要进行受控整理"
    except Exception:
        pass
    return answer, "文本模型不可用；已安全回退到规则摘要"


def polish_answer(state: AgentState) -> dict:
    """Polish the final answer via LLM if conditions are met."""
    if state.ok and state.route == "retrieve" and state.matches:
        state.answer, detail = _llm_polish(
            state.question, state.answer, state.matches, state.messages
        )
        return {"status": "success", "detail": detail}
    return {"status": "success", "detail": "生成最终回答"}
