from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINERU_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "manifest.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "data" / "cleaned" / "multimodal"
RAGFLOW_DIR = PROJECT_ROOT / "data" / "cleaned" / "multimodal_ragflow"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.jsonl"
VISUAL_ANNOTATIONS = PROJECT_ROOT / "data" / "cleaned" / "multimodal_visual" / "annotations.json"
PROCESSOR_VERSION = "1.2"

DROP_TYPES = {"page_number"}
DECORATIVE_PATTERNS = [
    re.compile(r"^第?\s*\d+\s*页$", re.I),
    re.compile(r"^page\s*\d+$", re.I),
    re.compile(r"^附件\s*\d+$"),
    re.compile(r"^[\-_=·•.。]{2,}$"),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(value: object) -> str:
    text = str(value or "").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_decorative(text: str) -> bool:
    if not text:
        return True
    return any(pattern.fullmatch(text) for pattern in DECORATIVE_PATTERNS)


def html_table_to_rows(table_html: str) -> list[list[str]]:
    soup = BeautifulSoup(table_html or "", "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def latest_successes() -> list[dict]:
    latest: dict[str, dict] = {}
    for row in read_jsonl(MINERU_MANIFEST):
        if row.get("source"):
            latest[row["source"]] = row
    return sorted((row for row in latest.values() if row.get("status") == "success"), key=lambda row: row["source"])


def find_content_list(row: dict) -> Path:
    markdown = PROJECT_ROOT / row["markdown"]
    candidates = [
        path
        for path in markdown.parent.glob("*content_list.json")
        if not path.name.endswith("_v2.json")
    ]
    if not candidates:
        raise FileNotFoundError(f"MinerU content list not found beside {markdown}")
    return candidates[0]


def make_unit_id(source_sha: str, page: int, index: int, kind: str) -> str:
    value = f"{source_sha}:{page}:{index}:{kind}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:16]


def page_text_context(items: list[dict], target_index: int, window: int = 2) -> list[str]:
    target_page = items[target_index].get("page_idx", 0)
    text_positions = [
        index
        for index, item in enumerate(items)
        if item.get("page_idx", 0) == target_page
        and item.get("type") in {"text", "header", "footer"}
        and not is_decorative(normalize_text(item.get("text")))
    ]
    before = [index for index in text_positions if index < target_index][-window:]
    after = [index for index in text_positions if index > target_index][:window]
    return [normalize_text(items[index].get("text")) for index in before + after]


def load_visual_annotations() -> dict[str, dict]:
    if not VISUAL_ANNOTATIONS.exists():
        return {}
    try:
        return json.loads(VISUAL_ANNOTATIONS.read_text(encoding="utf-8")).get("annotations", {})
    except (json.JSONDecodeError, OSError):
        return {}


def clean_document(row: dict, visual_annotations: dict[str, dict]) -> tuple[dict, str]:
    content_path = find_content_list(row)
    items = json.loads(content_path.read_text(encoding="utf-8"))
    source_sha = row["sha256"]
    repeated_edge_text = Counter(
        normalize_text(item.get("text"))
        for item in items
        if item.get("type") in {"header", "footer"} and normalize_text(item.get("text"))
    )
    units = []
    removed = []

    for index, item in enumerate(items):
        kind = item.get("type", "unknown")
        page = int(item.get("page_idx", 0)) + 1
        unit_id = make_unit_id(source_sha, page, index, kind)
        trace = {
            "unit_id": unit_id,
            "source_file": row["source"],
            "source_sha256": source_sha,
            "source_page": page,
            "bbox": item.get("bbox", []),
            "mineru_content_list": str(content_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }

        if kind in DROP_TYPES:
            removed.append({**trace, "type": kind, "reason": "page-number"})
            continue

        if kind in {"text", "header", "footer"}:
            text = normalize_text(item.get("text"))
            repeated = kind in {"header", "footer"} and repeated_edge_text[text] > 1
            if is_decorative(text) or repeated:
                removed.append({**trace, "type": kind, "text": text, "reason": "decorative-or-repeated-edge"})
                continue
            units.append(
                {
                    **trace,
                    "type": "text",
                    "text": text,
                    "heading_level": item.get("text_level"),
                }
            )
            continue

        if kind == "table":
            html = normalize_text(item.get("table_body"))
            rows = html_table_to_rows(html)
            captions = [normalize_text(value) for value in item.get("table_caption", []) if normalize_text(value)]
            footnotes = [normalize_text(value) for value in item.get("table_footnote", []) if normalize_text(value)]
            context = page_text_context(items, index)
            if not rows:
                removed.append(
                    {
                        **trace,
                        "type": kind,
                        "reason": "empty-table-no-cells",
                        "caption": captions,
                        "context": context,
                        "image_path": item.get("img_path", ""),
                    }
                )
                continue
            units.append(
                {
                    **trace,
                    "type": "table",
                    "caption": captions,
                    "footnote": footnotes,
                    "html": html,
                    "rows": rows,
                    "image_path": item.get("img_path", ""),
                    "context": context,
                }
            )
            continue

        if kind == "image":
            captions = [normalize_text(value) for value in item.get("image_caption", []) if normalize_text(value)]
            footnotes = [normalize_text(value) for value in item.get("image_footnote", []) if normalize_text(value)]
            context = page_text_context(items, index)
            caption_source = "explicit"
            if not captions and context:
                captions = [context[-1][:160]]
                caption_source = "derived-from-page-context"
            units.append(
                {
                    **trace,
                    "type": "image",
                    "caption": captions,
                    "caption_source": caption_source,
                    "footnote": footnotes,
                    "image_path": item.get("img_path", ""),
                    "context": context,
                }
            )
            continue

        removed.append({**trace, "type": kind, "reason": "unsupported-content-type"})

    for unit in units:
        if unit["type"] not in {"image", "table"}:
            continue
        annotation = visual_annotations.get(f"{source_sha}:{unit['unit_id']}")
        if not annotation:
            continue
        unit["visual_description"] = normalize_text(annotation.get("description"))
        unit["visual_visible_text"] = normalize_text(annotation.get("visible_text"))
        unit["visual_key_elements"] = [
            normalize_text(value) for value in annotation.get("key_elements", []) if normalize_text(value)
        ]
        unit["visual_keywords"] = [
            normalize_text(value) for value in annotation.get("retrieval_keywords", []) if normalize_text(value)
        ]
        unit["visual_caution"] = normalize_text(annotation.get("caution"))
        unit["visual_model"] = annotation.get("model")
        unit["visual_generated_at"] = annotation.get("generated_at")

    title = next(
        (unit["text"] for unit in units if unit["type"] == "text" and unit.get("heading_level") == 1),
        next((unit["text"] for unit in units if unit["type"] == "text"), Path(row["source"]).stem),
    )
    document = {
        "schema_version": PROCESSOR_VERSION,
        "title": title,
        "source_file": row["source"],
        "source_sha256": source_sha,
        "mineru_backend": row.get("backend"),
        "mineru_markdown": row.get("markdown"),
        "mineru_content_list": str(content_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "processed_at": now_iso(),
        "statistics": {
            "kept_units": len(units),
            "removed_units": len(removed),
            "text_units": sum(unit["type"] == "text" for unit in units),
            "table_units": sum(unit["type"] == "table" for unit in units),
            "image_units": sum(unit["type"] == "image" for unit in units),
            "visually_enriched_units": sum(bool(unit.get("visual_description")) for unit in units),
        },
        "units": units,
        "removed": removed,
    }

    markdown_parts = [
        f"# {title}",
        "",
        f"- 原始文件：{row['source']}",
        f"- SHA-256：{source_sha}",
        "- 清洗流程：MinerU 初洗 -> Python 二次清洗与图表关联",
        "- 表格格式：JSON + HTML",
        "",
    ]
    current_page = None
    for unit in units:
        if unit["source_page"] != current_page:
            current_page = unit["source_page"]
            markdown_parts.extend([f"## 第 {current_page} 页", ""])
        if unit["type"] == "text":
            level = unit.get("heading_level")
            if level:
                markdown_parts.extend([f"{'#' * min(int(level) + 2, 6)} {unit['text']}", ""])
            else:
                markdown_parts.extend([unit["text"], ""])
        elif unit["type"] == "table":
            markdown_parts.extend(
                [
                    f"### 表格 `{unit['unit_id']}`",
                    f"上下文：{'；'.join(unit['context']) or '无'}",
                    *([f"表题：{'；'.join(unit['caption'])}"] if unit["caption"] else []),
                    *([f"视觉描述：{unit['visual_description']}"] if unit.get("visual_description") else []),
                    *([f"可见文字：{unit['visual_visible_text']}"] if unit.get("visual_visible_text") else []),
                    *([f"视觉关键词：{'、'.join(unit['visual_keywords'])}"] if unit.get("visual_keywords") else []),
                    *([f"视觉注意：{unit['visual_caution']}"] if unit.get("visual_caution") else []),
                    unit["html"],
                    "",
                    "```json",
                    json.dumps(unit["rows"], ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        elif unit["type"] == "image":
            markdown_parts.extend(
                [
                    f"### 图像 `{unit['unit_id']}`",
                    f"图注：{'；'.join(unit['caption']) or '无显式图注'}",
                    f"上下文：{'；'.join(unit['context']) or '无'}",
                    *([f"视觉描述：{unit['visual_description']}"] if unit.get("visual_description") else []),
                    *([f"可见文字：{unit['visual_visible_text']}"] if unit.get("visual_visible_text") else []),
                    *([f"视觉要素：{'、'.join(unit['visual_key_elements'])}"] if unit.get("visual_key_elements") else []),
                    *([f"视觉关键词：{'、'.join(unit['visual_keywords'])}"] if unit.get("visual_keywords") else []),
                    *([f"视觉注意：{unit['visual_caution']}"] if unit.get("visual_caution") else []),
                    f"图像文件：{unit['image_path']}",
                    "",
                ]
            )
    return document, "\n".join(markdown_parts).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Associate and clean MinerU text, tables, and images.")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAGFLOW_DIR.mkdir(parents=True, exist_ok=True)
    visual_annotations = load_visual_annotations()
    latest_output: dict[str, dict] = {
        row.get("source_file"): row for row in read_jsonl(OUTPUT_MANIFEST) if row.get("source_file")
    }
    success = unchanged = failed = 0
    for row in latest_successes():
        previous = latest_output.get(row["source"])
        if (
            not args.refresh
            and previous
            and previous.get("source_sha256") == row.get("sha256")
            and previous.get("processor_version") == PROCESSOR_VERSION
            and previous.get("status") == "success"
        ):
            unchanged += 1
            continue
        try:
            document, markdown = clean_document(row, visual_annotations)
            stem = f"multimodal__{Path(row['source']).stem.strip('_')}__{row['sha256'][:12]}"
            json_path = OUTPUT_DIR / f"{stem}.json"
            markdown_path = RAGFLOW_DIR / f"{stem}.md"
            json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            markdown_path.write_text(markdown, encoding="utf-8")
            result = {
                "source_file": row["source"],
                "source_sha256": row["sha256"],
                "processor_version": PROCESSOR_VERSION,
                "status": "success",
                "processed_at": now_iso(),
                "json_path": str(json_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "markdown_path": str(markdown_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                **document["statistics"],
            }
            append_jsonl(OUTPUT_MANIFEST, result)
            print(
                f"[success] {row['source']}: text={result['text_units']}, "
                f"tables={result['table_units']}, images={result['image_units']}, removed={result['removed_units']}"
            )
            success += 1
        except Exception as exc:
            append_jsonl(
                OUTPUT_MANIFEST,
                {
                    "source_file": row["source"],
                    "source_sha256": row.get("sha256"),
                    "status": "failed",
                    "processed_at": now_iso(),
                    "error": str(exc),
                },
            )
            print(f"[failed] {row['source']}: {exc}")
            failed += 1
    print(f"Post-processing finished: success={success}, unchanged={unchanged}, failed={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
