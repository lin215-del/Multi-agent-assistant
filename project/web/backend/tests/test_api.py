"""app.py 的测试：端点契约 + 认证。

TDD 约定：用 FastAPI TestClient + monkeypatch 假 graph_service.ask，不真连 LLM/RAGFlow。
认证：直接注 token 进 auth 模块的内存表，不用走 login/register。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

import pytest
from fastapi.testclient import TestClient

from web.backend import app as app_module
from web.backend.app import create_app


@pytest.fixture
def auth_headers():
    """普通用户 token。"""
    from web.backend.auth import _tokens
    _tokens["test-token"] = {"username": "testuser", "role": "user"}
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_headers():
    """管理员 token。"""
    from web.backend.auth import _tokens
    _tokens["admin-token"] = {"username": "admin", "role": "admin"}
    return {"Authorization": "Bearer admin-token"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient：内存 SQLite + 假 ask。"""
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


# ========== 认证端点 ==========

def test_register_creates_user(client):
    r = client.post("/api/register", json={"username": "alice", "password": "pw123"})
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "user"
    assert data["username"] == "alice"
    assert "token" in data


def test_register_duplicate_rejected(client):
    client.post("/api/register", json={"username": "bob", "password": "pw"})
    r = client.post("/api/register", json={"username": "bob", "password": "pw"})
    assert r.status_code == 409


def test_register_empty_username_rejected(client):
    r = client.post("/api/register", json={"username": "", "password": "pw"})
    assert r.status_code == 400


def test_login_as_admin(client):
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "admin"
    assert "token" in data


def test_login_as_registered_user(client):
    client.post("/api/register", json={"username": "carol", "password": "pw456"})
    r = client.post("/api/login", json={"username": "carol", "password": "pw456"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"


def test_login_bad_password(client):
    client.post("/api/register", json={"username": "dave", "password": "right"})
    r = client.post("/api/login", json={"username": "dave", "password": "wrong"})
    assert r.status_code == 401


def test_me_returns_user_info(client, auth_headers):
    r = client.get("/api/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "testuser"
    assert data["role"] == "user"


def test_me_without_token_returns_401(client):
    r = client.get("/api/me")
    assert r.status_code == 401


# ========== /api/chat ==========

def test_chat_returns_answer_and_history_id(client, auth_headers):
    r = client.post("/api/chat", json={"question": "国奖申请条件"}, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "answer_for:国奖申请条件"
    assert data["route"] == "retrieve"
    assert isinstance(data["history_id"], int)
    assert data["latency_ms"] >= 0


def test_chat_requires_auth(client):
    r = client.post("/api/chat", json={"question": "x"})
    assert r.status_code == 401


def test_chat_rejects_missing_question(client, auth_headers):
    r = client.post("/api/chat", json={}, headers=auth_headers)
    assert r.status_code == 422


def test_chat_classifies_each_match_with_type(client, auth_headers, monkeypatch):
    fake_ask = lambda q: {
        "answer": "x",
        "route": "retrieve",
        "matches": [
            {"content": "| --- |\n| 表 |", "source": "PDF-1", "score": 0.9},
            {"content": "[图1] 流程图", "source": "PDF-1", "score": 0.85},
            {"content": "普通正文段落…", "source": "通知-1", "score": 0.7},
        ],
        "tool_output": None, "analysis": "", "reflection": None, "round": 0,
        "latency_ms": 10, "error": None,
    }
    monkeypatch.setattr("web.backend.graph_service.ask", fake_ask)
    r = client.post("/api/chat", json={"question": "x"}, headers=auth_headers)
    types = [m["type"] for m in r.json()["matches"]]
    assert types == ["table", "figure", "text"]


# ========== /api/cards ==========

def test_cards_returns_groups(client, auth_headers):
    r = client.get("/api/cards", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "groups" in data
    assert len(data["groups"]) == 2
    assert {g["name"] for g in data["groups"]} == {"教务通知", "学生办事指南"}
    assert len(data["groups"][0]["cards"]) >= 5


def test_cards_requires_auth(client):
    r = client.get("/api/cards")
    assert r.status_code == 401


def test_cards_by_id_returns_single_card(client, auth_headers):
    r = client.get("/api/cards/通知-857469", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == "通知-857469"


def test_cards_by_id_missing_returns_404(client, auth_headers):
    r = client.get("/api/cards/不存在的id", headers=auth_headers)
    assert r.status_code == 404


# ========== /api/history ==========

def test_history_lists_recent_after_chat(client, auth_headers):
    client.post("/api/chat", json={"question": "first"}, headers=auth_headers)
    r = client.get("/api/history?limit=10", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert rows[0]["question"] == "first"


def test_history_scoped_to_user(client, auth_headers, monkeypatch, tmp_path):
    """普通用户只能看自己的历史。"""
    from web.backend.auth import _tokens
    _tokens["other-token"] = {"username": "other", "role": "user"}
    client.post("/api/chat", json={"question": "mine"}, headers=auth_headers)
    client.post("/api/chat", json={"question": "theirs"}, headers={"Authorization": "Bearer other-token"})
    r = client.get("/api/history?limit=50", headers=auth_headers)
    questions = [row["question"] for row in r.json()]
    assert "mine" in questions
    assert "theirs" not in questions


def test_history_admin_sees_all(client, auth_headers, admin_headers):
    """管理员看全部记录。"""
    client.post("/api/chat", json={"question": "by_user"}, headers=auth_headers)
    r = client.get("/api/history?limit=50", headers=admin_headers)
    questions = [row["question"] for row in r.json()]
    assert "by_user" in questions


def test_history_by_id_returns_full_trace(client, auth_headers):
    chat = client.post("/api/chat", json={"question": "z"}, headers=auth_headers).json()
    r = client.get(f"/api/history/{chat['history_id']}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["question"] == "z"
    assert data["reflection"] == {"ok": True, "reason": "ok"}


def test_history_by_id_missing_returns_404(client, auth_headers):
    r = client.get("/api/history/99999", headers=auth_headers)
    assert r.status_code == 404


# ========== /api/documents（仅管理员） ==========

def test_documents_admin_only(client, auth_headers, admin_headers, monkeypatch, tmp_path):
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(app_module, "_list_ragflow_documents", lambda: [
        {"name": "通知-857469.md", "chunk_count": 5, "run": "DONE"},
    ])
    application = create_app()
    c = TestClient(application)
    # 普通用户 403
    r = c.get("/api/documents", headers=auth_headers)
    assert r.status_code == 403
    # 管理员 200
    r = c.get("/api/documents", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()["docs"]) == 1


def test_documents_handles_ragflow_error(monkeypatch, tmp_path):
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(
        app_module, "_list_ragflow_documents",
        lambda: (_ for _ in ()).throw(RuntimeError("RAGFlow down")),
    )
    from web.backend.auth import _tokens
    _tokens["adm-tok"] = {"username": "a", "role": "admin"}
    application = create_app()
    c = TestClient(application)
    r = c.get("/api/documents", headers={"Authorization": "Bearer adm-tok"})
    assert r.status_code == 503
    assert "RAGFlow" in r.json()["detail"]