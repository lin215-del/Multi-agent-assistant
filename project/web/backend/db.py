"""SQLite 历史持久化：每次问答存一条 trace，可按 id 查回。

字段见 plan §数据层 history 表结构。matches / reflection 是 JSON 列，序列化后存，
读时反序列化。文件路径 `web/backend/history.db`，启动时建表（幂等）。
"""
import json
import sqlite3
from typing import Any, Optional


class HistoryDB:
    """问答历史 SQLite 封装。路径传 ":memory:" 得内存库（测试用）。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question TEXT NOT NULL,
      route TEXT,
      answer TEXT,
      matches_json TEXT,
      reflection_json TEXT,
      analysis TEXT,
      round INTEGER DEFAULT 0,
      latency_ms INTEGER DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """

    def __init__(self, path: str):
        self.path = path
        # check_same_thread=False：FastAPI handler 在另一线程跑，SQLite 连接需要跨线程用
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init()

    def init(self) -> None:
        """建表（多次调用安全）。"""
        self._conn.execute(self.SCHEMA)
        self._conn.commit()

    def save(self, record: dict) -> int:
        """插入一条历史，返回新行 id。"""
        cur = self._conn.execute(
            """INSERT INTO history
               (question, route, answer, matches_json, reflection_json, analysis, round, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["question"],
                record.get("route"),
                record.get("answer"),
                json.dumps(record.get("matches") or [], ensure_ascii=False),
                json.dumps(record.get("reflection")) if record.get("reflection") is not None else None,
                record.get("analysis"),
                int(record.get("round") or 0),
                int(record.get("latency_ms") or 0),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_recent(self, limit: int = 50) -> list[dict]:
        """时间倒序列表，限制条数。"""
        cur = self._conn.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    def get(self, rid: int) -> Optional[dict]:
        """按 id 取完整 trace；不存在返回 None。"""
        cur = self._conn.execute("SELECT * FROM history WHERE id = ?", (rid,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def close(self) -> None:
        """关连接（测试清理用；进程退出时不强求）。"""
        self._conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Row → dict，并把 matches_json / reflection_json 反序列化回 Python 对象。"""
    d = dict(row)
    d["matches"] = json.loads(d.pop("matches_json") or "[]")
    refl = d.pop("reflection_json")
    d["reflection"] = json.loads(refl) if refl else None
    return d