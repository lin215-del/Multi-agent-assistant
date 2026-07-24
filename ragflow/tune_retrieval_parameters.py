from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from import_experiment_pipelines import PROJECT_ROOT, RagflowClient


BENCHMARK_PATH = PROJECT_ROOT / "config" / "retrieval_benchmark.json"
EXPERIMENT_CONFIG_PATH = PROJECT_ROOT / "config" / "chunk_experiment.json"
OUTPUT_JSON = PROJECT_ROOT / "outputs" / "ragflow_parameter_tuning.json"
OUTPUT_MD = PROJECT_ROOT / "outputs" / "ragflow_parameter_tuning.md"
RECOMMENDED_CONFIG = PROJECT_ROOT / "config" / "recommended_retrieval.json"
DEFAULT_BASE_URL = "http://localhost:8080/api/v1"


@dataclass(frozen=True)
class Candidate:
    dataset_key: str
    dataset_id: str
    vector_weight: float
    rerank_id: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunk_text(chunk: dict[str, Any]) -> str:
    return "\n".join(
        str(chunk.get(key) or "")
        for key in ("document_keyword", "document_name", "content", "content_with_weight", "preview")
    ).lower()


def relevant_rank(chunks: list[dict[str, Any]], patterns: list[str], threshold: float) -> int | None:
    lowered = [pattern.lower() for pattern in patterns]
    for rank, chunk in enumerate(chunks, start=1):
        if float(chunk.get("similarity") or 0) < threshold:
            continue
        text = chunk_text(chunk)
        if any(pattern in text for pattern in lowered):
            return rank
    return None


def score_separation(results: list[dict[str, Any]]) -> dict[str, float]:
    positive_scores = []
    negative_scores = []
    for item in results:
        if item["case_type"] == "negative":
            if not item.get("guarded"):
                negative_scores.append(item["chunks"][0]["similarity"] if item["chunks"] else 0.0)
            continue
        patterns = [pattern.lower() for pattern in item["relevant_patterns"]]
        relevant_scores = [
            chunk["similarity"]
            for chunk in item["chunks"]
            if any(pattern in chunk_text(chunk) for pattern in patterns)
        ]
        positive_scores.append(max(relevant_scores, default=0.0))
    minimum_positive = min(positive_scores, default=0.0)
    maximum_negative = max(negative_scores, default=0.0)
    return {
        "minimum_relevant_positive_score": minimum_positive,
        "maximum_negative_top_score": maximum_negative,
        "margin": minimum_positive - maximum_negative,
    }


def retrieve_case(
    base_url: str,
    candidate: Candidate,
    case: dict[str, Any],
    case_type: str,
) -> dict[str, Any]:
    client = RagflowClient(base_url)
    started = time.monotonic()
    data = client.request(
        "POST",
        "/retrieval",
        json={
            "dataset_ids": [candidate.dataset_id],
            "question": case["query"],
            "page": 1,
            "page_size": 10,
            "top_k": 10,
            "similarity_threshold": 0.0,
            "vector_similarity_weight": candidate.vector_weight,
            "rerank_id": candidate.rerank_id,
            "highlight": False,
        },
    )
    chunks = data.get("chunks", [])
    return {
        "case_id": case["id"],
        "case_type": case_type,
        "query": case["query"],
        "relevant_patterns": case.get("relevant_patterns", []),
        "guarded": bool(case.get("guarded", False)),
        "latency_seconds": round(time.monotonic() - started, 4),
        "chunks": [
            {
                "rank": rank,
                "similarity": float(chunk.get("similarity") or 0),
                "document_name": chunk.get("document_keyword") or chunk.get("document_name") or "",
                "preview": str(chunk.get("content") or chunk.get("content_with_weight") or "")[:240],
            }
            for rank, chunk in enumerate(chunks, start=1)
        ],
    }


def run_candidate(
    base_url: str,
    candidate: Candidate,
    benchmark: dict[str, Any],
    workers: int,
) -> list[dict[str, Any]]:
    jobs = [
        (case, "positive") for case in benchmark["positive_cases"]
    ] + [(case, "negative") for case in benchmark["negative_cases"]]
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(retrieve_case, base_url, candidate, case, case_type)
            for case, case_type in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: (item["case_type"], item["case_id"]))


def score_results(
    results: list[dict[str, Any]],
    threshold: float,
    allowed_ids: set[str] | None = None,
) -> dict[str, Any]:
    selected = results if allowed_ids is None else [item for item in results if item["case_id"] in allowed_ids]
    positives = [item for item in selected if item["case_type"] == "positive"]
    negatives = [item for item in selected if item["case_type"] == "negative"]
    ranks = []
    positive_details = []
    for item in positives:
        chunks = [chunk for chunk in item["chunks"] if chunk["similarity"] >= threshold]
        rank = relevant_rank(chunks, item["relevant_patterns"], threshold)
        ranks.append(rank)
        positive_details.append(
            {
                "case_id": item["case_id"],
                "query": item["query"],
                "rank": rank,
                "top_document": chunks[0]["document_name"] if chunks else "",
                "top_score": chunks[0]["similarity"] if chunks else 0,
            }
        )

    negative_details = []
    rejected = 0
    for item in negatives:
        top = item["chunks"][0] if item["chunks"] else None
        is_rejected = bool(item.get("guarded")) or not top or top["similarity"] < threshold
        rejected += int(is_rejected)
        negative_details.append(
            {
                "case_id": item["case_id"],
                "query": item["query"],
                "rejected": is_rejected,
                "top_document": top["document_name"] if top else "",
                "top_score": top["similarity"] if top else 0,
            }
        )

    total_positive = max(len(positives), 1)
    total_negative = max(len(negatives), 1)
    recall_1 = sum(rank == 1 for rank in ranks) / total_positive
    recall_3 = sum(bool(rank and rank <= 3) for rank in ranks) / total_positive
    recall_5 = sum(bool(rank and rank <= 5) for rank in ranks) / total_positive
    mrr = sum(1 / rank if rank else 0 for rank in ranks) / total_positive
    negative_rejection = rejected / total_negative
    objective = (
        0.35 * recall_1
        + 0.20 * recall_3
        + 0.10 * recall_5
        + 0.20 * mrr
        + 0.15 * negative_rejection
    )
    return {
        "threshold": threshold,
        "objective": objective,
        "recall_at_1": recall_1,
        "recall_at_3": recall_3,
        "recall_at_5": recall_5,
        "mrr": mrr,
        "negative_rejection_rate": negative_rejection,
        "positive_details": positive_details,
        "negative_details": negative_details,
    }


def threshold_grid(values: list[float]) -> list[float]:
    return sorted({round(value, 3) for value in values if 0 <= value <= 1})


def candidate_key(candidate: Candidate) -> str:
    mode = "rerank" if candidate.rerank_id else "base"
    return f"{candidate.dataset_key}:{mode}:w={candidate.vector_weight:.3f}"


def summarize_candidate(
    candidate: Candidate,
    results: list[dict[str, Any]],
    thresholds: list[float],
    training_ids: set[str],
) -> dict[str, Any]:
    scored = [score_results(results, threshold, training_ids) for threshold in thresholds]
    best = max(scored, key=lambda item: (item["objective"], item["negative_rejection_rate"], item["mrr"]))
    return {
        "dataset_key": candidate.dataset_key,
        "dataset_id": candidate.dataset_id,
        "vector_weight": candidate.vector_weight,
        "rerank_id": candidate.rerank_id,
        "mean_latency_seconds": statistics.mean(item["latency_seconds"] for item in results),
        "best": best,
        "threshold_scores": [
            {key: value for key, value in item.items() if not key.endswith("_details")}
            for item in scored
        ],
        "raw_results": results,
    }


def markdown_report(payload: dict[str, Any]) -> str:
    best = payload["recommendation"]
    lines = [
        "# RAGFlow 检索参数自动调优报告",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 推荐配置",
        "",
        f"- 数据集方案：{best['dataset_key']}",
        f"- 数据集 ID：`{best['dataset_id']}`",
        f"- 数据集分块数：{best['chunk_count']}",
        f"- 向量相似度权重：{best['vector_weight']:.3f}",
        f"- Rerank：{best['rerank_id'] or '关闭'}",
        f"- 最低相似度阈值：{best['similarity_threshold']:.3f}",
        f"- 验证集 Top 1：{best['metrics']['recall_at_1']:.1%}",
        f"- 验证集 Recall@3：{best['metrics']['recall_at_3']:.1%}",
        f"- 验证集 MRR：{best['metrics']['mrr']:.3f}",
        f"- 验证集无答案拒答率：{best['metrics']['negative_rejection_rate']:.1%}",
        f"- 正负样本分数间隔：{best['score_separation']['margin']:.4f}",
        "",
        "> 分数间隔较窄时，阈值附近的结果应拒答或进入人工复核；账号密码、隐私和医疗问题必须使用独立安全规则拦截。",
        "",
        "## 候选排名",
        "",
        "| 排名 | 数据集 | 模式 | 分块 | 向量权重 | 阈值 | 训练分 | 验证分 | Top 1 | Recall@3 | MRR | 拒答率 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(payload["leaderboard"], start=1):
        metrics = item["metrics"]
        lines.append(
            f"| {index} | {item['dataset_key']} | {'Rerank' if item['rerank_id'] else '基础'} | "
            f"{item['chunk_count']} | {item['vector_weight']:.3f} | "
            f"{item['threshold']:.3f} | {item['training_objective']:.3f} | {item['objective']:.3f} | "
            f"{metrics['recall_at_1']:.1%} | {metrics['recall_at_3']:.1%} | "
            f"{metrics['mrr']:.3f} | {metrics['negative_rejection_rate']:.1%} |"
        )
    lines.extend(["", "## 主要错误案例", ""])
    for item in best["metrics"]["positive_details"]:
        if item["rank"] != 1:
            lines.append(
                f"- `{item['case_id']}`：正确资料排名 {item['rank'] or '未进入 Top 10'}；"
                f"第一名 `{item['top_document'] or '无'}`，分数 {item['top_score']:.3f}。"
            )
    for item in best["metrics"]["negative_details"]:
        if not item["rejected"]:
            lines.append(
                f"- `{item['case_id']}`：无答案问题未拒答；第一名 "
                f"`{item['top_document'] or '无'}`，分数 {item['top_score']:.3f}。"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune RAGFlow retrieval parameters with labeled cases.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--datasets", nargs="*", choices=["A", "B", "C"], default=["A", "B", "C"])
    parser.add_argument("--apply", action="store_true", help="Activate the recommendation in the project config file.")
    parser.add_argument("--reuse-results", action="store_true", help="Re-score the last raw API results without calling RAGFlow again.")
    parser.add_argument("--notice-only", action="store_true", help="Tune the grounded official-notice fallback rather than core service cards.")
    parser.add_argument(
        "--rerank-id",
        default="BAAI/bge-reranker-v2-m3@default1@OpenAI-API-Compatible",
        help="Rerank model used by the notice fallback comparison.",
    )
    parser.add_argument(
        "--index-settle-seconds",
        type=float,
        default=15,
        help="Wait for the RAGFlow search index to become visible before a fresh benchmark.",
    )
    args = parser.parse_args()

    benchmark = load_json(BENCHMARK_PATH)
    if args.notice_only:
        benchmark = {
            **benchmark,
            "positive_cases": [
                item for item in benchmark["positive_cases"] if item.get("target") == "notice"
            ],
        }
    experiment_config = load_json(EXPERIMENT_CONFIG_PATH)
    client = RagflowClient(args.base_url)
    datasets_by_name = {item["name"]: item for item in client.list_datasets()}
    experiment_by_key = {item["key"]: item for item in experiment_config["datasets"]}
    dataset_ids = {}
    dataset_chunk_counts = {}
    for key in args.datasets:
        dataset = datasets_by_name.get(experiment_by_key[key]["name"])
        if not dataset:
            raise RuntimeError(f"Experiment dataset {key} is missing")
        dataset_ids[key] = dataset["id"]
        dataset_chunk_counts[key] = int(dataset.get("chunk_count") or 0)

    positive_ids = [item["id"] for item in benchmark["positive_cases"]]
    negative_ids = [item["id"] for item in benchmark["negative_cases"]]
    validation_ids = {
        *[case_id for index, case_id in enumerate(positive_ids) if index % 4 == 0],
        *[case_id for index, case_id in enumerate(negative_ids) if index % 3 == 0],
    }
    training_ids = set(positive_ids + negative_ids) - validation_ids

    coarse_weights = [0.3, 0.5, 0.7, 0.9]
    coarse_thresholds = threshold_grid([0.30 + index * 0.05 for index in range(10)])
    previous_payload = load_json(OUTPUT_JSON) if args.reuse_results and OUTPUT_JSON.exists() else None
    evaluations: dict[str, dict[str, Any]] = {}
    print(f"Benchmark: {len(benchmark['positive_cases'])} positive + {len(benchmark['negative_cases'])} negative")

    if not previous_payload and args.index_settle_seconds > 0:
        print(f"Waiting {args.index_settle_seconds:g}s for the RAGFlow index to settle")
        time.sleep(args.index_settle_seconds)

    if previous_payload:
        all_thresholds = threshold_grid([0.30 + index * 0.025 for index in range(21)])
        for old in previous_payload.get("evaluations", {}).values():
            candidate = Candidate(
                old["dataset_key"], old["dataset_id"], old["vector_weight"], old.get("rerank_id")
            )
            evaluations[candidate_key(candidate)] = summarize_candidate(
                candidate, old["raw_results"], all_thresholds, training_ids
            )
    else:
        for key, dataset_id in dataset_ids.items():
            for weight in coarse_weights:
                candidate = Candidate(key, dataset_id, weight)
                print(f"[coarse] {candidate_key(candidate)}")
                results = run_candidate(args.base_url, candidate, benchmark, args.workers)
                evaluations[candidate_key(candidate)] = summarize_candidate(
                    candidate, results, coarse_thresholds, training_ids
                )
            if args.notice_only and args.rerank_id:
                for weight in (0.8, 0.9, 1.0):
                    candidate = Candidate(key, dataset_id, weight, args.rerank_id)
                    print(f"[coarse] {candidate_key(candidate)}")
                    results = run_candidate(args.base_url, candidate, benchmark, args.workers)
                    evaluations[candidate_key(candidate)] = summarize_candidate(
                        candidate, results, coarse_thresholds, training_ids
                    )

    coarse_best = max(
        evaluations.values(),
        key=lambda item: (item["best"]["objective"], item["best"]["negative_rejection_rate"], item["best"]["mrr"]),
    )
    best_weight = coarse_best["vector_weight"]
    best_threshold = coarse_best["best"]["threshold"]
    refine_weights = threshold_grid([best_weight - 0.1, best_weight - 0.05, best_weight + 0.05, best_weight + 0.1])
    refine_thresholds = threshold_grid([best_threshold + offset for offset in (-0.075, -0.05, -0.025, 0, 0.025, 0.05, 0.075)])

    if not previous_payload:
        for key, dataset_id in dataset_ids.items():
            for weight in refine_weights:
                candidate = Candidate(key, dataset_id, weight, coarse_best.get("rerank_id"))
                key_name = candidate_key(candidate)
                if key_name in evaluations:
                    continue
                print(f"[refine] {key_name}")
                results = run_candidate(args.base_url, candidate, benchmark, args.workers)
                evaluations[key_name] = summarize_candidate(
                    candidate, results, refine_thresholds, training_ids
                )

    leaderboard = []
    for evaluation in evaluations.values():
        best = evaluation["best"]
        validation_metrics = score_results(
            evaluation["raw_results"], best["threshold"], validation_ids
        )
        leaderboard.append(
            {
                "dataset_key": evaluation["dataset_key"],
                "dataset_id": evaluation["dataset_id"],
                "chunk_count": dataset_chunk_counts[evaluation["dataset_key"]],
                "vector_weight": evaluation["vector_weight"],
                "rerank_id": evaluation.get("rerank_id"),
                "threshold": best["threshold"],
                "training_objective": best["objective"],
                "objective": validation_metrics["objective"],
                "training_metrics": best,
                "metrics": validation_metrics,
                "mean_latency_seconds": evaluation["mean_latency_seconds"],
            }
        )
    leaderboard.sort(
        key=lambda item: (
            item["training_objective"],
            item["objective"],
            item["metrics"]["negative_rejection_rate"],
            item["metrics"]["mrr"],
            -item["chunk_count"],
        ),
        reverse=True,
    )
    winner = leaderboard[0]
    winner_evaluation = evaluations[
        candidate_key(
            Candidate(
                winner["dataset_key"], winner["dataset_id"], winner["vector_weight"], winner.get("rerank_id")
            )
        )
    ]
    recommendation = {
        "dataset_key": winner["dataset_key"],
        "dataset_id": winner["dataset_id"],
        "chunk_count": winner["chunk_count"],
        "vector_weight": winner["vector_weight"],
        "rerank_id": winner.get("rerank_id"),
        "similarity_threshold": winner["threshold"],
        "top_k": 10,
        "metrics": winner["metrics"],
        "score_separation": score_separation(winner_evaluation["raw_results"]),
    }
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "benchmark_version": benchmark["version"],
        "positive_cases": len(benchmark["positive_cases"]),
        "negative_cases": len(benchmark["negative_cases"]),
        "training_case_ids": sorted(training_ids),
        "validation_case_ids": sorted(validation_ids),
        "recommendation": recommendation,
        "leaderboard": leaderboard,
        "evaluations": evaluations,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(markdown_report(payload), encoding="utf-8")
    RECOMMENDED_CONFIG.write_text(
        json.dumps(
            {
                "generated_at": payload["generated_at"],
                "dataset_key": recommendation["dataset_key"],
                "dataset_id": recommendation["dataset_id"],
                "chunk_count": recommendation["chunk_count"],
                "vector_similarity_weight": recommendation["vector_weight"],
                "rerank_id": recommendation["rerank_id"],
                "similarity_threshold": recommendation["similarity_threshold"],
                "top_k": recommendation["top_k"],
                "score_separation": recommendation["score_separation"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.apply:
        print(f"Recommendation activated in project config: {RECOMMENDED_CONFIG}")
    print(markdown_report(payload))


if __name__ == "__main__":
    main()
