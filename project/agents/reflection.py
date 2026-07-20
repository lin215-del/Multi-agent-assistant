"""反思 Agent（Reflection）：质检员，检查分析 agent 的草稿能不能交付。

检查 3 项：①有没有引用来源 ②答的是不是问的 ③资料不足时有没有坦白说（没瞎编）。
输出 {ok, reason} 写进 reflection。ok=False 时第 8 步触发回检索重试。
LLM 输出解析不出来时默认 ok=True（不因解析故障卡住流程）。
"""
import json
import os
import re

import requests

from agents.state import AgentState


def parse_check(raw):
    """把 LLM 质检输出解析成 {ok, reason}；解析不出来默认 ok=True（不卡流程）。"""
    if not raw:
        return {"ok": True, "reason": "反思无输出，默认通过"}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"ok": True, "reason": "反思输出非 JSON，默认通过"}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"ok": True, "reason": "反思 JSON 解析失败，默认通过"}
    ok = d.get("ok", True)
    if isinstance(ok, str):
        ok = ok.strip().lower() in ("true", "yes", "通过", "ok", "1")
    elif ok is None:
        ok = True
    return {"ok": bool(ok), "reason": str(d.get("reason", ""))}


def build_check_prompt(question, retrieved, analysis):
    """组装质检 prompt。纯函数，测试重点。"""
    sources = "、".join(c.get("source", "") for c in retrieved) if retrieved else "（无）"
    return f"""你是学生助手的质检员，判断下面这个回答能不能交付给学生。

判断标准（任意一条不满足就不通过）：
1. 有引用来源（回答里标注了资料出处）
2. 答的是学生问的问题（没跑题）
3. 资料不足时坦白说了"没找到可靠资料"，而不是瞎编

只输出 JSON：{{"ok": true 或 false, "reason": "一句话原因"}}

学生问题：{question}
可引用的来源：{sources}
待检查的回答：
{analysis}
"""


def check_with_llm(question, retrieved, analysis):
    """调 LLM（32B）当质检员，返回原始文本。"""
    base = os.environ["SILICONFLOW_API_BASE"]
    key = os.environ["SILICONFLOW_API_KEY"]
    model = os.environ.get("ANALYZER_MODEL", "Qwen/Qwen2.5-32B-Instruct")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": build_check_prompt(question, retrieved, analysis)}],
            "temperature": 0,
            "max_tokens": 200,
        },
        proxies={"http": None, "https": None},  # SiliconFlow 国内服务，绕 VPN 代理直连
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def reflection_node(state: AgentState) -> dict:
    """LangGraph 节点：读 question/retrieved/analysis → 质检 → 写回 reflection。"""
    raw = check_with_llm(state["question"], state.get("retrieved") or [], state.get("analysis", ""))
    return {"reflection": parse_check(raw)}
