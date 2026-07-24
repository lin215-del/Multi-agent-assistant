from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"
STATE_PATH = OUTPUT_DIR / "content_snapshot.json"
STATUS_PATH = OUTPUT_DIR / "automatic_update_status.json"
HISTORY_PATH = OUTPUT_DIR / "automatic_update_history.jsonl"
LOCK_PATH = OUTPUT_DIR / "automatic_update.lock"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def snapshot() -> dict[str, str]:
    result = {}
    directories = (
        PROJECT_ROOT / "data" / "cleaned" / "ragflow_markdown",
        PROJECT_ROOT / "data" / "cleaned" / "service_cards",
        PROJECT_ROOT / "data" / "cleaned" / "multimodal_ragflow",
    )
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class PipelineRun:
    def __init__(self, schedule: str) -> None:
        self.status: dict[str, Any] = {
            "schema_version": "1.0",
            "state": "running",
            "schedule": schedule,
            "started_at": now_iso(),
            "finished_at": None,
            "current_stage": None,
            "stages": [],
            "changes": {},
            "error": "",
        }
        self._flush()

    def _flush(self) -> None:
        write_json(STATUS_PATH, self.status)

    def stage(self, name: str, args: list[str], optional: bool = False) -> bool:
        record: dict[str, Any] = {
            "name": name,
            "state": "running",
            "started_at": now_iso(),
            "finished_at": None,
            "duration_seconds": None,
            "optional": optional,
            "error": "",
        }
        self.status["current_stage"] = name
        self.status["stages"].append(record)
        self._flush()
        print(f"\n=== {name} ===", flush=True)
        started = time.monotonic()
        try:
            subprocess.run([sys.executable, *args], cwd=PROJECT_ROOT, check=True)
            record["state"] = "success"
            return True
        except subprocess.CalledProcessError as exc:
            record["state"] = "warning" if optional else "failed"
            record["error"] = f"Command exited with status {exc.returncode}"
            if optional:
                print(f"[warning] {name}: {record['error']}", file=sys.stderr, flush=True)
                return False
            raise
        finally:
            record["finished_at"] = now_iso()
            record["duration_seconds"] = round(time.monotonic() - started, 2)
            self._flush()

    def finish(self, state: str, changes: dict[str, Any], error: str = "") -> None:
        self.status["state"] = state
        self.status["current_stage"] = None
        self.status["finished_at"] = now_iso()
        self.status["changes"] = changes
        self.status["error"] = error
        self._flush()
        with HISTORY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.status, ensure_ascii=False) + "\n")


def acquire_lock() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < 12 * 60 * 60:
            raise SystemExit("Another automatic update is already running")
        LOCK_PATH.unlink()
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SystemExit("Another automatic update is already running") from exc
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))


def content_changes(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "changed": sorted(path for path in set(before) & set(after) if before[path] != after[path]),
        "unchanged": sum(before.get(path) == digest for path, digest in after.items()),
        "total": len(after),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete automatic public-data refresh pipeline.")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max-pages-per-seed", type=int, default=12)
    parser.add_argument("--sync-ragflow", action="store_true")
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--skip-mineru", action="store_true")
    parser.add_argument("--skip-vlm", action="store_true")
    parser.add_argument("--schedule-label", default="每日 03:00")
    args = parser.parse_args()

    acquire_lock()
    before = snapshot()
    pipeline = PipelineRun(args.schedule_label)
    changes: dict[str, Any] = {}
    try:
        if not args.skip_crawl:
            pipeline.stage(
                "发现并采集官网更新",
                [
                    "crawler/jnu_crawler.py",
                    "--max-pages",
                    str(args.max_pages),
                    "--depth",
                    str(args.depth),
                    "--max-pages-per-seed",
                    str(args.max_pages_per_seed),
                ],
            )
        pipeline.stage("网页数据清洗", ["cleaner/clean_jnu_docs.py"])
        pipeline.stage("生成学生事务服务卡", ["cleaner/build_service_cards.py"])
        if not args.skip_mineru:
            pipeline.stage("MinerU 增量解析新附件", ["multimodal/mineru_pipeline.py"])
        pipeline.stage("图文表关联清洗", ["multimodal/postprocess_mineru.py"])
        if not args.skip_vlm:
            pipeline.stage("视觉模型语义标注", ["multimodal/enrich_visual_units.py", "--workers", "2"], optional=True)
            pipeline.stage("写回视觉描述到检索分块", ["multimodal/postprocess_mineru.py", "--refresh"])
        pipeline.stage("数据质量与官方链接检查", ["scripts/quality_gate.py", "--check-links"])
        if args.sync_ragflow:
            pipeline.stage("同步核心服务知识库", ["ragflow/import_core_services.py"])
            pipeline.stage(
                "增量同步多模态知识库",
                [
                    "ragflow/import_experiment_pipelines.py",
                    "--refresh-prefix",
                    "multimodal__",
                    "--refresh-changed",
                    "--prune",
                ],
            )
            pipeline.stage(
                "Sync native RAGFlow image chunks",
                [
                    "ragflow/sync_native_images.py",
                    "--datasets",
                    "A",
                    "--datasets",
                    "B",
                    "--datasets",
                    "C",
                ],
            )
        after = snapshot()
        changes = content_changes(before, after)
        state = {"generated_at": now_iso(), **changes, "hashes": after}
        write_json(STATE_PATH, state)
        pipeline.status["changes"] = changes
        pipeline.stage("刷新可视化看板", ["visualize_pipeline.py"])
        pipeline.finish("success", changes)
        print(json.dumps(changes, ensure_ascii=False, indent=2))
    except Exception as exc:
        after = snapshot()
        changes = content_changes(before, after)
        pipeline.finish("failed", changes, str(exc))
        raise
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
