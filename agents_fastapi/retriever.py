"""Retriever agent: RAGFlow API retrieval and grounded answer extraction."""

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from .state import AgentState

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RETRIEVAL_CONFIG: dict[str, Any] | None = None


def _load_retrieval_config() -> dict[str, Any]:
    global _RETRIEVAL_CONFIG
    if _RETRIEVAL_CONFIG is not None:
        return _RETRIEVAL_CONFIG
    defaults: dict[str, Any] = {
        "page_size": 5, "top_k": 30, "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.7, "keyword": True,
    }
    path = _PROJECT_ROOT / "config" / "recommended_core_retrieval.json"
    try:
        configured = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        configured = {}
    for key in defaults:
        if key in configured:
            defaults[key] = configured[key]
    defaults["page_size"] = max(1, min(20, int(defaults["page_size"])))
    defaults["top_k"] = max(defaults["page_size"], min(100, int(defaults["top_k"])))
    defaults["similarity_threshold"] = max(0.0, min(1.0, float(defaults["similarity_threshold"])))
    defaults["vector_similarity_weight"] = max(0.0, min(1.0, float(defaults["vector_similarity_weight"])))
    defaults["keyword"] = bool(defaults["keyword"])
    _RETRIEVAL_CONFIG = defaults
    return defaults


def _ragflow_headers() -> dict[str, str]:
    key = os.getenv("RAGFLOW_API_KEY", "")
    if not key:
        raise RuntimeError("RAGFLOW_API_KEY 未配置")
    return {"Authorization": f"Bearer {key}"}


def active_dataset_ids(route: str) -> list[str]:
    ids = [os.getenv("RAGFLOW_DATASET_ID", "")]
    ids = [i for i in ids if i]
    notice = os.getenv("RAGFLOW_NOTICE_DATASET_ID", "")
    if notice and notice not in ids:
        ids.append(notice)
    if not ids:
        raise RuntimeError("RAGFLOW_DATASET_ID 未配置")
    return ids


def _source_urls(content: str) -> list[str]:
    links: list[str] = []
    for m in re.findall(r"https?://[^\s<>()（）]+", content or ""):
        url = m.rstrip(".,，。；;：:!?！？]}>\"'")
        if url and url not in links:
            links.append(url)
    return links


def extract_source_url(content: str) -> str:
    links = _source_urls(content)
    return links[0] if links else ""


def normalized_document_name(value: str) -> str:
    return re.sub(r"\.(md|pdf|docx?|xlsx?)$", "", value.strip(), flags=re.I).casefold()


@lru_cache(maxsize=512)
def _local_document_source_url(document_name: str) -> str:
    wanted = normalized_document_name(document_name)
    if not wanted:
        return ""
    datasets_root = _PROJECT_ROOT / "knowledge_base" / "datasets"
    for catalog in datasets_root.glob("*/documents.jsonl"):
        try:
            rows = catalog.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for raw in rows:
            try:
                item = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if normalized_document_name(str(item.get("name") or "")) != wanted:
                continue
            blob_path = str(item.get("blob_path") or "")
            if not blob_path:
                continue
            try:
                url = extract_source_url(
                    (_PROJECT_ROOT / "knowledge_base" / blob_path).read_text(encoding="utf-8", errors="ignore")
                )
            except OSError:
                url = ""
            if url:
                return url
    return ""


def _plain_text(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"SHA-?256[:?]?\s*[0-9a-fA-F]{16,}", "", text)
    text = re.sub(r"[A-Za-z0-9_\-]{32,}\.(pdf|md|docx|xlsx|jpg|png)", "", text)
    text = re.sub(r"[#>*`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _source_location(item: dict[str, Any]) -> str:
    positions = item.get("positions") or item.get("position_int") or []
    if isinstance(positions, list) and positions:
        first = positions[0]
        if isinstance(first, (list, tuple)) and first:
            try:
                return f"第 {int(first[0]) + 1} 页附近"
            except (TypeError, ValueError):
                pass
    page = item.get("page_num") or item.get("page_number")
    return f"第 {page} 页" if page else "原文相关分块"


def _concise_answer_from_content(content: str) -> str:
    text = _plain_text(content)
    if not text:
        return "知识库找到了相关资料，但正文内容不足。请查看下方来源片段或官方来源。"
    lower = text.lower()
    is_recommend = ("推免" in text) or ("免试" in text) or ("推免申请" in text) or ("upload_article_files_d5_9e" in lower)
    if is_recommend:
        steps = []
        if "jw.jnu.edu.cn" in lower or "教务系统" in text:
            steps.append("登录暨南大学教务系统，使用门户账号密码进入。")
        if "注意事项" in text:
            steps.append("进入服务后先阅读推免申请报名注意事项。")
        if "推免申请报名" in text:
            steps.append('确认无误后点击"推免申请报名"按钮，按页面要求提交申请。')
        if not steps:
            steps = [
                "登录教务系统或手册指定的报名入口。",
                "按页面提示阅读注意事项并填写申请信息。",
                "提交前对照下方手册截图核对操作页面。",
            ]
        return "推免申请报名手册的核心操作：\n" + "\n".join(
            f"{i}. {step}" for i, step in enumerate(steps, 1)
        ) + '\n\n相关页面截图已放在下方"相关图片/表格"区域，可以对照操作。'
    sentences = re.split(r"[。；;]\s*", text)
    useful = [x.strip() for x in sentences if 12 <= len(x.strip()) <= 120]
    useful = useful[:3] or [text[:180]]
    return "根据知识库资料，可以这样处理：\n" + "\n".join(f"{i}. {item}。" for i, item in enumerate(useful, 1))


def ragflow_retrieve(state: AgentState) -> dict:
    """Call RAGFlow API. Reads state.retrieval_query, sets state.retrieved."""
    query = state.retrieval_query or state.expanded_question
    config = _load_retrieval_config()
    base_url = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080").rstrip("/")
    body: dict[str, Any] = {
        "dataset_ids": active_dataset_ids(state.route),
        "question": query,
        "page_size": config["page_size"],
        "top_k": config["top_k"],
        "similarity_threshold": config["similarity_threshold"],
        "vector_similarity_weight": config["vector_similarity_weight"],
        "keyword": config["keyword"],
        "highlight": False,
    }
    rerank = os.getenv("RAGFLOW_RERANK_ID", "")
    if rerank:
        body["rerank_id"] = rerank
    response = requests.post(
        f"{base_url}/api/v1/retrieval",
        headers={**_ragflow_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(str(payload.get("message") or "RAGFlow retrieval failed"))
    chunks = list((payload.get("data") or {}).get("chunks") or [])
    state.retrieved = chunks
    top_score = float((chunks[0] or {}).get("similarity") or 0) if chunks else 0
    return {"status": "success", "detail": f"召回 {len(chunks)} 个分块",
            "chunk_count": len(chunks), "top_score": top_score}


def make_grounded_answer(state: AgentState) -> dict:
    """Extract answer from retrieval results. Sets state.ok, answer, document_name, etc."""
    chunks = state.retrieved
    if not chunks:
        state.ok = False
        state.answer = "当前知识库未收录明确材料。为避免误导，我不会猜测答案。"
        state.document_name = ""
        state.source_url = ""
        state.similarity = 0.0
        state.matches = []
        return {"status": "insufficient", "detail": "无召回分块", "ok": False, "similarity": 0.0}

    top = chunks[0]
    content = str(top.get("content") or top.get("content_with_weight") or "")
    doc_name = str(top.get("document_keyword") or top.get("document_name") or "知识库文档")
    sim = float(top.get("similarity") or 0)

    if sim < 0.2 or len(content.strip()) < 30:
        state.ok = False
        state.answer = "当前知识库未收录明确材料。为避免误导，我不会猜测答案。"
        state.document_name = doc_name
        state.source_url = ""
        state.similarity = sim
        state.matches = []
        return {"status": "insufficient", "detail": "相似度或内容不足", "ok": False, "similarity": sim}

    state.ok = True
    state.answer = _concise_answer_from_content(content)
    state.document_name = doc_name
    state.similarity = sim

    matches = []
    for item in chunks[:5]:
        item_content = str(item.get("content") or item.get("content_with_weight") or "")
        matches.append({
            "document_name": str(item.get("document_keyword") or item.get("document_name") or "知识库文档"),
            "similarity": float(item.get("similarity") or 0),
            "snippet": f"{_source_location(item)}｜{_plain_text(item_content)[:220]}",
            "location": _source_location(item),
            "source_url": extract_source_url(item_content),
        })
    state.matches = matches

    wanted = normalized_document_name(doc_name)
    first_url = extract_source_url(content) or next(
        (str(m["source_url"]) for m in matches
         if m.get("source_url") and normalized_document_name(str(m.get("document_name") or "")) == wanted),
        "",
    )
    if not first_url:
        first_url = _local_document_source_url(doc_name)
    state.source_url = first_url

    return {"status": "success", "detail": f"最高相似度 {sim:.3f}", "ok": True, "similarity": sim}
