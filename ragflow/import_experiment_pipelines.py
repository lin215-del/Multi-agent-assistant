from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

from ragflow_auth import get_api_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "chunk_experiment.json"
STATE_PATH = PROJECT_ROOT / "outputs" / "chunk_experiment_state.json"
BASE_URL = "http://localhost:8080/api/v1"
SOURCE_DATASET_ID = "683cdc4a82a511f1b2e527d9437de36f"
CORPUS_DIRS = (
    PROJECT_ROOT / "data" / "cleaned" / "ragflow_markdown",
    PROJECT_ROOT / "data" / "cleaned" / "service_cards",
    PROJECT_ROOT / "data" / "cleaned" / "multimodal_ragflow",
)


class RagflowClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key or get_api_key()}"})

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        timeout = kwargs.pop("timeout", 120)
        response = self.session.request(method, f"{self.base_url}{path}", timeout=timeout, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or payload)
        return payload.get("data")

    def list_agents(self) -> list[dict[str, Any]]:
        data = self.request(
            "GET",
            "/agents",
            params={"page": 1, "page_size": 100, "canvas_category": "dataflow_canvas"},
        )
        return data.get("canvas", [])

    def ensure_pipeline(self, title: str, dsl: dict[str, Any]) -> dict[str, Any]:
        existing = next((item for item in self.list_agents() if item.get("title") == title), None)
        if existing:
            self.request(
                "PUT",
                f"/agents/{existing['id']}",
                json={"title": title, "dsl": dsl, "canvas_category": "dataflow_canvas"},
            )
            return {"id": existing["id"], "title": title, "action": "updated"}
        created = self.request(
            "POST",
            "/agents",
            json={"title": title, "dsl": dsl, "canvas_category": "dataflow_canvas"},
        )
        return {"id": created["id"], "title": title, "action": "created"}

    def list_datasets(self) -> list[dict[str, Any]]:
        return self.request("GET", "/datasets", params={"page": 1, "page_size": 100})

    def ensure_dataset(
        self,
        name: str,
        description: str,
        pipeline_id: str,
        embedding_model: str,
    ) -> dict[str, Any]:
        existing = next((item for item in self.list_datasets() if item.get("name") == name), None)
        payload = {
            "name": name,
            "description": description,
            "permission": "me",
            "parse_type": 0,
            "embedding_model": embedding_model,
            "pipeline_id": pipeline_id,
        }
        if existing:
            updated = self.request("PUT", f"/datasets/{existing['id']}", json=payload)
            return {**updated, "action": "updated"}
        created = self.request("POST", "/datasets", json=payload)
        return {**created, "action": "created"}

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.request(
                "GET",
                f"/datasets/{dataset_id}/documents",
                params={"page": page, "page_size": 100, "orderby": "create_time", "desc": False},
            )
            batch = data.get("docs", [])
            documents.extend(batch)
            if len(batch) < 100:
                return documents
            page += 1

    def upload_documents(self, dataset_id: str, paths: list[Path]) -> list[dict[str, Any]]:
        handles = []
        try:
            files = []
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                files.append(("file", (path.name, handle, "text/markdown")))
            return self.request("POST", f"/datasets/{dataset_id}/documents", files=files)
        finally:
            for handle in handles:
                handle.close()

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.request(
            "POST",
            f"/datasets/{dataset_id}/documents/parse",
            json={"document_ids": document_ids},
        )

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        if document_ids:
            self.request(
                "DELETE",
                f"/datasets/{dataset_id}/documents",
                json={"ids": document_ids, "delete_all": False},
            )

    def ingestion_logs(self, dataset_id: str) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/datasets/{dataset_id}/ingestions",
            params={"page": 1, "page_size": 100, "log_type": "file"},
        )


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_dsl(chunk_size: int, overlap: float, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "components": {
            "File": {
                "obj": {"component_name": "File", "params": {}},
                "downstream": ["Parser:0"],
                "upstream": [],
            },
            "Parser:0": {
                "obj": {
                    "component_name": "Parser",
                    "params": {
                        "setups": {
                            "markdown": {
                                "suffix": ["md", "markdown"],
                                "output_format": "json",
                                "preprocess": "main_content",
                                "flatten_media_to_text": False,
                            }
                        }
                    },
                },
                "downstream": ["TokenChunker:0"],
                "upstream": ["File"],
            },
            "TokenChunker:0": {
                "obj": {
                    "component_name": "TokenChunker",
                    "params": {
                        "delimiter_mode": "token_size",
                        "chunk_token_size": chunk_size,
                        "delimiters": [shared.get("delimiter", "\n\n")],
                        "overlapped_percent": overlap,
                        "table_context_size": shared.get("table_context_size", 100),
                        "image_context_size": shared.get("image_context_size", 100),
                    },
                },
                "downstream": ["Tokenizer:0"],
                "upstream": ["Parser:0"],
            },
            "Tokenizer:0": {
                "obj": {
                    "component_name": "Tokenizer",
                    "params": {
                        "search_method": ["embedding", "full_text"],
                        "filename_embd_weight": 0.1,
                        "fields": ["text"],
                    },
                },
                "downstream": [],
                "upstream": ["TokenChunker:0"],
            },
        },
        "path": [],
    }


def collect_corpus() -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for directory in CORPUS_DIRS:
        if not directory.exists():
            raise FileNotFoundError(f"Missing cleaned corpus directory: {directory}")
        for path in sorted(directory.glob("*.md")):
            if path.name in seen:
                raise RuntimeError(f"Duplicate corpus filename: {path.name}")
            seen.add(path.name)
            files.append(path)
    return files


def wait_for_pipeline(
    client: RagflowClient,
    dataset_id: str,
    expected_ids: set[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    last_summary = ""
    while True:
        documents = client.list_documents(dataset_id)
        selected = [item for item in documents if item.get("id") in expected_ids]
        done = [item for item in selected if float(item.get("progress") or 0) == 1]
        failed = [item for item in selected if float(item.get("progress") or 0) < 0]
        running = len(selected) - len(done) - len(failed)
        summary = f"done={len(done)} running={running} failed={len(failed)}"
        if summary != last_summary:
            print(f"  {summary}")
            last_summary = summary
        if len(done) + len(failed) >= len(expected_ids):
            logs = client.ingestion_logs(dataset_id)
            return {
                "done": len(done),
                "failed": len(failed),
                "log_count": logs.get("total", len(logs.get("logs", []))),
            }
        if time.monotonic() - started > timeout_seconds:
            logs = client.ingestion_logs(dataset_id)
            return {
                "done": len(done),
                "failed": len(failed),
                "running": running,
                "log_count": logs.get("total", len(logs.get("logs", []))),
                "timed_out": True,
            }
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create RAGFlow A/B/C dataflow chunk experiments.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--only", choices=["A", "B", "C"], action="append")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--refresh-prefix", action="append", default=[])
    parser.add_argument("--prune", action="store_true", help="Delete dataset documents that are no longer in the cleaned corpus.")
    parser.add_argument("--refresh-changed", action="store_true", help="Replace documents whose cleaned file hash changed.")
    args = parser.parse_args()

    config = load_config()
    corpus = collect_corpus()
    client = RagflowClient(args.base_url)
    source = client.request("GET", f"/datasets/{SOURCE_DATASET_ID}")
    embedding_model = source["embedding_model"]
    selected = set(args.only or ["A", "B", "C"])
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {"experiments": {}}
    state.update(
        {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source_dataset_id": SOURCE_DATASET_ID,
            "corpus_count": len(corpus),
        }
    )

    for experiment in config["datasets"]:
        key = experiment["key"]
        if key not in selected:
            continue
        chunk_tokens = experiment["chunk_token_num"]
        overlap_percent = experiment["overlapped_percent"]
        title = f"暨南大学学生助手-流水线{key}-{chunk_tokens}tokens"
        dataset_name = experiment["name"]
        dsl = build_dsl(
            chunk_tokens,
            overlap_percent / 100,
            config["shared_parser_config"],
        )
        pipeline = client.ensure_pipeline(title, dsl)
        dataset = client.ensure_dataset(
            dataset_name,
            f"同一份清洗语料的分块实验 {key}：{chunk_tokens} tokens，重叠 {overlap_percent}%。",
            pipeline["id"],
            embedding_model,
        )
        print(f"[{key}] pipeline {pipeline['action']}: {pipeline['id']}")
        print(f"[{key}] dataset {dataset['action']}: {dataset['id']}")

        existing = {item["name"]: item for item in client.list_documents(dataset["id"])}
        corpus_names = {path.name for path in corpus}
        corpus_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in corpus}
        previous_hashes = state.get("experiments", {}).get(key, {}).get("corpus_hashes", {})
        stale_ids = [item["id"] for name, item in existing.items() if name not in corpus_names]
        if args.prune and stale_ids:
            client.delete_documents(dataset["id"], stale_ids)
            print(f"[{key}] pruned {len(stale_ids)} documents no longer present in the cleaned corpus")
            existing = {item["name"]: item for item in client.list_documents(dataset["id"])}
        refresh_ids = [
            item["id"]
            for name, item in existing.items()
            if any(name.startswith(prefix) for prefix in args.refresh_prefix)
            or (args.refresh_changed and name in previous_hashes and previous_hashes[name] != corpus_hashes.get(name))
        ]
        if refresh_ids:
            client.delete_documents(dataset["id"], refresh_ids)
            print(f"[{key}] deleted {len(refresh_ids)} changed documents for refresh")
            existing = {item["name"]: item for item in client.list_documents(dataset["id"])}
        missing = [path for path in corpus if path.name not in existing]
        uploaded = client.upload_documents(dataset["id"], missing) if missing else []
        documents = client.list_documents(dataset["id"])
        target_ids = {item["id"] for item in documents if item.get("name") in corpus_names}
        print(f"[{key}] corpus={len(corpus)} uploaded={len(uploaded)} target={len(target_ids)}")
        if len(target_ids) != len(corpus):
            raise RuntimeError(f"Dataset {key} has {len(target_ids)} of {len(corpus)} corpus documents")

        pending = [
            item["id"]
            for item in documents
            if item["id"] in target_ids and float(item.get("progress") or 0) != 1
        ]
        if pending:
            client.parse_documents(dataset["id"], pending)
            print(f"[{key}] queued {len(pending)} documents through dataflow")
        result = {"done": len(target_ids) - len(pending), "log_count": 0}
        if not args.no_wait and pending:
            result = wait_for_pipeline(client, dataset["id"], set(pending), args.timeout)
        elif not pending:
            logs = client.ingestion_logs(dataset["id"])
            result["log_count"] = logs.get("total", len(logs.get("logs", [])))

        state["experiments"][key] = {
            "pipeline_id": pipeline["id"],
            "dataset_id": dataset["id"],
            "dataset_name": dataset_name,
            "chunk_tokens": chunk_tokens,
            "overlap_percent": overlap_percent,
            "document_count": len(target_ids),
            "corpus_hashes": corpus_hashes,
            **result,
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
