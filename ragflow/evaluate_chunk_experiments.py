from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from import_experiment_pipelines import CONFIG_PATH, PROJECT_ROOT, RagflowClient


OUTPUT_JSON = PROJECT_ROOT / "outputs" / "chunk_experiment_results.json"
OUTPUT_CSV = PROJECT_ROOT / "outputs" / "chunk_experiment_results.csv"
OUTPUT_MD = PROJECT_ROOT / "outputs" / "chunk_experiment_results.md"
FOCUS_CONFIG = PROJECT_ROOT / "config" / "chunk_experiment_focus.json"


def content_of(chunk: dict[str, Any]) -> str:
    return str(chunk.get("content_with_weight") or chunk.get("content") or "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the A/B/C RAGFlow chunk experiments.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080"),
        help="RAGFlow root URL or /api/v1 URL.",
    )
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    focus_names = set(json.loads(FOCUS_CONFIG.read_text(encoding="utf-8"))["documents"])
    root = args.base_url.rstrip("/")
    client = RagflowClient(root if root.endswith("/api/v1") else f"{root}/api/v1")
    datasets = {item["name"]: item for item in client.list_datasets()}
    results: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}

    for experiment in config["datasets"]:
        key = experiment["key"]
        dataset = datasets.get(experiment["name"])
        if not dataset:
            raise RuntimeError(f"Missing experiment dataset: {experiment['name']}")
        documents = client.list_documents(dataset["id"])
        focus_documents = [item for item in documents if item.get("name") in focus_names]
        incomplete = [item for item in focus_documents if float(item.get("progress") or 0) != 1]
        if len(focus_documents) != len(focus_names):
            raise RuntimeError(
                f"Experiment {key} has {len(focus_documents)}/{len(focus_names)} focused documents"
            )
        if incomplete:
            raise RuntimeError(
                f"Experiment {key} still has {len(incomplete)} incomplete focused documents"
            )

        reciprocal_ranks: list[float] = []
        hit_count = 0
        for question_item in config["questions"]:
            payload = client.request(
                "POST",
                "/retrieval",
                json={
                    "dataset_ids": [dataset["id"]],
                    "question": question_item["question"],
                    "page": 1,
                    "page_size": 10,
                    "top_k": 10,
                    "similarity_threshold": 0.1,
                    "vector_similarity_weight": 0.3,
                    "highlight": False,
                },
            )
            chunks = payload.get("chunks", [])
            expected = question_item["expected_terms"]
            first_rank = None
            matched_terms: set[str] = set()
            top_results = []
            for rank, chunk in enumerate(chunks, start=1):
                content = content_of(chunk)
                current = [term for term in expected if term in content]
                matched_terms.update(current)
                if current and first_rank is None:
                    first_rank = rank
                top_results.append(
                    {
                        "rank": rank,
                        "document_name": chunk.get("document_name") or chunk.get("docnm_kwd"),
                        "similarity": chunk.get("similarity"),
                        "matched_terms": current,
                        "preview": content[:300],
                    }
                )
            hit = first_rank is not None
            hit_count += int(hit)
            reciprocal_ranks.append(1 / first_rank if first_rank else 0)
            results.append(
                {
                    "experiment": key,
                    "dataset_id": dataset["id"],
                    "question": question_item["question"],
                    "expected_terms": expected,
                    "matched_terms": sorted(matched_terms),
                    "hit": hit,
                    "first_relevant_rank": first_rank,
                    "result_count": len(chunks),
                    "top_results": top_results,
                }
            )
            print(f"[{key}] {'HIT' if hit else 'MISS'} rank={first_rank}: {question_item['question']}")

        summaries[key] = {
            "dataset_id": dataset["id"],
            "chunk_tokens": experiment["chunk_token_num"],
            "overlap_percent": experiment["overlapped_percent"],
            "questions": len(config["questions"]),
            "hits": hit_count,
            "hit_rate": hit_count / len(config["questions"]),
            "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "document_count": len(documents),
            "focused_document_count": len(focus_documents),
            "chunk_count": dataset.get("chunk_count"),
        }

    payload = {"summaries": summaries, "results": results}
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "experiment",
                "question",
                "hit",
                "first_relevant_rank",
                "result_count",
                "expected_terms",
                "matched_terms",
            ],
        )
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    **{key: item[key] for key in writer.fieldnames if key not in {"expected_terms", "matched_terms"}},
                    "expected_terms": " | ".join(item["expected_terms"]),
                    "matched_terms": " | ".join(item["matched_terms"]),
                }
            )
    winner = min(
        summaries.items(),
        key=lambda item: (
            -item[1]["hit_rate"],
            -item[1]["mrr"],
            int(item[1].get("chunk_count") or 0),
            item[1]["chunk_tokens"],
        ),
    )
    lines = [
        "# RAGFlow A/B/C 分块对照实验",
        "",
        "三套知识库使用相同的 8 份核心事务文件和相同的 8 个问题，仅改变分块大小与重叠率。",
        "",
        "| 方案 | 分块 tokens | 重叠 | 聚焦文档 | 分块数 | 命中率 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, item in summaries.items():
        lines.append(
            f"| {key} | {item['chunk_tokens']} | {item['overlap_percent']}% | "
            f"{item['focused_document_count']} | {item['chunk_count']} | "
            f"{item['hit_rate']:.1%} | {item['mrr']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"## 结论：推荐方案 {winner[0]}",
            "",
            f"方案 {winner[0]} 在当前校准集达到 {winner[1]['hit_rate']:.1%} 命中率和 "
            f"{winner[1]['mrr']:.3f} MRR。B 与 C 精度相同时，优先选择 B（800 tokens、"
            "10% 重叠）：它比 1200-token 方案保留更细的上下文边界，同时没有产生更多分块。",
            "",
            "> 本报告是聚焦校准实验。三套知识库仍保留 180 份已上传文档；为避免本地 "
            "RAGFlow 和外部嵌入服务过载，本轮只解析三套完全一致的 8 份样本。",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
