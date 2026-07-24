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
QUESTIONS = [
    "本科生请假申请表在哪里下载？",
    "学籍相关文件里有没有转专业申请表？",
    "在校证明和成绩单怎么打印？",
    "新生相关下载材料在哪里？",
]


def main() -> None:
    api_key = os.getenv("RAGFLOW_API_KEY")
    if not api_key:
        raise SystemExit("Missing RAGFLOW_API_KEY")

    rag = RAGFlow(api_key=api_key, base_url=BASE_URL)
    dataset = rag.list_datasets(id=DATASET_ID)[0]
    print(f"Dataset: {dataset.name} ({dataset.id}), docs={dataset.document_count}, chunks={dataset.chunk_count}")

    for question in QUESTIONS:
        print(f"\nQUERY: {question}")
        chunks = rag.retrieve(
            dataset_ids=[dataset.id],
            question=question,
            page_size=5,
            similarity_threshold=0.05,
            vector_similarity_weight=0.3,
            top_k=20,
            keyword=True,
        )
        for chunk in chunks[:5]:
            content = (getattr(chunk, "content", "") or "").replace("\n", " ")
            print(f"- {getattr(chunk, 'document_name', '')} | similarity={getattr(chunk, 'similarity', None)}")
            print(f"  {content[:220]}")


if __name__ == "__main__":
    main()
