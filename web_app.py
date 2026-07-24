from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "ragflow"))
BOOT_LOG = PROJECT_ROOT / "data" / "feedback" / "web_startup.log"


def boot_marker(message: str) -> None:
    BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BOOT_LOG.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

boot_marker("Loading core services")
from core_services import ask_core_service
boot_marker("Loading multimodal media library")
from multimodal.media_library import attach_media, public_media_library, resolve_public_file
from multimodal.query_image import analyze_query_image
from web_ragflow import WebRagflowError, client_from_payload, parse_connection, snapshot_catalog
from web_settings import SETTINGS_HTML
boot_marker("Loading pipeline dashboard")
from visualize_pipeline import build_coverage_report, build_dashboard
boot_marker("Imports ready")


HOST = os.getenv("ASSISTANT_HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", os.getenv("ASSISTANT_PORT", "8090")))
REQUIRE_BROWSER_CONNECTION = os.getenv("REQUIRE_BROWSER_CONNECTION", "0").lower() in {"1", "true", "yes"}
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(30 * 1024 * 1024)))
MAX_QUESTION_LENGTH = int(os.getenv("MAX_QUESTION_LENGTH", "300"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
REQUEST_HISTORY: dict[str, deque[float]] = defaultdict(deque)
REQUEST_LOCK = threading.Lock()
IMPORT_JOBS: dict[str, dict] = {}
IMPORT_LOCK = threading.Lock()
STARTUP_LOG = BOOT_LOG


def log(message: str) -> None:
    STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with STARTUP_LOG.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    if os.getenv("ASSISTANT_CONSOLE_LOG") == "1" and sys.stdout is not None:
        print(message)


def run_snapshot_import(job_id: str, connection: dict[str, str], snapshot_dataset_id: str) -> None:
    def progress(uploaded: int, skipped: int, total: int) -> None:
        with IMPORT_LOCK:
            IMPORT_JOBS[job_id].update(
                {"status": "running", "uploaded": uploaded, "skipped": skipped, "total": total}
            )

    try:
        from web_ragflow import WebRagflowClient

        client = WebRagflowClient(connection["base_url"], connection["api_key"])
        result = client.import_snapshot(
            connection["dataset_id"], snapshot_dataset_id, progress=progress
        )
        with IMPORT_LOCK:
            IMPORT_JOBS[job_id].update({"status": "complete", **result})
    except Exception as exc:
        log(f"snapshot import failed: {type(exc).__name__}")
        with IMPORT_LOCK:
            IMPORT_JOBS[job_id].update(
                {"status": "failed", "message": str(exc)[:240] or "项目数据导入失败。"}
            )
    finally:
        connection.clear()

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>暨南大学学生助手</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d9e0ea;
      --brand: #0f6f64;
      --brand-dark: #09544b;
      --accent: #b42318;
      --soft: #ecfdf3;
      --shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .topbar {
      max-width: 980px;
      margin: 0 auto;
      padding: 18px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: var(--brand);
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 800;
      flex: 0 0 auto;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 700;
    }
    .status {
      font-size: 13px;
      color: var(--brand-dark);
      background: var(--soft);
      border: 1px solid #b7ebc6;
      padding: 7px 10px;
      border-radius: 999px;
      white-space: nowrap;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 24px 40px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 260px;
      gap: 16px;
    }
    .workspace, .side {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .workspace { padding: 22px; }
    .side { padding: 16px; align-self: start; }
    .label {
      display: block;
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 10px;
    }
    .ask-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 112px;
      gap: 10px;
      align-items: stretch;
    }
    .photo-tools {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-top: 10px;
      min-height: 38px;
    }
    .photo-input { display: none; }
    .photo-button, .photo-remove {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--brand-dark);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    .photo-button:hover, .photo-remove:hover { border-color: #88bdb5; background: #f4fbf9; }
    .photo-remove { display: none; }
    .photo-preview {
      display: none;
      width: 46px;
      height: 46px;
      object-fit: cover;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .photo-note { flex: 1 1 260px; min-width: 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
    .image-analysis {
      margin: 0 0 14px;
      padding: 10px 12px;
      border-left: 3px solid var(--brand);
      background: #f4fbf9;
      color: #344054;
      font-size: 13px;
      line-height: 1.6;
    }
    input {
      width: 100%;
      min-width: 0;
      border: 1px solid #b8c2d0;
      border-radius: 6px;
      padding: 13px 14px;
      font-size: 16px;
      color: var(--text);
      background: #fff;
      outline: none;
    }
    input:focus {
      border-color: var(--brand);
      box-shadow: 0 0 0 3px rgba(15, 111, 100, 0.14);
    }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--brand);
      color: #fff;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: var(--brand-dark); }
    button:disabled { opacity: .65; cursor: wait; }
    .answer {
      margin-top: 20px;
      border-top: 1px solid var(--line);
      padding-top: 20px;
    }
    .answer h2, .side h2 {
      margin: 0 0 12px;
      font-size: 16px;
    }
    .answer-text {
      font-size: 18px;
      line-height: 1.7;
      margin: 0 0 16px;
    }
    .meta {
      display: none;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }
    .meta a {
      color: var(--brand-dark);
      overflow-wrap: anywhere;
    }
    .chips {
      display: grid;
      gap: 8px;
      margin-bottom: 16px;
    }
    .chip {
      border: 1px solid #c8d2df;
      background: #fff;
      color: var(--text);
      padding: 9px 10px;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
    }
    .matches {
      margin-top: 18px;
      display: grid;
      gap: 10px;
    }
    .match {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 11px 12px;
      background: #fbfcfe;
      font-size: 13px;
      color: var(--muted);
    }
    .match strong {
      display: block;
      color: var(--text);
      font-size: 14px;
      margin-bottom: 4px;
    }
    .empty {
      color: var(--muted);
      line-height: 1.7;
      margin: 0;
    }
    .error { color: var(--accent); }
    .guardrail {
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px solid #fecdca;
      border-radius: 6px;
      background: #fff6f5;
      color: #912018;
      font-size: 14px;
      line-height: 1.6;
    }
    .primary-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 0 14px;
      border-radius: 6px;
      background: var(--brand);
      color: #fff;
      font-weight: 700;
      text-decoration: none;
      margin-bottom: 12px;
    }
    .primary-link:hover { background: var(--brand-dark); text-decoration: none; }
    .action-links { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .action-links .primary-link { margin-bottom: 0; }
    .source-link {
      display: inline-flex;
      align-items: center;
      min-height: 40px;
      padding: 0 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--brand-dark);
      font-weight: 700;
    }
    .mini-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
    }
    .mini-meta span {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      background: #fff;
    }
    .result-count {
      margin-left: 8px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 500;
    }
    .related-results {
      margin-top: 18px;
      border-top: 1px solid var(--line);
    }
    .related-results h3 {
      margin: 16px 0 4px;
      font-size: 16px;
    }
    .related-item {
      padding: 14px 0;
      border-bottom: 1px solid var(--line);
    }
    .related-item:last-child { border-bottom: 0; }
    .related-item h4 { margin: 0 0 6px; font-size: 16px; }
    .related-item p { margin: 0 0 9px; color: var(--text); line-height: 1.65; }
    .related-meta { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
    .related-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .related-actions a {
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--brand-dark);
      font-size: 13px;
      font-weight: 700;
    }
    .media-block { margin: 16px 0; }
    .media-block h3 { margin: 0 0 10px; font-size: 16px; }
    .media-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }
    .media-item {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #fff;
    }
    .media-item a { display: block; color: inherit; text-decoration: none; }
    .media-item img {
      display: block;
      width: 100%;
      height: 180px;
      object-fit: contain;
      background: #f7f8fa;
    }
    .media-item figcaption {
      padding: 9px 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    details {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      margin-top: 10px;
    }
    summary {
      cursor: pointer;
      padding: 12px;
      font-weight: 700;
      color: var(--text);
    }
    .guide-card {
      margin: 0;
      border: 1px solid var(--line);
      border-width: 1px 0 0;
      border-radius: 0;
      background: #fbfcfe;
      overflow: hidden;
    }
    .guide-head {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 8px;
      border-radius: 999px;
      background: #eef7f5;
      color: var(--brand-dark);
      font-size: 13px;
      font-weight: 700;
    }
    .guide-body {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
    }
    .guide-field {
      padding: 12px;
      border-bottom: 1px solid var(--line);
      min-width: 0;
    }
    .guide-field:nth-child(odd) {
      border-right: 1px solid var(--line);
    }
    .guide-field strong {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 5px;
    }
    .guide-field span {
      display: block;
      line-height: 1.6;
      overflow-wrap: anywhere;
    }
    .guide-list {
      grid-column: 1 / -1;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .guide-list strong {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 7px;
    }
    .guide-list ol, .guide-list ul {
      margin: 0;
      padding-left: 20px;
      line-height: 1.75;
    }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; padding: 18px 14px 30px; }
      .topbar { padding: 14px; align-items: flex-start; flex-direction: column; }
      .ask-row { grid-template-columns: 1fr; }
      button { min-height: 46px; }
      .guide-body { grid-template-columns: 1fr; }
      .guide-field:nth-child(odd) { border-right: 0; }
    }
    /* Public-facing shell: compact navigation, stable search, and readable results. */
    body { background: #f2f4f7; }
    header { position: sticky; top: 0; z-index: 20; box-shadow: 0 1px 0 rgba(16, 24, 40, .03); }
    .topbar { max-width: 1180px; min-height: 68px; padding: 12px 24px; }
    .mark { width: 40px; height: 40px; }
    .brand-copy { display: grid; gap: 2px; min-width: 0; }
    .brand-copy small { color: var(--muted); font-size: 12px; }
    .top-actions { display: flex; align-items: center; gap: 10px; }
    .nav { display: inline-flex; align-items: center; gap: 4px; padding: 3px; border: 1px solid var(--line); border-radius: 7px; background: #f8fafc; }
    .nav a { min-height: 34px; display: inline-flex; align-items: center; padding: 0 11px; border-radius: 5px; color: #475467; font-size: 13px; font-weight: 700; text-decoration: none; }
    .nav a.active { color: #fff; background: var(--brand); }
    .status { position: relative; padding: 7px 10px 7px 24px; border-radius: 6px; }
    .status::before { content: ""; position: absolute; left: 10px; top: 50%; width: 7px; height: 7px; border-radius: 50%; background: #12b76a; transform: translateY(-50%); }
    main { max-width: 1180px; padding: 32px 24px 52px; grid-template-columns: minmax(0, 1fr) 280px; gap: 0; }
    .workspace { min-height: 590px; padding: 28px; border-radius: 8px 0 0 8px; box-shadow: 0 8px 24px rgba(16, 24, 40, .05); }
    .side { min-height: 590px; padding: 28px 22px; border-left: 0; border-radius: 0 8px 8px 0; box-shadow: 0 8px 24px rgba(16, 24, 40, .05); }
    .section-kicker { margin: 0 0 6px; color: var(--brand-dark); font-size: 13px; font-weight: 700; }
    .query-title { margin: 0 0 6px; font-size: 22px; line-height: 1.35; }
    .query-copy { margin: 0 0 22px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .label { font-weight: 700; color: #344054; }
    .ask-row { grid-template-columns: minmax(0, 1fr) 104px; }
    input { min-height: 50px; padding: 13px 16px; border-color: #aeb9c8; }
    button { min-height: 50px; transition: background .15s ease, box-shadow .15s ease, transform .15s ease; }
    button:hover { box-shadow: 0 4px 10px rgba(15, 111, 100, .18); }
    button:active { transform: translateY(1px); }
    .answer { margin-top: 26px; padding-top: 24px; }
    .answer h2 { font-size: 18px; }
    .answer-text { max-width: 760px; font-size: 17px; }
    .side h2 { font-size: 15px; }
    .chips { gap: 7px; }
    .chip { min-height: 0; width: 100%; text-align: left; line-height: 1.45; font-weight: 500; box-shadow: none; }
    .chip:hover { color: var(--brand-dark); border-color: #88bdb5; background: #f4fbf9; box-shadow: none; }
    .side-note { padding-top: 14px; border-top: 1px solid var(--line); font-size: 12px; }
    .media-item img { aspect-ratio: 4 / 3; height: auto; min-height: 150px; }
    .guardrail { border-left: 3px solid var(--accent); }
    @media (max-width: 820px) {
      html, body { max-width: 100%; overflow-x: hidden; }
      .topbar { align-items: stretch; flex-direction: column; gap: 10px; }
      .top-actions { justify-content: space-between; }
      .status { display: none; }
      main { width: 100%; min-width: 0; grid-template-columns: minmax(0, 1fr); padding: 16px 12px 32px; }
      .workspace { width: 100%; min-width: 0; min-height: auto; padding: 20px 16px; border-radius: 8px 8px 0 0; }
      .side { width: 100%; min-width: 0; min-height: auto; padding: 20px 16px; border-top: 0; border-left: 1px solid var(--line); border-radius: 0 0 8px 8px; }
      .query-title { font-size: 20px; }
      .ask-row { grid-template-columns: 1fr; }
      .photo-tools { display: grid; grid-template-columns: auto minmax(0, 1fr); }
      .photo-note { overflow-wrap: anywhere; }
      .media-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <div class="mark">暨</div>
        <div class="brand-copy"><h1>暨南大学学生助手</h1><small>学生事务与官方材料检索</small></div>
      </div>
      <div class="top-actions">
        <nav class="nav" aria-label="主导航"><a class="active" href="/">学生助手</a><a href="/pipeline">数据看板</a><a href="/settings">连接与导入</a></nav>
        <div class="status" id="kb-status">知识库连接</div>
      </div>
    </div>
  </header>
  <main>
    <section class="workspace">
      <p class="section-kicker">学生事务查询</p>
      <h2 class="query-title">需要办理什么事情？</h2>
      <p class="query-copy">输入事项名称或具体问题，助手会返回官方说明、附件下载和相关图片。</p>
      <label class="label" for="question">输入学生办事问题</label>
      <div class="ask-row">
        <input id="question" autocomplete="off" value="本科生请假申请表在哪里下载？" />
        <button id="askBtn">查询</button>
      </div>
      <div class="photo-tools">
        <label class="photo-button" for="photoInput">添加照片</label>
        <input class="photo-input" id="photoInput" type="file" accept="image/jpeg,image/png,image/webp" />
        <img class="photo-preview" id="photoPreview" alt="待识别照片预览" />
        <button class="photo-remove" id="photoRemove" type="button">移除</button>
        <span class="photo-note">支持 JPG、PNG、WebP，最大 6 MB。照片不在本系统保存，请先遮挡个人信息。</span>
      </div>
      <div class="answer" id="answer">
        <p class="empty">可查询请假申请表、转专业申请表、成绩单和在学证明、新生入学资格申请表等第一批服务材料。</p>
      </div>
    </section>
    <aside class="side">
      <h2>推荐问题</h2>
      <div class="chips" id="examples">
        <button type="button" class="chip">本科生请假申请表在哪里下载？</button>
        <button type="button" class="chip">转专业申请表在哪里？</button>
        <button type="button" class="chip">成绩单和在学证明怎么打印？</button>
        <button type="button" class="chip">学生证遗失怎么补办？</button>
        <button type="button" class="chip">新生保留入学资格申请表在哪里下载？</button>
        <button type="button" class="chip">推免申请报名怎么操作？</button>
      </div>
      <p class="empty side-note">答案仅依据已收录的官方材料；缺少可靠依据时会明确拒答并记录数据缺口。</p>
    </aside>
  </main>
  <script>
    const input = document.querySelector("#question");
    const button = document.querySelector("#askBtn");
    const answer = document.querySelector("#answer");
    const photoInput = document.querySelector("#photoInput");
    const photoPreview = document.querySelector("#photoPreview");
    const photoRemove = document.querySelector("#photoRemove");
    let selectedImage = null;
    function browserConnection() {
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem("jnu-ragflow-connection") || "{}"); } catch {}
      const apiKey = sessionStorage.getItem("jnu-ragflow-api-key") || localStorage.getItem("jnu-ragflow-api-key") || "";
      return saved.base_url && apiKey ? { ...saved, api_key: apiKey } : null;
    }
    const activeConnection = browserConnection();
    const kbStatus = document.querySelector("#kb-status");
    if (kbStatus) kbStatus.textContent = activeConnection ? "个人知识库已配置" : "请先配置知识库";

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
      }[char]));
    }

    function render(data) {
      const guide = data.guide || {};
      const imageAnalysis = data.image_analysis || {};
      const imageAnalysisBlock = data.query_mode === "image" ? `
        <div class="image-analysis">
          <strong>照片识别</strong> ${escapeHtml(imageAnalysis.description || "已提取图片中的检索线索。")}
          ${imageAnalysis.intent ? `<div>识别事项：${escapeHtml(imageAnalysis.intent)}</div>` : ""}
          ${imageAnalysis.warning ? `<div>识别提示：${escapeHtml(imageAnalysis.warning)}</div>` : ""}
        </div>
      ` : "";
      const downloads = (data.downloads || []).map(item => `
        <a class="primary-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">直接下载：${escapeHtml(item.name)}</a>
      `).join("");
      const sourceIsDownload = (data.downloads || []).some(item => item.url === data.source_url);
      const source = data.source_url && !sourceIsDownload
        ? `<a class="source-link" href="${escapeHtml(data.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(data.source_label || "查看官方说明")}</a>`
        : "";
      const actions = downloads || source ? `<div class="action-links">${downloads}${source}</div>` : "";
      const mediaItems = (data.media || []).map(item => `
        <figure class="media-item">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">
            <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.caption || "文档图片")}" loading="lazy" />
            <figcaption>${escapeHtml(item.caption || "文档图片")}${item.page ? ` · 第 ${Number(item.page)} 页` : ""}</figcaption>
          </a>
        </figure>
      `).join("");
      const mediaBlock = data.ok && mediaItems ? `
        <section class="media-block"><h3>相关图片</h3><div class="media-grid">${mediaItems}</div></section>
      ` : "";
      const miniMeta = data.ok ? `
        <div class="mini-meta">
          ${guide.service_type ? `<span>${escapeHtml(guide.service_type)}</span>` : ""}
          ${guide.department ? `<span>${escapeHtml(guide.department)}</span>` : ""}
          ${guide.materials ? `<span>${escapeHtml(guide.materials)}</span>` : ""}
        </div>
      ` : "";
      const relatedMatches = (data.matches || []).filter(item =>
        item.document_name &&
        item.document_name !== data.document_name &&
        Number(item.similarity || 0) >= Number(data.threshold || 0)
      );
      const relatedItems = relatedMatches.map(item => {
        const itemDownloads = (item.downloads || []).map(download => `
          <a href="${escapeHtml(download.url)}" target="_blank" rel="noreferrer">直接下载：${escapeHtml(download.name)}</a>
        `).join("");
        const itemSource = item.source_url
          ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_label || "查看官方说明")}</a>`
          : "";
        const itemMedia = (item.media || []).slice(0, 2).map(medium => `
          <figure class="media-item"><a href="${escapeHtml(medium.url)}" target="_blank" rel="noreferrer">
            <img src="${escapeHtml(medium.url)}" alt="${escapeHtml(medium.caption || "文档图片")}" loading="lazy" />
            <figcaption>${escapeHtml(medium.caption || "文档图片")}</figcaption>
          </a></figure>
        `).join("");
        return `
          <article class="related-item">
            <h4>${escapeHtml((item.document_name || "相关结果").replace(/\.md$/i, ""))}</h4>
            <div class="related-meta">相关度 ${Number(item.similarity || 0).toFixed(3)}</div>
            <p>${escapeHtml(item.answer || item.snippet || "")}</p>
            <div class="related-actions">${itemDownloads}${itemSource}</div>
            ${itemMedia ? `<div class="media-grid">${itemMedia}</div>` : ""}
          </article>
        `;
      }).join("");
      const relatedResults = data.ok && relatedItems ? `
        <section class="related-results">
          <h3>其他相关结果</h3>
          ${relatedItems}
        </section>
      ` : "";
      const visibleResultCount = data.ok ? 1 + relatedMatches.length : 0;
      const matches = (data.matches || []).map(item => `
        <div class="match">
          <strong>${escapeHtml(item.document_name || "未命名文档")} · 相似度 ${Number(item.similarity || 0).toFixed(3)}</strong>
          <div>${escapeHtml(item.snippet || item.answer || "")}</div>
        </div>
      `).join("");
      const guardrail = data.ok ? "" : `
        <div class="guardrail">
          未提供答案的问题已记录为待补充数据。当前最低可信相似度阈值：${Number(data.threshold || 0).toFixed(2)}
        </div>
      `;
      const steps = (guide.steps || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
      const notes = (guide.notes || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
      const guideCard = data.ok ? `
        <details>
          <summary>查看办事细节</summary>
          <div class="guide-card">
            <div class="guide-body">
              <div class="guide-field"><strong>适用对象</strong><span>${escapeHtml(guide.audience || "当前知识库暂未收录")}</span></div>
              <div class="guide-field"><strong>办理入口</strong><span>${escapeHtml(guide.entrance || "当前知识库暂未收录")}</span></div>
              <div class="guide-field"><strong>所需材料</strong><span>${escapeHtml(guide.materials || "当前知识库暂未收录")}</span></div>
              <div class="guide-field"><strong>负责部门</strong><span>${escapeHtml(guide.department || "当前知识库暂未收录")}</span></div>
              <div class="guide-list"><strong>办理步骤</strong><ol>${steps || "<li>当前知识库暂未收录具体流程，请以来源页面为准。</li>"}</ol></div>
              <div class="guide-list"><strong>注意事项</strong><ul>${notes || "<li>当前知识库暂未收录具体注意事项，请以来源页面为准。</li>"}</ul></div>
              <div class="guide-list"><strong>检索依据</strong><div>命中文档：${escapeHtml(data.document_name || "无")} · 相似度 ${Number(data.similarity || 0).toFixed(3)}</div></div>
            </div>
          </div>
        </details>
      ` : "";
      const matchDetails = data.ok && matches ? `
        <details>
          <summary>查看匹配片段</summary>
          <div class="matches">${matches}</div>
        </details>
      ` : "";
      answer.innerHTML = `
        <h2>回答${visibleResultCount > 1 ? `<span class="result-count">找到 ${visibleResultCount} 个相关结果</span>` : ""}</h2>
        ${imageAnalysisBlock}
        <p class="answer-text ${data.ok ? "" : "error"}">${escapeHtml(data.answer)}</p>
        ${guardrail}
        ${actions}
        ${mediaBlock}
        ${miniMeta}
        ${relatedResults}
        ${guideCard}
        ${matchDetails}
      `;
    }

    async function ask() {
      const question = input.value.trim();
      if (!question && !selectedImage) {
        input.focus();
        return;
      }
      button.disabled = true;
      button.textContent = "查询中";
      answer.innerHTML = `<p class="empty">${selectedImage ? "正在识别照片并检索知识库..." : "正在检索知识库..."}</p>`;
      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            image_base64: selectedImage ? selectedImage.base64 : "",
            image_mime: selectedImage ? selectedImage.mime : "",
            connection: browserConnection()
          })
        });
        const data = await response.json();
        render(data);
      } catch (error) {
        answer.innerHTML = `<p class="empty error">查询失败，请确认 Docker 和 RAGFlow 正在运行。</p>`;
      } finally {
        button.disabled = false;
        button.textContent = "查询";
      }
    }

    button.addEventListener("click", ask);
    photoInput.addEventListener("change", () => {
      const file = photoInput.files && photoInput.files[0];
      if (!file) return;
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 6 * 1024 * 1024) {
        selectedImage = null;
        photoInput.value = "";
        answer.innerHTML = `<p class="empty error">请选择不超过 6 MB 的 JPG、PNG 或 WebP 图片。</p>`;
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const value = String(reader.result || "");
        selectedImage = { mime: file.type, base64: value.split(",", 2)[1] || "" };
        photoPreview.src = value;
        photoPreview.style.display = "block";
        photoRemove.style.display = "inline-flex";
      };
      reader.readAsDataURL(file);
    });
    photoRemove.addEventListener("click", () => {
      selectedImage = null;
      photoInput.value = "";
      photoPreview.removeAttribute("src");
      photoPreview.style.display = "none";
      photoRemove.style.display = "none";
    });
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") ask();
    });
    document.querySelector("#examples").addEventListener("click", event => {
      if (!event.target.classList.contains("chip")) return;
      input.value = event.target.textContent;
      ask();
    });
  </script>
</body>
</html>
"""


class StudentAssistantHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        log(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def rate_limited(self) -> bool:
        now = time.monotonic()
        client = self.client_address[0]
        with REQUEST_LOCK:
            history = REQUEST_HISTORY[client]
            while history and now - history[0] > RATE_LIMIT_WINDOW:
                history.popleft()
            if len(history) >= RATE_LIMIT_REQUESTS:
                return True
            history.append(now)
        return False

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self.send_json({"status": "ok"})
            return
        if path == "/api/coverage":
            self.send_json(build_coverage_report())
            return
        if path == "/api/media-index":
            self.send_json(public_media_library())
            return
        if path == "/api/ragflow/snapshots":
            self.send_json({"ok": True, "snapshots": snapshot_catalog()})
            return
        if path.startswith(("/media/", "/multimodal-source/")):
            resolved = resolve_public_file(path)
            if not resolved:
                self.send_error(404)
                return
            file_path, mime_type = resolved
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'inline; filename="{file_path.name}"')
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/pipeline":
            body = build_dashboard().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/settings":
            body = SETTINGS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {
            "/api/ask",
            "/api/ragflow/connect",
            "/api/ragflow/documents",
            "/api/ragflow/upload",
            "/api/ragflow/import-snapshot",
            "/api/ragflow/import-status",
        }:
            self.send_error(404)
            return

        if self.rate_limited():
            self.send_json({"ok": False, "answer": "请求过于频繁，请稍后再试。"}, status=429)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_json({"ok": False, "answer": "请求内容无效或过长。"}, status=413)
            return
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if path.startswith("/api/ragflow/"):
                if path == "/api/ragflow/import-status":
                    job_id = str(payload.get("job_id") or "")
                    with IMPORT_LOCK:
                        job = dict(IMPORT_JOBS.get(job_id) or {})
                    if not job:
                        raise WebRagflowError("未找到导入任务。")
                    self.send_json({"ok": True, "job": job})
                    return
                client, connection = client_from_payload(payload)
                if path == "/api/ragflow/connect":
                    datasets = [
                        {
                            "id": str(item.get("id") or ""),
                            "name": str(item.get("name") or "未命名知识库"),
                            "document_count": int(item.get("document_count") or 0),
                            "chunk_count": int(item.get("chunk_count") or 0),
                        }
                        for item in client.list_datasets()
                    ]
                    self.send_json({"ok": True, "datasets": datasets})
                    return
                if path == "/api/ragflow/documents":
                    data = client.list_documents(connection["dataset_id"])
                    documents = data.get("docs", []) if isinstance(data, dict) else []
                    self.send_json({"ok": True, "documents": documents, "total": len(documents)})
                    return
                if path == "/api/ragflow/import-snapshot":
                    if not connection["dataset_id"]:
                        raise WebRagflowError("请先选择导入目标知识库。")
                    snapshot_dataset_id = str(payload.get("snapshot_dataset_id") or "")
                    if snapshot_dataset_id not in {item["id"] for item in snapshot_catalog()}:
                        raise WebRagflowError("请选择有效的项目知识库快照。")
                    job_id = uuid.uuid4().hex
                    with IMPORT_LOCK:
                        IMPORT_JOBS[job_id] = {
                            "status": "queued",
                            "uploaded": 0,
                            "skipped": 0,
                            "total": next(
                                item["documents"]
                                for item in snapshot_catalog()
                                if item["id"] == snapshot_dataset_id
                            ),
                        }
                    threading.Thread(
                        target=run_snapshot_import,
                        args=(job_id, dict(connection), snapshot_dataset_id),
                        daemon=True,
                    ).start()
                    self.send_json({"ok": True, "job_id": job_id})
                    return
                uploaded = client.upload_and_parse(connection["dataset_id"], payload.get("files") or [])
                self.send_json(
                    {
                        "ok": True,
                        "uploaded": [
                            {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
                            for item in uploaded
                        ],
                    }
                )
                return
            if REQUIRE_BROWSER_CONNECTION and not payload.get("connection"):
                self.send_json(
                    {"ok": False, "answer": "请先打开“连接与导入”配置 RAGFlow。"},
                    status=400,
                )
                return
            question = str(payload.get("question", "")).strip()
            image_base64 = str(payload.get("image_base64", "")).strip()
            image_mime = str(payload.get("image_mime", "")).strip().lower()
            if (not question and not image_base64) or len(question) > MAX_QUESTION_LENGTH:
                self.send_json({"ok": False, "answer": "请输入问题或选择照片，文字不能超过 300 个字符。"}, status=400)
                return
            image_analysis = None
            retrieval_question = question
            if image_base64:
                image_analysis = analyze_query_image(image_base64, image_mime, question)
                retrieval_parts = [
                    question,
                    image_analysis.get("retrieval_query", ""),
                    image_analysis.get("intent", ""),
                    image_analysis.get("visible_text", ""),
                ]
                retrieval_question = "\n".join(part for part in retrieval_parts if part).strip()
            connection = parse_connection(payload) if payload.get("connection") else None
            result = attach_media(ask_core_service(retrieval_question, connection), retrieval_question)
            if image_analysis:
                result["query_mode"] = "image"
                result["image_analysis"] = {
                    "description": image_analysis.get("description", ""),
                    "intent": image_analysis.get("intent", ""),
                    "warning": image_analysis.get("warning", ""),
                }
        except WebRagflowError as exc:
            self.send_json({"ok": False, "message": str(exc), "answer": str(exc)}, status=400)
            return
        except ValueError as exc:
            message = str(exc)
            if not message.startswith(("仅支持", "图片", "无法读取")):
                message = "请求格式无效。"
            self.send_json({"ok": False, "answer": message}, status=400)
            return
        except Exception as exc:
            log(f"ask failed: {type(exc).__name__}: {exc}")
            self.send_json(
                {
                    "ok": False,
                    "answer": "查询暂时失败，请稍后重试。",
                    "source_url": "",
                    "document_name": "",
                    "similarity": 0,
                    "matches": [],
                },
                status=500,
            )
            return
        self.send_json(result)


def main() -> None:
    try:
        log(f"Starting student assistant on {HOST}:{PORT}")
        server = ThreadingHTTPServer((HOST, PORT), StudentAssistantHandler)
        log(f"Student assistant is running at http://{HOST}:{PORT}")
        server.serve_forever()
    except Exception:
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
