"""app.py 的测试。TDD：用 FastAPI TestClient + monkeypatch 假 graph_service.ask，
不真连 LLM/RAGFlow；只验端点契约（请求形状 / 响应字段 / 落库 / 状态码）。

真联通性冒烟放最后用 .env 真值跑一次。
"""
import json
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

import pytest
from fastapi.testclient import TestClient

from web.backend import app as app_module
from web.backend.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    """建一个用内存 SQLite 的 FastAPI TestClient；monkeypatch graph_service.ask 用假函数。"""
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    fake_ask = lambda q: {
        "answer": f"answer_for:{q}",
        "route": "retrieve",
        "matches": [{"content": "c", "source": "通知-1", "score": 0.9}],
        "tool_output": None,
        "analysis": "draft",
        "reflection": {"ok": True, "reason": "ok"},
        "round": 0,
        "latency_ms": 12,
        "error": None,
    }
    monkeypatch.setattr("web.backend.graph_service.ask", fake_ask)
    application = create_app()
    return TestClient(application)


# ---------- /api/chat ----------
def test_chat_returns_answer_and_history_id(client):
    """POST /api/chat 调 ask + 落库，返回 {answer, history_id, ...}。"""
    r = client.post("/api/chat", json={"question": "国奖申请条件"})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "answer_for:国奖申请条件"
    assert data["route"] == "retrieve"
    assert isinstance(data["history_id"], int)
    assert data["latency_ms"] >= 0


def test_chat_rejects_missing_question(client):
    """没 question 字段 → 422 校验失败。"""
    r = client.post("/api/chat", json={})
    assert r.status_code == 422


def test_chat_classifies_each_match_with_type(client, monkeypatch):
    """matches 列表里每条 chunk 都被 classify_chunk 加 type 字段（table/figure/text）。"""
    fake_ask = lambda q: {
        "answer": "x",
        "route": "retrieve",
        "matches": [
            {"content": "| --- |\n| 表 |", "source": "PDF-1", "score": 0.9},   # 表格
            {"content": "[图1] 流程图", "source": "PDF-1", "score": 0.85},     # 图
            {"content": "普通正文段落…", "source": "通知-1", "score": 0.7},   # 正文
        ],
        "tool_output": None, "analysis": "", "reflection": None, "round": 0,
        "latency_ms": 10, "error": None,
    }
    monkeypatch.setattr("web.backend.graph_service.ask", fake_ask)
    r = client.post("/api/chat", json={"question": "x"})
    types = [m["type"] for m in r.json()["matches"]]
    assert types == ["table", "figure", "text"]


# ---------- /api/cards ----------
def test_cards_returns_groups(client):
    """GET /api/cards → cards.json 全量。"""
    r = client.get("/api/cards")
    assert r.status_code == 200
    data = r.json()
    assert "groups" in data
    assert len(data["groups"]) == 2
    assert {g["name"] for g in data["groups"]} == {"教务通知", "学生办事指南"}
    assert len(data["groups"][0]["cards"]) >= 5


def test_cards_by_id_returns_single_card(client):
    """GET /api/cards/{id} → 单卡片详情。"""
    r = client.get("/api/cards/通知-857469")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "通知-857469"
    assert "title" in data


def test_cards_by_id_missing_returns_404(client):
    """不存在的卡片 id → 404。"""
    r = client.get("/api/cards/不存在的id")
    assert r.status_code == 404


# ---------- /api/history ----------
def test_history_lists_recent_after_chat(client):
    """先聊一次，再查历史应能拿到刚才那条。"""
    client.post("/api/chat", json={"question": "first"})
    r = client.get("/api/history?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert rows[0]["question"] == "first"


def test_history_by_id_returns_full_trace(client):
    """GET /api/history/{id} → 完整 trace（含 reflection / matches / analysis）。"""
    chat = client.post("/api/chat", json={"question": "z"}).json()
    rid = chat["history_id"]
    r = client.get(f"/api/history/{rid}")
    assert r.status_code == 200
    data = r.json()
    assert data["question"] == "z"
    assert data["reflection"] == {"ok": True, "reason": "ok"}
    assert isinstance(data["matches"], list)


def test_history_by_id_missing_returns_404(client):
    """不存在的 history id → 404。"""
    r = client.get("/api/history/99999")
    assert r.status_code == 404


# ---------- /api/documents ----------
def test_documents_proxies_ragflow_list(monkeypatch, tmp_path):
    """GET /api/documents 代理 RAGFlow；monkeypatch _list_ragflow_documents 不依赖 env/真实请求。"""
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(
        app_module, "_list_ragflow_documents",
        lambda: [
            {"name": "通知-857469.md", "chunk_count": 5, "run": "DONE"},
            {"name": "PDF-yingzai.md", "chunk_count": 12, "run": "DONE"},
        ],
    )
    application = create_app()
    c = TestClient(application)
    r = c.get("/api/documents")
    assert r.status_code == 200
    docs = r.json()["docs"]
    assert len(docs) == 2
    assert docs[0]["name"] == "通知-857469.md"


def test_documents_handles_ragflow_error(monkeypatch, tmp_path):
    """RAGFlow 抛异常时返回 503 + 错误信息（FastAPI 默认 detail 字段）。"""
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(
        app_module, "_list_ragflow_documents",
        lambda: (_ for _ in ()).throw(RuntimeError("RAGFlow down")),
    )
    application = create_app()
    c = TestClient(application)
    r = c.get("/api/documents")
    assert r.status_code == 503
    assert "RAGFlow" in r.json()["detail"]