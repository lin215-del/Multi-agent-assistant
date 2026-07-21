"""FastAPI 后端入口：六端点 + 静态托管前端。

启动流程：
  create_app() 建应用 + 在闭包里实例化 DB；模块顶层尝试编译 LangGraph（图无 env 时 warning）。

端点：
  POST /api/chat        问答（调 ask + classify chunks + 落库 + 返回 trace）
  GET  /api/cards       服务卡片清单
  GET  /api/cards/{id}  单卡片详情
  GET  /api/history     历史倒序列表
  GET  /api/history/{id} 单条 trace
  GET  /api/documents   代理 RAGFlow 文档列表
  GET  /                静态托管 web/frontend/
"""
import json
import os
import warnings
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

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
    """启动时读 cards.json；缺失用空 groups 兜底（不阻塞启动）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        warnings.warn(f"cards.json not found at {path}; /api/cards 返回空")
        return {"groups": []}


def _list_ragflow_documents() -> list[dict]:
    """代理 RAGFlow GET /api/v1/datasets/{id}/documents，返回 [{name,chunk_count,run}, ...]。"""
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
    """给每个 chunk 加 type（table/figure/text），答辫多模态差异化的钩子。"""
    out = []
    for m in matches or []:
        m2 = dict(m)
        m2["type"] = classify_chunk(m.get("content", ""))
        out.append(m2)
    return out


def _flat_card_index(cards: dict) -> dict:
    """把 cards.json 拍平为 {id: card} 字典，方便按 id 查。"""
    idx = {}
    for g in cards.get("groups", []):
        for c in g.get("cards", []):
            idx[c["id"]] = {**c, "group": g["name"]}
    return idx


def create_app() -> FastAPI:
    """工厂函数：测试和真实启动都用它；DB 路径由模块级 DB_PATH 控制（测试 monkeypatch 替换）。

    DB 实例放闭包，不依赖 application.state（避免 lifespan 时序问题）。
    """
    db = HistoryDB(DB_PATH)
    cards = _load_cards(CARDS_PATH)
    card_index = _flat_card_index(cards)

    application = FastAPI(title="暨大学生助手 API")

    @application.post("/api/chat")
    def chat(payload: dict):
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
        }
        try:
            trace["history_id"] = db.save(record)
        except Exception as exc:
            warnings.warn(f"history 落库失败: {exc}")
            trace["history_id"] = None
        return trace

    @application.get("/api/cards")
    def list_cards():
        return cards

    @application.get("/api/cards/{card_id}")
    def get_card(card_id: str):
        if card_id not in card_index:
            raise HTTPException(status_code=404, detail=f"卡片不存在: {card_id}")
        return card_index[card_id]

    @application.get("/api/history")
    def list_history(limit: int = 50):
        return db.list_recent(limit=limit)

    @application.get("/api/history/{rid}")
    def get_history(rid: int):
        row = db.get(rid)
        if row is None:
            raise HTTPException(status_code=404, detail=f"历史不存在: {rid}")
        return row

    @application.get("/api/documents")
    def list_documents():
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
    """模块 import 时尝试编译 LangGraph 图；env 缺失时 warning 不报错。"""
    try:
        compile_app()
    except KeyError as exc:
        warnings.warn(f"LangGraph 未编译（env 缺失: {exc}）；/api/chat 会在调用时失败，直到补齐 env")


_safe_compile_at_import()