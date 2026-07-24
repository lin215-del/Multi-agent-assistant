from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEANED_DOCS = PROJECT_ROOT / "data" / "cleaned" / "documents.jsonl"
SERVICE_CARDS = PROJECT_ROOT / "data" / "cleaned" / "service_cards"
MULTIMODAL_DIR = PROJECT_ROOT / "data" / "cleaned" / "multimodal"
MULTIMODAL_INDEX = PROJECT_ROOT / "data" / "multimodal_index.json"
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge_base"
OUTPUT_JSON = PROJECT_ROOT / "outputs" / "quality_gate.json"
OUTPUT_MD = PROJECT_ROOT / "outputs" / "quality_gate.md"
URL_PATTERN = re.compile(r"https?://[^\s|)>\]]+")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def check_url(url: str) -> dict[str, Any]:
    started = time.monotonic()
    headers = {"User-Agent": "JNUStudentAssistantQualityCheck/1.0"}
    try:
        response = requests.get(url, headers=headers, timeout=12, allow_redirects=True, stream=True)
        return {
            "url": url,
            "status": response.status_code,
            "ok": response.status_code < 400,
            "final_url": response.url,
            "latency_seconds": round(time.monotonic() - started, 3),
        }
    except requests.RequestException as exc:
        return {
            "url": url,
            "status": 0,
            "ok": False,
            "error": str(exc).replace("\n", " ")[:240],
            "latency_seconds": round(time.monotonic() - started, 3),
        }


def multimodal_findings() -> dict[str, Any]:
    if MULTIMODAL_INDEX.exists():
        try:
            index = json.loads(MULTIMODAL_INDEX.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, TypeError):
            index = []
        if not isinstance(index, list):
            index = []
        images: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        missing_assets: list[dict[str, Any]] = []
        for item in index:
            if not isinstance(item, dict):
                continue
            finding = {
                "file": MULTIMODAL_INDEX.name,
                "unit_id": item.get("id"),
                "page": item.get("page"),
            }
            asset_path = str(item.get("asset_path") or "")
            if asset_path:
                absolute = (KNOWLEDGE_BASE / asset_path).resolve()
                resolved = absolute.is_relative_to(KNOWLEDGE_BASE.resolve()) and absolute.is_file()
                image = {
                    **finding,
                    "missing_caption": not bool(item.get("caption")),
                    "derived_caption": False,
                    "missing_context": not bool(item.get("context") or item.get("snippet")),
                    "resolved": resolved,
                }
                images.append(image)
                if not resolved:
                    missing_assets.append({**finding, "asset_path": asset_path})
            if item.get("rows") or item.get("is_table"):
                rows = item.get("rows") or []
                nonempty_cells = sum(bool(str(cell).strip()) for row in rows for cell in row)
                tables.append(
                    {
                        **finding,
                        "empty": bool(item.get("rows") is not None) and not rows,
                        "sparse": bool(rows) and nonempty_cells < 4,
                        "row_count": len(rows),
                        "image_only": bool(item.get("is_table") and not item.get("rows")),
                    }
                )
        return {
            "documents": len({item.get("document") for item in index if isinstance(item, dict)}),
            "resources": len(index),
            "images": len(images),
            "tables": len(tables),
            "structured_tables": sum(1 for item in tables if not item["image_only"]),
            "images_missing_caption": [item for item in images if item["missing_caption"]],
            "images_missing_context": [item for item in images if item["missing_context"]],
            "images_with_derived_caption": [],
            "missing_assets": missing_assets,
            "empty_tables": [item for item in tables if item["empty"]],
            "sparse_tables": [item for item in tables if item["sparse"]],
        }

    files = sorted(MULTIMODAL_DIR.glob("*.json")) if MULTIMODAL_DIR.exists() else []
    images = []
    tables = []
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        for unit in document.get("units", []):
            finding = {"file": path.name, "unit_id": unit.get("unit_id"), "page": unit.get("source_page")}
            if unit.get("type") == "image":
                images.append(
                    {
                        **finding,
                        "missing_caption": not bool(unit.get("caption")),
                        "derived_caption": unit.get("caption_source") == "derived-from-page-context",
                        "missing_context": not bool(unit.get("context")),
                    }
                )
            elif unit.get("type") == "table":
                rows = unit.get("rows") or []
                nonempty_cells = sum(bool(str(cell).strip()) for row in rows for cell in row)
                tables.append(
                    {
                        **finding,
                        "empty": not rows,
                        "sparse": bool(rows) and nonempty_cells < 4,
                        "row_count": len(rows),
                    }
                )
    return {
        "documents": len(files),
        "resources": len(images) + len(tables),
        "images": len(images),
        "tables": len(tables),
        "structured_tables": len(tables),
        "images_missing_caption": [item for item in images if item["missing_caption"]],
        "images_missing_context": [item for item in images if item["missing_context"]],
        "images_with_derived_caption": [item for item in images if item.get("derived_caption")],
        "missing_assets": [],
        "empty_tables": [item for item in tables if item["empty"]],
        "sparse_tables": [item for item in tables if item["sparse"]],
    }


def build_report(check_links: bool, workers: int) -> dict[str, Any]:
    cleaned = read_jsonl(CLEANED_DOCS)
    card_paths = sorted(SERVICE_CARDS.glob("*.md")) if SERVICE_CARDS.exists() else []
    card_texts = [path.read_text(encoding="utf-8", errors="replace") for path in card_paths]
    urls = sorted(
        {
            *[row.get("source_url", "") for row in cleaned if row.get("source_url")],
            *[url.rstrip(".,，。") for text in card_texts for url in URL_PATTERN.findall(text)],
        }
    )
    link_results: list[dict[str, Any]] = []
    if check_links:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            link_results = list(executor.map(check_url, urls))

    dates = [row.get("date") for row in cleaned if row.get("date")]
    stale = []
    current_year = datetime.now().year
    for row in cleaned:
        match = re.search(r"(20\d{2})", str(row.get("date") or ""))
        if match and current_year - int(match.group(1)) >= 3:
            stale.append({"title": row.get("title"), "date": row.get("date"), "url": row.get("source_url")})

    multimodal = multimodal_findings()
    broken = [item for item in link_results if not item["ok"]]
    warnings = []
    if not cleaned and not card_paths:
        warnings.append("未发现传统 cleaned 文档或服务卡片；当前质量检查仅覆盖知识库快照")
    if not multimodal["resources"]:
        warnings.append("未发现可检查的多模态资源")
    if broken:
        warnings.append(f"发现 {len(broken)} 个不可访问链接")
    if multimodal["images_missing_caption"]:
        warnings.append(f"发现 {len(multimodal['images_missing_caption'])} 个无显式图注的图像")
    if multimodal["empty_tables"] or multimodal["sparse_tables"]:
        warnings.append(
            f"发现 {len(multimodal['empty_tables'])} 个空表格和 {len(multimodal['sparse_tables'])} 个稀疏表格"
        )
    if multimodal["missing_assets"]:
        warnings.append(f"发现 {len(multimodal['missing_assets'])} 个多模态资源文件缺失")
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "cleaned_documents": len(cleaned),
            "service_cards": len(card_paths),
            "source_urls": len(urls),
            "checked_urls": len(link_results),
            "broken_urls": len(broken),
            "stale_documents": len(stale),
            "multimodal_documents": multimodal["documents"],
            "multimodal_resources": multimodal["resources"],
            "missing_multimodal_assets": len(multimodal["missing_assets"]),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "broken_links": broken,
        "stale_documents": stale,
        "multimodal": multimodal,
        "links": link_results,
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 数据与多模态质量门禁",
        "",
        f"- 清洗文档：{summary['cleaned_documents']}",
        f"- 服务卡片：{summary['service_cards']}",
        f"- 链接：检查 {summary['checked_urls']}，失败 {summary['broken_urls']}",
        f"- 可能过期文档：{summary['stale_documents']}",
        f"- 多模态文档：{summary['multimodal_documents']}",
        f"- 多模态资源：{summary['multimodal_resources']}",
        f"- 缺失资源文件：{summary['missing_multimodal_assets']}",
        "",
        "## 警告",
        "",
        *([f"- {item}" for item in report["warnings"]] or ["- 无"]),
        "",
        "## 不可访问链接",
        "",
        *(
            [f"- `{item['status']}` {item['url']}" for item in report["broken_links"]]
            or ["- 无"]
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit student-assistant data, links, and multimodal output.")
    parser.add_argument("--check-links", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = build_report(args.check_links, args.workers)
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(markdown_report(report), encoding="utf-8")
    print(markdown_report(report))
    if args.strict and (
        report["summary"]["broken_urls"]
        or report["summary"]["missing_multimodal_assets"]
        or not report["summary"]["multimodal_resources"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
