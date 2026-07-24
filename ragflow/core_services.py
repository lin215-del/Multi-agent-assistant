from __future__ import annotations

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from import_experiment_pipelines import RagflowClient
from multimodal.media_library import multimodal_document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_CONFIG_PATH = PROJECT_ROOT / "config" / "recommended_core_retrieval.json"
NOTICE_CONFIG_PATH = PROJECT_ROOT / "config" / "recommended_retrieval.json"

BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:8080")
DATASET_NAME = os.getenv("RAGFLOW_CORE_DATASET_NAME", "暨南大学学生助手-核心服务卡片")
CORE_CONFIG = json.loads(CORE_CONFIG_PATH.read_text(encoding="utf-8")) if CORE_CONFIG_PATH.exists() else {}
NOTICE_CONFIG = json.loads(NOTICE_CONFIG_PATH.read_text(encoding="utf-8")) if NOTICE_CONFIG_PATH.exists() else {}
MIN_ACCEPT_SIMILARITY = float(
    os.getenv("MIN_ACCEPT_SIMILARITY", str(CORE_CONFIG.get("similarity_threshold", 0.24)))
)
VECTOR_SIMILARITY_WEIGHT = float(
    os.getenv("VECTOR_SIMILARITY_WEIGHT", str(CORE_CONFIG.get("vector_similarity_weight", 0.1)))
)
TOP_K = int(os.getenv("RAGFLOW_TOP_K", str(CORE_CONFIG.get("top_k", 20))))
PAGE_SIZE = int(os.getenv("RAGFLOW_PAGE_SIZE", str(CORE_CONFIG.get("page_size", 3))))
RERANK_ID = os.getenv("RAGFLOW_RERANK_ID", str(CORE_CONFIG.get("rerank_id") or "")).strip() or None
USE_KEYWORD = os.getenv("RAGFLOW_KEYWORD", str(CORE_CONFIG.get("keyword", False))).lower() in {"1", "true", "yes"}
UNANSWERED_LOG = PROJECT_ROOT / "data" / "feedback" / "unanswered_questions.jsonl"
SERVICE_CARD_DIR = PROJECT_ROOT / "data" / "cleaned" / "service_cards"
LOCAL_KEYWORD_SIMILARITY = MIN_ACCEPT_SIMILARITY + 0.05

SAFETY_RULES = [
    (
        "credentials",
        ("账号密码", "教务系统密码", "验证码", "帮我查密码", "破解密码"),
        "我不能查询、提供或推测任何账号密码、验证码等认证信息。请通过学校官方账号找回渠道处理。",
    ),
    (
        "personal_data",
        ("身份证号码", "身份证号", "家庭住址", "私人手机", "隐私信息"),
        "我不能提供或协助查询他人的身份证号、住址、私人电话等个人信息。",
    ),
    (
        "medical_advice",
        ("吃什么药", "用药剂量", "药吃多少", "帮我诊断", "应该服用"),
        "我不能进行医疗诊断或给出具体用药和剂量建议。请联系校医院或正规医疗机构。",
    ),
    (
        "admission_prediction",
        ("一定能被录取", "多少分一定能", "保证录取", "预测录取", "录取概率", "多少分能稳进"),
        "我不能保证或预测个人录取结果。请以暨南大学招生办公室公布的招生政策、计划和正式录取结果为准。",
    ),
    (
        "unpublished_or_future_fact",
        (
            "尚未公开的比赛评分",
            "未公开的比赛评分",
            "2028年ai应用创新大赛的获奖名单",
            "还没发布的奖学金名额",
            "未发布的奖学金名额",
            "明天番禺校区会不会下雨",
        ),
        "这项信息尚未由学校公开，或不属于当前知识库可以核实的事实。我不会预测或编造结果，请以学校后续官方通知为准。",
    ),
]


def safety_response(question: str) -> dict[str, Any] | None:
    normalized = "".join(question.lower().split())
    for reason, phrases, answer in SAFETY_RULES:
        if any("".join(phrase.lower().split()) in normalized for phrase in phrases):
            return {
                "ok": False,
                "answer": answer,
                "source_url": "",
                "downloads": [],
                "document_name": "",
                "similarity": 0,
                "matches": [],
                "guide": {},
                "reason": reason,
                "threshold": MIN_ACCEPT_SIMILARITY,
            }
    return None


def pick_field(content: str, field: str) -> str:
    pattern = rf"{re.escape(field)}：(.+?)(?:\n\n|\r\n\r\n|$)"
    match = re.search(pattern, content, flags=re.S)
    if not match:
        return ""
    return " ".join(match.group(1).split())


def pick_block(content: str, field: str) -> list[str]:
    pattern = rf"^{re.escape(field)}：\s*\n(.+?)(?:\n\n\S+：|\Z)"
    match = re.search(pattern, content, flags=re.S | re.M)
    if not match:
        return []
    lines = []
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\d+\.\s*", "", line)
        line = re.sub(r"^-\s*", "", line)
        if line:
            lines.append(line)
    return lines


def pick_downloads(content: str) -> list[dict[str, str]]:
    downloads = []
    for line in pick_block(content, "下载文件"):
        name, separator, url = line.partition("|")
        if not separator:
            continue
        name = name.strip()
        url = url.strip()
        if name and url.startswith(("https://", "http://")):
            downloads.append({"name": name, "url": url})
    return downloads


def local_card_content(document_name: str, fallback: str) -> str:
    if document_name:
        path = SERVICE_CARD_DIR / document_name
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    return fallback


def guide_from_content(content: str) -> dict[str, Any]:
    return {
        "category": pick_field(content, "类别"),
        "service_type": pick_field(content, "事项类型"),
        "department": pick_field(content, "负责部门"),
        "audience": pick_field(content, "适用对象"),
        "entrance": pick_field(content, "办理入口"),
        "materials": pick_field(content, "所需材料"),
        "steps": pick_block(content, "办理步骤"),
        "notes": pick_block(content, "注意事项"),
    }


def match_from_content(document_name: str, content: str, similarity: float) -> dict[str, Any]:
    return {
        "document_name": document_name,
        "similarity": similarity,
        "answer": pick_field(content, "直接回答"),
        "source_url": pick_field(content, "来源链接"),
        "downloads": pick_downloads(content),
        "guide": guide_from_content(content),
        "snippet": " ".join(content.split())[:300],
    }


def grounded_notice_fallback(
    rag: RagflowClient,
    question: str,
    dataset_id: str | None = None,
) -> dict[str, Any] | None:
    dataset_id = dataset_id or NOTICE_CONFIG.get("dataset_id")
    if not dataset_id:
        return None
    threshold = float(NOTICE_CONFIG.get("similarity_threshold", 0.7))
    retrieval = rag.request(
        "POST",
        "/retrieval",
        json={
            "dataset_ids": [dataset_id],
            "question": question,
            "page_size": 3,
            "top_k": int(NOTICE_CONFIG.get("top_k", 10)),
            "similarity_threshold": threshold,
            "vector_similarity_weight": float(NOTICE_CONFIG.get("vector_similarity_weight", 0.75)),
            "rerank_id": NOTICE_CONFIG.get("rerank_id"),
            "keyword": False,
            "highlight": False,
        },
    )
    chunks = retrieval.get("chunks", [])
    if not chunks:
        return None
    top = chunks[0]
    content = str(top.get("content") or top.get("content_with_weight") or "")
    document_name = top.get("document_keyword") or top.get("document_name") or "官方通知"
    multimodal = multimodal_document(str(document_name))
    source_match = re.search(r"(?:来源链接|来源)：\s*(https?://\S+)", content)
    if source_match:
        source_url = source_match.group(1).rstrip(".,，。)")
        if not re.match(r"https?://(?:[^/]+\.)?jnu\.edu\.cn(?:/|$)", source_url, flags=re.I):
            return None
    elif multimodal and multimodal.get("source_url"):
        source_url = str(multimodal["source_url"])
    else:
        return None
    body = content.split("## 正文", 1)[-1]
    lines = [
        re.sub(r"^#+\s*", "", line).strip()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith(("来源：", "部门：", "日期：", "分类："))
    ]
    title = lines[0] if lines else ""
    paragraphs = [
        line
        for line in lines[1:]
        if len(line) >= 30
        and line != title
        and not line.startswith(("http://", "https://", "更新时间：", "Copyright"))
    ]
    excerpt = " ".join(([title] if title else []) + paragraphs[:2])[:360].strip()
    if len(excerpt) < 30:
        return None
    similarity = float(top.get("similarity") or 0)
    media = list(multimodal.get("media", [])) if multimodal else []
    is_multimodal = bool(multimodal)
    match = {
        "document_name": document_name,
        "similarity": similarity,
        "answer": excerpt,
        "source_url": source_url,
        "source_label": "查看原始附件" if is_multimodal else "查看官方说明",
        "downloads": [],
        "media": media,
        "guide": {
            "category": "多模态附件" if is_multimodal else "官方通知/资料",
            "service_type": "MinerU 图文摘录" if is_multimodal else "原文摘录",
            "department": "暨南大学附件" if is_multimodal else "暨南大学官方来源",
            "audience": "相关学生",
            "entrance": "查看原始附件" if is_multimodal else "来源页面",
            "materials": "官方公开信息",
            "steps": [],
            "notes": ["这是知识库原文摘录，不对原文未明确的信息作推测。"],
        },
        "snippet": excerpt,
    }
    return {
        "ok": True,
        "answer": f"知识库找到相关官方材料，以下为原文摘录：{excerpt}",
        "source_url": source_url,
        "source_label": "查看原始附件" if is_multimodal else "查看官方说明",
        "downloads": [],
        "media": media,
        "document_name": document_name,
        "similarity": similarity,
        "matches": [match],
        "guide": match["guide"],
        "reason": "grounded_notice_excerpt",
        "threshold": threshold,
    }


def local_keyword_fallback(question: str) -> dict[str, Any] | None:
    question_text = question.lower()
    best: tuple[int, bool, Path, str] | None = None
    for path in SERVICE_CARD_DIR.glob("*.md"):
        content = path.read_text(encoding="utf-8", errors="replace")
        keywords = [
            keyword.strip().lower()
            for keyword in pick_field(content, "关键词").replace("，", ",").split(",")
            if keyword.strip()
        ]
        title = path.stem.lower()
        score = 0
        exact_title = bool(title and title in question_text)
        if exact_title:
            score += 3
        for keyword in keywords:
            if len(keyword) >= 2 and keyword in question_text:
                score += 2 if len(keyword) >= 4 else 1
        if score >= 2 and (best is None or score > best[0]):
            best = (score, exact_title, path, content)
    if best is None:
        return None
    similarity = 0.99 if best[1] else min(0.85, LOCAL_KEYWORD_SIMILARITY + best[0] * 0.1)
    return match_from_content(best[2].name, best[3], similarity)


def load_ragflow(connection: dict[str, str] | None = None):
    if connection:
        return RagflowClient(
            f"{connection['base_url'].rstrip('/')}/api/v1",
            api_key=connection["api_key"],
        )
    return RagflowClient(f"{BASE_URL.rstrip('/')}/api/v1")


def log_unanswered(question: str, reason: str, matches: list[dict[str, Any]]) -> None:
    UNANSWERED_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "reason": reason,
        "top_matches": [
            {
                "document_name": item.get("document_name", ""),
                "similarity": item.get("similarity", 0),
                "answer": item.get("answer", ""),
                "source_url": item.get("source_url", ""),
            }
            for item in matches[:3]
        ],
    }
    with UNANSWERED_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def ask_core_service(question: str, connection: dict[str, str] | None = None) -> dict[str, Any]:
    question = question.strip()
    if not question:
        return {
            "ok": False,
            "answer": "请输入一个问题。",
            "source_url": "",
            "downloads": [],
            "document_name": "",
            "similarity": 0,
            "matches": [],
            "guide": {},
            "threshold": MIN_ACCEPT_SIMILARITY,
        }

    guarded = safety_response(question)
    if guarded:
        log_unanswered(question, guarded["reason"], [])
        return guarded

    rag = load_ragflow(connection)
    configured_dataset_id = (connection or {}).get("dataset_id")
    dataset = next(
        (
            item
            for item in rag.list_datasets()
            if item.get("id") == configured_dataset_id
            or (not configured_dataset_id and item.get("name") == DATASET_NAME)
        ),
        None,
    )
    if not dataset:
        raise RuntimeError("RAGFlow knowledge base not found")
    retrieval = rag.request(
        "POST",
        "/retrieval",
        json={
            "dataset_ids": [dataset["id"]],
            "question": question,
            "page_size": PAGE_SIZE,
            "similarity_threshold": MIN_ACCEPT_SIMILARITY,
            "vector_similarity_weight": VECTOR_SIMILARITY_WEIGHT,
            "top_k": TOP_K,
            "rerank_id": RERANK_ID,
            "keyword": USE_KEYWORD,
            "cross_languages": CORE_CONFIG.get("cross_languages", []),
            "metadata_condition": CORE_CONFIG.get("metadata_condition"),
            "use_kg": bool(CORE_CONFIG.get("use_kg", False)),
            "highlight": False,
        },
    )
    chunks = retrieval.get("chunks", [])

    matches = []
    for chunk in chunks[:3]:
        content = chunk.get("content") or chunk.get("content_with_weight") or ""
        document_name = chunk.get("document_keyword") or chunk.get("document_name") or ""
        full_content = local_card_content(document_name, content)
        matches.append(match_from_content(document_name, full_content, float(chunk.get("similarity") or 0)))

    use_project_cards = not connection or dataset.get("name") == DATASET_NAME
    keyword_match = local_keyword_fallback(question) if use_project_cards else None
    if keyword_match:
        for item in matches:
            if item["document_name"] == keyword_match["document_name"]:
                item["similarity"] = max(item["similarity"], keyword_match["similarity"])
                break
        else:
            matches.append(keyword_match)

    best = max(matches, key=lambda item: item["similarity"]) if matches else None
    if not best or not best["answer"]:
        notice_dataset_id = (connection or {}).get("notice_dataset_id")
        notice = (
            grounded_notice_fallback(rag, question, notice_dataset_id)
            if not connection or notice_dataset_id
            else None
        )
        if notice:
            return notice
        if connection and chunks:
            top = chunks[0]
            content = " ".join(
                str(top.get("content") or top.get("content_with_weight") or "").split()
            )[:520]
            if content:
                document_name = str(
                    top.get("document_keyword") or top.get("document_name") or "知识库材料"
                )
                similarity = float(top.get("similarity") or 0)
                return {
                    "ok": True,
                    "answer": f"知识库找到相关原文：{content}",
                    "source_url": "",
                    "downloads": [],
                    "document_name": document_name,
                    "similarity": similarity,
                    "matches": [{
                        "document_name": document_name,
                        "similarity": similarity,
                        "answer": content,
                        "source_url": "",
                        "downloads": [],
                        "guide": {},
                        "snippet": content,
                    }],
                    "guide": {},
                    "reason": "configured_dataset_excerpt",
                    "threshold": MIN_ACCEPT_SIMILARITY,
                }
        log_unanswered(question, "no_direct_answer", matches)
        return {
            "ok": False,
            "answer": "当前知识库未收录明确材料。",
            "source_url": "",
            "downloads": [],
            "document_name": "",
            "similarity": 0,
            "matches": matches,
            "guide": {},
            "threshold": MIN_ACCEPT_SIMILARITY,
        }

    if best["similarity"] < MIN_ACCEPT_SIMILARITY:
        notice_dataset_id = (connection or {}).get("notice_dataset_id")
        notice = (
            grounded_notice_fallback(rag, question, notice_dataset_id)
            if not connection or notice_dataset_id
            else None
        )
        if notice:
            return notice
        log_unanswered(question, "low_similarity", matches)
        return {
            "ok": False,
            "answer": "当前知识库未收录明确材料。为避免误导学生，我不会根据不相关资料猜测答案。",
            "source_url": "",
            "downloads": [],
            "document_name": best["document_name"],
            "similarity": best["similarity"],
            "matches": matches,
            "guide": best.get("guide", {}),
            "reason": "low_similarity",
            "threshold": MIN_ACCEPT_SIMILARITY,
        }

    return {
        "ok": True,
        "answer": best["answer"],
        "source_url": best["source_url"],
        "downloads": best.get("downloads", []),
        "document_name": best["document_name"],
        "similarity": best["similarity"],
        "matches": matches,
        "guide": best.get("guide", {}),
        "reason": "answered",
        "threshold": MIN_ACCEPT_SIMILARITY,
    }
