from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGFLOW_SDK = PROJECT_ROOT.parent / "ragflow" / "sdk" / "python"
MINERU_DIR = PROJECT_ROOT / "data" / "cleaned" / "mineru_ragflow"
FILES_DIR = PROJECT_ROOT / "data" / "files"
PARSE_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "manifest.jsonl"
IMPORT_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "ragflow_import.jsonl"
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
DATASET_ID = os.getenv("RAGFLOW_PHASE1_DATASET_ID", "683cdc4a82a511f1b2e527d9437de36f")


def append_result(row: dict) -> None:
    IMPORT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with IMPORT_MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def list_all_documents(dataset) -> list:
    documents = []
    page = 1
    while True:
        batch = dataset.list_documents(page=page, page_size=100)
        documents.extend(batch)
        if len(batch) < 100:
            return documents
        page += 1


def successful_replacements() -> dict[str, str]:
    latest: dict[str, dict] = {}
    if not PARSE_MANIFEST.exists():
        return {}
    with PARSE_MANIFEST.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("source"):
                latest[row["source"]] = row
    replacements = {}
    for source_name, row in latest.items():
        if row.get("status") != "success" or not row.get("ragflow_markdown"):
            continue
        replacements[Path(row["ragflow_markdown"]).name] = source_name
    return replacements


def main() -> None:
    if not MINERU_DIR.exists():
        raise SystemExit("No MinerU RAGFlow Markdown found. Run multimodal/mineru_pipeline.py first.")

    sys.path.insert(0, str(RAGFLOW_SDK))
    from ragflow_sdk import RAGFlow

    rag = RAGFlow(api_key=get_api_key(), base_url=BASE_URL)
    datasets = rag.list_datasets(page_size=100)
    dataset = next((item for item in datasets if item.id == DATASET_ID), None)
    if dataset is None:
        raise SystemExit(f"RAGFlow dataset not found or not owned by this account: {DATASET_ID}")

    existing_documents = list_all_documents(dataset)
    existing = {doc.name for doc in existing_documents}
    paths = sorted(MINERU_DIR.glob("*.md"))
    pending = [path for path in paths if path.name not in existing]
    if pending:
        docs = [{"display_name": path.name, "blob": path.open("rb")} for path in pending]
        try:
            uploaded = dataset.upload_documents(docs)
        finally:
            for doc in docs:
                doc["blob"].close()

        print(f"Uploaded {len(uploaded)} MinerU documents to {dataset.name} ({dataset.id}).")
        uploaded_names = {doc.id: doc.name for doc in uploaded}
        statuses = dataset.parse_documents([doc.id for doc in uploaded])
        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for document_id, run, chunk_count, token_count in statuses:
            row = {
                "document_id": document_id,
                "document_name": uploaded_names.get(document_id, ""),
                "status": str(run),
                "chunks": chunk_count,
                "tokens": token_count,
                "dataset_id": dataset.id,
                "finished_at": finished_at,
            }
            append_result(row)
            print(f"{document_id}: {run}, chunks={chunk_count}, tokens={token_count}")
    else:
        print(f"No new MinerU documents. Existing/skipped: {len(paths)}")

    current_documents = list_all_documents(dataset)
    current_names = {doc.name for doc in current_documents}
    replacements = successful_replacements()
    preserved_sources = {
        source_name for mineru_name, source_name in replacements.items() if mineru_name in current_names
    }
    attachment_paths = [
        path
        for path in sorted(FILES_DIR.glob("*"))
        if path.name in preserved_sources and path.name not in current_names
    ]
    if attachment_paths:
        attachment_docs = [{"display_name": path.name, "blob": path.open("rb")} for path in attachment_paths]
        try:
            uploaded_attachments = dataset.upload_documents(attachment_docs)
        finally:
            for doc in attachment_docs:
                doc["blob"].close()
        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for document in uploaded_attachments:
            append_result(
                {
                    "document_id": document.id,
                    "document_name": document.name,
                    "status": "ATTACHMENT_ONLY",
                    "chunks": 0,
                    "tokens": 0,
                    "dataset_id": dataset.id,
                    "finished_at": finished_at,
                }
            )
        print(
            f"Preserved {len(uploaded_attachments)} original attachment(s) without parsing; "
            "MinerU Markdown remains the searchable copy."
        )


if __name__ == "__main__":
    main()
