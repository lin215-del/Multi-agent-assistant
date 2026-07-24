from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"
sys.path.insert(0, str(RAGFLOW_SDK))

from ragflow_sdk import RAGFlow


DATASET_ID = os.getenv("RAGFLOW_DATASET_ID", "683cdc4a82a511f1b2e527d9437de36f")
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
CHAT_NAME = os.getenv("RAGFLOW_CHAT_NAME", "暨南大学学生助手-v2")


PROMPT_CONFIG = {
    "system": """你是暨南大学学生助手。你只能依据知识库内容回答学生关于暨南大学公开办事材料、表格模板、学籍、成绩证明、新生材料、选课、推免、实践教学等问题。

回答要求：
1. 先直接回答学生要去哪找、材料叫什么、适用事项是什么。
2. 如果知识库里有来源链接，必须列出来源。
3. 如果知识库没有明确答案，说“当前知识库未收录明确材料”，不要编造。
4. 回答保持简洁、中文。""",
    "parameters": [
        {"key": "knowledge", "optional": True},
    ],
}


def main() -> None:
    api_key = os.getenv("RAGFLOW_API_KEY")
    if not api_key:
        raise SystemExit("Missing RAGFLOW_API_KEY")

    rag = RAGFlow(api_key=api_key, base_url=BASE_URL)
    chats = rag.list_chats(name=CHAT_NAME)
    if chats:
        chat = chats[0]
        print(f"Using existing chat: {chat.name} ({chat.id})")
    else:
        chat = rag.create_chat(
            name=CHAT_NAME,
            dataset_ids=[DATASET_ID],
            prompt_config=PROMPT_CONFIG,
        )
        print(f"Created chat: {chat.name} ({chat.id})")

    session = chat.create_session("第一阶段测试")
    answer = next(session.ask("本科生请假申请表在哪里下载？", stream=False))
    print("\nTEST ANSWER:")
    print(answer.content)
    if answer.reference:
        print("\nREFERENCES:")
        for ref in answer.reference[:5]:
            print("-", ref.get("document_name"), ref.get("similarity"))


if __name__ == "__main__":
    main()
