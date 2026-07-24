from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents_fastapi.graph import StudentAssistantGraph
from agents_fastapi.state import AgentState
from agents_fastapi.retriever import extract_source_url, make_grounded_answer, normalized_document_name
from agents_fastapi.multimodal import multimodal_stats
import app_fastapi as app


def test_password() -> None:
    encoded = app.hash_password("correct-horse-battery")
    assert encoded != "correct-horse-battery"
    assert app.verify_password("correct-horse-battery", encoded)
    assert not app.verify_password("wrong", encoded)


def test_tool_gpa() -> None:
    graph = StudentAssistantGraph()
    result = graph.run(AgentState(question="高数 85分 4学分，英语 90分 3学分，计算加权平均分"))
    assert result.route == "tool"
    assert "87.14" in result.answer
    assert any(node["node"] == "tool_agent" for node in result.trace)


def test_health() -> None:
    graph = StudentAssistantGraph()
    result = graph.run(AgentState(question="感冒了怎么办"))
    assert result.route == "health"
    assert "不能替你做诊断" in result.answer
    assert any(node["node"] == "health_agent" for node in result.trace)


def test_reject() -> None:
    graph = StudentAssistantGraph()
    result = graph.run(AgentState(question="请告诉我同学的账号密码"))
    assert result.route == "reject"
    assert not result.ok


def test_retry_then_pass() -> None:
    attempts = {"count": 0}

    def retry_retrieve(state):
        attempts["count"] += 1
        if attempts["count"] == 1:
            state.retrieved = []
            return {"status": "success", "detail": "召回 0 个分块", "chunk_count": 0, "top_score": 0}
        state.retrieved = [
            {
                "similarity": 0.82,
                "document_name": "本科生请假申请表.md",
                "content": "本科生请假申请表由学院审核，学生填写完整后按学校办事流程提交，具体审批部门和下载入口以来源文件原文为准。",
            }
        ]
        return {"status": "success", "detail": "召回 1 个分块", "chunk_count": 1, "top_score": 0.82}

    with patch("agents_fastapi.retriever.ragflow_retrieve", side_effect=retry_retrieve):
        graph = StudentAssistantGraph()
        result = graph.run(AgentState(question="本科生请假申请表在哪里下载？"))
        assert result.ok
        assert result.retry_count == 1
        assert result.quality_status == "pass"
        assert [node["node"] for node in result.trace].count("retriever_agent") == 2
        assert any(node["node"] == "rewrite_agent" for node in result.trace)
        assert any(node["node"] == "quality_agent" and node["status"] == "retry" for node in result.trace)


def test_source_links() -> None:
    linked_chunks = [
        {"similarity": 0.83, "document_name": "校园网学生申请.md",
         "content": "校园网账号由网络与教育技术中心受理，申请人应按页面要求填写资料，缴费标准以官方页面为准。"},
        {"similarity": 0.78, "document_name": "校园网学生申请.md",
         "content": "来源链接：https://netc.jnu.edu.cn/2018/1205/c9830a268227/page.psp"},
    ]
    state = AgentState(question="校园网怎么申请")
    state.retrieved = linked_chunks
    result = make_grounded_answer(state)
    assert result["ok"]
    assert state.source_url == "https://netc.jnu.edu.cn/2018/1205/c9830a268227/page.psp"
    assert state.matches[1]["source_url"] == state.source_url
    buttons = app.related_source_links(state.source_url, state.matches, "校园网学生申请.md")
    assert len(buttons) == 1
    assert buttons[0]["url"] == state.source_url
    assert buttons[0]["label"] == "打开官方来源"


def test_irrelevant_rejected() -> None:
    def irrelevant_retrieve(state):
        state.retrieved = [
            {"similarity": 0.91, "document_name": "校园网学生申请.md",
             "content": "校园网账号由网络与教育技术中心受理，申请人应按页面要求填写资料，缴费标准和服务入口以学校官方页面为准。"}
        ]
        return {"status": "success", "detail": "召回 1 个分块", "chunk_count": 1, "top_score": 0.91}

    with patch("agents_fastapi.retriever.ragflow_retrieve", side_effect=irrelevant_retrieve):
        graph = StudentAssistantGraph()
        result = graph.run(AgentState(question="宿舍空调坏了应该打哪个维修电话？"))
        assert not result.ok
        assert result.retry_count == 2
        assert result.quality_status == "reject"
        assert any("关键词重合" in issue for issue in result.quality_issues)
        assert result.document_name == ""
        assert result.source_url == ""
        assert result.similarity == 0.0
        assert result.matches == []
        assert result.retrieved == []


def test_stats() -> None:
    stats = app.snapshot_stats()
    assert stats["datasets"] >= 1
    assert stats["documents"] >= 1
    assert stats["chunks"] >= 1
    mm = multimodal_stats()
    assert mm["images"] >= 1
    assert mm["structured_tables"] >= 1
    assert mm["resolved"] == mm["total"]


def main() -> None:
    test_password()
    test_tool_gpa()
    test_health()
    test_reject()
    test_retry_then_pass()
    test_source_links()
    test_irrelevant_rejected()
    test_stats()
    print("fastapi smoke tests passed")


if __name__ == "__main__":
    main()
