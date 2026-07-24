from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env.local"
RESTORE_SCRIPT = PROJECT_ROOT / "scripts" / "restore_team_ragflow.py"
CORE_DATASET_NAME = "暨南大学学生助手-核心服务卡片"
NOTICE_DATASET_NAME = "暨南大学学生助手-第一阶段"
PLACEHOLDER_MARKERS = ("replace-with-", "change-this-", "your-")


def read_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_local_env(values: dict[str, str]) -> None:
    ordered_keys = [
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_DATASET_ID",
        "RAGFLOW_NOTICE_DATASET_ID",
        "RAGFLOW_RERANK_ID",
        "ALLOW_PRIVATE_RAGFLOW",
        "ASSISTANT_HOST",
        "ASSISTANT_PORT",
        "VLM_BASE_URL",
        "VLM_API_KEY",
        "VLM_MODEL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
    ]
    lines = [f"{key}={values[key]}" for key in ordered_keys if key in values]
    lines.extend(
        f"{key}={value}"
        for key, value in sorted(values.items())
        if key not in ordered_keys
    )
    temporary = ENV_FILE.with_suffix(".local.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)


def usable_secret(value: str) -> bool:
    lowered = value.strip().lower()
    return bool(lowered) and not any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def list_datasets(base_url: str, api_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{base_url.rstrip('/')}/api/v1/datasets",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"page": 1, "page_size": 100},
        timeout=(5, 30),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(str(payload.get("message") or "RAGFlow 请求失败"))
    data = payload.get("data")
    return list(data) if isinstance(data, list) else []


def choose_dataset_ids(datasets: list[dict[str, Any]]) -> tuple[str, str]:
    by_name = {str(item.get("name") or ""): item for item in datasets}
    primary = by_name.get(CORE_DATASET_NAME)
    notice = by_name.get(NOTICE_DATASET_NAME)
    if primary is None:
        primary = next(
            (
                item
                for item in datasets
                if "实验" not in str(item.get("name") or "")
            ),
            datasets[0] if datasets else None,
        )
    if notice is primary:
        notice = None
    return (
        str((primary or {}).get("id") or ""),
        str((notice or {}).get("id") or ""),
    )


def restore_recommended(base_url: str, api_key: str) -> None:
    print("未发现项目核心知识库，正在从仓库快照自动恢复……")
    child_env = os.environ.copy()
    child_env["RAGFLOW_API_KEY"] = api_key
    subprocess.run(
        [
            sys.executable,
            str(RESTORE_SCRIPT),
            "--base-url",
            base_url,
            "--scope",
            "recommended",
        ],
        cwd=PROJECT_ROOT,
        env=child_env,
        check=True,
    )


def main() -> None:
    values = read_local_env()
    base_url = (
        os.getenv("RAGFLOW_BASE_URL")
        or values.get("RAGFLOW_BASE_URL")
        or "http://localhost:8080"
    ).strip().rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY") or values.get("RAGFLOW_API_KEY", "")

    if not usable_secret(api_key):
        api_key = getpass.getpass("请输入本机 RAGFlow API Key（输入不会显示）: ").strip()
    if not usable_secret(api_key):
        raise SystemExit("未提供有效的 RAGFlow API Key。")

    try:
        datasets = list_datasets(base_url, api_key)
    except Exception as exc:
        raise SystemExit(
            f"无法连接 RAGFlow：{exc}\n"
            f"请先确认 {base_url} 已启动，并且 API Key 有效。"
        ) from exc

    dataset_names = {str(item.get("name") or "") for item in datasets}
    if CORE_DATASET_NAME not in dataset_names:
        restore_recommended(base_url, api_key)
        datasets = list_datasets(base_url, api_key)

    dataset_id, notice_dataset_id = choose_dataset_ids(datasets)
    if not dataset_id:
        raise SystemExit("RAGFlow 中没有可用知识库，自动恢复也未返回知识库 ID。")

    values.update(
        {
            "RAGFLOW_BASE_URL": base_url,
            "RAGFLOW_API_KEY": api_key,
            "RAGFLOW_DATASET_ID": dataset_id,
            "RAGFLOW_NOTICE_DATASET_ID": notice_dataset_id,
            "RAGFLOW_RERANK_ID": values.get("RAGFLOW_RERANK_ID", ""),
            "ALLOW_PRIVATE_RAGFLOW": "1",
            "ASSISTANT_HOST": values.get("ASSISTANT_HOST", "127.0.0.1"),
            "ASSISTANT_PORT": values.get("ASSISTANT_PORT", "8090"),
        }
    )
    write_local_env(values)

    selected = next(
        (str(item.get("name") or "") for item in datasets if str(item.get("id")) == dataset_id),
        dataset_id,
    )
    print(f"自动配置完成：{selected}")
    print("配置已保存到本机 .env.local；该文件不会上传 GitHub。")


if __name__ == "__main__":
    main()
