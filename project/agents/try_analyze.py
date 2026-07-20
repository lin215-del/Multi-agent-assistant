"""手动实测：看检索+分析的返回内容。两种模式：

默认（检索→分析）：跳过调度，直接看检索资料 + 生成答案
  .venv/Scripts/python.exe agents/try_analyze.py "推免生申请需要什么条件"

--graph（调度→检索→分析）：跑完整 LangGraph 流水线，多打一行路由决策
  .venv/Scripts/python.exe agents/try_analyze.py "推免生申请需要什么条件" --graph

临时换分析模型（不改 .env）：
  ... --model Qwen/Qwen2.5-7B-Instruct

前提：VPN 开着（RAGFlow 检索要调 SiliconFlow embedding，不开会 SSL 失败）。
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")  # 避免 Windows 控制台 GBK 打中文崩

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_env():
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def main():
    load_env()
    parser = argparse.ArgumentParser(description="手动跑检索+分析，看返回内容")
    parser.add_argument("question", help="要问的问题")
    parser.add_argument("--model", default=None,
                        help="临时覆盖分析模型 ANALYZER_MODEL，如 Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--top-k", type=int, default=8, help="检索 chunk 数，默认 8（仅默认模式生效）")
    parser.add_argument("--graph", action="store_true",
                        help="跑完整 LangGraph 流水线（调度→检索→分析）")
    args = parser.parse_args()

    if args.model:
        os.environ["ANALYZER_MODEL"] = args.model

    print("问题：", args.question)
    print("分析模型：", os.environ.get("ANALYZER_MODEL", "(未设)"))
    print("模式：", "完整图（调度→检索→分析）" if args.graph else "检索→分析")

    if args.graph:
        from agents.graph import build_graph
        print("\n正在跑 LangGraph 流水线...")
        result = build_graph().invoke({"question": args.question})
        print("===== 路由决策 =====", result.get("route"))
        refl = result.get("reflection") or {}
        if refl:
            print("===== 反思 ===== ok=%s | %s" % (refl.get("ok"), refl.get("reason")))
        if result.get("tool_output"):
            print("===== 工具结果 =====", result["tool_output"])
        chunks = result.get("retrieved", [])
        if chunks:
            print("===== 检索到 %d 个 chunk =====" % len(chunks))
            for i, c in enumerate(chunks[:5], 1):
                print("[%d] score=%.3f | %s" % (i, c["score"], c["source"]))
                print("   ", c["content"][:80].replace("\n", " "))
        print("\n===== 最终答案 =====")
        print(result.get("final", ""))
    else:
        from agents.retriever import retrieve_chunks
        from agents.analyzer import generate_with_llm
        print("\n正在检索...")
        chunks = retrieve_chunks(args.question, top_k=args.top_k)
        print("===== 检索到 %d 个 chunk =====" % len(chunks))
        for i, c in enumerate(chunks, 1):
            print("[%d] score=%.3f | %s" % (i, c["score"], c["source"]))
            print("   ", c["content"][:80].replace("\n", " "))
        print("\n正在生成答案...")
        print("\n===== 答案 =====")
        print(generate_with_llm(args.question, chunks))


if __name__ == "__main__":
    main()
