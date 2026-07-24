from __future__ import annotations

import sys

from core_services import ask_core_service


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = "本科生请假申请表在哪里下载？"

    result = ask_core_service(question)
    print(result["answer"])
    if result["source_url"]:
        print(f"来源链接：{result['source_url']}")
    if result["document_name"]:
        print(f"命中文档：{result['document_name']}")
    print(f"相似度：{result['similarity']:.3f}")


if __name__ == "__main__":
    main()
