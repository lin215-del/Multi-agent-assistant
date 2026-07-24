from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "knowledge_base"
DEFAULT_BASE_URL = "http://localhost:8080/api/v1"
WRITE_LOCK = threading.Lock()

DATASET_FIELDS = (
    "id",
    "name",
    "description",
    "document_count",
    "chunk_count",
    "embedding_model",
    "chunk_method",
    "parser_config",
    "pipeline_id",
    "create_date",
    "update_date",
)
DOCUMENT_FIELDS = (
    "id",
    "name",
    "suffix",
    "size",
    "chunk_count",
    "token_count",
    "run",
    "status",
    "source_type",
    "parser_config",
    "meta_fields",
    "create_date",
    "update_date",
)
CHUNK_FIELDS = (
    "id",
    "document_id",
    "content",
    "important_keywords",
    "questions",
    "available",
    "image_id",
    "positions",
    "tag_kwd",
)
SECRET_PATTERNS = (
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"bce-v3/[A-Za-z0-9_./-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
)
SNAPSHOT_README = """# RAGFlow 知识库快照

本目录由 `ragflow/export_knowledge_bases.py` 从本机 RAGFlow REST API 导出，用于团队审阅、版本归档和离线备份。

包含 `manifest.json`、各知识库的配置/文档/分块、按 SHA-256 去重的文档原件与原生图片，以及 `SHA256SUMS.txt`。

不包含 RAGFlow API Token、模型 API Key、数据库密码、账号、昵称、创建者 ID、反馈日志和聊天记录。

重新导出：

```powershell
python ragflow\\export_knowledge_bases.py --workers 8
```
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with WRITE_LOCK:
        if path.exists() and path.read_bytes() == data:
            return
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)


def write_json(path: Path, data: Any) -> None:
    atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write(path, content.encode("utf-8"))


def public_fields(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: value.get(field) for field in fields if field in value}


def safe_suffix(value: str, fallback: str = "bin") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower().lstrip("."))
    return cleaned[:12] or fallback


class RagflowExporter:
    def __init__(self, base_url: str, output: Path, workers: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.output = output
        self.workers = max(1, workers)
        self.headers = {"Authorization": f"Bearer {get_api_key()}"}

    def json_request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = requests.get(
            f"{self.base_url}{path}", headers=self.headers, params=params, timeout=180
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or payload)
        return payload.get("data")

    def binary_request(self, path: str) -> tuple[bytes, str]:
        response = requests.get(f"{self.base_url}{path}", headers=self.headers, timeout=180)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
        return response.content, content_type

    def list_datasets(self) -> list[dict[str, Any]]:
        return self.json_request("/datasets", params={"page": 1, "page_size": 100})

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.json_request(
                f"/datasets/{dataset_id}/documents",
                params={"page": page, "page_size": 100, "orderby": "create_time", "desc": False},
            )
            batch = data.get("docs", [])
            documents.extend(batch)
            if len(batch) < 100:
                return documents
            page += 1

    def list_chunks(self, dataset_id: str, document_id: str) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.json_request(
                f"/datasets/{dataset_id}/documents/{document_id}/chunks",
                params={"page": page, "page_size": 100},
            )
            batch = data.get("chunks", [])
            chunks.extend(batch)
            if len(batch) < 100:
                return chunks
            page += 1

    def store_blob(self, category: str, data: bytes, suffix: str) -> tuple[str, str]:
        digest = sha256(data)
        relative = Path("blobs") / category / digest[:2] / f"{digest}.{safe_suffix(suffix)}"
        atomic_write(self.output / relative, data)
        return digest, relative.as_posix()

    def export_document(self, dataset_id: str, document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        document_id = str(document["id"])
        file_data, file_type = self.binary_request(f"/datasets/{dataset_id}/documents/{document_id}")
        suffix = str(document.get("suffix") or mimetypes.guess_extension(file_type) or "bin")
        file_hash, file_path = self.store_blob("documents", file_data, suffix)
        exported_document = {
            **public_fields(document, DOCUMENT_FIELDS),
            "sha256": file_hash,
            "blob_path": file_path,
            "content_type": file_type,
        }

        exported_chunks = []
        for chunk in self.list_chunks(dataset_id, document_id):
            exported = public_fields(chunk, CHUNK_FIELDS)
            image_id = str(chunk.get("image_id") or "")
            if image_id:
                image_data, image_type = self.binary_request(f"/documents/images/{image_id}")
                image_suffix = mimetypes.guess_extension(image_type) or ".bin"
                image_hash, image_path = self.store_blob("images", image_data, image_suffix)
                exported.update(
                    {
                        "image_sha256": image_hash,
                        "image_blob_path": image_path,
                        "image_content_type": image_type,
                    }
                )
            exported_chunks.append(exported)
        return exported_document, exported_chunks

    def export_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(dataset["id"])
        documents = self.list_documents(dataset_id)
        exported_documents: list[dict[str, Any]] = []
        exported_chunks: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.export_document, dataset_id, document): document for document in documents
            }
            for future in as_completed(futures):
                document = futures[future]
                try:
                    document_result, chunks = future.result()
                    exported_documents.append(document_result)
                    exported_chunks.extend(chunks)
                except Exception as exc:
                    errors.append({"document_id": str(document.get("id")), "name": str(document.get("name")), "error": str(exc)})
                completed += 1
                if completed % 25 == 0 or completed == len(documents):
                    print(f"  {dataset.get('name')}: {completed}/{len(documents)}", flush=True)

        exported_documents.sort(key=lambda item: (str(item.get("name")), str(item.get("id"))))
        exported_chunks.sort(key=lambda item: (str(item.get("document_id")), str(item.get("id"))))
        dataset_dir = self.output / "datasets" / dataset_id
        write_json(dataset_dir / "dataset.json", public_fields(dataset, DATASET_FIELDS))
        write_jsonl(dataset_dir / "documents.jsonl", exported_documents)
        write_jsonl(dataset_dir / "chunks.jsonl", exported_chunks)
        summary = {
            "id": dataset_id,
            "name": dataset.get("name"),
            "documents": len(exported_documents),
            "chunks": len(exported_chunks),
            "image_chunks": sum(bool(item.get("image_id")) for item in exported_chunks),
            "errors": errors,
            "path": f"datasets/{dataset_id}",
        }
        write_json(dataset_dir / "summary.json", summary)
        return summary

    def verify_no_secrets(self) -> None:
        for path in self.output.rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            for pattern in SECRET_PATTERNS:
                if pattern.search(data):
                    raise RuntimeError(f"Potential credential found in export: {path.relative_to(self.output)}")

    def checksums(self) -> None:
        rows = []
        for path in sorted(item for item in self.output.rglob("*") if item.is_file()):
            relative = path.relative_to(self.output).as_posix()
            if relative == "SHA256SUMS.txt":
                continue
            rows.append(f"{sha256(path.read_bytes())}  {relative}")
        atomic_write(self.output / "SHA256SUMS.txt", ("\n".join(rows) + "\n").encode("utf-8"))

    def run(self) -> dict[str, Any]:
        if self.output.exists():
            resolved = self.output.resolve()
            if resolved == PROJECT_ROOT.resolve() or PROJECT_ROOT.resolve() not in resolved.parents:
                raise RuntimeError("Export directory must be inside the project root")
            shutil.rmtree(self.output)
        self.output.mkdir(parents=True)
        atomic_write(self.output / "README.md", SNAPSHOT_README.encode("utf-8"))
        datasets = sorted(self.list_datasets(), key=lambda item: str(item.get("name")))
        summaries = []
        for dataset in datasets:
            print(f"Exporting {dataset.get('name')} ({dataset.get('id')})", flush=True)
            summaries.append(self.export_dataset(dataset))
        manifest = {
            "schema_version": "1.0",
            "exported_at": now_iso(),
            "source": "RAGFlow REST API",
            "dataset_count": len(summaries),
            "document_count": sum(item["documents"] for item in summaries),
            "chunk_count": sum(item["chunks"] for item in summaries),
            "image_chunk_count": sum(item["image_chunks"] for item in summaries),
            "datasets": summaries,
        }
        write_json(self.output / "manifest.json", manifest)
        self.verify_no_secrets()
        self.checksums()
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export all owned RAGFlow knowledge bases without credentials.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    exporter = RagflowExporter(args.base_url, output.resolve(), args.workers)
    result = exporter.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(dataset["errors"] for dataset in result["datasets"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
