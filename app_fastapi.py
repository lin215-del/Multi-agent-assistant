from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents_fastapi.graph import StudentAssistantGraph
from agents_fastapi.state import AgentState
from agents_fastapi.tracing import trace as make_trace
from agents_fastapi.retriever import extract_source_url, normalized_document_name
from agents_fastapi.multimodal import find_multimodal_assets, load_multimodal_index, multimodal_stats
from multimodal.query_image import analyze_query_image

PROJECT_ROOT = Path(__file__).resolve().parent
TRACE_DIR = PROJECT_ROOT / "data" / "feedback"
TRACE_FILE = TRACE_DIR / "agent_traces.jsonl"
DB_FILE = TRACE_DIR / "assistant.sqlite3"
MULTIMODAL_INDEX_FILE = PROJECT_ROOT / "data" / "multimodal_index.json"
MINERU_DIR = PROJECT_ROOT / "data" / "cleaned" / "mineru"
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"


def load_local_env() -> None:
    for name in (".env", ".env.local"):
        path = PROJECT_ROOT / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()

DEFAULT_RAGFLOW_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080").rstrip("/")
DEFAULT_RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY", "")
DEFAULT_DATASET_ID = os.getenv("RAGFLOW_DATASET_ID", "")
DEFAULT_NOTICE_DATASET_ID = os.getenv("RAGFLOW_NOTICE_DATASET_ID", "")
RERANK_ID = os.getenv("RAGFLOW_RERANK_ID", "")
SESSION_TTL_SECONDS = max(1, int(os.getenv("SESSION_TTL_HOURS", "12"))) * 3600


class ChatMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    messages: list[ChatMessage] = Field(default_factory=list)
    conversation_id: str | None = None


class TraceNode(BaseModel):
    node: str
    status: str
    detail: str
    query: str = ""
    score: float | None = None
    duration_ms: int = 0


class AgentRun(BaseModel):
    id: str
    question: str
    route: str
    answer: str
    ok: bool
    document_name: str = ""
    source_url: str = ""
    similarity: float = 0.0
    created_at: float
    trace: list[TraceNode]
    matches: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    multimodal: list[dict[str, Any]] = Field(default_factory=list)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=8, max_length=128)


app = FastAPI(title="暨南大学学生助手", version="1.0.0")

if MINERU_DIR.exists():
    app.mount("/mineru-assets", StaticFiles(directory=str(MINERU_DIR)), name="mineru_assets")
if KNOWLEDGE_BASE_DIR.exists():
    app.mount("/knowledge-assets", StaticFiles(directory=str(KNOWLEDGE_BASE_DIR)), name="knowledge_assets")


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response



def db() -> sqlite3.Connection:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            create table if not exists users (
                id integer primary key autoincrement,
                username text unique not null,
                display_name text not null,
                role text not null default 'student',
                password text not null
            );
            create table if not exists sessions (
                token text primary key,
                user_id integer not null,
                created_at real not null
            );
            create table if not exists conversations (
                id text primary key,
                user_id integer not null,
                title text not null,
                created_at real not null,
                updated_at real not null
            );
            create table if not exists messages (
                id text primary key,
                conversation_id text not null,
                role text not null,
                content text not null,
                created_at real not null
            );
            """
        )
        rows = conn.execute("select id, password from users").fetchall()
        for row in rows:
            if not str(row["password"]).startswith("pbkdf2_sha256$"):
                conn.execute("update users set password=? where id=?", (hash_password(str(row["password"])), row["id"]))
        admin_username = os.getenv("ASSISTANT_ADMIN_USERNAME", "").strip()
        admin_password = os.getenv("ASSISTANT_ADMIN_PASSWORD", "")
        if admin_username and admin_password and not conn.execute("select id from users where username=?", (admin_username,)).fetchone():
            conn.execute(
                "insert into users(username, display_name, role, password) values(?,?,?,?)",
                (admin_username, admin_username, "admin", hash_password(admin_password)),
            )


init_db()


def current_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get("student_session")
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            """
            select u.id, u.username, u.display_name, u.role
            from sessions s join users u on u.id = s.user_id
            where s.token=? and s.created_at>=?
            """,
            (token, time.time() - SESSION_TTL_SECONDS),
        ).fetchone()
        if not row:
            conn.execute("delete from sessions where token=?", (token,))
    return dict(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def create_session(username: str, password: str) -> str | None:
    with db() as conn:
        row = conn.execute("select id, password from users where username=?", (username.strip(),)).fetchone()
        if not row or not verify_password(password, str(row["password"])):
            return None
        conn.execute("delete from sessions where created_at<?", (time.time() - SESSION_TTL_SECONDS,))
        token = secrets.token_urlsafe(32)
        conn.execute("insert into sessions(token, user_id, created_at) values(?,?,?)", (token, row["id"], time.time()))
        return token


def create_user(username: str, display_name: str, password: str, *, role: str = "student") -> tuple[bool, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        return False, "账号只能包含字母、数字、点、下划线或短横线，长度 3-32 位"
    if len(password) < 8:
        return False, "密码至少需要 8 位"
    try:
        with db() as conn:
            conn.execute(
                "insert into users(username, display_name, role, password) values(?,?,?,?)",
                (username, display_name[:40] or username, role, hash_password(password)),
            )
        return True, "创建成功"
    except sqlite3.IntegrityError:
        return False, "账号已存在"


def user_count() -> int:
    with db() as conn:
        return int(conn.execute("select count(*) from users").fetchone()[0])


def delete_session(token: str) -> None:
    with db() as conn:
        conn.execute("delete from sessions where token=?", (token,))


def save_conversation_message(user_id: int, conversation_id: str | None, question: str, answer: str) -> str:
    cid = conversation_id or str(uuid.uuid4())
    now = time.time()
    title = question[:30] or "新对话"
    with db() as conn:
        exists = conn.execute("select id, user_id from conversations where id=?", (cid,)).fetchone()
        if not exists:
            conn.execute(
                "insert into conversations(id, user_id, title, created_at, updated_at) values(?,?,?,?,?)",
                (cid, user_id, title, now, now),
            )
        else:
            if int(exists["user_id"]) != user_id:
                raise HTTPException(status_code=403, detail="不能写入其他用户的对话")
            conn.execute("update conversations set updated_at=? where id=?", (now, cid))
        conn.execute("insert into messages(id, conversation_id, role, content, created_at) values(?,?,?,?,?)", (str(uuid.uuid4()), cid, "user", question, now))
        conn.execute("insert into messages(id, conversation_id, role, content, created_at) values(?,?,?,?,?)", (str(uuid.uuid4()), cid, "assistant", answer, now))
    return cid


def conversation_messages(user_id: int, conversation_id: str | None, limit: int = 8) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    with db() as conn:
        owner = conn.execute(
            "select user_id from conversations where id=?",
            (conversation_id,),
        ).fetchone()
        if not owner:
            return []
        if int(owner["user_id"]) != user_id:
            raise HTTPException(status_code=403, detail="不能读取其他用户的对话")
        rows = conn.execute(
            """
            select role, content from messages
            where conversation_id=?
            order by created_at desc
            limit ?
            """,
            (conversation_id, max(1, min(20, limit))),
        ).fetchall()
    return [{"role": str(row["role"]), "content": str(row["content"])} for row in reversed(rows)]



def related_source_links(
    source: str,
    matches: list[dict[str, Any]],
    document_name: str = "",
) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    if source:
        candidates.append(("打开官方来源", source))
    wanted = normalized_document_name(document_name)
    for match in matches:
        match_name = str(match.get("document_name") or "")
        if wanted and normalized_document_name(match_name) != wanted:
            continue
        url = str(match.get("source_url") or "")
        if not url:
            continue
        label = re.sub(r"\.(md|pdf|docx?|xlsx?)$", "", match_name or "相关网页", flags=re.I)
        candidates.append((f"打开：{label}", url))
    for label, url in candidates:
        if url in seen or not re.fullmatch(r"https?://\S+", url):
            continue
        seen.add(url)
        links.append({"label": label, "url": url})
    return links[:5]


def snapshot_stats() -> dict[str, int]:
    datasets_dir = PROJECT_ROOT / "knowledge_base" / "datasets"
    result = {"datasets": 0, "documents": 0, "chunks": 0, "image_chunks": 0}
    if not datasets_dir.exists():
        return result
    for dataset_dir in datasets_dir.iterdir():
        if not dataset_dir.is_dir():
            continue
        result["datasets"] += 1
        summary_file = dataset_dir / "summary.json"
        if not summary_file.exists():
            continue
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result["documents"] += int(summary.get("documents") or summary.get("document_count") or 0)
        result["chunks"] += int(summary.get("chunks") or summary.get("chunk_count") or 0)
        result["image_chunks"] += int(summary.get("image_chunks") or summary.get("image_chunk_count") or 0)
    return result


def ragflow_connection_status() -> tuple[bool, str]:
    if not DEFAULT_RAGFLOW_API_KEY:
        return False, "未配置 API Key"
    try:
        response = requests.get(
            f"{DEFAULT_RAGFLOW_BASE_URL}/api/v1/datasets",
            headers={"Authorization": f"Bearer {DEFAULT_RAGFLOW_API_KEY}"},
            params={"page": 1, "page_size": 1},
            timeout=3,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") == 0:
            return True, "RAGFlow 已连接"
        return False, str(payload.get("message") or "RAGFlow 返回错误")
    except Exception as exc:
        return False, f"RAGFlow 离线：{str(exc)[:100]}"


def save_local_settings(values: dict[str, str]) -> None:
    allowed = {
        "RAGFLOW_BASE_URL", "RAGFLOW_API_KEY", "RAGFLOW_DATASET_ID",
        "RAGFLOW_NOTICE_DATASET_ID", "RAGFLOW_RERANK_ID",
        "VLM_BASE_URL", "VLM_API_KEY", "VLM_MODEL",
        "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    }
    target = PROJECT_ROOT / ".env.local"
    existing: dict[str, str] = {}
    if target.exists():
        for raw in target.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                key, value = raw.split("=", 1)
                existing[key.strip()] = value.strip()
    for key, value in values.items():
        if key not in allowed:
            continue
        cleaned = value.strip().replace("\r", "").replace("\n", "")
        if key.endswith("_API_KEY") and not cleaned:
            continue
        existing[key] = cleaned
    temporary = target.with_suffix(".local.tmp")
    temporary.write_text("\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n", encoding="utf-8")
    temporary.replace(target)
    os.environ.update(existing)
    global DEFAULT_RAGFLOW_BASE_URL, DEFAULT_RAGFLOW_API_KEY, DEFAULT_DATASET_ID, DEFAULT_NOTICE_DATASET_ID, RERANK_ID
    DEFAULT_RAGFLOW_BASE_URL = existing.get("RAGFLOW_BASE_URL", DEFAULT_RAGFLOW_BASE_URL).rstrip("/")
    DEFAULT_RAGFLOW_API_KEY = existing.get("RAGFLOW_API_KEY", DEFAULT_RAGFLOW_API_KEY)
    DEFAULT_DATASET_ID = existing.get("RAGFLOW_DATASET_ID", DEFAULT_DATASET_ID)
    DEFAULT_NOTICE_DATASET_ID = existing.get("RAGFLOW_NOTICE_DATASET_ID", DEFAULT_NOTICE_DATASET_ID)
    RERANK_ID = existing.get("RAGFLOW_RERANK_ID", RERANK_ID)
    assistant_graph.cache_clear()


def save_run(run: AgentRun) -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as file:
        file.write(run.model_dump_json(ensure_ascii=False) + "\n")


def recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    if not TRACE_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    with TRACE_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows[-limit:][::-1]


@lru_cache(maxsize=1)
def assistant_graph() -> StudentAssistantGraph:
    return StudentAssistantGraph()


def execute_question(
    question: str,
    messages: list[dict[str, str]],
    conversation_id: str | None = None,
) -> tuple[AgentState, list[dict[str, Any]]]:
    state = assistant_graph().run(
        AgentState(question=question.strip(), messages=messages),
        thread_id=conversation_id,
    )
    multimodal = (
        find_multimodal_assets(state.question, state.document_name, state.matches)
        if state.ok
        else []
    )
    state.trace.append(make_trace("multimodal_agent", "success", f"关联 {len(multimodal)} 个图片/表格资源", state.document_name))
    return state, multimodal



@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "fastapi-student-assistant"}


@app.post("/api/login")
def api_login(payload: LoginRequest) -> JSONResponse:
    token = create_session(payload.username, payload.password)
    if not token:
        return JSONResponse(status_code=401, content={"ok": False, "message": "账号或密码错误"})
    response = JSONResponse(content={"ok": True})
    response.set_cookie("student_session", token, httponly=True, samesite="lax", max_age=SESSION_TTL_SECONDS)
    return response


@app.post("/api/register")
def api_register(payload: RegisterRequest) -> dict[str, Any]:
    ok, message = create_user(payload.username, payload.display_name, payload.password)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


@app.post("/login")
def login_form(username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    token = create_session(username, password)
    if not token:
        return RedirectResponse("/login?error=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("student_session", token, httponly=True, samesite="lax", max_age=SESSION_TTL_SECONDS)
    return response


@app.post("/register")
def register_form(
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    ok, _ = create_user(username.strip(), display_name.strip(), password)
    if not ok:
        return RedirectResponse("/register?error=1", status_code=303)
    return RedirectResponse("/login?registered=1", status_code=303)


@app.post("/setup")
def setup_form(
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    if user_count() != 0:
        return RedirectResponse("/login", status_code=303)
    ok, _ = create_user(username.strip(), display_name.strip(), password, role="admin")
    return RedirectResponse("/login?setup=1" if ok else "/setup?error=1", status_code=303)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get("student_session")
    if token:
        delete_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("student_session")
    return response


@app.get("/api/me")
def api_me(request: Request) -> dict[str, Any]:
    user = current_user(request)
    return {"ok": bool(user), "user": user}


@app.get("/api/conversations")
def api_conversations(request: Request) -> dict[str, Any]:
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            "select id, title, created_at, updated_at from conversations where user_id=? order by updated_at desc limit 30",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "conversations": [dict(row) for row in rows]}


@app.post("/api/ask")
def ask(payload: AskRequest, request: Request) -> dict[str, Any]:
    user = require_user(request)
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    stored_messages = conversation_messages(int(user["id"]), payload.conversation_id)
    request_messages = [m.model_dump() for m in payload.messages]
    state, multimodal = execute_question(
        payload.question,
        (stored_messages + request_messages)[-12:],
        conversation_id,
    )
    run = AgentRun(
        id=str(uuid.uuid4()),
        question=state.question,
        route=state.route,
        answer=state.answer,
        ok=state.ok,
        document_name=state.document_name,
        source_url=state.source_url,
        similarity=state.similarity,
        created_at=time.time(),
        trace=state.trace,
        matches=state.matches,
        links=related_source_links(state.source_url, state.matches, state.document_name) if state.ok else [],
        multimodal=multimodal,
    )
    save_run(run)
    result = run.model_dump()
    result["conversation_id"] = save_conversation_message(
        int(user["id"]),
        conversation_id,
        state.question,
        state.answer,
    )
    return result


@app.post("/api/ask-image")
async def ask_image(
    request: Request,
    image: UploadFile = File(...),
    question: str = Form(""),
    conversation_id: str = Form(""),
) -> dict[str, Any]:
    user = require_user(request)
    mime_type = image.content_type or ""
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 WebP 图片")
    raw = await image.read(6 * 1024 * 1024 + 1)
    if len(raw) > 6 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片不能超过 6 MB")
    try:
        visual = analyze_query_image(base64.b64encode(raw).decode("ascii"), mime_type, question)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"图片识别失败：{str(exc)[:160]}") from exc
    retrieval_question = str(visual.get("retrieval_query") or question or visual.get("visible_text") or "").strip()
    if not retrieval_question:
        raise HTTPException(status_code=422, detail="图片中没有识别出可检索的学生事务信息")
    active_conversation_id = conversation_id or str(uuid.uuid4())
    stored_messages = conversation_messages(int(user["id"]), conversation_id or None)
    state, multimodal = execute_question(
        retrieval_question,
        stored_messages,
        active_conversation_id,
    )
    state.trace.insert(0, trace("vision_agent", "success", str(visual.get("description") or "完成图片识别"), retrieval_question))
    run = AgentRun(
        id=str(uuid.uuid4()),
        question=question or retrieval_question,
        route=state.route,
        answer=state.answer,
        ok=state.ok,
        document_name=state.document_name,
        source_url=state.source_url,
        similarity=state.similarity,
        created_at=time.time(),
        trace=state.trace,
        matches=state.matches,
        links=related_source_links(state.source_url, state.matches, state.document_name) if state.ok else [],
        multimodal=multimodal,
    )
    save_run(run)
    result = run.model_dump()
    result["vision"] = visual
    result["conversation_id"] = save_conversation_message(
        int(user["id"]),
        active_conversation_id,
        run.question,
        state.answer,
    )
    return result


@app.get("/api/multimodal-index")
def api_multimodal_index(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"ok": True, "stats": multimodal_stats(), "items": load_multimodal_index()[:50]}


@app.get("/api/agent-runs")
def agent_runs(request: Request, limit: int = 50) -> dict[str, Any]:
    require_admin(request)
    return {"ok": True, "runs": recent_runs(limit)}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> Any:
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    admin_nav = '<a href="/agent-logs">Agent 日志</a><a href="/pipeline">数据看板</a><a href="/settings">连接配置</a><a href="/admin/users">用户管理</a>' if user["role"] == "admin" else ""
    page = HTML.replace("__USER__", html.escape(str(user["display_name"]))).replace("__ROLE__", html.escape(str(user["role"]))).replace("__ADMIN_NAV__", admin_nav)
    return HTMLResponse(page)


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return LOGIN_HTML


@app.get("/register", response_class=HTMLResponse)
def register_page() -> str:
    return REGISTER_HTML


@app.get("/setup", response_class=HTMLResponse)
def setup_page() -> Any:
    if user_count() != 0:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(SETUP_HTML)


@app.get("/agent-logs", response_class=HTMLResponse)
def agent_logs(request: Request) -> Any:
    user = current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(LOGS_HTML)


@app.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request) -> Any:
    user = current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    stats = multimodal_stats()
    snapshot = snapshot_stats()
    online, status = ragflow_connection_status()
    page = (
        PIPELINE_HTML.replace("__RAGFLOW_STATUS__", html.escape(status))
        .replace("__RAGFLOW_CLASS__", "success" if online else "error")
        .replace("__DATASETS__", str(snapshot["datasets"]))
        .replace("__DOCUMENTS__", str(snapshot["documents"]))
        .replace("__CHUNKS__", str(snapshot["chunks"]))
        .replace("__IMAGE_CHUNKS__", str(snapshot["image_chunks"]))
        .replace("__MEDIA_TOTAL__", str(stats["total"]))
        .replace("__MEDIA_IMAGES__", str(stats["images"]))
        .replace("__MEDIA_TABLES__", str(stats["tables"]))
        .replace("__MEDIA_STRUCTURED_TABLES__", str(stats["structured_tables"]))
        .replace("__MEDIA_RESOLVED__", str(stats["resolved"]))
    )
    return HTMLResponse(page)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> Any:
    user = current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    configured = bool(DEFAULT_RAGFLOW_API_KEY and DEFAULT_DATASET_ID)
    status = "已配置 RAGFlow，可直接查询。" if configured else "未配置 RAGFlow，请在 .env.local 中填写 RAGFLOW_API_KEY 和 RAGFLOW_DATASET_ID。"
    page = (
        SETTINGS_HTML.replace("__STATUS__", status)
        .replace("__BASE_URL__", html.escape(DEFAULT_RAGFLOW_BASE_URL))
        .replace("__DATASET_ID__", html.escape(DEFAULT_DATASET_ID))
        .replace("__NOTICE_DATASET_ID__", html.escape(DEFAULT_NOTICE_DATASET_ID))
        .replace("__RERANK_ID__", html.escape(RERANK_ID))
        .replace("__VLM_BASE_URL__", html.escape(os.getenv("VLM_BASE_URL", "")))
        .replace("__VLM_MODEL__", html.escape(os.getenv("VLM_MODEL", "")))
        .replace("__LLM_BASE_URL__", html.escape(os.getenv("LLM_BASE_URL", "")))
        .replace("__LLM_MODEL__", html.escape(os.getenv("LLM_MODEL", "")))
    )
    return HTMLResponse(page)


@app.post("/settings")
def update_settings(
    request: Request,
    ragflow_base_url: str = Form(...),
    ragflow_api_key: str = Form(""),
    ragflow_dataset_id: str = Form(...),
    ragflow_notice_dataset_id: str = Form(""),
    ragflow_rerank_id: str = Form(""),
    vlm_base_url: str = Form(""),
    vlm_api_key: str = Form(""),
    vlm_model: str = Form(""),
    llm_base_url: str = Form(""),
    llm_api_key: str = Form(""),
    llm_model: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    save_local_settings(
        {
            "RAGFLOW_BASE_URL": ragflow_base_url,
            "RAGFLOW_API_KEY": ragflow_api_key,
            "RAGFLOW_DATASET_ID": ragflow_dataset_id,
            "RAGFLOW_NOTICE_DATASET_ID": ragflow_notice_dataset_id,
            "RAGFLOW_RERANK_ID": ragflow_rerank_id,
            "VLM_BASE_URL": vlm_base_url,
            "VLM_API_KEY": vlm_api_key,
            "VLM_MODEL": vlm_model,
            "LLM_BASE_URL": llm_base_url,
            "LLM_API_KEY": llm_api_key,
            "LLM_MODEL": llm_model,
        }
    )
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request) -> Any:
    user = current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    with db() as conn:
        rows = conn.execute("select id, username, display_name, role from users order by id").fetchall()
    cards = "".join(
        f'<div class="card"><b>{html.escape(str(row["display_name"]))}</b>'
        f'<p class="muted">@{html.escape(str(row["username"]))} · {html.escape(str(row["role"]))}</p>'
        f'<form method="post" action="/admin/users/{int(row["id"])}/role"><select name="role">'
        f'<option value="student"{" selected" if row["role"] == "student" else ""}>普通用户</option>'
        f'<option value="admin"{" selected" if row["role"] == "admin" else ""}>管理员</option>'
        f'</select><button>保存角色</button></form></div>'
        for row in rows
    )
    return HTMLResponse(ADMIN_USERS_HTML.replace("__USERS__", cards))


@app.post("/admin/users/{user_id}/role")
def update_user_role(user_id: int, request: Request, role: str = Form(...)) -> RedirectResponse:
    admin = require_admin(request)
    if role not in {"student", "admin"}:
        raise HTTPException(status_code=422, detail="角色无效")
    if user_id == int(admin["id"]) and role != "admin":
        raise HTTPException(status_code=409, detail="不能取消自己的管理员权限")
    with db() as conn:
        conn.execute("update users set role=? where id=?", (role, user_id))
    return RedirectResponse("/admin/users", status_code=303)


@app.exception_handler(Exception)
async def app_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"ok": False, "message": str(exc)[:300]})


CSS = """
body{margin:0;background:#f3f5f8;color:#142033;font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif}
.shell{display:grid;grid-template-columns:248px 1fr;min-height:100vh}.side{background:#101828;color:white;padding:24px 16px}.logo{display:flex;gap:12px;align-items:center;margin-bottom:32px}.mark{width:44px;height:44px;border-radius:8px;background:#087d72;display:grid;place-items:center;font-weight:800}.nav a{display:block;color:#d0d5dd;text-decoration:none;padding:12px 14px;border-radius:7px;margin:6px 0}.nav a.active,.nav a:hover{background:#2563eb;color:white}.main{padding:30px;max-width:1120px}.panel{background:white;border:1px solid #d9e0ea;border-radius:8px;padding:24px;margin-bottom:16px}h1{margin:0 0 8px;font-size:26px}p{line-height:1.7}.muted{color:#667085}.query{display:grid;grid-template-columns:1fr 110px;gap:10px}textarea{min-height:86px;border:1px solid #b8c2d0;border-radius:7px;padding:14px;font-size:16px}button{border:0;border-radius:7px;background:#087d72;color:white;font-weight:800;font-size:15px;cursor:pointer}.answer{white-space:pre-wrap;font-size:17px;line-height:1.75}.meta{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.pill{border:1px solid #d9e0ea;border-radius:999px;padding:5px 9px;background:#f8fafc;color:#475467;font-size:13px}.source-links{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.source-button{display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:7px;background:#087d72;color:white;text-decoration:none;font-weight:800;box-shadow:0 1px 2px rgba(16,24,40,.12)}.source-button:hover{background:#06685f}.trace{display:grid;gap:10px}.node{border:1px solid #d9e0ea;border-left:4px solid #087d72;border-radius:7px;padding:12px;background:#fbfcfe}.node.error,.node.rejected{border-left-color:#b42318}.node strong{display:block}.node small{color:#667085}.match{border:1px solid #d9e0ea;border-radius:7px;padding:10px;margin-top:8px;background:#fbfcfe}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{border:1px solid #d9e0ea;border-radius:8px;padding:14px;background:#fff}.run{cursor:pointer}.run:hover{border-color:#087d72;background:#f6fffd}@media(max-width:800px){.shell{grid-template-columns:1fr}.query{grid-template-columns:1fr}button{min-height:46px}}
.account{position:absolute;bottom:18px;left:16px;right:16px;border-top:1px solid #27364d;padding-top:16px;color:#d0d5dd}.account a{color:#d0d5dd}.login{max-width:440px;margin:8vh auto;background:white;border:1px solid #d9e0ea;border-radius:8px;padding:28px}.login input,.panel input,.panel select,.card select{box-sizing:border-box;width:100%;border:1px solid #b8c2d0;border-radius:7px;padding:12px;margin:8px 0 14px;font-size:15px}.login button,.panel form button,.card form button{width:100%;min-height:44px}.login .hint{background:#f1f8f6;border-left:4px solid #087d72;padding:10px;margin-top:14px;color:#475467}.upload{display:flex;gap:12px;align-items:center;margin-top:12px;padding:12px;background:#f8fafc;border:1px dashed #98a2b3;border-radius:7px}.status.success{color:#067647}.status.error{color:#b42318}.side{position:relative}
.table-wrap{overflow:auto;max-height:260px;border:1px solid #d9e0ea;border-radius:6px}.data-table{border-collapse:collapse;width:100%;font-size:13px}.data-table td{border:1px solid #e4e7ec;padding:6px 8px;min-width:80px;vertical-align:top}.data-table tr:first-child td{background:#f1f8f6;font-weight:700}
"""

LOGIN_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>登录 · 暨南大学学生助手</title><style>{CSS}</style></head><body><main class="login"><h1>暨南大学学生助手</h1><p class="muted">登录后使用学生事务问答与历史记录。</p><form method="post" action="/login"><label>账号</label><input name="username" autocomplete="username" required><label>密码</label><input name="password" type="password" autocomplete="current-password" required><button>登录</button></form><div class="hint">没有账号？<a href="/register">注册普通用户</a>。密码使用 PBKDF2 哈希保存，不会明文写入数据库。</div></main></body></html>"""

REGISTER_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>注册 · 暨南大学学生助手</title><style>{CSS}</style></head><body><main class="login"><h1>注册普通用户</h1><form method="post" action="/register"><label>账号</label><input name="username" minlength="3" maxlength="32" required><label>显示名称</label><input name="display_name" maxlength="40" required><label>密码（至少 8 位）</label><input name="password" type="password" minlength="8" required><button>注册</button></form><p><a href="/login">返回登录</a></p></main></body></html>"""

SETUP_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>首次设置 · 暨南大学学生助手</title><style>{CSS}</style></head><body><main class="login"><h1>首次设置</h1><p class="muted">创建本机第一个管理员。此页面只在数据库中没有用户时开放。</p><form method="post" action="/setup"><label>管理员账号</label><input name="username" minlength="3" maxlength="32" required><label>显示名称</label><input name="display_name" maxlength="40" required><label>密码（至少 8 位）</label><input name="password" type="password" minlength="8" required><button>创建管理员</button></form></main></body></html>"""

HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>暨南大学学生助手</title><style>{CSS}</style></head><body><div class="shell"><aside class="side"><div class="logo"><div class="mark">暨</div><div><b>学生问答助手</b><br><span class="muted">FastAPI + LangGraph</span></div></div><nav class="nav"><a class="active" href="/">智能问答</a>__ADMIN_NAV__</nav><div class="account"><b>__USER__</b><br><span class="muted">__ROLE__</span><br><a href="/logout">退出登录</a></div></aside><main class="main"><section class="panel"><h1>学生事务查询</h1><p class="muted">输入自然语言问题，系统会经过 Intent、Router、Retriever、Reflection、Answer 等 Agent 链路。</p><div class="query"><textarea id="q" placeholder="例如：本科生请假申请表在哪里下载？"></textarea><button onclick="ask()">查询</button></div><div class="upload"><input id="image" type="file" accept="image/jpeg,image/png,image/webp"><span class="muted">可上传通知、表格或办事页面截图（最大 6 MB）</span></div></section><section class="panel"><h2>回答</h2><div id="answer" class="answer muted">等待提问。</div><div id="meta" class="meta"></div><div id="links" class="source-links"></div><h3>执行过程</h3><div id="trace" class="trace"></div><div id="matches"></div><div id="multimodal"></div></section><section class="panel"><h2>历史对话</h2><div id="history" class="grid"></div></section></main></div><script>
let currentConversation=null;
function renderLinks(items){{links.innerHTML='';for(const item of (items||[])){{try{{const url=new URL(item.url);if(!['http:','https:'].includes(url.protocol))continue;const link=document.createElement('a');link.className='source-button';link.target='_blank';link.rel='noopener noreferrer';link.href=url.href;link.textContent='↗ '+(item.label||'打开相关网页');links.appendChild(link);}}catch(_error){{}}}}}}
function renderMultimodal(items){{multimodal.innerHTML='';if(!items||!items.length)return;const heading=document.createElement('h3');heading.textContent='相关图片/表格';multimodal.appendChild(heading);const grid=document.createElement('div');grid.className='grid';for(const item of items){{const card=document.createElement('div');card.className='card';if(item.url){{const image=document.createElement('img');image.src=item.url;image.alt=item.caption||item.document||'知识库图片';image.loading='lazy';image.style.cssText='width:100%;max-height:240px;object-fit:contain;border:1px solid #d9e0ea;border-radius:6px;background:#fff';card.appendChild(image);}}if(item.rows&&item.rows.length){{const wrap=document.createElement('div');wrap.className='table-wrap';const table=document.createElement('table');table.className='data-table';for(const row of item.rows.slice(0,12)){{const tr=document.createElement('tr');for(const cell of row.slice(0,8)){{const td=document.createElement('td');td.textContent=String(cell||'');tr.appendChild(td);}}table.appendChild(tr);}}wrap.appendChild(table);card.appendChild(wrap);}}const caption=document.createElement('p');const strong=document.createElement('b');strong.textContent=item.caption||'知识库多模态资源';caption.appendChild(strong);card.appendChild(caption);const source=document.createElement('p');source.className='muted';source.textContent=[item.document,item.page].filter(Boolean).join(' · ');card.appendChild(source);grid.appendChild(card);}}multimodal.appendChild(grid);}}
async function ask(){{const q=document.getElementById('q').value.trim();const file=document.getElementById('image').files[0];if(!q&&!file)return;answer.textContent='处理中...';trace.innerHTML='';matches.innerHTML='';multimodal.innerHTML='';links.innerHTML='';let r;if(file){{const form=new FormData();form.append('image',file);form.append('question',q);form.append('conversation_id',currentConversation||'');r=await fetch('/api/ask-image',{{method:'POST',body:form}});}}else{{r=await fetch('/api/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{question:q,messages:[],conversation_id:currentConversation}})}});}}const d=await r.json();if(!r.ok){{answer.textContent=d.detail||d.message||'请求失败';return;}}currentConversation=d.conversation_id||currentConversation;answer.textContent=d.answer||d.message;meta.innerHTML=`<span class="pill">分类：${{d.route||'-'}}</span><span class="pill">来源：${{d.document_name||'-'}}</span><span class="pill">相似度：${{Number(d.similarity||0).toFixed(3)}}</span>`;renderLinks((d.links&&d.links.length)?d.links:(d.source_url?[{{label:'打开官方来源',url:d.source_url}}]:[]));trace.innerHTML=(d.trace||[]).map(n=>`<div class="node ${{n.status}}"><strong>${{n.node}} · ${{n.status}}</strong><small>${{n.duration_ms}} ms · 分数 ${{n.score??''}}</small><p>${{n.detail}}</p></div>`).join('');matches.innerHTML=(d.matches||[]).map(m=>`<div class="match"><b>${{m.document_name}} · ${{Number(m.similarity||0).toFixed(3)}}</b><p>${{m.snippet||''}}</p></div>`).join('');renderMultimodal(d.multimodal||[]);loadHistory();}}
async function loadHistory(){{const r=await fetch('/api/conversations');const d=await r.json();history.innerHTML=(d.conversations||[]).map(c=>`<div class="card"><b>${{c.title}}</b><p class="muted">${{new Date(c.updated_at*1000).toLocaleString()}}</p></div>`).join('')||'<p class="muted">暂无历史。</p>';}}loadHistory();
</script></body></html>"""

LOGS_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent 日志</title><style>{CSS}</style></head><body><div class="shell"><aside class="side"><div class="logo"><div class="mark">暨</div><div><b>Agent 可视化日志</b><br><span class="muted">Trace Console</span></div></div><nav class="nav"><a href="/">智能问答</a><a class="active" href="/agent-logs">Agent 可视化日志</a><a href="/pipeline">数据看板</a><a href="/settings">连接配置</a></nav></aside><main class="main"><section class="panel"><h1>Agent 执行记录</h1><p class="muted">展示每次提问经过的智能体节点、状态、耗时、相似度和最终答案。</p><button onclick="load()">刷新</button></section><section id="runs" class="grid"></section></main></div><script>
async function load(){{const r=await fetch('/api/agent-runs');const d=await r.json();runs.innerHTML=(d.runs||[]).map(run=>`<article class="card run"><h3>${{run.question}}</h3><p>${{run.answer.slice(0,140)}}...</p><div class="meta"><span class="pill">${{run.route}}</span><span class="pill">${{run.ok?'通过':'拒答'}}</span><span class="pill">${{new Date(run.created_at*1000).toLocaleString()}}</span></div><div class="trace">${{(run.trace||[]).map(n=>`<div class="node ${{n.status}}"><strong>${{n.node}} · ${{n.status}}</strong><small>${{n.duration_ms}} ms</small><p>${{n.detail}}</p></div>`).join('')}}</div></article>`).join('')||'<div class="panel">暂无日志，先去智能问答提一个问题。</div>';}}load();
</script></body></html>"""

PIPELINE_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>数据看板</title><style>{CSS}</style></head><body><div class="shell"><aside class="side"><div class="logo"><div class="mark">暨</div><div><b>数据看板</b><br><span class="muted">Pipeline</span></div></div><nav class="nav"><a href="/">智能问答</a><a href="/agent-logs">Agent 日志</a><a class="active" href="/pipeline">数据看板</a><a href="/settings">连接配置</a><a href="/admin/users">用户管理</a></nav></aside><main class="main"><section class="panel"><h1>数据处理与知识库状态</h1><p class="status __RAGFLOW_CLASS__">__RAGFLOW_STATUS__</p><div class="grid"><div class="card"><h3>知识库</h3><p>__DATASETS__ 套</p></div><div class="card"><h3>文档</h3><p>__DOCUMENTS__ 份</p></div><div class="card"><h3>文本分块</h3><p>__CHUNKS__ 个</p></div><div class="card"><h3>图片分块</h3><p>__IMAGE_CHUNKS__ 个</p></div></div></section><section class="panel"><h2>多模态资源</h2><div class="grid"><div class="card"><h3>资源总数</h3><p>__MEDIA_TOTAL__</p></div><div class="card"><h3>可展示图片</h3><p>__MEDIA_IMAGES__</p></div><div class="card"><h3>表格资源</h3><p>__MEDIA_TABLES__</p></div><div class="card"><h3>结构化表格</h3><p>__MEDIA_STRUCTURED_TABLES__</p></div><div class="card"><h3>已解析资源</h3><p>__MEDIA_RESOLVED__ / __MEDIA_TOTAL__</p></div></div></section><section class="panel"><h2>处理流程</h2><div class="trace"><div class="node"><strong>Crawler</strong><p>采集暨南大学公开网页与附件。</p></div><div class="node"><strong>Cleaner / MinerU</strong><p>保留业务上下文、图片语义、可见文字和页码，表格同步转换为 JSON 行列结构。</p></div><div class="node"><strong>Snapshot Index</strong><p>对图片哈希和表格内容去重，校验本地资源路径并生成可检索多模态索引。</p></div><div class="node"><strong>RAGFlow Import</strong><p>导入知识库并解析分块。</p></div><div class="node"><strong>FastAPI + LangGraph</strong><p>Intent → Router → Retriever/Tool → Quality/Retry → Reflection → Answer。</p></div></div></section></main></div></body></html>"""

SETTINGS_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>连接配置</title><style>{CSS}</style></head><body><div class="shell"><aside class="side"><div class="logo"><div class="mark">暨</div><div><b>连接配置</b><br><span class="muted">Settings</span></div></div><nav class="nav"><a href="/">智能问答</a><a href="/agent-logs">Agent 日志</a><a href="/pipeline">数据看板</a><a class="active" href="/settings">连接配置</a><a href="/admin/users">用户管理</a></nav></aside><main class="main"><section class="panel"><h1>FastAPI + RAGFlow 配置</h1><p class="muted">__STATUS__</p><form method="post" action="/settings"><label>RAGFlow 地址</label><input name="ragflow_base_url" value="__BASE_URL__" required><label>API Key（留空则保留现有 Key）</label><input name="ragflow_api_key" type="password" autocomplete="off"><label>问答知识库 ID</label><input name="ragflow_dataset_id" value="__DATASET_ID__" required><label>通知补充知识库 ID（可选）</label><input name="ragflow_notice_dataset_id" value="__NOTICE_DATASET_ID__"><label>重排模型 ID（可选；RAGFlow 未配置时请留空）</label><input name="ragflow_rerank_id" value="__RERANK_ID__"><h2>截图识别模型（可选）</h2><p class="muted">配置后可识别通知、表格和办事页面截图；最终答案仍必须通过 RAGFlow 证据校验。</p><label>VLM API 地址</label><input name="vlm_base_url" value="__VLM_BASE_URL__" placeholder="https://api.siliconflow.cn/v1"><label>VLM API Key（留空则保留现有 Key）</label><input name="vlm_api_key" type="password" autocomplete="off"><label>VLM 模型</label><input name="vlm_model" value="__VLM_MODEL__" placeholder="Qwen/Qwen2.5-VL-72B-Instruct"><h2>受控文本模型（可选）</h2><p class="muted">只在检索证据通过质量门禁后整理语言；不配置时继续使用现有规则摘要。</p><label>LLM API 地址</label><input name="llm_base_url" value="__LLM_BASE_URL__" placeholder="https://api.siliconflow.cn/v1"><label>LLM API Key（留空则保留现有 Key）</label><input name="llm_api_key" type="password" autocomplete="off"><label>LLM 模型</label><input name="llm_model" value="__LLM_MODEL__" placeholder="Qwen/Qwen2.5-32B-Instruct"><button>保存到本机并立即生效</button></form><p class="muted">配置写入被 Git 忽略的 <code>.env.local</code>，刷新或重启后仍然保留。页面不会回显 API Key。</p></section></main></div></body></html>"""

ADMIN_USERS_HTML = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>用户管理</title><style>{CSS}</style></head><body><div class="shell"><aside class="side"><div class="logo"><div class="mark">暨</div><div><b>用户管理</b><br><span class="muted">RBAC</span></div></div><nav class="nav"><a href="/">智能问答</a><a href="/agent-logs">Agent 日志</a><a href="/pipeline">数据看板</a><a href="/settings">连接配置</a><a class="active" href="/admin/users">用户管理</a></nav></aside><main class="main"><section class="panel"><h1>账号与角色权限</h1><p class="muted">普通用户只能进行问答；管理员可查看日志、数据看板、连接配置和用户管理。</p></section><section class="grid">__USERS__</section></main></div></body></html>"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app_fastapi:app", host=os.getenv("ASSISTANT_HOST", "127.0.0.1"), port=int(os.getenv("ASSISTANT_PORT", "8090")), reload=False)
