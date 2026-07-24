from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge_base"
DATASETS_DIR = KNOWLEDGE_BASE / "datasets"
INDEX_FILE = PROJECT_ROOT / "data" / "multimodal_index.json"
REPORT_FILE = PROJECT_ROOT / "outputs" / "multimodal_snapshot_report.json"


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            yield value


def labelled_value(text: str, label: str) -> str:
    match = re.search(rf"(?:^|\n){re.escape(label)}[：:]\s*(.+?)(?=\n\S+[：:]|\Z)", text, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def table_rows(content: str) -> list[list[str]]:
    soup = BeautifulSoup(content, "html.parser")
    rows: list[list[str]] = []
    for row in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip() for cell in row.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def compact_text(content: str, limit: int = 500) -> str:
    text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def normalized_name(name: str) -> str:
    value = re.sub(r"\.(md|pdf|docx?|xlsx?|html?)$", "", name, flags=re.I)
    return re.sub(r"^\d+_\d+_", "", value).strip()


def build_index() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_images: set[str] = set()
    seen_tables: set[str] = set()
    missing_assets: list[str] = []
    dataset_count = 0

    for dataset_dir in sorted(DATASETS_DIR.glob("*")):
        if not dataset_dir.is_dir():
            continue
        dataset_count += 1
        try:
            summary = json.loads((dataset_dir / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            summary = {}
        dataset_name = str(summary.get("name") or dataset_dir.name)
        documents = {
            str(row.get("id") or ""): row
            for row in read_jsonl(dataset_dir / "documents.jsonl")
            if row.get("id")
        }

        for chunk in read_jsonl(dataset_dir / "chunks.jsonl"):
            content = str(chunk.get("content") or "")
            document = documents.get(str(chunk.get("document_id") or ""), {})
            document_name = normalized_name(str(document.get("name") or "知识库文档"))
            image_path = str(chunk.get("image_blob_path") or "").replace("\\", "/").lstrip("/")

            if image_path:
                image_sha = str(chunk.get("image_sha256") or Path(image_path).stem)
                if image_sha in seen_images:
                    continue
                seen_images.add(image_sha)
                absolute_asset = (KNOWLEDGE_BASE / image_path).resolve()
                if not absolute_asset.is_relative_to(KNOWLEDGE_BASE.resolve()) or not absolute_asset.is_file():
                    missing_assets.append(image_path)
                    continue

                parsed_document = labelled_value(content, "文档")
                caption = labelled_value(content, "视觉描述")
                visible_text = labelled_value(content, "可见文字")
                visual_type = labelled_value(content, "类型")
                page_text = labelled_value(content, "页码")
                keywords = labelled_value(content, "检索关键词")
                questions = [str(value) for value in (chunk.get("questions") or []) if value]
                important = [str(value) for value in (chunk.get("important_keywords") or []) if value]
                items.append(
                    {
                        "id": f"image-{image_sha[:16]}",
                        "type": "image",
                        "is_table": "表格" in visual_type,
                        "visual_type": visual_type or "文档图片",
                        "document": parsed_document or document_name,
                        "document_name": document_name,
                        "page": page_text,
                        "caption": caption or compact_text(content, 260),
                        "context": content,
                        "snippet": compact_text(content),
                        "visible_text": visible_text,
                        "keywords": important + ([keywords] if keywords else []),
                        "questions": questions,
                        "asset_path": image_path,
                        "url": f"/knowledge-assets/{image_path}",
                        "content_type": str(chunk.get("image_content_type") or "image/jpeg"),
                        "source_dataset": dataset_name,
                        "source_dataset_id": dataset_dir.name,
                        "source_document_id": str(chunk.get("document_id") or ""),
                        "sha256": image_sha,
                    }
                )
                continue

            if "<table" not in content.lower():
                continue
            rows = table_rows(content)
            if not rows:
                continue
            fingerprint_source = json.dumps(
                {"document": document_name, "rows": rows},
                ensure_ascii=False,
                sort_keys=True,
            )
            fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
            if fingerprint in seen_tables:
                continue
            seen_tables.add(fingerprint)
            items.append(
                {
                    "id": f"table-{fingerprint[:16]}",
                    "type": "table",
                    "is_table": True,
                    "visual_type": "结构化表格",
                    "document": document_name,
                    "document_name": document_name,
                    "page": "",
                    "caption": f"{document_name}中的结构化表格",
                    "context": compact_text(content, 1000),
                    "snippet": compact_text(content),
                    "visible_text": compact_text(content, 1000),
                    "keywords": [str(value) for value in (chunk.get("important_keywords") or []) if value],
                    "questions": [str(value) for value in (chunk.get("questions") or []) if value],
                    "rows": rows,
                    "url": "",
                    "source_dataset": dataset_name,
                    "source_dataset_id": dataset_dir.name,
                    "source_document_id": str(chunk.get("document_id") or ""),
                    "sha256": fingerprint,
                }
            )

    items.sort(key=lambda item: (str(item.get("document") or ""), str(item.get("id") or "")))
    physical_images = sum(1 for item in items if item.get("asset_path"))
    structured_tables = sum(1 for item in items if item.get("rows"))
    report = {
        "datasets_scanned": dataset_count,
        "items": len(items),
        "physical_images": physical_images,
        "table_images": sum(1 for item in items if item.get("asset_path") and item.get("is_table")),
        "structured_tables": structured_tables,
        "documents": len({item.get("document") for item in items if item.get("document")}),
        "missing_assets": sorted(set(missing_assets)),
    }
    return items, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the multimodal index from the local RAGFlow snapshot.")
    parser.add_argument("--check", action="store_true", help="Validate without replacing the index.")
    args = parser.parse_args()
    items, report = build_index()
    if not args.check:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not items or report["missing_assets"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
