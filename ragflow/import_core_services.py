from __future__ import annotations

import os
import sys
from pathlib import Path

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"
SERVICE_CARD_DIR = PROJECT_ROOT / "data" / "cleaned" / "service_cards"

DATASET_NAME = os.getenv("RAGFLOW_CORE_DATASET_NAME", "暨南大学学生助手-核心服务卡片")
DATASET_DESCRIPTION = "暨南大学学生高频办事材料、表格模板和来源链接，用于第一阶段稳定问答演示。"
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
REFRESH = os.getenv("RAGFLOW_REFRESH_CORE", "").lower() in {"1", "true", "yes"}


def main() -> None:
    api_key = get_api_key()
    if not SERVICE_CARD_DIR.exists():
        raise SystemExit(f"Service card directory not found: {SERVICE_CARD_DIR}")

    sys.path.insert(0, str(RAGFLOW_SDK))
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=api_key, base_url=BASE_URL)
    try:
        datasets = rag.list_datasets(name=DATASET_NAME)
    except Exception as exc:
        if "lacks permission for dataset" not in str(exc):
            raise
        datasets = []
    if datasets:
        dataset = datasets[0]
        print(f"Using existing dataset: {dataset.name} ({dataset.id})")
    else:
        dataset = rag.create_dataset(
            name=DATASET_NAME,
            description=DATASET_DESCRIPTION,
            permission="me",
            chunk_method="naive",
        )
        print(f"Created dataset: {dataset.name} ({dataset.id})")

    if REFRESH:
        existing = list(dataset.list_documents(page_size=100))
        if existing:
            dataset.delete_documents(ids=[doc.id for doc in existing])
            print(f"Deleted {len(existing)} existing documents for refresh.")

    existing_names = {doc.name for doc in dataset.list_documents(page_size=100)}
    upload_docs: list[dict] = []
    for path in sorted(SERVICE_CARD_DIR.glob("*.md")):
        if path.name in existing_names:
            continue
        upload_docs.append({"display_name": path.name, "blob": path.open("rb")})

    if not upload_docs:
        print("No new service cards to upload.")
        print(f"Dataset summary: docs={dataset.document_count}, chunks={dataset.chunk_count}")
        return

    try:
        uploaded = dataset.upload_documents(upload_docs)
        print(f"Uploaded {len(uploaded)} service cards.")
        statuses = dataset.parse_documents([doc.id for doc in uploaded])
    finally:
        for doc in upload_docs:
            doc["blob"].close()

    for doc_id, run, chunk_count, token_count in statuses:
        print(f"{doc_id}: {run}, chunks={chunk_count}, tokens={token_count}")

    refreshed = rag.list_datasets(id=dataset.id)[0]
    print(f"Dataset summary: {refreshed.name} ({refreshed.id}), docs={refreshed.document_count}, chunks={refreshed.chunk_count}")


if __name__ == "__main__":
    main()
