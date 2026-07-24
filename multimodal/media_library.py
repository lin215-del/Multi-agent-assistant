from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MULTIMODAL_DIR = PROJECT_ROOT / "data" / "cleaned" / "multimodal"
MINERU_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "manifest.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _source_paths() -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for row in _read_jsonl(MINERU_MANIFEST):
        source = str(row.get("source") or "")
        raw_path = row.get("source_path")
        if not source or not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            paths[source] = path.resolve()
    return paths


def build_media_library() -> dict[str, Any]:
    source_paths = _source_paths()
    documents: dict[str, dict[str, Any]] = {}
    media_paths: dict[str, Path] = {}
    source_files: dict[str, Path] = {}
    image_count = 0
    table_count = 0

    for json_path in sorted(MULTIMODAL_DIR.glob("multimodal__*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        content_list = PROJECT_ROOT / str(data.get("mineru_content_list") or "")
        asset_root = content_list.parent
        source_name = str(data.get("source_file") or "")
        source_sha = str(data.get("source_sha256") or "")
        source_path = source_paths.get(source_name)
        source_url = ""
        if source_path:
            source_token = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:24]
            source_files[source_token] = source_path
            source_url = f"/multimodal-source/{source_token}{source_path.suffix.lower()}"

        document_name = f"{json_path.stem}.md"
        record = {
            "document_name": document_name,
            "title": str(data.get("title") or source_name or json_path.stem),
            "source_file": source_name,
            "source_url": source_url,
            "media": [],
        }
        for unit in data.get("units", []):
            kind = str(unit.get("type") or "")
            image_path = str(unit.get("image_path") or "")
            if kind not in {"image", "table"} or not image_path:
                continue
            path = (asset_root / image_path).resolve()
            if not path.exists() or not path.is_file():
                continue
            token_seed = f"{source_sha}:{unit.get('unit_id')}:{path.name}"
            token = hashlib.sha256(token_seed.encode("utf-8")).hexdigest()[:24]
            media_paths[token] = path
            captions = [str(item).strip() for item in unit.get("caption", []) if str(item).strip()]
            context = [str(item).strip() for item in unit.get("context", []) if str(item).strip()]
            visual_description = str(unit.get("visual_description") or "").strip()
            visual_visible_text = str(unit.get("visual_visible_text") or "").strip()
            visual_keywords = [str(item).strip() for item in unit.get("visual_keywords", []) if str(item).strip()]
            caption = visual_description or "；".join(captions) or (context[-1][:160] if context else "")
            if kind == "image":
                image_count += 1
            else:
                table_count += 1
            record["media"].append(
                {
                    "id": token,
                    "type": kind,
                    "url": f"/media/{token}{path.suffix.lower()}",
                    "caption": caption or ("表格截图" if kind == "table" else "文档图片"),
                    "page": int(unit.get("source_page") or 0),
                    "unit_id": str(unit.get("unit_id") or ""),
                    "visual_description": visual_description,
                    "visible_text": visual_visible_text,
                    "keywords": visual_keywords,
                }
            )
        if record["media"]:
            documents[document_name] = record

    items = []
    for document in documents.values():
        for medium in document["media"]:
            items.append(
                {
                    **medium,
                    "document_name": document["document_name"],
                    "title": document["title"],
                    "source_file": document["source_file"],
                    "source_url": document["source_url"],
                }
            )
    return {
        "summary": {
            "documents": len(documents),
            "media": len(items),
            "images": image_count,
            "tables": table_count,
        },
        "documents": documents,
        "items": items,
        "_media_paths": media_paths,
        "_source_files": source_files,
    }


def public_media_library(limit: int | None = None) -> dict[str, Any]:
    library = build_media_library()
    items = library["items"] if limit is None else library["items"][:limit]
    return {"summary": library["summary"], "items": items}


def media_for_document(document_name: str, limit: int = 4) -> list[dict[str, Any]]:
    record = build_media_library()["documents"].get(Path(document_name).name)
    return list(record.get("media", []))[:limit] if record else []


def _bigrams(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())
    return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}


def related_media(question: str, limit: int = 4) -> list[dict[str, Any]]:
    question_terms = _bigrams(question)
    if not question_terms:
        return []
    ranked = []
    for document in build_media_library()["documents"].values():
        searchable = " ".join(
            [
                str(document.get("title") or ""),
                str(document.get("source_file") or ""),
                *[str(item.get("caption") or "") for item in document.get("media", [])],
                *[str(item.get("visible_text") or "") for item in document.get("media", [])],
                *[" ".join(item.get("keywords") or []) for item in document.get("media", [])],
            ]
        )
        overlap = len(question_terms & _bigrams(searchable))
        if overlap >= 4:
            ranked.append((overlap, document))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for _, document in ranked:
        for medium in document["media"]:
            selected.append(
                {
                    **medium,
                    "title": document["title"],
                    "source_url": document["source_url"],
                }
            )
            if len(selected) >= limit:
                return selected
    return selected


def multimodal_document(document_name: str) -> dict[str, Any] | None:
    record = build_media_library()["documents"].get(Path(document_name).name)
    if not record:
        return None
    return {key: value for key, value in record.items() if key != "media"} | {
        "media": list(record["media"][:4])
    }


def resolve_public_file(request_path: str) -> tuple[Path, str] | None:
    library = build_media_library()
    parts = request_path.strip("/").split("/")
    if len(parts) != 2:
        return None
    route, filename = parts
    token = filename.split(".", 1)[0]
    if route == "media":
        path = library["_media_paths"].get(token)
    elif route == "multimodal-source":
        path = library["_source_files"].get(token)
    else:
        return None
    if not path or not path.exists():
        return None
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path, mime_type


def attach_media(result: dict[str, Any], question: str = "") -> dict[str, Any]:
    for match in result.get("matches", []):
        match["media"] = media_for_document(str(match.get("document_name") or ""))
    direct_media = media_for_document(str(result.get("document_name") or ""))
    result["media"] = direct_media or related_media(question)
    return result
