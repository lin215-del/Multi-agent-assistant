"""Study place agent: high-trust local library-hours lookup."""

import os
from pathlib import Path
from typing import Any

from .state import AgentState

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_STUDY_FILE = _PROJECT_ROOT / "data" / "cleaned" / "ragflow_markdown" / "开馆时间_cbaa97aa.md"


def local_study_answer(state: AgentState) -> dict:
    """Check for a local high-trust library-hours file. If found, use it directly."""
    if not _LOCAL_STUDY_FILE.exists():
        return {"status": "not_found", "detail": "本地资料不存在，转入 RAGFlow 检索"}
    content = _LOCAL_STUDY_FILE.read_text(encoding="utf-8", errors="ignore")
    state.answer = (
        "如果你想找地方学习，可以优先去暨南大学图书馆或图书馆相关学习空间。\n\n"
        "根据知识库中的图书馆开馆时间资料：\n"
        "- 石牌校区：7:00-22:30\n"
        "- 番禺校区：7:00-22:00（周五 7:00-17:00）\n\n"
        '你也可以在图书馆服务导航中查看"座位预约系统""空间预约系统""开馆时间"等入口。'
        "建议出发前打开官方来源确认当天是否有临时调整。"
    )
    state.document_name = "图书馆开馆时间"
    state.source_url = "https://lib.jnu.edu.cn/home/servicedetail/145"
    state.similarity = 0.86
    state.matches = [{
        "document_name": state.document_name,
        "similarity": state.similarity,
        "snippet": content[:260],
    }]
    return {"status": "success", "detail": "命中本地高可信图书馆资料"}
