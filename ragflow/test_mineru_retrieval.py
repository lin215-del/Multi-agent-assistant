from __future__ import annotations

import os
import sys
from pathlib import Path

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"
DATASET_ID = os.getenv("RAGFLOW_PHASE1_DATASET_ID", "683cdc4a82a511f1b2e527d9437de36f")
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
QUESTION = os.getenv("MINERU_TEST_QUESTION", "全日制本科毕业生学士学位证明书申请表")


def main() -> None:
    sys.path.insert(0, str(RAGFLOW_SDK))
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=get_api_key(), base_url=BASE_URL)
    datasets = rag.list_datasets(page_size=100)
    dataset = next((item for item in datasets if item.id == DATASET_ID), None)
    if dataset is None:
        raise SystemExit(f"Dataset unavailable: {DATASET_ID}")

    chunks = rag.retrieve(
        dataset_ids=[dataset.id],
        question=QUESTION,
        page_size=10,
        similarity_threshold=0.05,
        vector_similarity_weight=0.3,
        top_k=30,
        keyword=True,
    )
    mineru_hits = [chunk for chunk in chunks if (getattr(chunk, "document_name", "") or "").startswith("mineru__")]
    print(f"Question: {QUESTION}")
    for chunk in chunks[:5]:
        print(f"- {getattr(chunk, 'document_name', '')}: {getattr(chunk, 'similarity', 0):.3f}")
    if not mineru_hits:
        raise SystemExit("No MinerU document appeared in the retrieval results.")
    print(f"MinerU retrieval verified: {mineru_hits[0].document_name}")


if __name__ == "__main__":
    main()
