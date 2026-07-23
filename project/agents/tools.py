"""工具 Agent（Tool）：给学生算数用，目前只有"学分加权平均分"计算器。

流程：tool_node 读学生问题 → LLM 抽出每门课的分数+学分 → compute_weighted_average 算
→ 写进 tool_output。分析 agent 生成答案时会带上【工具计算结果】那节。
OCR 没做（图已在清洗层 VLM 预处理过），接口留好以后扩展。
"""
import json
import os

import requests

from agents.state import AgentState


def compute_weighted_average(courses):
    """学分加权平均分。courses: [{"score": 85, "credits": 4}, ...]。
    返回 {weighted_average, total_credits, course_count}；空或总学分 0 返回 None。"""
    if not courses:
        return None
    total_credits = sum(c["credits"] for c in courses)
    if total_credits == 0:
        return None
    total_weighted = sum(c["score"] * c["credits"] for c in courses)
    return {
        "weighted_average": round(total_weighted / total_credits, 2),
        "total_credits": total_credits,
        "course_count": len(courses),
    }


def _parse_courses_json(raw):
    """从 LLM 输出里抠出 JSON 数组，转成 [{score, credits}, ...]；抠不出或缺字段返回 []。

    用括号计数找第一个完整 JSON 数组——比正则贪婪匹配更准：
    "第一个 [...] 第二个 [...]" 不会把两个数组串在一起 parse 失败。"""
    if not raw:
        return []
    start = raw.find("[")
    if start == -1:
        return []
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "[":
            depth += 1
        elif raw[i] == "]":
            depth -= 1
            if depth == 0:
                try:
                    arr = json.loads(raw[start:i + 1])
                except Exception:
                    return []
                out = []
                for c in arr:
                    if isinstance(c, dict) and "score" in c and "credits" in c:
                        try:
                            out.append({"score": float(c["score"]), "credits": float(c["credits"])})
                        except (TypeError, ValueError):
                            continue
                return out
    return []


_EXTRACT_PROMPT = """你是课程成绩解析器。从学生问题里抽出每门课的【分数】和【学分】，只输出 JSON 数组，不要任何解释。
格式：[{"score": 85, "credits": 4}]（分数 0-100，学分正数）

例子：
问题：我高数85分学分4，英语90分学分3，算下加权平均分
[{"score":85,"credits":4},{"score":90,"credits":3}]

问题：物理78（学分3）、化学82（学分3）、生物90（学分2）
[{"score":78,"credits":3},{"score":82,"credits":3},{"score":90,"credits":2}]
"""


def extract_courses_with_llm(question):
    """调 LLM 从问句抽出课程列表。"""
    base = os.environ["SILICONFLOW_API_BASE"]
    key = os.environ["SILICONFLOW_API_KEY"]
    model = os.environ.get("ANALYZER_MODEL", "Qwen/Qwen2.5-32B-Instruct")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": _EXTRACT_PROMPT + "\n问题：" + question}],
            "temperature": 0,
            "max_tokens": 200,
        },
        proxies={"http": None, "https": None},  # SiliconFlow 国内服务，绕 VPN 代理直连
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_courses_json(resp.json()["choices"][0]["message"]["content"])


def tool_node(state: AgentState) -> dict:
    """LangGraph 节点：读 question → 抽课程 → 算 → 写回 tool_output。"""
    courses = extract_courses_with_llm(state["question"])
    result = compute_weighted_average(courses)
    if result is None:
        return {"tool_output": "未能从问题中解析出课程成绩，无法计算"}
    return {"tool_output": "加权平均分：{wa}（共{n}门课，{tc}学分）".format(
        wa=result["weighted_average"], n=result["course_count"], tc=result["total_credits"])}
