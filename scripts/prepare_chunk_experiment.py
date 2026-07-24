from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from restore_team_ragflow import RagflowClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "chunk_experiment.json"
FOCUS_CONFIG = PROJECT_ROOT / "config" / "chunk_experiment_focus.json"
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "chunk_experiment_preparation.json"


def batches(items: list[str], size: int = 50) -> list[list[str]]:
    return [items[offset : offset + size] for offset in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reduce A/B/C to identical focused samples and queue a controlled parse."
    )
    parser.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL", "http://localhost"))
    parser.add_argument(
        "--stop-only",
        action="store_true",
        help="Stop experiment parsing without clearing or re-queuing documents.",
    )
    parser.add_argument(
        "--datasets",
        nargs="*",
        choices=["A", "B", "C"],
        default=["A", "B", "C"],
    )
    args = parser.parse_args()
    api_key = os.getenv("RAGFLOW_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("RAGFLOW_API_KEY is required.")

    experiments = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))["datasets"]
    focus_names = set(json.loads(FOCUS_CONFIG.read_text(encoding="utf-8"))["documents"])
    client = RagflowClient(args.base_url, api_key)
    live = {item["name"]: item for item in client.list_datasets()}
    report: list[dict[str, Any]] = []

    for experiment in experiments:
        if experiment["key"] not in args.datasets:
            continue
        dataset = live.get(experiment["name"])
        if not dataset:
            raise RuntimeError(f"Missing experiment dataset: {experiment['name']}")
        dataset_id = str(dataset["id"])
        documents = client.list_documents(dataset_id)
        by_name = {str(item.get("name")): item for item in documents}
        missing = sorted(focus_names - set(by_name))
        if missing:
            raise RuntimeError(f"{experiment['key']} is missing focused documents: {missing}")

        running_ids = [
            str(item["id"])
            for item in documents
            if str(item.get("run") or "").upper() == "RUNNING"
        ]
        for group in batches(running_ids):
            client.request(
                "POST",
                f"/datasets/{dataset_id}/documents/stop",
                json={"document_ids": group},
            )

        cleared = 0
        if args.stop_only:
            report.append(
                {
                    "key": experiment["key"],
                    "dataset_id": dataset_id,
                    "focused_documents": len(focus_names),
                    "stopped_tasks": len(running_ids),
                    "cleared_non_focus_documents": 0,
                    "parse_queued": 0,
                }
            )
            print(f"{experiment['key']}: stopped={len(running_ids)}")
            continue
        for item in documents:
            chunk_count = max(
                int(item.get("chunk_num") or 0),
                int(item.get("chunk_count") or 0),
            )
            if item.get("name") in focus_names or chunk_count <= 0:
                continue
            client.request(
                "DELETE",
                f"/datasets/{dataset_id}/documents/{item['id']}/chunks",
            )
            cleared += 1

        selected = [by_name[name] for name in sorted(focus_names)]
        parse_ids = [
            str(item["id"])
            for item in selected
            if str(item.get("run") or "").upper() != "DONE"
            or max(
                int(item.get("chunk_num") or 0),
                int(item.get("chunk_count") or 0),
            )
            <= 0
        ]
        client.parse_documents(dataset_id, parse_ids)
        report.append(
            {
                "key": experiment["key"],
                "dataset_id": dataset_id,
                "focused_documents": len(selected),
                "stopped_tasks": len(running_ids),
                "cleared_non_focus_documents": cleared,
                "parse_queued": len(parse_ids),
            }
        )
        print(
            f"{experiment['key']}: stopped={len(running_ids)}, "
            f"cleared={cleared}, queued={len(parse_ids)}"
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"datasets": report}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
