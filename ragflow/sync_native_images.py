from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
EXPERIMENT_STATE = PROJECT_ROOT / "outputs" / "chunk_experiment_state.json"
SYNC_STATE = PROJECT_ROOT / "outputs" / "native_image_sync.json"
BASE_URL = "http://localhost:8080/api/v1"


class RagflowClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {get_api_key()}"})

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method, f"{self.base_url}{path}", timeout=180, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or payload)
        return payload.get("data")

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.request(
                "GET",
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
            data = self.request(
                "GET",
                f"/datasets/{dataset_id}/documents/{document_id}/chunks",
                params={"page": page, "page_size": 100},
            )
            batch = data.get("chunks", [])
            chunks.extend(batch)
            if len(batch) < 100:
                return chunks
            page += 1

    def add_image_chunk(
        self,
        dataset_id: str,
        document_id: str,
        content: str,
        keywords: list[str],
        questions: list[str],
        image_path: Path,
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data = self.request(
            "POST",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks",
            json={
                "content": content,
                "important_keywords": keywords,
                "questions": questions,
                "image_base64": encoded,
            },
        )
        return data.get("chunk", {})

    def delete_chunks(self, dataset_id: str, document_id: str, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self.request(
                "DELETE",
                f"/datasets/{dataset_id}/documents/{document_id}/chunks",
                json={"chunk_ids": chunk_ids, "delete_all": False},
            )

    def verify_image(self, image_id: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/documents/images/{image_id}", timeout=60)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/") or not response.content:
            raise RuntimeError(f"RAGFlow returned an invalid image response: {content_type}")
        return {"content_type": content_type, "bytes": len(response.content)}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_state(data: dict[str, Any]) -> None:
    SYNC_STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SYNC_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SYNC_STATE)


def load_targets(labels: list[str]) -> list[tuple[str, str, str]]:
    state = json.loads(EXPERIMENT_STATE.read_text(encoding="utf-8"))
    experiments = state.get("experiments", {})
    targets = []
    for label in labels:
        experiment = experiments.get(label)
        if not experiment:
            raise RuntimeError(f"Unknown or unavailable experiment: {label}")
        targets.append((label, experiment["dataset_id"], experiment["dataset_name"]))
    return targets


def build_content(item: dict[str, Any]) -> str:
    kind = "表格截图" if item.get("type") == "table" else "图片"
    keywords = "、".join(item.get("keywords") or [])
    return "\n".join(
        line
        for line in (
            f"原生视觉单元：{item['unit_id']}",
            f"文档：{item['title']}",
            f"页码：第 {item.get('page') or '未知'} 页",
            f"类型：{kind}",
            f"视觉描述：{item.get('visual_description') or item.get('caption') or '无'}",
            f"可见文字：{item.get('visible_text') or '无'}",
            f"检索关键词：{keywords}" if keywords else "",
            "来源：MinerU 多模态解析及视觉模型清洗",
        )
        if line
    )


def questions_for(item: dict[str, Any]) -> list[str]:
    title = str(item.get("title") or "该材料")
    page = item.get("page") or "相关"
    return [
        f"{title}第{page}页的图片展示了什么？",
        f"{title}中的{item.get('caption') or '图片内容'}在哪里？",
    ]


def sync_dataset(
    client: RagflowClient,
    label: str,
    dataset_id: str,
    dataset_name: str,
    items: list[dict[str, Any]],
    media_paths: dict[str, Path],
    limit: int | None,
) -> dict[str, Any]:
    documents = {item["name"]: item for item in client.list_documents(dataset_id)}
    summary: dict[str, Any] = {
        "label": label,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "created": 0,
        "skipped": 0,
        "replaced": 0,
        "failed": 0,
        "verified": 0,
        "image_ids": [],
        "errors": [],
    }
    selected = items[:limit] if limit else items
    chunk_cache: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        document = documents.get(item["document_name"])
        image_path = media_paths.get(item["id"])
        if not document or not image_path:
            summary["failed"] += 1
            summary["errors"].append(
                {"unit_id": item["unit_id"], "error": "Matching RAGFlow document or local image is missing"}
            )
            continue
        document_id = document["id"]
        try:
            if document_id not in chunk_cache:
                chunk_cache[document_id] = client.list_chunks(dataset_id, document_id)
            marker = f"原生视觉单元：{item['unit_id']}"
            existing = [chunk for chunk in chunk_cache[document_id] if marker in str(chunk.get("content") or "")]
            content = build_content(item)
            current = next(
                (
                    chunk
                    for chunk in existing
                    if chunk.get("image_id") and str(chunk.get("content") or "").strip() == content.strip()
                ),
                None,
            )
            if current:
                image_id = current["image_id"]
                summary["skipped"] += 1
            else:
                if existing:
                    client.delete_chunks(dataset_id, document_id, [chunk["id"] for chunk in existing])
                    summary["replaced"] += 1
                chunk = client.add_image_chunk(
                    dataset_id,
                    document_id,
                    content,
                    list(dict.fromkeys(item.get("keywords") or []))[:12],
                    questions_for(item),
                    image_path,
                )
                image_id = str(chunk.get("image_id") or "")
                if not image_id:
                    raise RuntimeError("RAGFlow created the chunk without image_id")
                summary["created"] += 1
            verification = client.verify_image(image_id)
            summary["verified"] += 1
            summary["image_ids"].append(
                {
                    "unit_id": item["unit_id"],
                    "document_name": item["document_name"],
                    "image_id": image_id,
                    **verification,
                }
            )
        except Exception as exc:
            summary["failed"] += 1
            summary["errors"].append({"unit_id": item["unit_id"], "error": str(exc)})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Store MinerU visual units as native RAGFlow image chunks.")
    parser.add_argument("--datasets", action="append", choices=["A", "B", "C"], default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    from multimodal.media_library import build_media_library

    labels = args.datasets or ["C"]
    library = build_media_library()
    client = RagflowClient(args.base_url)
    result = {
        "generated_at": now_iso(),
        "source": "MinerU visual units",
        "media_count": len(library["items"]),
        "datasets": [],
    }
    for label, dataset_id, dataset_name in load_targets(labels):
        summary = sync_dataset(
            client,
            label,
            dataset_id,
            dataset_name,
            library["items"],
            library["_media_paths"],
            args.limit,
        )
        result["datasets"].append(summary)
        print(
            f"{label}: created={summary['created']} skipped={summary['skipped']} "
            f"verified={summary['verified']} failed={summary['failed']}",
            flush=True,
        )
    write_state(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(dataset["failed"] for dataset in result["datasets"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
