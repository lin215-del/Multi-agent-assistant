from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"
MARKDOWN_DIR = PROJECT_ROOT / "data" / "cleaned" / "ragflow_markdown"
SERVICE_CARD_DIR = PROJECT_ROOT / "data" / "cleaned" / "service_cards"
MINERU_DIR = PROJECT_ROOT / "data" / "cleaned" / "mineru_ragflow"
MINERU_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "manifest.jsonl"
FILES_DIR = PROJECT_ROOT / "data" / "files"

DATASET_NAME = os.getenv("RAGFLOW_DATASET_NAME", "暨南大学学生助手-第一阶段")
DATASET_DESCRIPTION = "暨南大学学生常用办事指南、表格模板、学籍、新生、选课、推免、实践教学等公开官方资料。"
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
REFRESH = os.getenv("RAGFLOW_REFRESH_PHASE1", "").lower() in {"1", "true", "yes"}
SUPPORTED_EXTRA_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md"}


def mineru_replaced_sources() -> set[str]:
    latest: dict[str, dict] = {}
    if not MINERU_MANIFEST.exists():
        return set()
    with MINERU_MANIFEST.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("source"):
                latest[row["source"]] = row
    return {name for name, row in latest.items() if row.get("status") == "success"}


def load_sdk() -> None:
    sys.path.insert(0, str(RAGFLOW_SDK))


def collect_upload_files() -> list[dict]:
    paths = sorted(MARKDOWN_DIR.glob("*.md"))
    if SERVICE_CARD_DIR.exists():
        paths.extend(sorted(SERVICE_CARD_DIR.glob("*.md")))
    if MINERU_DIR.exists():
        paths.extend(sorted(MINERU_DIR.glob("*.md")))
    replaced_sources = mineru_replaced_sources()
    paths.extend(
        path
        for path in sorted(FILES_DIR.glob("*"))
        if path.suffix.lower() in SUPPORTED_EXTRA_SUFFIXES and path.name not in replaced_sources
    )

    docs: list[dict] = []
    for path in paths:
        docs.append({"display_name": path.name, "blob": path.open("rb")})
    return docs


def close_files(docs: list[dict]) -> None:
    for doc in docs:
        doc["blob"].close()


def list_all_documents(dataset) -> list:
    documents = []
    page = 1
    while True:
        batch = dataset.list_documents(page=page, page_size=100)
        documents.extend(batch)
        if len(batch) < 100:
            return documents
        page += 1


def main() -> None:
    if not MARKDOWN_DIR.exists():
        raise SystemExit(f"Markdown directory not found: {MARKDOWN_DIR}")

    load_sdk()
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=get_api_key(), base_url=BASE_URL)

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
        existing_docs = list_all_documents(dataset)
        if existing_docs:
            dataset.delete_documents(ids=[doc.id for doc in existing_docs])
            print(f"Deleted {len(existing_docs)} existing documents for refresh.")

    existing_names = {doc.name for doc in list_all_documents(dataset)}
    all_docs = collect_upload_files()
    docs = [doc for doc in all_docs if doc["display_name"] not in existing_names]
    skipped = len(all_docs) - len(docs)
    for doc in all_docs:
        if doc not in docs:
            doc["blob"].close()
    if not docs:
        print(f"No new files to upload. Existing/skipped: {skipped}")
        return

    try:
        uploaded = dataset.upload_documents(docs)
        print(f"Uploaded {len(uploaded)} files. Existing/skipped: {skipped}")
        document_ids = [doc.id for doc in uploaded]
    finally:
        close_files(docs)

    print("Starting parse/index...")
    statuses = dataset.parse_documents(document_ids)
    for doc_id, run, chunk_count, token_count in statuses:
        print(f"{doc_id}: {run}, chunks={chunk_count}, tokens={token_count}")
    print("Import finished.")


if __name__ == "__main__":
    main()
