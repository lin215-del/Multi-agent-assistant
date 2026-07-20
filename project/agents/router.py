"""调度 Agent（Router）：第一个接到学生问题，判断该走哪条路。

输出 4 选 1：
  retrieve — 要查学校资料库（规章制度、通知、流程、申请条件等）
  tool     — 纯计算（算 GPA、学分、综测分）
  both     — 又查又算
  reject   — 跟学生事务无关 / 闲聊 / 要实时外部信息（天气、股价）

LLM 输出解析不出来时兜底 retrieve（交给检索+反思兜底，不轻易拒答）。
"""
import os

import requests

from agents.state import AgentState, Route

VALID_ROUTES = ("retrieve", "tool", "both", "reject")

# few-shot：给几个例子，教 LLM 怎么分类
_FEWSHOT = """你是学生助手的调度员。把学生问题分到下面 4 类之一，只回答类别名（retrieve/tool/both/reject），不要任何解释：
- retrieve：要查学校资料库才能答（规章制度、通知、流程、申请条件等）
- tool：纯计算类（算 GPA、算学分、算加权平均分等）
- both：既要查资料又要算
- reject：跟学生事务无关、闲聊、或要实时外部信息（天气、股价等）

例子：
问题：国家奖学金申请条件是什么
类别：retrieve
问题：我 GPA 3.6，帮我算算够不够国奖线
类别：both
问题：帮我算一下这 5 门课的加权平均分
类别：tool
问题：今天广州天气怎么样
类别：reject
问题：你好呀
类别：reject
"""


def parse_route(text: str) -> Route:
    """把 LLM 原始输出解析成合法 Route；解析不出来兜底 retrieve。"""
    if not text:
        return "retrieve"
    t = text.strip().lower()
    for r in VALID_ROUTES:
        if r in t:
            return r  # type: ignore[return-value]
    return "retrieve"


def _build_prompt(question: str) -> str:
    return f"{_FEWSHOT}\n问题：{question}\n类别："


def classify_with_llm(question: str) -> str:
    """调 SiliconFlow 文本模型分类，返回 LLM 的原始文本（未解析）。"""
    base = os.environ["SILICONFLOW_API_BASE"]
    key = os.environ["SILICONFLOW_API_KEY"]
    model = os.environ.get("TEXT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": _build_prompt(question)}],
            "temperature": 0,
            "max_tokens": 10,
        },
        proxies={"http": None, "https": None},  # SiliconFlow 国内服务，绕 VPN 代理直连
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def router_node(state: AgentState) -> dict:
    """LangGraph 节点：读 question → 调 LLM 分类 → 写回 route + query。"""
    question = state["question"]
    raw = classify_with_llm(question)
    route = parse_route(raw)
    return {"route": route, "query": question}
