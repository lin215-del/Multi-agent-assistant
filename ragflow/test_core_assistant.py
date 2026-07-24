from __future__ import annotations

import os
import sys
from pathlib import Path

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"

BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
DATASET_NAME = os.getenv("RAGFLOW_CORE_DATASET_NAME", "暨南大学学生助手-核心服务卡片")
CHAT_NAME = os.getenv("RAGFLOW_CORE_CHAT_NAME", "暨南大学学生助手-核心服务")

QUESTIONS = [
    "本科生请假申请表在哪里下载？",
    "转专业申请表在哪里？",
    "成绩单和在学证明怎么打印？",
    "新生保留入学资格申请表在哪里下载？",
]


def main() -> None:
    api_key = get_api_key()

    sys.path.insert(0, str(RAGFLOW_SDK))
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=api_key, base_url=BASE_URL)
    dataset = rag.list_datasets(name=DATASET_NAME)[0]
    chat = rag.list_chats(name=CHAT_NAME)[0]

    print(f"Dataset: {dataset.name} ({dataset.id}), docs={dataset.document_count}, chunks={dataset.chunk_count}")
    print(f"Chat: {chat.name} ({chat.id})")

    for question in QUESTIONS:
        print(f"\nQUERY: {question}")
        chunks = rag.retrieve(
            dataset_ids=[dataset.id],
            question=question,
            page_size=3,
            similarity_threshold=0.01,
            vector_similarity_weight=0.1,
            top_k=20,
            keyword=True,
        )
        for chunk in chunks[:3]:
            content = (getattr(chunk, "content", "") or "").replace("\n", " ")
            print(f"- {getattr(chunk, 'document_name', '')} | similarity={getattr(chunk, 'similarity', None)}")
            print(f"  {content[:180]}")

        session = chat.create_session(f"test: {question[:20]}")
        answer = next(session.ask(question + " 请给出来源链接。", stream=False))
        print("ANSWER:")
        print(answer.content)


if __name__ == "__main__":
    main()
