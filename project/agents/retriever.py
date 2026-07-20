"""检索 Agent（Retriever）：去 RAGFlow 知识库捞 top-k chunks 喂给分析 agent。

dataset '暨大学生助手-多模态清洗'（29 篇：HTML 通知正文 + PDF 段落 + 表格 + 图 VLM 描述）。
每个 chunk 抽成 {content, source, score}：
  content — chunk 正文（分析 agent 拼答案的原料）
  source  — 来源文档名（document_keyword；RAGFlow 不按 chunk 给 URL，文档名一样可溯源）
  score   — 相关度 similarity（反思 agent 可参考判断资料够不够）
"""
import os

import requests

from agents.state import AgentState

# 暨大学生助手-多模态清洗 dataset；可用环境变量 RAGFLOW_DATASET_ID 覆盖
DATASET_ID = os.environ.get(
    "RAGFLOW_DATASET_ID", "a37fbd80835011f19401935c69409f04"
)
DEFAULT_TOP_K = 8


def parse_chunks(api_response: dict) -> list[dict]:
    """把 RAGFlow 原始返回抽成干净 chunks；异常输入返回空列表不抛。"""
    data = (api_response or {}).get("data") or {}
    chunks = data.get("chunks") or []
    return [
        {
            "content": c.get("content", ""),
            "source": c.get("document_keyword", ""),
            "score": c.get("similarity", 0.0),
        }
        for c in chunks
    ]


def retrieve_chunks(query: str, dataset_id: str = DATASET_ID, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """调 RAGFlow retrieval API，返回解析后的 chunks。"""
    base = os.environ["RAGFLOW_BASE_URL"]
    key = os.environ["RAGFLOW_API_KEY"]
    r = requests.post(
        f"{base}/api/v1/retrieval",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "question": query,
            "dataset_ids": [dataset_id],
            "page": 1,
            "page_size": top_k,
            "similarity_threshold": 0.2,
        },
        timeout=30,
    )
    r.raise_for_status()
    return parse_chunks(r.json())


def retriever_node(state: AgentState) -> dict:
    """LangGraph 节点：读 query（没有退回 question）→ 检索 → 写回 retrieved。"""
    query = state.get("query") or state["question"]
    chunks = retrieve_chunks(query)
    return {"retrieved": chunks}
