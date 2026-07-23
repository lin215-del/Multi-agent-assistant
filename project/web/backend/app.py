"""FastAPI 后端入口：六端点 + 认证 + 静态托管前端。

启动流程：
  create_app() 建应用 + 在闭包里实例化 DB；模块顶层尝试编译 LangGraph（图无 env 时 warning）。

端点：
  POST /api/register  注册普通用户
  POST /api/login     登录（管理员 / 普通用户）
  GET  /api/me        当前用户信息
  POST /api/chat      问答（需登录，调 ask + classify chunks + 落库 + 返回 trace）
  GET  /api/cards     服务卡片清单（需登录）
  GET  /api/cards/{id} 单卡片详情（需登录）
  GET  /api/history   历史倒序列表（管理员看全部，用户看自己）
  GET  /api/history/{id} 单条 trace（需登录）
  GET  /api/documents 代理 RAGFlow 文档列表（仅管理员）
  GET  /              静态托管 web/frontend/
"""
import json
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import requests
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.staticfiles import StaticFiles

from web.backend.auth import register_user, login_user, get_token_info
from web.backend.chunk_classifier import classify_chunk
from web.backend.db import HistoryDB
from web.backend.graph_service import compile_app

DB_PATH = os.environ.get(
    "HISTORY_DB_PATH",
    str(Path(__file__).resolve().parent / "history.db"),
)
CARDS_PATH = str(Path(__file__).resolve().parent / "cards.json")
FRONTEND_DIR = str(Path(__file__).resolve().parent.parent / "frontend")


def _load_cards(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        warnings.warn(f"cards.json not found at {path}; /api/cards 返回空")
        return {"groups": []}


def _list_ragflow_documents() -> list[dict]:
    base = os.environ["RAGFLOW_BASE_URL"]
    key = os.environ["RAGFLOW_API_KEY"]
    ds = os.environ["RAGFLOW_DATASET_ID"]
    r = requests.get(
        f"{base}/api/v1/datasets/{ds}/documents",
        headers={"Authorization": f"Bearer {key}"},
        params={"page": 1, "page_size": 100},
        timeout=15,
    )
    r.raise_for_status()
    docs = r.json().get("data", {}).get("docs", []) or []
    return [
        {"name": d.get("name", ""), "chunk_count": d.get("chunk_count", 0), "run": d.get("run", "")}
        for d in docs
    ]


def _enrich_matches(matches: list[dict]) -> list[dict]:
    out = []
    for m in matches or []:
        m2 = dict(m)
        m2["type"] = classify_chunk(m.get("content", ""))
        out.append(m2)
    return out


def _flat_card_index(cards: dict) -> dict:
    idx = {}
    for g in cards.get("groups", []):
        for c in g.get("cards", []):
            idx[c["id"]] = {**c, "group": g["name"]}
    return idx


def _get_current_user(authorization: str = Header(None)) -> dict:
    """FastAPI 依赖：从 Authorization header 解析当前用户。未登录/过期抛 401。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[len("Bearer "):]
    info = get_token_info(token)
    if info is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return info


def _require_admin(user: dict = Depends(_get_current_user)) -> dict:
    """仅管理员可访问。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return user


def create_app() -> FastAPI:
    db = HistoryDB(DB_PATH)
    cards = _load_cards(CARDS_PATH)
    card_index = _flat_card_index(cards)

    application = FastAPI(title="暨大学生助手 API")

    # ---- 认证端点 ----

    @application.post("/api/register")
    def register(payload: dict):
        username = (payload.get("username") or "").strip()
        password = (payload.get("password") or "").strip()
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        try:
            return register_user(username, password, DB_PATH)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    @application.post("/api/login")
    def login(payload: dict):
        username = (payload.get("username") or "").strip()
        password = (payload.get("password") or "").strip()
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        try:
            return login_user(username, password, DB_PATH)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))

    @application.get("/api/me")
    def me(user: dict = Depends(_get_current_user)):
        return {"username": user["username"], "role": user["role"]}

    # ---- 业务端点 ----

    @application.post("/api/chat")
    def chat(payload: dict, user: dict = Depends(_get_current_user)):
        from web.backend.graph_service import ask
        question = (payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="question 不能为空")

        trace = ask(question)
        trace["matches"] = _enrich_matches(trace.get("matches") or [])

        record = {
            "question": question,
            "route": trace.get("route"),
            "answer": trace.get("answer"),
            "matches": trace["matches"],
            "reflection": trace.get("reflection"),
            "analysis": trace.get("analysis"),
            "round": trace.get("round"),
            "latency_ms": trace.get("latency_ms"),
            "username": user["username"],
        }
        try:
            trace["history_id"] = db.save(record)
        except Exception as exc:
            warnings.warn(f"history 落库失败: {exc}")
            trace["history_id"] = None
        return trace

    @application.get("/api/cards")
    def list_cards(user: dict = Depends(_get_current_user)):
        return cards

    @application.get("/api/cards/{card_id}")
    def get_card(card_id: str, user: dict = Depends(_get_current_user)):
        if card_id not in card_index:
            raise HTTPException(status_code=404, detail=f"卡片不存在: {card_id}")
        return card_index[card_id]

    @application.get("/api/history")
    def list_history(limit: int = 50, user: dict = Depends(_get_current_user)):
        # 管理员看全部，普通用户只看自己
        uname = None if user["role"] == "admin" else user["username"]
        return db.list_recent(limit=limit, username=uname)

    @application.get("/api/history/{rid}")
    def get_history(rid: int, user: dict = Depends(_get_current_user)):
        row = db.get(rid)
        if row is None:
            raise HTTPException(status_code=404, detail=f"历史不存在: {rid}")
        return row

    @application.get("/api/documents")
    def list_documents(user: dict = Depends(_require_admin)):
        try:
            docs = _list_ragflow_documents()
            return {"docs": docs, "count": len(docs)}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"RAGFlow 不可用: {exc}")

    if os.path.isdir(FRONTEND_DIR):
        application.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return application


APP = create_app()


def _safe_compile_at_import():
    try:
        compile_app()
    except KeyError as exc:
        warnings.warn(f"LangGraph 未编译（env 缺失: {exc}）；/api/chat 会在调用时失败，直到补齐 env")


_safe_compile_at_import()