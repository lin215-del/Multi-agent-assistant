from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"

BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
DATASET_NAME = os.getenv("RAGFLOW_CORE_DATASET_NAME", "暨南大学学生助手-核心服务卡片")
CHAT_NAME = os.getenv("RAGFLOW_CORE_CHAT_NAME", "暨南大学学生助手-核心服务")

PROMPT_CONFIG = {
    "system": """你是暨南大学学生助手。你只依据知识库内容回答学生关于暨南大学公开办事材料、表格模板、学籍、成绩证明、新生材料等问题。

回答要求：
1. 优先读取知识库里的“直接回答”和“来源链接”。
2. 学生问下载位置、模板、表格时，直接给出材料名称、所在栏目和来源链接。
3. 不要编造未收录的流程、电话、地点或网址。
4. 如果知识库没有明确答案，说“当前知识库未收录明确材料”。
5. 回答保持简洁、中文。""",
    "parameters": [{"key": "knowledge", "optional": True}],
    "quote": True,
}


def main() -> None:
    api_key = os.getenv("RAGFLOW_API_KEY")
    if not api_key:
        raise SystemExit("Missing RAGFLOW_API_KEY environment variable.")

    sys.path.insert(0, str(RAGFLOW_SDK))
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=api_key, base_url=BASE_URL)
    try:
        datasets = rag.list_datasets(name=DATASET_NAME)
    except Exception as exc:
        if "lacks permission for dataset" not in str(exc):
            raise
        datasets = []
    if not datasets:
        raise SystemExit(f"Dataset not found: {DATASET_NAME}. Run import_core_services.py first.")
    dataset = datasets[0]

    try:
        chats = rag.list_chats(name=CHAT_NAME)
    except Exception as exc:
        if "lacks permission for chat" not in str(exc):
            raise
        chats = []
    if chats:
        chat = chats[0]
        print(f"Using existing chat: {chat.name} ({chat.id})")
    else:
        chat = rag.create_chat(
            name=CHAT_NAME,
            dataset_ids=[dataset.id],
            prompt_config=PROMPT_CONFIG,
            similarity_threshold=0.01,
            vector_similarity_weight=0.1,
            top_n=3,
            top_k=20,
        )
        print(f"Created chat: {chat.name} ({chat.id})")

    print(f"Dataset: {dataset.name} ({dataset.id})")
    print(f"Chat: {chat.name} ({chat.id})")


if __name__ == "__main__":
    main()
