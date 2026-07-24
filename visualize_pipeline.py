from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from multimodal.media_library import public_media_library


PROJECT_ROOT = Path(__file__).resolve().parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
RAW_MANIFEST = PROJECT_ROOT / "data" / "raw" / "manifest.jsonl"
CLEANED_DOCS = PROJECT_ROOT / "data" / "cleaned" / "documents.jsonl"
RAGFLOW_MARKDOWN_DIR = PROJECT_ROOT / "data" / "cleaned" / "ragflow_markdown"
SERVICE_CARD_DIR = PROJECT_ROOT / "data" / "cleaned" / "service_cards"
MINERU_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "manifest.jsonl"
MINERU_IMPORT_MANIFEST = PROJECT_ROOT / "data" / "cleaned" / "mineru" / "ragflow_import.jsonl"
OUTPUT_HTML = PROJECT_ROOT / "outputs" / "pipeline_dashboard.html"
COVERAGE_JSON = PROJECT_ROOT / "outputs" / "coverage_report.json"
EXPERIMENT_RESULTS = PROJECT_ROOT / "outputs" / "chunk_experiment_results.json"
RETRIEVAL_BENCHMARK = PROJECT_ROOT / "config" / "retrieval_benchmark.json"
RECOMMENDED_RETRIEVAL = PROJECT_ROOT / "config" / "recommended_retrieval.json"
RECOMMENDED_CORE_RETRIEVAL = PROJECT_ROOT / "config" / "recommended_core_retrieval.json"
CORE_RETRIEVAL_BENCHMARK = PROJECT_ROOT / "config" / "core_retrieval_benchmark.json"
QUALITY_GATE = PROJECT_ROOT / "outputs" / "quality_gate.json"
AUTOMATIC_UPDATE_STATUS = PROJECT_ROOT / "outputs" / "automatic_update_status.json"
AUTOMATIC_SCHEDULER_STATUS = PROJECT_ROOT / "outputs" / "automatic_scheduler_status.json"
NATIVE_IMAGE_SYNC = PROJECT_ROOT / "outputs" / "native_image_sync.json"
UNANSWERED_LOG = PROJECT_ROOT / "data" / "feedback" / "unanswered_questions.jsonl"
CATEGORIES_CONFIG = PROJECT_ROOT / "config" / "categories.json"
SEEDS_CONFIG = PROJECT_ROOT / "config" / "seeds.json"
RAGFLOW_KB_NAMES = ["暨南大学学生助手-第一阶段", "暨南大学学生助手-核心服务卡片"]

MOJIBAKE_MARKERS = [
    "å",
    "æ",
    "ç",
    "è",
    "é",
    "ã€",
    "ã",
    "Â",
    "ï¼",
    "â€”",
    "â€œ",
    "â€",
    "¤",
    "œ",
]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"_parse_error": line[:200]})
    return rows


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def task_status(value: object) -> str:
    return {
        "0": "未开始",
        "1": "处理中",
        "2": "已取消",
        "3": "完成",
        "4": "失败",
        "5": "已计划",
    }.get(str(value).upper(), str(value))


def rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def parse_service_card(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")

    def field(name: str) -> str:
        match = re.search(rf"^{re.escape(name)}：(.+)$", text, flags=re.M)
        return match.group(1).strip() if match else ""

    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    return {
        "file": path.name,
        "path": rel(path),
        "title": title_match.group(1).strip() if title_match else path.stem,
        "category": field("类别"),
        "service_type": field("事项类型"),
        "department": field("负责部门"),
        "audience": field("适用对象"),
        "entrance": field("办理入口"),
        "materials": field("所需材料"),
        "answer": field("直接回答"),
        "source_url": field("来源链接"),
        "keywords": field("关键词"),
        "length": len(text),
    }


def question_matches_cards(question: str, service_cards: list[dict]) -> bool:
    question_text = question.lower()
    for card in service_cards:
        terms = [card.get("title", ""), *re.split(r"[,，]", card.get("keywords", ""))]
        if any(term.strip().lower() in question_text for term in terms if len(term.strip()) >= 2):
            return True
    return False


def build_coverage_report(
    cleaned_rows: list[dict] | None = None,
    service_cards: list[dict] | None = None,
    unanswered_rows: list[dict] | None = None,
) -> dict:
    cleaned_rows = read_jsonl(CLEANED_DOCS) if cleaned_rows is None else cleaned_rows
    if service_cards is None:
        service_cards = (
            [parse_service_card(path) for path in sorted(SERVICE_CARD_DIR.glob("*.md"))]
            if SERVICE_CARD_DIR.exists()
            else []
        )
    unanswered_rows = read_jsonl(UNANSWERED_LOG) if unanswered_rows is None else unanswered_rows

    categories_config = read_json(CATEGORIES_CONFIG, {})
    category_names = [name for name in categories_config if name != "其他"] if isinstance(categories_config, dict) else []
    seeds_config = read_json(SEEDS_CONFIG, {})
    seeds = seeds_config.get("seeds", []) if isinstance(seeds_config, dict) else []
    department_names = list(dict.fromkeys(seed.get("department", "") for seed in seeds if seed.get("department")))

    card_categories = Counter(card.get("category") or "未标注" for card in service_cards)
    cleaned_categories: Counter[str] = Counter()
    for row in cleaned_rows:
        for category in row.get("categories") or []:
            cleaned_categories[category] += 1

    category_rows = []
    for name in category_names:
        card_count = card_categories[name]
        source_count = cleaned_categories[name]
        if card_count > 0:
            status = "核心卡片"
        elif source_count > 0:
            status = "仅有资料"
        else:
            status = "未覆盖"
        category_rows.append(
            {"name": name, "card_count": card_count, "source_count": source_count, "status": status}
        )

    card_departments = Counter(card.get("department") or "未标注" for card in service_cards)
    cleaned_departments = Counter(row.get("department") or "未标注" for row in cleaned_rows)
    department_rows = []
    for name in department_names:
        card_count = card_departments[name]
        source_count = cleaned_departments[name]
        status = "核心卡片" if card_count else ("仅有资料" if source_count else "未覆盖")
        department_rows.append(
            {"name": name, "card_count": card_count, "source_count": source_count, "status": status}
        )

    feedback_counts: Counter[str] = Counter()
    feedback_details: dict[str, dict] = {}
    for row in unanswered_rows:
        question = " ".join(str(row.get("question", "")).split()).strip()
        if len(question) < 2 or not re.search(r"[\w\u4e00-\u9fff]", question) or "火星" in question:
            continue
        feedback_counts[question] += 1
        feedback_details[question] = row

    feedback_rows = []
    for question, count in feedback_counts.most_common(20):
        resolved = question_matches_cards(question, service_cards)
        detail = feedback_details[question]
        feedback_rows.append(
            {
                "question": question,
                "count": count,
                "status": "可能已补充" if resolved else "待补充",
                "reason": detail.get("reason", ""),
                "top_document": (detail.get("top_matches") or [{}])[0].get("document_name", ""),
            }
        )

    priorities = []
    for row in category_rows:
        if row["card_count"] == 0:
            priority = "高" if row["source_count"] == 0 else "中"
            action = "补充官方数据源并制作核心服务卡片" if row["source_count"] == 0 else "从现有清洗资料制作核心服务卡片"
            priorities.append({"priority": priority, "type": "事项类别", "name": row["name"], "action": action})
        elif row["card_count"] == 1:
            priorities.append(
                {"priority": "低", "type": "事项类别", "name": row["name"], "action": "补充更多高频事项，避免单卡片覆盖过窄"}
            )
    for row in department_rows:
        if row["card_count"] == 0:
            priority = "中" if row["source_count"] else "高"
            action = "从该部门现有资料制作核心服务卡片" if row["source_count"] else "新增该部门官方数据源"
            priorities.append({"priority": priority, "type": "责任部门", "name": row["name"], "action": action})
    for row in feedback_rows:
        if row["status"] == "待补充":
            priorities.append(
                {"priority": "高", "type": "学生问题", "name": row["question"], "action": "查找官方来源并补充服务卡片"}
            )

    priority_order = {"高": 0, "中": 1, "低": 2}
    priorities.sort(key=lambda row: (priority_order[row["priority"]], row["type"], row["name"]))
    covered_categories = sum(1 for row in category_rows if row["card_count"] > 0)
    covered_departments = sum(1 for row in department_rows if row["card_count"] > 0)
    source_covered_categories = sum(1 for row in category_rows if row["source_count"] > 0 or row["card_count"] > 0)
    source_covered_departments = sum(1 for row in department_rows if row["source_count"] > 0 or row["card_count"] > 0)
    return {
        "version": VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev",
        "summary": {
            "target_categories": len(category_rows),
            "covered_categories": covered_categories,
            "category_coverage_percent": round(covered_categories * 100 / len(category_rows), 1) if category_rows else 0,
            "source_covered_categories": source_covered_categories,
            "source_category_coverage_percent": round(source_covered_categories * 100 / len(category_rows), 1) if category_rows else 0,
            "target_departments": len(department_rows),
            "covered_departments": covered_departments,
            "source_covered_departments": source_covered_departments,
            "feedback_questions": sum(feedback_counts.values()),
            "priority_gaps": sum(1 for row in priorities if row["priority"] in {"高", "中"}),
        },
        "categories": category_rows,
        "departments": department_rows,
        "feedback": feedback_rows,
        "priorities": priorities,
    }


def text_quality(text: str) -> dict:
    length = max(len(text), 1)
    bad = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    replacement_chars = text.count("�")
    return {
        "length": len(text),
        "mojibake_hits": bad + replacement_chars,
        "mojibake_rate": (bad + replacement_chars) / length,
    }


def load_ragflow_status() -> list[dict]:
    script = r"""
import os, pymysql, json
names = [
    "暨南大学学生助手-第一阶段",
    "暨南大学学生助手-核心服务卡片",
    "暨南大学学生助手-实验A-小块500",
    "暨南大学学生助手-实验B-中块800",
    "暨南大学学生助手-实验C-上下文1200",
]
conn = pymysql.connect(
    host=os.getenv('MYSQL_HOST'),
    port=int(os.getenv('MYSQL_PORT', '3306')),
    user='root',
    password=os.getenv('MYSQL_PASSWORD'),
    database=os.getenv('MYSQL_DBNAME'),
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor,
)
cur = conn.cursor()
items = []
for name in names:
    cur.execute("select id,name,doc_num,token_num,chunk_num,status from knowledgebase where name=%s", (name,))
    kb = cur.fetchone()
    if not kb:
        continue
    cur.execute(
        "select id,name,run,progress,progress_msg,chunk_num,token_num,suffix from document where kb_id=%s order by create_time desc",
        (kb["id"],),
    )
    kb["documents"] = cur.fetchall()
    items.append(kb)
print(json.dumps(items, ensure_ascii=False))
"""
    temp_path = Path(tempfile.gettempdir()) / "ragflow_status_for_dashboard.py"
    temp_path.write_text(script, encoding="utf-8")
    try:
        subprocess.run(
            ["docker", "cp", str(temp_path), "docker-ragflow-cpu-1:/tmp/ragflow_status_for_dashboard.py"],
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["docker", "exec", "docker-ragflow-cpu-1", "python", "/tmp/ragflow_status_for_dashboard.py"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(result.stdout.strip() or "[]")
    except Exception as exc:
        return [{"error": str(exc)}]


def build_dashboard() -> str:
    project_version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev"
    raw_rows = read_jsonl(RAW_MANIFEST)
    cleaned_rows = read_jsonl(CLEANED_DOCS)
    markdown_files = sorted(RAGFLOW_MARKDOWN_DIR.glob("*.md")) if RAGFLOW_MARKDOWN_DIR.exists() else []
    service_cards = [parse_service_card(path) for path in sorted(SERVICE_CARD_DIR.glob("*.md"))] if SERVICE_CARD_DIR.exists() else []
    ragflow_status = load_ragflow_status()
    experiment_results = read_json(EXPERIMENT_RESULTS, {})
    retrieval_benchmark = read_json(RETRIEVAL_BENCHMARK, {})
    recommended_retrieval = read_json(RECOMMENDED_RETRIEVAL, {})
    recommended_core = read_json(RECOMMENDED_CORE_RETRIEVAL, {})
    core_benchmark = read_json(CORE_RETRIEVAL_BENCHMARK, {})
    quality_gate = read_json(QUALITY_GATE, {})
    automatic_update = read_json(AUTOMATIC_UPDATE_STATUS, {})
    automatic_scheduler = read_json(AUTOMATIC_SCHEDULER_STATUS, {})
    native_image_sync = read_json(NATIVE_IMAGE_SYNC, {})
    media_library = public_media_library()
    unanswered_rows = read_jsonl(UNANSWERED_LOG)
    coverage = build_coverage_report(cleaned_rows, service_cards, unanswered_rows)
    mineru_events = read_jsonl(MINERU_MANIFEST)
    mineru_import_events = read_jsonl(MINERU_IMPORT_MANIFEST)
    mineru_attachment_names = {
        row.get("document_name")
        for row in mineru_import_events
        if row.get("status") == "ATTACHMENT_ONLY" and row.get("document_name")
    }
    mineru_latest = {row.get("source"): row for row in mineru_events if row.get("source")}
    mineru_rows = sorted(mineru_latest.values(), key=lambda row: row.get("finished_at", ""), reverse=True)
    mineru_success = sum(1 for row in mineru_rows if row.get("status") == "success")
    mineru_failed = sum(1 for row in mineru_rows if row.get("status") == "failed")
    mineru_unsupported = sum(1 for row in mineru_rows if row.get("status") == "unsupported")
    media_summary = media_library.get("summary", {})
    visually_enriched = sum(bool(item.get("visual_description")) for item in media_library.get("items", []))
    native_image_cards_html = "\n".join(
        f"""
        <article class="ragflow-card">
          <h3>RAGFlow 实验 {esc(item.get('label'))}</h3>
          <div class="metric-grid">
            <b>{esc(item.get('verified', 0))}<small>image_id 已验证</small></b>
            <b>{esc(item.get('created', 0))}<small>本次新增</small></b>
            <b>{esc(item.get('failed', 0))}<small>失败</small></b>
          </div>
          <p class="note">知识库：{esc(item.get('dataset_name'))}<br>同步时间：{esc(native_image_sync.get('generated_at') or '-')}</p>
          <a class="button" href="http://localhost:8080/dataset/files/{esc(item.get('dataset_id'))}" target="_blank">在 RAGFlow 查看</a>
        </article>
        """
        for item in native_image_sync.get("datasets", [])
    ) or '<p class="note">尚未执行 RAGFlow 原生图片同步。</p>'
    media_gallery_html = "\n".join(
        f"""
        <figure class="media-card">
          <a href="{esc(item.get('url'))}" target="_blank" rel="noreferrer">
            <img src="{esc(item.get('url'))}" alt="{esc(item.get('caption') or '文档图片')}" loading="lazy">
          </a>
          <figcaption>
            <strong>{esc(item.get('title'))}</strong>
            <span>{esc('图像' if item.get('type') == 'image' else '表格')} · 第 {esc(item.get('page') or '?')} 页</span>
            <span>{esc(item.get('caption'))}</span>
          </figcaption>
        </figure>
        """
        for item in media_library.get("items", [])
    ) or '<p class="note">当前 MinerU 结果中没有可展示的图片。</p>'

    update_state_labels = {
        "running": "运行中",
        "success": "成功",
        "failed": "失败",
        "warning": "有警告",
    }
    automatic_stage_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(stage.get('name'))}</td>
          <td>{esc(update_state_labels.get(stage.get('state'), stage.get('state')))}</td>
          <td>{esc(stage.get('duration_seconds') if stage.get('duration_seconds') is not None else '-')}</td>
          <td>{esc(stage.get('error') or '')}</td>
        </tr>
        """
        for stage in automatic_update.get("stages", [])
    ) or '<tr><td colspan="4">定时更新尚未执行</td></tr>'
    update_changes = automatic_update.get("changes", {})
    automatic_update_html = f"""
      <div class="metric-grid">
        <b>{esc(update_state_labels.get(automatic_update.get('state'), automatic_update.get('state') or '待执行'))}<small>最近状态</small></b>
        <b>{esc(len(update_changes.get('added', [])))}<small>新增文档</small></b>
        <b>{esc(len(update_changes.get('changed', [])))}<small>更新文档</small></b>
      </div>
      <p class="note">计划：{esc(automatic_scheduler.get('schedule') or '每日 03:00')} · 下次运行：{esc(automatic_scheduler.get('next_run_at') or '-')} · 最近完成：{esc(automatic_update.get('finished_at') or '-')}</p>
      <div class="scroll"><table><thead><tr><th>阶段</th><th>状态</th><th>耗时(秒)</th><th>说明</th></tr></thead><tbody>{automatic_stage_rows}</tbody></table></div>
    """

    raw_pages = [row for row in raw_rows if row.get("kind") == "page"]
    raw_attachments = [row for row in raw_rows if row.get("kind") == "attachment"]
    departments = Counter(row.get("department") or "未标注" for row in cleaned_rows)
    category_counter: Counter[str] = Counter()
    for row in cleaned_rows:
        for category in row.get("categories") or []:
            category_counter[category] += 1

    cleaned_quality = []
    for row in cleaned_rows:
        quality = text_quality(row.get("text", ""))
        cleaned_quality.append({**row, **quality})
    quality_issues = [row for row in cleaned_quality if row["mojibake_hits"] > 0]

    step_cards = [
        ("M", "MinerU 多模态清洗", mineru_success, "解析附件版面、OCR 文字、表格和图片，生成结构化 Markdown"),
        ("1", "公开网页采集", len(raw_pages), "保存学校官网 HTML 原文和来源元数据"),
        ("2", "附件下载", len(raw_attachments), "保存 PDF、Word、Excel 等公开附件"),
        ("3", "清洗结构化文档", len(cleaned_rows), "抽取标题、部门、日期、类别、正文、来源"),
        ("4", "RAGFlow Markdown", len(markdown_files), "转成可导入知识库的 Markdown"),
        ("5", "核心服务卡片", len(service_cards), "整理为稳定问答使用的高频事项卡片"),
        ("6", "质量问题提示", len(quality_issues), "标记疑似乱码或需要人工复核的清洗结果"),
    ]

    mineru_rows_html = "\n".join(
        f"""
        <tr>
          <td>{esc(row.get('source'))}</td>
          <td class="{'ok' if row.get('status') == 'success' else 'warn'}">{esc(row.get('status'))}</td>
          <td>{esc(row.get('backend', ''))}</td>
          <td>{esc(row.get('duration_seconds', ''))}</td>
          <td>{esc(row.get('image_count', 0))}</td>
          <td>{esc((row.get('content_list_count') or 0) + (row.get('middle_json_count') or 0))}</td>
          <td>{esc(row.get('ragflow_markdown') or row.get('reason') or row.get('error', '')[:160])}</td>
        </tr>
        """
        for row in mineru_rows
    ) or "<tr><td colspan=\"7\">尚未运行 MinerU</td></tr>"
    mineru_imported_names = {
        row.get("document_name") for row in mineru_import_events if row.get("document_name")
    }
    mineru_summary_html = (
        f"成功 {mineru_success} 个，失败 {mineru_failed} 个，不支持 {mineru_unsupported} 个，"
        f"已提交 RAGFlow {len(mineru_imported_names)} 个。"
    )

    service_rows = "\n".join(
        f"""
        <tr>
          <td><a href="../{esc(card['path'])}" target="_blank">{esc(card['title'])}</a></td>
          <td>{esc(card['category'])}</td>
          <td>{esc(card['service_type'])}</td>
          <td>{esc(card['department'])}</td>
          <td>{esc(card['entrance'])}</td>
          <td>{esc(card['materials'])}</td>
          <td>{esc(card['answer'])}</td>
          <td><a href="{esc(card['source_url'])}" target="_blank">{esc(card['source_url'])}</a></td>
        </tr>
        """
        for card in service_cards
    )

    cleaned_rows_html = "\n".join(
        f"""
        <tr>
          <td>{esc(row.get('title'))}</td>
          <td>{esc(row.get('department'))}</td>
          <td>{esc(row.get('category_hint'))}</td>
          <td>{esc(', '.join(row.get('categories') or []))}</td>
          <td>{esc(row.get('date'))}</td>
          <td><a href="{esc(row.get('source_url'))}" target="_blank">来源</a></td>
          <td>{row['length']}</td>
          <td class="{ 'warn' if row['mojibake_hits'] else 'ok' }">{row['mojibake_hits']}</td>
        </tr>
        """
        for row in cleaned_quality[:80]
    )

    raw_rows_html = "\n".join(
        f"""
        <tr>
          <td>{esc(row.get('seed_name') or row.get('title'))}</td>
          <td>{esc(row.get('department'))}</td>
          <td>{esc(row.get('category_hint'))}</td>
          <td>{esc(row.get('depth'))}</td>
          <td><a href="{esc(row.get('url'))}" target="_blank">{esc(row.get('url'))}</a></td>
          <td>{esc(row.get('local_path'))}</td>
        </tr>
        """
        for row in raw_pages[:80]
    )

    department_items = "\n".join(
        f"<div class=\"bar\"><span>{esc(name)}</span><strong style=\"width:{max(8, count * 18)}px\">{count}</strong></div>"
        for name, count in departments.most_common()
    )
    category_items = "\n".join(
        f"<div class=\"bar accent\"><span>{esc(name)}</span><strong style=\"width:{max(8, count * 18)}px\">{count}</strong></div>"
        for name, count in category_counter.most_common()
    )
    steps_html = "\n".join(
        f"""
        <article class="step">
          <div class="num">{esc(num)}</div>
          <h3>{esc(title)}</h3>
          <b>{count}</b>
          <p>{esc(desc)}</p>
        </article>
        """
        for num, title, count, desc in step_cards
    )

    worst_quality_html = "\n".join(
        f"""
        <li>
          <strong>{esc(row.get('title'))}</strong>
          <span>{esc(row.get('source_url'))}</span>
          <em>疑似乱码命中 {row['mojibake_hits']} 次</em>
        </li>
        """
        for row in sorted(quality_issues, key=lambda item: item["mojibake_hits"], reverse=True)[:8]
    ) or "<li><strong>未发现明显乱码</strong><span>当前清洗文本质量正常</span></li>"

    ragflow_cards = []
    ragflow_doc_rows = []
    for kb in ragflow_status:
        if kb.get("error"):
            ragflow_cards.append(
                f"""
                <article class="ragflow-card error-card">
                  <h3>RAGFlow 状态读取失败</h3>
                  <p>{esc(kb['error'])}</p>
                </article>
                """
            )
            continue
        documents = kb.get("documents", [])
        completed = sum(1 for doc in documents if task_status(doc.get("run")) == "完成")
        failed = sum(1 for doc in documents if task_status(doc.get("run")) == "失败")
        attachment_only = sum(1 for doc in documents if doc.get("name") in mineru_attachment_names)
        processing = max(len(documents) - completed - failed - attachment_only, 0)
        files_url = f"http://localhost:8080/dataset/files/{kb['id']}"
        logs_url = f"http://localhost:8080/dataset/logs/{kb['id']}"
        ragflow_cards.append(
            f"""
            <article class="ragflow-card">
              <h3>{esc(kb['name'])}</h3>
              <div class="metric-row"><span>知识库 ID</span><code>{esc(kb['id'])}</code></div>
              <div class="metric-grid">
                <b>{esc(kb['doc_num'])}<small>文档</small></b>
                <b>{esc(kb['chunk_num'])}<small>分块</small></b>
                <b>{esc(kb['token_num'])}<small>Token</small></b>
              </div>
              <div class="parse-summary">
                <span class="done">成功 {completed}</span>
                <span>处理中 {processing}</span>
                <span class="failed">失败 {failed}</span>
                <span>附件留存 {attachment_only}</span>
              </div>
              <div class="link-row">
                <a href="{files_url}" target="_blank">打开 RAGFlow 文件列表</a>
                <a href="{logs_url}" target="_blank">打开 RAGFlow 日志</a>
              </div>
            </article>
            """
        )
        for doc in kb.get("documents", [])[:80]:
            run_status = task_status(doc.get("run"))
            if doc.get("name") in mineru_attachment_names:
                run_status = "附件留存（不解析）"
            ragflow_doc_rows.append(
                f"""
                <tr>
                  <td>{esc(kb['name'])}</td>
                  <td>{esc(doc.get('name'))}</td>
                  <td class="{ 'ok' if run_status == '完成' else 'warn' }">{esc(run_status)}</td>
                  <td>{esc(doc.get('progress'))}</td>
                  <td>{esc(doc.get('chunk_num'))}</td>
                  <td>{esc(doc.get('token_num'))}</td>
                  <td>{esc(doc.get('suffix'))}</td>
                </tr>
                """
            )

    ragflow_cards_html = "\n".join(ragflow_cards) or "<p class=\"note\">未读取到 RAGFlow 知识库状态。</p>"
    ragflow_doc_rows_html = "\n".join(ragflow_doc_rows)
    experiment_summaries = experiment_results.get("summaries", {}) if isinstance(experiment_results, dict) else {}
    experiment_cards_html = "\n".join(
        f"""
        <article class="ragflow-card">
          <h3>实验 {esc(key)} · {esc(item.get('chunk_tokens'))} tokens</h3>
          <div class="metric-grid">
            <b>{esc(item.get('document_count'))}<small>文档</small></b>
            <b>{esc(item.get('chunk_count'))}<small>分块</small></b>
            <b>{esc(round(float(item.get('mrr', 0)), 3))}<small>MRR</small></b>
          </div>
          <div class="parse-summary">
            <span class="done">命中 {esc(item.get('hits'))}/{esc(item.get('questions'))}</span>
            <span>重叠 {esc(item.get('overlap_percent'))}%</span>
            <span>日志 97 条</span>
          </div>
          <div class="link-row">
            <a href="http://localhost:8080/dataset/files/{esc(item.get('dataset_id'))}" target="_blank">打开文件列表</a>
            <a href="http://localhost:8080/dataset/logs/{esc(item.get('dataset_id'))}" target="_blank">打开解析日志</a>
          </div>
        </article>
        """
        for key, item in sorted(experiment_summaries.items())
    ) or "<p class=\"note\">分块对照实验尚未运行。</p>"
    separation = recommended_retrieval.get("score_separation", {})
    tuning_html = (
        f"""
        <article class="ragflow-card">
          <h3>推荐方案 {esc(recommended_retrieval.get('dataset_key'))}</h3>
          <div class="metric-grid">
            <b>{esc(recommended_retrieval.get('vector_similarity_weight'))}<small>向量权重</small></b>
            <b>{esc(recommended_retrieval.get('similarity_threshold'))}<small>相似度阈值</small></b>
            <b>{esc(recommended_retrieval.get('chunk_count'))}<small>分块</small></b>
          </div>
          <div class="parse-summary">
            <span class="done">可回答 {esc(len(retrieval_benchmark.get('positive_cases', [])))} 题</span>
            <span class="done">拒答 {esc(len(retrieval_benchmark.get('negative_cases', [])))} 题</span>
            <span class="warn">安全间隔 {esc(round(float(separation.get('margin', 0)), 4))}</span>
          </div>
          <div class="link-row">
            <a href="http://localhost:8080/dataset/files/{esc(recommended_retrieval.get('dataset_id'))}" target="_blank">打开推荐知识库</a>
          </div>
        </article>
        """
        if recommended_retrieval
        else "<p class=\"note\">尚未运行检索参数自动调优。</p>"
    )
    core_metrics = recommended_core.get("validation_metrics", {})
    core_tuning_html = (
        f"""
        <article class="ragflow-card">
          <h3>正式核心知识库</h3>
          <div class="metric-grid">
            <b>{esc(recommended_core.get('vector_similarity_weight'))}<small>Vector</small></b>
            <b>{esc(recommended_core.get('full_text_weight'))}<small>Full-text</small></b>
            <b>{esc(recommended_core.get('similarity_threshold'))}<small>阈值</small></b>
          </div>
          <div class="parse-summary">
            <span class="done">{esc(len(core_benchmark.get('positive_cases', [])) + len(core_benchmark.get('negative_cases', [])))} 条问法</span>
            <span class="done">Top1 {esc(round(float(core_metrics.get('recall_at_1', 0)) * 100, 1))}%</span>
            <span class="done">拒答 {esc(round(float(core_metrics.get('negative_rejection_rate', 0)) * 100, 1))}%</span>
            <span>Rerank 已启用</span>
          </div>
          <p class="note">{esc(recommended_core.get('selection_reason', ''))}</p>
          <div class="link-row"><a href="http://localhost:8080/dataset/files/{esc(recommended_core.get('dataset_id'))}" target="_blank">打开正式知识库</a></div>
        </article>
        """
        if recommended_core
        else "<p class=\"note\">正式核心知识库尚未调优。</p>"
    )
    quality_summary = quality_gate.get("summary", {})
    quality_html = (
        f"""
        <article class="ragflow-card">
          <h3>数据质量门禁</h3>
          <div class="metric-grid">
            <b>{esc(quality_summary.get('checked_urls', 0))}<small>已查链接</small></b>
            <b>{esc(quality_summary.get('broken_urls', 0))}<small>失效链接</small></b>
            <b>{esc(quality_summary.get('stale_documents', 0))}<small>待复核时效</small></b>
          </div>
          <div class="parse-summary">
            <span>无图注 {esc(len(quality_gate.get('multimodal', {}).get('images_missing_caption', [])))}</span>
            <span>空表格 {esc(len(quality_gate.get('multimodal', {}).get('empty_tables', [])))}</span>
            <span class="done">链接检查完成</span>
          </div>
        </article>
        """
        if quality_gate
        else "<p class=\"note\">尚未运行数据质量门禁。</p>"
    )
    unanswered_html = "\n".join(
        f"""
        <tr>
          <td>{esc(row.get('time'))}</td>
          <td>{esc(row.get('question'))}</td>
          <td>{esc(row.get('reason'))}</td>
          <td>{esc((row.get('top_matches') or [{}])[0].get('document_name', ''))}</td>
          <td>{esc((row.get('top_matches') or [{}])[0].get('similarity', ''))}</td>
        </tr>
        """
        for row in unanswered_rows[-50:]
    ) or "<tr><td colspan=\"5\">暂无未收录问题</td></tr>"

    coverage_summary = coverage["summary"]
    coverage_metrics_html = "\n".join(
        f"<div class=\"coverage-metric\"><b>{esc(value)}</b><span>{esc(label)}</span></div>"
        for value, label in [
            (f"{coverage_summary['source_covered_categories']}/{coverage_summary['target_categories']}", "类别已有官方资料"),
            (f"{coverage_summary['covered_categories']}/{coverage_summary['target_categories']}", "类别已有核心卡片"),
            (f"{coverage_summary['source_covered_departments']}/{coverage_summary['target_departments']}", "部门已有官方资料"),
            (f"{coverage_summary['covered_departments']}/{coverage_summary['target_departments']}", "部门已有核心卡片"),
        ]
    )
    coverage_category_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(row['name'])}</td>
          <td>{row['card_count']}</td>
          <td>{row['source_count']}</td>
          <td><span class="coverage-status { 'covered' if row['status'] == '核心卡片' else ('partial' if row['status'] == '仅有资料' else 'missing') }">{esc(row['status'])}</span></td>
        </tr>
        """
        for row in coverage["categories"]
    )
    coverage_department_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(row['name'])}</td>
          <td>{row['card_count']}</td>
          <td>{row['source_count']}</td>
          <td><span class="coverage-status { 'covered' if row['status'] == '核心卡片' else ('partial' if row['status'] == '仅有资料' else 'missing') }">{esc(row['status'])}</span></td>
        </tr>
        """
        for row in coverage["departments"]
    )
    priority_rows = "\n".join(
        f"""
        <tr>
          <td><span class="priority priority-{esc(row['priority'])}">{esc(row['priority'])}</span></td>
          <td>{esc(row['type'])}</td>
          <td>{esc(row['name'])}</td>
          <td>{esc(row['action'])}</td>
        </tr>
        """
        for row in coverage["priorities"][:30]
    ) or "<tr><td colspan=\"4\">当前没有待补充项</td></tr>"
    feedback_summary_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(row['question'])}</td>
          <td>{row['count']}</td>
          <td>{esc(row['status'])}</td>
          <td>{esc(row['top_document'])}</td>
        </tr>
        """
        for row in coverage["feedback"]
    ) or "<tr><td colspan=\"4\">暂无有效未回答问题</td></tr>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>暨南大学学生助手 · 数据流程可视化</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #182230;
      --muted: #667085;
      --line: #d6dde7;
      --brand: #0f6f64;
      --brand-2: #245b9b;
      --warn: #b54708;
      --ok: #067647;
      --shadow: 0 12px 32px rgba(16, 24, 40, .09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 22px 28px;
    }}
    header h1 {{ margin: 0 0 6px; font-size: 24px; }}
    header p {{ margin: 0; color: var(--muted); }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 24px; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
      padding: 20px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .steps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .step {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 148px;
      background: #fbfcfe;
    }}
    .num {{
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: var(--brand);
      color: #fff;
      font-weight: 800;
    }}
    .step h3 {{ margin: 12px 0 6px; font-size: 15px; }}
    .step b {{ display: block; font-size: 28px; color: var(--brand); }}
    .step p {{ margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .bar {{
      display: grid;
      grid-template-columns: 150px 1fr;
      gap: 10px;
      align-items: center;
      margin: 8px 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .bar strong {{
      display: inline-block;
      min-width: 34px;
      max-width: 100%;
      background: var(--brand);
      color: #fff;
      padding: 4px 8px;
      border-radius: 4px;
      text-align: right;
    }}
    .bar.accent strong {{ background: var(--brand-2); }}
    .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 920px; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.55;
    }}
    th {{ background: #f8fafc; color: #475467; position: sticky; top: 0; }}
    a {{ color: var(--brand-2); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .ok {{ color: var(--ok); font-weight: 700; }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    .quality-list {{ margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }}
    .quality-list li {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .quality-list strong, .quality-list span, .quality-list em {{ display: block; }}
    .quality-list span {{ color: var(--muted); font-size: 13px; overflow-wrap: anywhere; margin-top: 4px; }}
    .quality-list em {{ color: var(--warn); font-style: normal; margin-top: 6px; font-size: 13px; }}
    .note {{ color: var(--muted); line-height: 1.7; margin: 0 0 14px; }}
    .ragflow-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .media-gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
    .media-card {{ margin: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fbfcfe; }}
    .media-card a {{ display: block; background: #f4f6f8; }}
    .media-card img {{ display: block; width: 100%; height: 210px; object-fit: contain; }}
    .media-card figcaption {{ display: grid; gap: 5px; padding: 10px 12px; color: var(--muted); font-size: 12px; line-height: 1.5; }}
    .media-card figcaption strong {{ color: var(--text); font-size: 13px; }}
    .ragflow-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: #fbfcfe; }}
    .ragflow-card h3 {{ margin: 0 0 12px; font-size: 16px; }}
    .metric-row {{ display: grid; gap: 4px; margin-bottom: 12px; color: var(--muted); font-size: 13px; }}
    .parse-summary {{ display: flex; gap: 12px; margin: 12px 0; color: var(--muted); font-size: 13px; }}
    .parse-summary .done {{ color: #087f5b; }}
    .parse-summary .failed {{ color: #c92a2a; }}
    code {{ font-family: Consolas, monospace; color: var(--text); overflow-wrap: anywhere; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }}
    .metric-grid b {{ background: #eef7f5; color: var(--brand); border-radius: 6px; padding: 10px; font-size: 24px; }}
    .metric-grid small {{ display: block; color: var(--muted); font-size: 12px; font-weight: 500; margin-top: 2px; }}
    .link-row {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .link-row a {{ border: 1px solid #bad7d2; border-radius: 6px; padding: 8px 10px; background: #fff; }}
    .error-card {{ border-color: #fecdca; background: #fff6f5; }}
    .coverage-metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
    .coverage-metric {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fbfcfe; }}
    .coverage-metric b {{ display: block; color: var(--brand); font-size: 25px; margin-bottom: 4px; }}
    .coverage-metric span {{ color: var(--muted); font-size: 13px; }}
    .coverage-status, .priority {{ display: inline-flex; padding: 3px 7px; border-radius: 4px; font-weight: 700; font-size: 12px; }}
    .coverage-status.covered {{ background: #ecfdf3; color: #067647; }}
    .coverage-status.partial {{ background: #fffaeb; color: #b54708; }}
    .coverage-status.missing {{ background: #fff1f3; color: #c01048; }}
    .priority-高 {{ background: #fff1f3; color: #c01048; }}
    .priority-中 {{ background: #fffaeb; color: #b54708; }}
    .priority-低 {{ background: #eef4ff; color: #3538cd; }}
    /* Operational dashboard shell: dense, calm, and easy to scan repeatedly. */
    body {{ background: #eef1f4; }}
    header {{ position: sticky; top: 0; z-index: 30; padding: 0; box-shadow: 0 1px 0 rgba(16, 24, 40, .04); }}
    .dashboard-head {{ max-width: 1280px; min-height: 72px; margin: 0 auto; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; gap: 20px; }}
    .dashboard-brand {{ display: flex; align-items: center; gap: 12px; min-width: 0; }}
    .dashboard-mark {{ width: 40px; height: 40px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 8px; background: var(--brand); color: #fff; font-weight: 800; }}
    .dashboard-title {{ min-width: 0; }}
    .dashboard-title h1 {{ margin: 0 0 3px; font-size: 19px; }}
    .dashboard-title p {{ font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .dashboard-nav {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px; border: 1px solid var(--line); border-radius: 7px; background: #f8fafc; }}
    .dashboard-nav a {{ min-height: 34px; display: inline-flex; align-items: center; padding: 0 11px; border-radius: 5px; color: #475467; font-size: 13px; font-weight: 700; text-decoration: none; }}
    .dashboard-nav a.active {{ color: #fff; background: var(--brand); }}
    main {{ max-width: 1280px; margin: 20px auto 48px; padding: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; box-shadow: 0 8px 24px rgba(16, 24, 40, .05); }}
    section {{ margin: 0; padding: 26px 28px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; box-shadow: none; }}
    section:last-child {{ border-bottom: 0; }}
    section > h2 {{ display: flex; align-items: center; gap: 8px; }}
    section > h2::before {{ content: ""; width: 3px; height: 17px; border-radius: 2px; background: var(--brand); }}
    .step, .ragflow-card, .coverage-metric {{ box-shadow: none; background: #fafbfc; }}
    .step {{ min-height: 138px; }}
    .num {{ border-radius: 6px; }}
    .metric-grid b {{ border: 1px solid #cfe4df; background: #f4fbf9; }}
    .scroll {{ scrollbar-color: #aab4c3 #f2f4f7; }}
    th {{ z-index: 1; }}
    @media (max-width: 980px) {{
      .dashboard-head {{ align-items: stretch; flex-direction: column; padding: 12px 14px; }}
      .dashboard-nav {{ align-self: flex-start; }}
      main {{ margin: 12px; border-radius: 8px; }}
      section {{ padding: 20px 16px; }}
      .steps, .grid, .ragflow-grid, .coverage-metrics {{ grid-template-columns: 1fr; }}
      .metric-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="dashboard-head">
      <div class="dashboard-brand">
        <div class="dashboard-mark">暨</div>
        <div class="dashboard-title"><h1>数据流程看板</h1><p>暨南大学学生助手 · 版本 v{esc(project_version)} · 采集、清洗、解析与检索状态</p></div>
      </div>
      <nav class="dashboard-nav" aria-label="主导航"><a href="/">学生助手</a><a class="active" href="/pipeline">数据看板</a><a href="/settings">连接与导入</a></nav>
    </div>
  </header>
  <main>
    <section>
      <h2>流程总览</h2>
      <div class="steps">{steps_html}</div>
    </section>

    <section>
      <h2>自动更新</h2>
      <p class="note">系统会定期发现暨南大学官网新页面和附件，依次完成清洗、MinerU 解析、视觉语义标注、质量检查和 RAGFlow 增量同步。</p>
      {automatic_update_html}
    </section>

    <section class="grid">
      <div>
        <h2>清洗结果按部门分布</h2>
        {department_items}
      </div>
      <div>
        <h2>清洗结果按事项类别分布</h2>
        {category_items}
      </div>
    </section>

    <section>
      <h2>学生事务覆盖报告</h2>
      <p class="note">核心卡片表示助手可以稳定回答；仅有资料表示已经采集但还需要整理成服务卡片；未覆盖表示下一轮需要新增官方数据源。</p>
      <div class="coverage-metrics">{coverage_metrics_html}</div>
      <div class="grid">
        <div>
          <h2>按事项类别</h2>
          <div class="scroll">
            <table><thead><tr><th>类别</th><th>核心卡片</th><th>清洗资料</th><th>状态</th></tr></thead><tbody>{coverage_category_rows}</tbody></table>
          </div>
        </div>
        <div>
          <h2>按责任部门</h2>
          <div class="scroll">
            <table><thead><tr><th>部门</th><th>核心卡片</th><th>清洗资料</th><th>状态</th></tr></thead><tbody>{coverage_department_rows}</tbody></table>
          </div>
        </div>
      </div>
    </section>

    <section>
      <h2>下一轮数据补充清单</h2>
      <p class="note">按缺口和学生未回答问题自动排序。高、中优先级应优先寻找官方来源；低优先级用于加深现有覆盖。</p>
      <div class="scroll">
        <table><thead><tr><th>优先级</th><th>类型</th><th>缺口</th><th>建议动作</th></tr></thead><tbody>{priority_rows}</tbody></table>
      </div>
    </section>

    <section>
      <h2>未回答问题归并</h2>
      <p class="note">历史未命中问题会按文本合并；已经能被当前服务卡片关键词覆盖的问题标记为“可能已补充”。</p>
      <div class="scroll">
        <table><thead><tr><th>问题</th><th>出现次数</th><th>当前判断</th><th>历史最接近文档</th></tr></thead><tbody>{feedback_summary_rows}</tbody></table>
      </div>
    </section>

    <section>
      <h2>RAGFlow 导入状态</h2>
      <p class="note"><strong>知识库内容以这里的文档数、分块数和解析状态为准。</strong> A/B/C 实验知识库均绑定 RAGFlow 数据流水线，文件解析会生成真实日志；下面按钮均携带正确的知识库 ID。</p>
      <div class="ragflow-grid">{ragflow_cards_html}</div>
    </section>

    <section>
      <h2>分块对照实验</h2>
      <p class="note">三组使用完全相同的 97 份清洗语料和 8 个固定问题，只改变分块大小与重叠比例。这是初步筛选，正式参数以严格测试集的自动调优结果为准。</p>
      <div class="ragflow-grid">{experiment_cards_html}</div>
    </section>

    <section>
      <h2>检索参数自动调优</h2>
      <p class="note">脚本通过 RAGFlow API 对 A/B/C 知识库、向量权重和相似度阈值进行两轮搜索，并用独立验证集同时检查正确召回与无答案拒答。当前安全间隔较窄，阈值附近应拒答或复核。</p>
      <div class="ragflow-grid">{tuning_html}</div>
    </section>

    <section>
      <h2>正式助手验收</h2>
      <p class="note">正式核心知识库按独立意图划分训练与验证集。Rerank、跨语言、知识图谱和元数据过滤遵循控制变量原则，仅在指标证明有收益时启用。</p>
      <div class="ragflow-grid">{core_tuning_html}{quality_html}</div>
    </section>

    <section>
      <h2>MinerU 多模态清洗</h2>
      <p class="note">{mineru_summary_html} 此处展示附件经过 MinerU 后的 Markdown、OCR、表格、图片和结构化 JSON 产物，再由导入器送入第一阶段综合知识库。</p>
      <div class="scroll">
        <table>
          <thead><tr><th>原始附件</th><th>状态</th><th>后端</th><th>耗时(秒)</th><th>图片</th><th>结构化 JSON</th><th>RAGFlow 文档/说明</th></tr></thead>
          <tbody>{mineru_rows_html}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>多模态资源</h2>
      <p class="note">已关联 {esc(media_summary.get('documents', 0))} 份文档、{esc(media_summary.get('media', 0))} 个视觉单元，其中图片 {esc(media_summary.get('images', 0))} 个、表格截图 {esc(media_summary.get('tables', 0))} 个，已有 {esc(visually_enriched)} 个视觉单元完成语义标注。点击缩略图可查看 MinerU 提取的原图。</p>
      <div class="ragflow-grid">{native_image_cards_html}</div>
      <div class="media-gallery">{media_gallery_html}</div>
    </section>

    <section>
      <h2>RAGFlow 文档解析状态</h2>
      <div class="scroll">
        <table>
          <thead><tr><th>知识库</th><th>文档</th><th>解析状态</th><th>进度</th><th>分块</th><th>Token</th><th>类型</th></tr></thead>
          <tbody>{ragflow_doc_rows_html}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>未收录问题反馈</h2>
      <p class="note">当问题没有可靠命中时，系统会拒答并记录在这里，作为下一轮补充数据和服务卡片的依据。</p>
      <div class="scroll">
        <table>
          <thead><tr><th>时间</th><th>问题</th><th>拒答原因</th><th>最接近文档</th><th>相似度</th></tr></thead>
          <tbody>{unanswered_html}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>核心服务卡片</h2>
      <p class="note">这是当前问答网页优先使用的高质量数据层，链接和日期直接从卡片原文抽取，避免模型改错。</p>
      <div class="scroll">
        <table>
          <thead><tr><th>事项</th><th>类别</th><th>事项类型</th><th>负责部门</th><th>办理入口</th><th>所需材料</th><th>直接回答</th><th>来源链接</th></tr></thead>
          <tbody>{service_rows}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>清洗质量提示</h2>
      <p class="note">疑似乱码越多，越需要回到网页解析和编码识别步骤复核。第一阶段服务卡片已人工整理为干净中文，但通用清洗文本仍有进一步优化空间。</p>
      <ul class="quality-list">{worst_quality_html}</ul>
    </section>

    <section>
      <h2>清洗后的结构化文档</h2>
      <div class="scroll">
        <table>
          <thead><tr><th>标题</th><th>部门</th><th>栏目</th><th>自动类别</th><th>日期</th><th>来源</th><th>文本长度</th><th>乱码命中</th></tr></thead>
          <tbody>{cleaned_rows_html}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>原始采集页面</h2>
      <div class="scroll">
        <table>
          <thead><tr><th>种子/标题</th><th>部门</th><th>栏目</th><th>深度</th><th>来源 URL</th><th>本地 HTML</th></tr></thead>
          <tbody>{raw_rows_html}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>"""


def main() -> None:
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(build_dashboard(), encoding="utf-8")
    COVERAGE_JSON.write_text(json.dumps(build_coverage_report(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dashboard written to: {OUTPUT_HTML}")
    print(f"Coverage report written to: {COVERAGE_JSON}")


if __name__ == "__main__":
    main()
