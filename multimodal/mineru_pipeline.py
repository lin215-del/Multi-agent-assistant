from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "files"
OUTPUT_DIR = PROJECT_ROOT / "data" / "cleaned" / "mineru"
RAGFLOW_DIR = PROJECT_ROOT / "data" / "cleaned" / "mineru_ragflow"
MANIFEST_PATH = OUTPUT_DIR / "manifest.jsonl"

DEFAULT_RUNTIME = Path(r"D:\student-assistant-runtime")
DEFAULT_MINERU = DEFAULT_RUNTIME / "mineru-venv" / "Scripts" / "mineru.exe"
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".docx", ".pptx", ".xlsx"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "_", value).strip("._")
    return cleaned[:120] or "document"


def project_relative(path: Path) -> str:
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return str(path)
    return str(relative).replace("\\", "/")


def read_latest_manifest() -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not MANIFEST_PATH.exists():
        return latest
    with MANIFEST_PATH.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            source = row.get("source")
            if source:
                latest[source] = row
    return latest


def append_manifest(row: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def mineru_environment(runtime: Path) -> dict[str, str]:
    env = os.environ.copy()
    locations = {
        "HF_HOME": runtime / "huggingface",
        "MODELSCOPE_CACHE": runtime / "modelscope",
        "XDG_CACHE_HOME": runtime / "cache",
        "TEMP": runtime / "tmp",
        "TMP": runtime / "tmp",
    }
    for key, path in locations.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return env


def choose_markdown(output: Path) -> Path:
    candidates = [path for path in output.rglob("*.md") if path.is_file()]
    if not candidates:
        raise RuntimeError("MinerU completed but did not produce Markdown")
    return max(candidates, key=lambda path: path.stat().st_size)


def copy_ragflow_markdown(source: Path, markdown: Path, sha256: str, backend: str) -> Path:
    RAGFLOW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAGFLOW_DIR / f"mineru__{safe_name(source.stem)}__{sha256[:12]}.md"
    body = markdown.read_text(encoding="utf-8", errors="replace").strip()
    header = (
        f"# {source.stem}\n\n"
        f"- 原始文件：{source.name}\n"
        f"- 多模态解析器：MinerU\n"
        f"- 解析后端：{backend}\n"
        f"- 文件校验：{sha256}\n\n"
        "---\n\n"
    )
    target.write_text(header + body + "\n", encoding="utf-8")
    return target


def parse_one(source: Path, executable: Path, runtime: Path, backend: str, timeout: int) -> dict:
    sha256 = file_sha256(source)
    document_output = OUTPUT_DIR / f"{safe_name(source.stem)}__{sha256[:12]}"
    if document_output.exists():
        shutil.rmtree(document_output)
    document_output.mkdir(parents=True, exist_ok=True)

    command = [
        str(executable),
        "-p",
        str(source),
        "-o",
        str(document_output),
        "-b",
        backend,
        "-m",
        "auto",
        "-l",
        "ch",
        "-f",
        "true",
        "-t",
        "true",
    ]
    started = time.monotonic()
    result = subprocess.run(
        command,
        env=mineru_environment(runtime),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    duration = round(time.monotonic() - started, 2)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "MinerU failed").strip()[-4000:])

    markdown = choose_markdown(document_output)
    ragflow_markdown = copy_ragflow_markdown(source, markdown, sha256, backend)
    content_lists = sorted(document_output.rglob("*content_list*.json"))
    middle_json = sorted(document_output.rglob("*middle*.json"))
    images = [path for path in document_output.rglob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    return {
        "source": source.name,
        "source_path": project_relative(source),
        "sha256": sha256,
        "status": "success",
        "backend": backend,
        "finished_at": now_iso(),
        "duration_seconds": duration,
        "markdown": str(markdown.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "ragflow_markdown": str(ragflow_markdown.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "content_list_count": len(content_lists),
        "middle_json_count": len(middle_json),
        "image_count": len(images),
    }


def collect_sources(selected: list[str]) -> list[Path]:
    if selected:
        sources = [Path(value).resolve() for value in selected]
    else:
        sources = sorted(path.resolve() for path in INPUT_DIR.iterdir() if path.is_file())
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse student-assistant attachments with MinerU.")
    parser.add_argument("paths", nargs="*", help="Optional files. Defaults to data/files.")
    parser.add_argument("--backend", default=os.getenv("MINERU_BACKEND", "pipeline"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout per file in seconds.")
    args = parser.parse_args()

    runtime = Path(os.getenv("MINERU_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    executable = Path(os.getenv("MINERU_EXECUTABLE", str(DEFAULT_MINERU)))
    if not executable.exists():
        raise SystemExit(f"MinerU executable not found: {executable}")
    if not INPUT_DIR.exists() and not args.paths:
        raise SystemExit(f"Input directory not found: {INPUT_DIR}")

    latest = read_latest_manifest()
    sources = collect_sources(args.paths)
    if args.limit:
        sources = sources[: args.limit]

    success = skipped = failed = unsupported = 0
    for source in sources:
        if not source.exists() or not source.is_file():
            print(f"[missing] {source}")
            failed += 1
            continue
        if source.suffix.lower() not in SUPPORTED_SUFFIXES:
            row = {
                "source": source.name,
                "source_path": str(source),
                "status": "unsupported",
                "reason": f"MinerU does not support {source.suffix or 'this file type'}",
                "finished_at": now_iso(),
            }
            append_manifest(row)
            print(f"[unsupported] {source.name}")
            unsupported += 1
            continue

        sha256 = file_sha256(source)
        previous = latest.get(source.name, {})
        if not args.refresh and previous.get("status") == "success" and previous.get("sha256") == sha256:
            print(f"[unchanged] {source.name}")
            skipped += 1
            continue

        print(f"[parsing] {source.name}", flush=True)
        try:
            row = parse_one(source, executable, runtime, args.backend, args.timeout)
            append_manifest(row)
            print(
                f"[success] {source.name}: {row['duration_seconds']}s, "
                f"images={row['image_count']}, structured={row['content_list_count'] + row['middle_json_count']}"
            )
            success += 1
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            row = {
                "source": source.name,
                "source_path": str(source),
                "sha256": sha256,
                "status": "failed",
                "backend": args.backend,
                "finished_at": now_iso(),
                "error": str(exc)[-4000:],
            }
            append_manifest(row)
            print(f"[failed] {source.name}: {exc}", file=sys.stderr)
            failed += 1

    print(f"MinerU finished: success={success}, unchanged={skipped}, unsupported={unsupported}, failed={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
