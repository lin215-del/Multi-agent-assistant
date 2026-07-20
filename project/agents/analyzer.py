"""分析 Agent（Analyzer）：拿"问题 + 检索资料 + 工具结果"拼成给学生的答案。

要求 LLM：分点回答、标注来源、资料不足就坦白说（喂给反思 agent 做质检）。
草稿写进工作台 analysis 字段，由反思 agent 决定是否交付。
"""
import os

import requests

from agents.state import AgentState


def build_prompt(question: str, chunks: list[dict], tool_output=None) -> str:
    """把问题/资料/工具结果组装成 LLM prompt。纯函数，测试重点。"""
    lines = [
        "你是暨南大学学生事务助手。根据下面提供的资料和工具结果回答学生问题。",
        "要求：",
        "1. 只根据资料和工具结果回答，不要编造里面没有的内容",
        "2. 分点回答，清楚有条理",
        "3. 用到资料的地方标注来源，格式：（来源：文档名）",
        "4. 如果既没有资料、也没有工具结果，直接说‘这个问题我目前没有找到可靠资料，建议咨询辅导员’，不要硬答",
        "",
        "学生问题：" + question,
        "",
        "【参考资料】",
    ]
    if chunks:
        for i, c in enumerate(chunks, 1):
            lines.append("【资料" + str(i) + "】来源：" + str(c.get("source", "")))
            lines.append(str(c.get("content", "")))
            lines.append("")
    else:
        lines.append("（没有检索到相关资料）")
        lines.append("")
    if tool_output:
        lines.append("【工具计算结果】")
        lines.append(str(tool_output))
        lines.append("")
    return "\n".join(lines)


def generate_with_llm(question: str, chunks: list[dict], tool_output=None) -> str:
    """调 SiliconFlow 文本模型生成草稿答案。"""
    base = os.environ["SILICONFLOW_API_BASE"]
    key = os.environ["SILICONFLOW_API_KEY"]
    model = os.environ.get("ANALYZER_MODEL", "Qwen/Qwen2.5-32B-Instruct")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": build_prompt(question, chunks, tool_output)}],
            "temperature": 0.3,
            "max_tokens": 800,
        },
        proxies={"http": None, "https": None},  # SiliconFlow 国内服务，绕 VPN 代理直连
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def analyzer_node(state: AgentState) -> dict:
    """LangGraph 节点：读 question/retrieved/tool_output → 生成草稿 → 写回 analysis。"""
    question = state["question"]
    chunks = state.get("retrieved") or []
    tool_output = state.get("tool_output")
    draft = generate_with_llm(question, chunks, tool_output)
    return {"analysis": draft}
