from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = PROJECT_ROOT / "knowledge_base"
MANIFEST_PATH = SNAPSHOT_ROOT / "manifest.json"
CHECKSUM_PATH = SNAPSHOT_ROOT / "SHA256SUMS.txt"
EXPERIMENT_CONFIG_PATH = PROJECT_ROOT / "config" / "chunk_experiment.json"
REPORT_PATH = PROJECT_ROOT / "outputs" / "team_restore.json"
CORE_DATASET_NAMES = {
    "暨南大学学生助手-核心服务卡片",
    "暨南大学学生助手-第一阶段",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def verify_snapshot() -> dict[str, Any]:
    if not MANIFEST_PATH.exists() or not CHECKSUM_PATH.exists():
        raise RuntimeError("知识库快照不完整，请重新从 GitHub 下载整个项目。")
    expected: dict[str, str] = {}
    for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        expected[relative] = digest
    failures = []
    for relative, digest in expected.items():
        path = SNAPSHOT_ROOT / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            failures.append(relative)
    if failures:
        sample = "、".join(failures[:5])
        raise RuntimeError(f"知识库快照校验失败（{sample}），请重新下载后再试。")
    return read_json(MANIFEST_PATH)


class RagflowClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        root = base_url.rstrip("/")
        self.base_url = root if root.endswith("/api/v1") else f"{root}/api/v1"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=180,
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"RAGFlow 返回了非 JSON 响应（HTTP {response.status_code}）。"
            ) from exc
        if not response.ok or payload.get("code") != 0:
            message = payload.get("message") or payload.get("data") or response.reason
            raise RuntimeError(f"RAGFlow 请求失败（HTTP {response.status_code}）：{message}")
        return payload.get("data")

    def list_datasets(self) -> list[dict[str, Any]]:
        return self.request("GET", "/datasets", params={"page": 1, "page_size": 100})

    def list_agents(self) -> list[dict[str, Any]]:
        data = self.request(
            "GET",
            "/agents",
            params={"page": 1, "page_size": 100, "canvas_category": "dataflow_canvas"},
        )
        return data.get("canvas", [])

    def ensure_pipeline(self, title: str, dsl: dict[str, Any]) -> str:
        existing = next(
            (item for item in self.list_agents() if item.get("title") == title),
            None,
        )
        payload = {"title": title, "dsl": dsl, "canvas_category": "dataflow_canvas"}
        if existing:
            self.request("PUT", f"/agents/{existing['id']}", json=payload)
            return str(existing["id"])
        created = self.request("POST", "/agents", json=payload)
        return str(created["id"])

    def ensure_dataset(
        self,
        source: dict[str, Any],
        pipeline_id: str | None,
        embedding_model: str | None,
    ) -> tuple[dict[str, Any], bool]:
        existing = next(
            (item for item in self.list_datasets() if item.get("name") == source["name"]),
            None,
        )
        if existing:
            return existing, False
        payload: dict[str, Any] = {
            "name": source["name"],
            "description": source.get("description") or "",
            "permission": "me",
        }
        if embedding_model:
            payload["embedding_model"] = embedding_model
        if pipeline_id:
            payload.update({"pipeline_id": pipeline_id, "parse_type": 0})
        else:
            payload["chunk_method"] = source.get("chunk_method") or "naive"
            if source.get("parser_config"):
                payload["parser_config"] = source["parser_config"]
        created = self.request("POST", "/datasets", json=payload)
        return created, True

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.request(
                "GET",
                f"/datasets/{dataset_id}/documents",
                params={
                    "page": page,
                    "page_size": 100,
                    "orderby": "create_time",
                    "desc": False,
                },
            )
            batch = data.get("docs", [])
            documents.extend(batch)
            if len(batch) < 100:
                return documents
            page += 1

    def upload_documents(
        self,
        dataset_id: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        handles = []
        files = []
        try:
            for row in rows:
                path = (SNAPSHOT_ROOT / row["blob_path"]).resolve()
                if SNAPSHOT_ROOT.resolve() not in path.parents or not path.is_file():
                    raise RuntimeError(f"快照文件路径无效：{row['blob_path']}")
                handle = path.open("rb")
                handles.append(handle)
                content_type = row.get("content_type") or mimetypes.guess_type(row["name"])[0]
                files.append(
                    ("file", (row["name"], handle, content_type or "application/octet-stream"))
                )
            return self.request(
                "POST",
                f"/datasets/{dataset_id}/documents",
                files=files,
            )
        finally:
            for handle in handles:
                handle.close()

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        if document_ids:
            self.request(
                "POST",
                f"/datasets/{dataset_id}/documents/parse",
                json={"document_ids": document_ids},
            )


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


def experiment_for_name(name: str) -> dict[str, Any] | None:
    config = read_json(EXPERIMENT_CONFIG_PATH)
    return next((item for item in config["datasets"] if item["name"] == name), None)


def selected_datasets(manifest: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    datasets = manifest["datasets"]
    if scope == "all":
        return datasets
    return [item for item in datasets if item["name"] in CORE_DATASET_NAMES]


def restore_dataset(
    client: RagflowClient,
    summary: dict[str, Any],
    batch_size: int,
    embedding_model_override: str | None,
) -> dict[str, Any]:
    source_dir = SNAPSHOT_ROOT / summary["path"]
    source = read_json(source_dir / "dataset.json")
    rows = read_jsonl(source_dir / "documents.jsonl")
    pipeline_id = None
    experiment = experiment_for_name(source["name"])
    if experiment:
        config = read_json(EXPERIMENT_CONFIG_PATH)
        title = (
            f"暨南大学学生助手-流水线{experiment['key']}-"
            f"{experiment['chunk_token_num']}tokens"
        )
        dsl = build_dsl(
            experiment["chunk_token_num"],
            experiment["overlapped_percent"] / 100,
            config["shared_parser_config"],
        )
        pipeline_id = client.ensure_pipeline(title, dsl)
    # Let the target RAGFlow use its configured default embedding model unless
    # the operator explicitly requests one. Snapshot provider/model identifiers
    # are not portable across teammates' RAGFlow installations.
    embedding_model = embedding_model_override
    dataset, created = client.ensure_dataset(source, pipeline_id, embedding_model)
    dataset_id = str(dataset["id"])
    existing = {str(item.get("name")) for item in client.list_documents(dataset_id)}
    pending = [row for row in rows if str(row["name"]) not in existing]
    uploaded_total = 0
    parsed_total = 0
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        uploaded = client.upload_documents(dataset_id, batch)
        uploaded_by_name = {str(item.get("name")): str(item.get("id")) for item in uploaded}
        parse_ids = [
            uploaded_by_name[row["name"]]
            for row in batch
            if int(row.get("chunk_count") or 0) > 0 and row["name"] in uploaded_by_name
        ]
        client.parse_documents(dataset_id, parse_ids)
        uploaded_total += len(uploaded)
        parsed_total += len(parse_ids)
        print(
            f"  {source['name']}: {min(offset + len(batch), len(pending))}/"
            f"{len(pending)} 已上传",
            flush=True,
        )
    return {
        "source_id": summary["id"],
        "dataset_id": dataset_id,
        "name": source["name"],
        "created": created,
        "snapshot_documents": len(rows),
        "uploaded": uploaded_total,
        "skipped": len(rows) - len(pending),
        "parse_queued": parsed_total,
        "pipeline_id": pipeline_id,
    }


def write_report(scope: str, base_url: str, results: list[dict[str, Any]]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    preferred = next(
        (item for item in results if item["name"] == "暨南大学学生助手-核心服务卡片"),
        results[0] if results else None,
    )
    report = {
        "restored_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope,
        "ragflow_base_url": base_url,
        "preferred_dataset_id": preferred["dataset_id"] if preferred else "",
        "datasets": results,
        "notes": [
            "API Key 未写入此报告。",
            "解析在 RAGFlow 后台继续运行，请在知识库文件列表或日志页查看进度。",
            "Vercel 无法访问本机 localhost；本地数据供本地 RAGFlow 或本地学生助手使用。",
            "原生 image_id 属于目标 RAGFlow 对象存储，重新解析后可能与快照中的 ID 不同。",
        ],
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="从 GitHub 快照恢复团队 RAGFlow 知识库。")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--scope", choices=["recommended", "all"], default="all")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--embedding-model")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 20:
        raise SystemExit("--batch-size 必须在 1 到 20 之间。")

    print("正在校验 GitHub 知识库快照...")
    manifest = verify_snapshot()
    targets = selected_datasets(manifest, args.scope)
    print(
        f"快照校验通过：准备恢复 {len(targets)} 个知识库、"
        f"{sum(item['documents'] for item in targets)} 条知识库记录。"
    )
    if args.dry_run:
        for item in targets:
            print(f"- {item['name']}：{item['documents']} 份文档")
        return

    api_key = os.getenv("RAGFLOW_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("请输入本机 RAGFlow API Key（输入不会显示）：").strip()
    if not api_key:
        raise SystemExit("未提供 RAGFlow API Key。")

    client = RagflowClient(args.base_url, api_key)
    client.list_datasets()
    results = []
    for index, summary in enumerate(targets, 1):
        print(f"[{index}/{len(targets)}] 恢复 {summary['name']}")
        results.append(
            restore_dataset(
                client,
                summary,
                args.batch_size,
                args.embedding_model,
            )
        )
    write_report(args.scope, args.base_url, results)
    print(f"恢复任务已提交。报告：{REPORT_PATH}")
    for result in results:
        print(
            f"- {result['name']}：新增 {result['uploaded']}，"
            f"跳过 {result['skipped']}，解析队列 {result['parse_queued']}"
        )


if __name__ == "__main__":
    main()
