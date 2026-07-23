"""Chunk 审计报告：对 RAGFlow 检索回来的 chunks 做启发式质量评估，输出 Markdown 报告。

复用 agents.retriever.retrieve_chunks 取数据，纯启发式评估（不调 LLM）。
用法：python -m scripts.chunk_audit --queries queries.txt --top-k 10 --output report.md
"""
import argparse
import json
import os
import re
import sys
import time


def assess_chunk(chunk: dict) -> dict:
    """对单个 chunk 做启发式质量评估。

    返回字段：
      has_title — content 是否含标题标记（## / ### / 【】
      has_table_structure — 是否含 Markdown 表格管道符
      is_truncated — content 是否可能被截断
      is_figure — 是否为图描述 chunk
      content_length — 字符数
      quality_score — 综合质量分 0-1
    """
    content = (chunk or {}).get("content", "")
    if not content:
        return {
            "has_title": False, "has_table_structure": False,
            "is_truncated": False, "is_figure": False,
            "content_length": 0, "quality_score": 0.0,
        }

    has_title = bool(re.search(r'^#{1,3}\s|^#{1,3}(?:表格|图片|图\d)|【.+】', content, re.MULTILINE))
    has_table = "|---" in content or "| ---" in content or "<table" in content
    is_truncated = _looks_truncated(content)
    is_figure = "[图" in content or "图片描述：" in content
    length = len(content)

    score = 0.0
    if has_title:
        score += 0.25
    if not is_truncated:
        score += 0.30
    if 100 <= length <= 2000:
        score += 0.20
    elif length > 0:
        score += 0.10  # 太短或太长打折
    if content.strip():
        score += 0.25

    return {
        "has_title": has_title,
        "has_table_structure": has_table,
        "is_truncated": is_truncated,
        "is_figure": is_figure,
        "content_length": length,
        "quality_score": round(score, 2),
    }


def _looks_truncated(content: str) -> bool:
    """判断 content 是否可能被 MinerU / RAGFlow 截断。"""
    content = content.rstrip()
    if content.endswith("...") or content.endswith("……"):
        return True
    # 最后 20 字符无句末标点 → 可能截断
    tail = content[-20:]
    return not bool(re.search(r'[。！？.!?\n]', tail))


def audit_query(query: str, top_k: int = 10) -> list[dict]:
    """对单个测试查询检索 chunks 并逐一评估。"""
    from agents.retriever import retrieve_chunks
    chunks = retrieve_chunks(query, top_k=top_k)
    results = []
    for c in chunks:
        assessment = assess_chunk(c)
        results.append({
            "source": c.get("source", ""),
            "score": c.get("score", 0),
            "content_preview": c.get("content", "")[:120],
            "assessment": assessment,
        })
    return results


def run_audit(queries: list[str], top_k: int = 10) -> dict:
    """跑全量审计，输出结构化报告。"""
    per_query = []
    all_scores = []
    for q in queries:
        q = q.strip()
        if not q or q.startswith("#"):
            continue
        chunks = audit_query(q, top_k=top_k)
        scores = [c["assessment"]["quality_score"] for c in chunks]
        all_scores.extend(scores)
        per_query.append({
            "query": q,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        })

    total_chunks = sum(p["chunk_count"] for p in per_query)
    truncation_count = sum(
        1 for p in per_query for c in p["chunks"] if c["assessment"]["is_truncated"]
    )
    table_count = sum(
        1 for p in per_query for c in p["chunks"] if c["assessment"]["has_table_structure"]
    )
    figure_count = sum(
        1 for p in per_query for c in p["chunks"] if c["assessment"]["is_figure"]
    )

    return {
        "meta": {
            "total_queries": len(per_query),
            "total_chunks": total_chunks,
            "top_k": top_k,
        },
        "per_query": per_query,
        "summary": {
            "avg_quality_score": round(sum(all_scores) / len(all_scores), 2) if all_scores else 0,
            "truncation_rate": round(truncation_count / total_chunks, 2) if total_chunks else 0,
            "table_rate": round(table_count / total_chunks, 2) if total_chunks else 0,
            "figure_rate": round(figure_count / total_chunks, 2) if total_chunks else 0,
        },
    }


def format_report_markdown(report: dict) -> str:
    """把审计报告格式化为 Markdown。"""
    meta = report["meta"]
    summary = report["summary"]
    lines = [
        "# Chunk 审计报告",
        "",
        "## 概览",
        "",
        f"- 测试查询数：{meta['total_queries']}",
        f"- 总 chunk 数：{meta['total_chunks']}",
        f"- 每查询 top-k：{meta['top_k']}",
        "",
        "## 汇总统计",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 平均质量分 | {summary['avg_quality_score']} |",
        f"| 截断率 | {summary['truncation_rate']} |",
        f"| 表格 chunk 占比 | {summary['table_rate']} |",
        f"| 图描述 chunk 占比 | {summary['figure_rate']} |",
        "",
        "## 逐查询详情",
        "",
    ]

    for pq in report["per_query"]:
        lines.append(f"### 查询：{pq['query']}")
        lines.append(f"")
        lines.append(f"检索到 {pq['chunk_count']} 个 chunk，平均质量分 {pq['avg_score']}")
        lines.append("")
        lines.append("| # | 来源 | 相关度 | 长度 | 标题 | 表格 | 截断 | 图 | 质量分 | 内容预览 |")
        lines.append("|---|------|--------|------|------|------|------|----|--------|----------|")
        for i, c in enumerate(pq["chunks"], 1):
            a = c["assessment"]
            lines.append(
                f"| {i} | {c['source'][:30]} | {c['score']:.2f} | {a['content_length']} | "
                f"{'Y' if a['has_title'] else '-'} | "
                f"{'Y' if a['has_table_structure'] else '-'} | "
                f"{'⚠' if a['is_truncated'] else '-'} | "
                f"{'Y' if a['is_figure'] else '-'} | "
                f"{a['quality_score']} | "
                f"{c['content_preview'][:60]} |"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Chunk 审计报告")
    parser.add_argument("--queries", default=None, help="查询列表文件（每行一个查询）")
    parser.add_argument("--top-k", type=int, default=10, help="每查询检索 chunk 数（默认 10）")
    parser.add_argument("--output", default=None, help="输出 Markdown 文件路径（默认 stdout）")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON 而非 Markdown")
    args = parser.parse_args()

    # 加载环境变量（如果还没加载）
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.queries:
        with open(args.queries, "r", encoding="utf-8") as f:
            queries = f.readlines()
    else:
        # 默认测试查询
        queries = [
            "国家奖学金申请条件",
            "转专业流程",
            "学分绩点怎么算",
            "毕业论文格式要求",
            "助学金申请",
        ]

    print(f"审计中：{len(queries)} 条查询，top-k={args.top_k}...", file=sys.stderr)
    report = run_audit(queries, top_k=args.top_k)

    if getattr(args, "json"):
        output = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        output = format_report_markdown(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"报告已写入 {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
