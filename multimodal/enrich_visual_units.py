from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MULTIMODAL_DIR = PROJECT_ROOT / "data" / "cleaned" / "multimodal"
ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "cleaned" / "multimodal_visual" / "annotations.json"
DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"
RAGFLOW_CONTAINER = os.getenv("RAGFLOW_CONTAINER", "docker-ragflow-cpu-1")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_annotations() -> dict[str, Any]:
    if not ANNOTATIONS_PATH.exists():
        return {"schema_version": "1.0", "updated_at": now_iso(), "annotations": {}}
    try:
        data = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault("schema_version", "1.0")
    data.setdefault("annotations", {})
    return data


def save_annotations(data: dict[str, Any]) -> None:
    ANNOTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_iso()
    temporary = ANNOTATIONS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(ANNOTATIONS_PATH)


def get_siliconflow_api_key() -> str:
    direct = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if direct:
        return direct
    code = (
        "import json,os,pymysql;"
        "c=pymysql.connect(host=os.getenv('MYSQL_HOST'),port=int(os.getenv('MYSQL_PORT','3306'))," 
        "user='root',password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DBNAME'),charset='utf8mb4');"
        "q=c.cursor();q.execute(\"select api_key from tenant_llm where lower(llm_factory)='siliconflow' "
        "and api_key is not null and api_key<>'' order by update_time desc limit 1\");"
        "r=q.fetchone();v=r[0] if r else '';"
        "v=json.loads(v).get('api_key','') if v and str(v).lstrip().startswith('{') else v;"
        "print(v or '')"
    )
    result = subprocess.run(
        ["docker", "exec", RAGFLOW_CONTAINER, "python", "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    key = result.stdout.strip()
    if not key:
        raise RuntimeError("No SiliconFlow API key is configured in RAGFlow")
    return key


def collect_units() -> list[dict[str, Any]]:
    units = []
    for json_path in sorted(MULTIMODAL_DIR.glob("multimodal__*.json")):
        try:
            document = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        content_list = PROJECT_ROOT / str(document.get("mineru_content_list") or "")
        for unit in document.get("units", []):
            if unit.get("type") not in {"image", "table"} or not unit.get("image_path"):
                continue
            image_path = (content_list.parent / str(unit["image_path"])).resolve()
            if not image_path.is_file():
                continue
            units.append(
                {
                    "key": f"{document.get('source_sha256')}:{unit.get('unit_id')}",
                    "document": json_path.name,
                    "title": document.get("title") or document.get("source_file"),
                    "source_file": document.get("source_file"),
                    "source_page": unit.get("source_page"),
                    "unit_id": unit.get("unit_id"),
                    "type": unit.get("type"),
                    "caption": unit.get("caption") or [],
                    "context": unit.get("context") or [],
                    "image_path": image_path,
                }
            )
    return units


def parse_json_response(value: str) -> dict[str, Any]:
    value = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.S)
    candidate = fenced.group(1) if fenced else value[value.find("{") : value.rfind("}") + 1]
    result = json.loads(candidate)
    return {
        "description": str(result.get("description") or "").strip(),
        "visible_text": str(result.get("visible_text") or "").strip(),
        "key_elements": [str(item).strip() for item in result.get("key_elements", []) if str(item).strip()],
        "retrieval_keywords": [
            str(item).strip() for item in result.get("retrieval_keywords", []) if str(item).strip()
        ],
        "caution": str(result.get("caution") or "").strip(),
    }


def enrich_one(unit: dict[str, Any], api_key: str, api_base: str, model: str, timeout: int) -> dict[str, Any]:
    image_path: Path = unit["image_path"]
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    prompt = f"""你正在为暨南大学学生事务知识库清洗公开材料中的视觉内容。
文档：{unit['title']}
页码：{unit['source_page']}
类型：{unit['type']}
原有图注：{'；'.join(unit['caption']) or '无'}
附近正文：{'；'.join(unit['context']) or '无'}

请只根据图片中确实可见的信息，输出一个 JSON 对象：
description：1-3句准确说明图片或表格展示了什么；
visible_text：对学生检索有价值的界面文字、表头或字段，无法辨认则留空；
key_elements：主要界面区域、按钮、步骤或表格结构数组；
retrieval_keywords：5-12个适合中文检索的关键词数组；
caution：模糊、截断或无法确认的信息，若无则留空。
不得猜测被遮挡内容，不得抄录密码、二维码内容、身份证号、手机号等敏感信息。只输出 JSON。"""
    response = requests.post(
        f"{api_base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 900,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    result = parse_json_response(content)
    if not result["description"]:
        raise RuntimeError("Visual model returned an empty description")
    return {
        **result,
        "model": model,
        "image_sha256": file_sha256(image_path),
        "generated_at": now_iso(),
        "document": unit["document"],
        "source_file": unit["source_file"],
        "source_page": unit["source_page"],
        "unit_id": unit["unit_id"],
        "type": unit["type"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Describe MinerU visual units with a multimodal model.")
    parser.add_argument("--model", default=os.getenv("VISUAL_MODEL", DEFAULT_MODEL))
    parser.add_argument("--api-base", default=os.getenv("SILICONFLOW_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state = load_annotations()
    annotations = state["annotations"]
    pending = []
    unchanged = 0
    for unit in collect_units():
        image_sha = file_sha256(unit["image_path"])
        existing = annotations.get(unit["key"], {})
        if not args.refresh and existing.get("image_sha256") == image_sha and existing.get("model") == args.model:
            unchanged += 1
            continue
        pending.append(unit)
    if args.limit:
        pending = pending[: args.limit]
    print(f"Visual units: pending={len(pending)}, unchanged={unchanged}")
    if args.dry_run or not pending:
        return

    api_key = get_siliconflow_api_key()
    lock = threading.Lock()
    success = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(enrich_one, unit, api_key, args.api_base, args.model, args.timeout): unit
            for unit in pending
        }
        for future in as_completed(futures):
            unit = futures[future]
            try:
                annotation = future.result()
                with lock:
                    annotations[unit["key"]] = annotation
                    save_annotations(state)
                success += 1
                print(f"[success] {unit['source_file']} page {unit['source_page']} {unit['type']}")
            except Exception as exc:
                failed += 1
                print(f"[failed] {unit['source_file']} page {unit['source_page']}: {exc}")
    print(f"Visual enrichment finished: success={success}, unchanged={unchanged}, failed={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
