"""认证模块：管理员固定账号 + 普通用户注册/登录。

安全设计：
- 密码用 PBKDF2-HMAC-SHA256 + 随机盐哈希（hashlib 标准库，零额外依赖）
- Token 用 secrets.token_urlsafe 生成，存内存 dict（进程重启全部失效，需重新登录）
- 管理员凭据从 .env 读，不落 SQLite
"""
import hashlib
import os
import secrets
import sqlite3
from typing import Optional

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

_tokens: dict[str, dict] = {}


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256，100k 迭代。返回 (hash_hex, salt_hex)。"""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return dk.hex(), salt


def _ensure_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "username TEXT PRIMARY KEY, password_hash TEXT, salt TEXT, "
        "created_at TEXT DEFAULT (datetime('now','localtime')))"
    )
    conn.commit()


def register_user(username: str, password: str, db_path: str) -> dict:
    """注册普通用户。用户名已存在抛 ValueError。返回 {token, role, username}。"""
    if not username or not password:
        raise ValueError("用户名和密码不能为空")
    pw_hash, salt = _hash_password(password)
    conn = sqlite3.connect(db_path)
    try:
        _ensure_users_table(conn)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, pw_hash, salt),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("该用户名已被注册")
    finally:
        conn.close()
    return _issue_token(username, "user")


def login_user(username: str, password: str, db_path: str) -> dict:
    """先匹配管理员，再查用户表。返回 {token, role, username}。失败抛 ValueError。"""
    if not username or not password:
        raise ValueError("用户名和密码不能为空")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return _issue_token(username, "admin")
    conn = sqlite3.connect(db_path)
    try:
        _ensure_users_table(conn)
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("用户名或密码错误")
    stored_hash, salt = row
    computed_hash, _ = _hash_password(password, salt)
    if not secrets.compare_digest(stored_hash, computed_hash):
        raise ValueError("用户名或密码错误")
    return _issue_token(username, "user")


def _issue_token(username: str, role: str) -> dict:
    token = secrets.token_urlsafe(32)
    _tokens[token] = {"username": username, "role": role}
    return {"token": token, "role": role, "username": username}


def get_token_info(token: str) -> Optional[dict]:
    return _tokens.get(token)
