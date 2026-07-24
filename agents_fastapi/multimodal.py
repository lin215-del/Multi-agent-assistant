"""Multimodal assets: load and search the visual media index."""

import json
import os
import re
from pathlib import Path
from typing import Any

from .retriever import normalized_document_name

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_INDEX_FILE = _PROJECT_ROOT / "data" / "multimodal_index.json"
_KNOWLEDGE_BASE_DIR = _PROJECT_ROOT / "knowledge_base"


def load_multimodal_index() -> list[dict[str, Any]]:
    if not _INDEX_FILE.exists():
        return []
    try:
        value = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError, TypeError):
        return []


def find_multimodal_assets(
    question: str,
    document_name: str,
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = load_multimodal_index()
    if not index:
        return []
    hay = " ".join(
        [question, document_name]
        + [str(m.get("document_name", "")) + " " + str(m.get("snippet", "")) for m in matches]
    )
    query_terms = [
        term
        for seg in re.findall(r"[一-鿿]{2,}", hay)
        for term in (seg, *[seg[i : i + 2] for i in range(len(seg) - 1)])
    ]
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in index:
        asset_path = str(item.get("asset_path") or "")
        has_asset = bool(asset_path and (_KNOWLEDGE_BASE_DIR / asset_path).is_file())
        has_rows = bool(item.get("rows"))
        if not has_asset and not has_rows:
            continue
        blob = " ".join(
            str(item.get(k, ""))
            for k in ["document", "document_name", "caption", "snippet", "visible_text", "keywords", "questions"]
        )
        score = 0
        for m in matches:
            name = str(m.get("document_name", ""))
            n = normalized_document_name(name)
            if n and n[:18] in normalized_document_name(blob):
                score += 8
        nd = normalized_document_name(document_name)
        if nd and nd[:18] in normalized_document_name(blob):
            score += 10
        score += min(8, sum(1 for t in dict.fromkeys(query_terms) if len(t) >= 2 and t in blob))
        if score:
            scored.append((score, item))
    scored.sort(key=lambda v: (v[0], bool(v[1].get("asset_path"))), reverse=True)
    if not scored:
        return []
    min_score = max(3, scored[0][0] - 4)
    return [item for score, item in scored if score >= min_score][:6]


def multimodal_stats() -> dict[str, int]:
    index = load_multimodal_index()
    return {
        "total": len(index),
        "images": sum(1 for x in index if x.get("asset_path")),
        "tables": sum(1 for x in index if x.get("is_table") or x.get("rows")),
        "structured_tables": sum(1 for x in index if x.get("rows")),
        "resolved": sum(
            1 for x in index
            if x.get("rows") or (x.get("asset_path") and (_KNOWLEDGE_BASE_DIR / str(x.get("asset_path"))).is_file())
        ),
        "documents": len({x.get("document") for x in index if x.get("document")}),
    }
