"""Shared tracing utilities for agent modules."""

import time


def now_ms(start: float) -> int:
    """Elapsed milliseconds since `start` (a time.perf_counter() value)."""
    return int((time.perf_counter() - start) * 1000)


def trace(
    node: str,
    status: str,
    detail: str,
    query: str = "",
    score: float | None = None,
    start: float | None = None,
) -> dict:
    """Build a trace record dict compatible with the TraceNode pydantic model."""
    return {
        "node": node,
        "status": status,
        "detail": detail,
        "query": query,
        "score": score,
        "duration_ms": now_ms(start) if start else 0,
    }
