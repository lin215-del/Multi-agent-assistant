"""db.py 的测试。TDD：先用内存 SQLite 验 save / list_recent / get 行为。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

from web.backend.db import HistoryDB


def _new_db():
    """建一个内存 SQLite DB；每次调用得到独立的库，避免测试间污染。"""
    return HistoryDB(":memory:")


def test_save_then_get_roundtrip():
    """save 一条历史 → get 拿回，字段值完全一致。"""
    db = _new_db()
    rid = db.save({
        "question": "国奖申请条件是什么",
        "route": "retrieve",
        "answer": "学习成绩优异…（来源：通知-857469）",
        "matches": [{"content": "国奖申请条件…", "source": "通知-857469", "score": 0.85, "type": "text"}],
        "reflection": {"ok": True, "reason": "引用了来源"},
        "analysis": "草稿…",
        "round": 0,
        "latency_ms": 2300,
    })
    assert rid == 1
    row = db.get(rid)
    assert row["question"] == "国奖申请条件是什么"
    assert row["route"] == "retrieve"
    assert row["matches"][0]["source"] == "通知-857469"
    assert row["matches"][0]["type"] == "text"
    assert row["reflection"] == {"ok": True, "reason": "引用了来源"}
    assert row["latency_ms"] == 2300
    assert row["round"] == 0
    assert row["created_at"]  # 非空字符串


def test_list_recent_orders_newest_first():
    """list_recent 倒序：最新插入的在最前。"""
    db = _new_db()
    db.save({"question": "第一个问题", "answer": "答案 1"})
    db.save({"question": "第二个问题", "answer": "答案 2"})
    db.save({"question": "第三个问题", "answer": "答案 3"})
    rows = db.list_recent(limit=10)
    assert [r["question"] for r in rows] == ["第三个问题", "第二个问题", "第一个问题"]


def test_list_recent_respects_limit():
    """limit 截断：插 3 条只取 2 条。"""
    db = _new_db()
    for i in range(3):
        db.save({"question": f"q{i}", "answer": f"a{i}"})
    assert len(db.list_recent(limit=2)) == 2


def test_get_missing_returns_none():
    """不存在的 id 返回 None，不抛。"""
    db = _new_db()
    assert db.get(999) is None


def test_save_with_missing_optional_fields_uses_defaults():
    """matches / reflection 等可选字段缺省时存空值，get 出来类型稳定。"""
    db = _new_db()
    rid = db.save({"question": "极简", "answer": "答"})
    row = db.get(rid)
    assert row["matches"] == []
    assert row["reflection"] is None
    assert row["route"] is None
    assert row["round"] == 0
    assert row["latency_ms"] == 0


def test_init_creates_table_if_missing(tmp_path=None):
    """init 一次后，表存在；多次 init 安全（幂等）。"""
    db = _new_db()
    db.init()  # 第二次调用应该不报错
    db.save({"question": "x", "answer": "y"})
    assert db.list_recent(limit=10)  # 不抛异常即过