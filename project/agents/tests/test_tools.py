"""tools.py 的测试。TDD：compute_weighted_average + _parse_courses_json + tool_node。

LLM 解析是 IO 边界，用 monkeypatch；纯数学和纯解析逻辑测全。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # agents/tests
AGENTS = os.path.dirname(HERE)                            # agents
ROOT = os.path.dirname(AGENTS)                            # project
sys.path.insert(0, ROOT)

from agents.tools import compute_weighted_average, _parse_courses_json, tool_node


# ---------- compute_weighted_average：学分加权平均 ----------
def test_two_courses_weighted():
    courses = [{"score": 85, "credits": 4}, {"score": 90, "credits": 3}]
    r = compute_weighted_average(courses)
    # (85*4 + 90*3) / 7 = 610/7 = 87.142...
    assert r["weighted_average"] == 87.14
    assert r["total_credits"] == 7
    assert r["course_count"] == 2


def test_single_course_returns_its_score():
    r = compute_weighted_average([{"score": 92, "credits": 3}])
    assert r["weighted_average"] == 92.0
    assert r["course_count"] == 1


def test_empty_returns_none():
    assert compute_weighted_average([]) is None
    assert compute_weighted_average(None) is None


def test_zero_total_credits_returns_none():
    """所有课学分都是 0，除零无意义，返回 None。"""
    assert compute_weighted_average([{"score": 85, "credits": 0}]) is None


def test_ignores_extra_fields():
    """课程 dict 带名字等额外字段不影响计算。"""
    r = compute_weighted_average([{"name": "高数", "score": 80, "credits": 2}])
    assert r["weighted_average"] == 80.0


# ---------- _parse_courses_json：从 LLM 文本抠 JSON ----------
def test_parse_clean_json():
    raw = '[{"score":85,"credits":4},{"score":90,"credits":3}]'
    assert _parse_courses_json(raw) == [
        {"score": 85.0, "credits": 4.0}, {"score": 90.0, "credits": 3.0}]


def test_parse_json_in_code_fence():
    raw = '```json\n[{"score":78,"credits":3}]\n```'
    assert _parse_courses_json(raw) == [{"score": 78.0, "credits": 3.0}]


def test_parse_extracts_from_surrounding_text():
    raw = '结果是 [{"score":80,"credits":2}] 哦'
    assert _parse_courses_json(raw) == [{"score": 80.0, "credits": 2.0}]


def test_parse_garbage_returns_empty():
    assert _parse_courses_json("乱七八糟") == []
    assert _parse_courses_json("") == []
    assert _parse_courses_json(None) == []


def test_parse_handles_trailing_brackets():
    """贪梦正则会从第一个 [ 吃到最后一个 ]——后面有 [1,2] 多余内容时，
    json.loads 整个串会失败，返回 []。应只取第一个完整 JSON 数组。"""
    raw = '[{"score":85,"credits":4}] 参考范围 [3, 5]'
    assert _parse_courses_json(raw) == [{"score": 85.0, "credits": 4.0}]


def test_parse_handles_multiple_json_arrays():
    """LLM 可能输出多组 JSON，只取第一组。"""
    raw = '第一个 [{"score":78,"credits":3}] 第二个 [{"score":90,"credits":2}]'
    assert _parse_courses_json(raw) == [{"score": 78.0, "credits": 3.0}]


def test_parse_skips_items_missing_fields():
    raw = '[{"score":85},{"credits":3},{"score":90,"credits":3}]'
    # 前两项缺字段被跳过，只留第三项
    assert _parse_courses_json(raw) == [{"score": 90.0, "credits": 3.0}]


# ---------- tool_node：把计算结果写进 State ----------
def test_tool_node_computes_and_writes_output(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.extract_courses_with_llm",
        lambda q: [{"score": 85, "credits": 4}, {"score": 90, "credits": 3}],
    )
    out = tool_node({"question": "高数85(4学分)英语90(3学分)"})
    assert "87.14" in out["tool_output"]


def test_tool_node_handles_no_courses(monkeypatch):
    """LLM 没解析出课程时，写一条'无法计算'，不崩。"""
    monkeypatch.setattr("agents.tools.extract_courses_with_llm", lambda q: [])
    out = tool_node({"question": "随便"})
    assert "无法" in out["tool_output"] or "未能" in out["tool_output"]
