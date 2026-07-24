from __future__ import annotations

import base64
import ipaddress
import json
import mimetypes
import os
import socket
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_BASE_ROOT = PROJECT_ROOT / "knowledge_base"
MAX_UPLOAD_FILE_BYTES = int(os.getenv("MAX_UPLOAD_FILE_BYTES", str(12 * 1024 * 1024)))
MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "10"))
ALLOW_PRIVATE_RAGFLOW = os.getenv("ALLOW_PRIVATE_RAGFLOW", "0").lower() in {"1", "true", "yes"}
ALLOWED_SUFFIXES = {
    ".csv", ".docx", ".html", ".jpeg", ".jpg", ".json", ".md", ".pdf",
    ".png", ".pptx", ".txt", ".webp", ".xlsx",
}


class WebRagflowError(ValueError):
    pass


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    if raw.endswith("/api/v1"):
        raw = raw[:-7]
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise WebRagflowError("请输入有效的 RAGFlow HTTP(S) 地址。")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise WebRagflowError("RAGFlow 地址只填写站点根地址，例如 https://ragflow.example.com。")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise WebRagflowError("远程 RAGFlow 必须使用 HTTPS，避免 API Key 明文传输。")

    if not ALLOW_PRIVATE_RAGFLOW:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
        except socket.gaierror as exc:
            raise WebRagflowError("无法解析 RAGFlow 地址，请检查域名。") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise WebRagflowError(
                    "当前公共站点不能连接 localhost 或内网 RAGFlow；请使用可公网访问的 HTTPS 地址。"
                )
    return raw


def parse_connection(payload: dict[str, Any]) -> dict[str, str]:
    connection = payload.get("connection") or {}
    if not isinstance(connection, dict):
        raise WebRagflowError("连接配置格式无效。")
    base_url = normalize_base_url(str(connection.get("base_url") or ""))
    api_key = str(connection.get("api_key") or "").strip()
    if not api_key or len(api_key) > 2048:
        raise WebRagflowError("请输入有效的 RAGFlow API Key。")
    return {
        "base_url": base_url,
        "api_key": api_key,
        "dataset_id": str(connection.get("dataset_id") or "").strip(),
        "notice_dataset_id": str(connection.get("notice_dataset_id") or "").strip(),
    }


class WebRagflowClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = f"{normalize_base_url(base_url)}/api/v1"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=(10, 120),
                allow_redirects=False,
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise WebRagflowError("无法连接 RAGFlow，请检查地址、HTTPS 和网络访问权限。") from exc
        except ValueError as exc:
            raise WebRagflowError("RAGFlow 返回了无法识别的响应。") from exc
        if payload.get("code") != 0:
            message = str(payload.get("message") or "RAGFlow 请求失败")
            raise WebRagflowError(message[:240])
        return payload.get("data")

    def list_datasets(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/datasets", params={"page": 1, "page_size": 100})
        return data if isinstance(data, list) else []

    def list_documents(self, dataset_id: str) -> dict[str, Any]:
        if not dataset_id:
            raise WebRagflowError("请先选择知识库。")
        return self.request(
            "GET",
            f"/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 100, "orderby": "create_time", "desc": True},
        )

    def upload_and_parse(self, dataset_id: str, files: list[dict[str, str]]) -> list[dict[str, Any]]:
        if not dataset_id:
            raise WebRagflowError("请先选择导入目标知识库。")
        if not files or len(files) > MAX_UPLOAD_FILES:
            raise WebRagflowError(f"每次请选择 1 至 {MAX_UPLOAD_FILES} 个文件。")

        multipart = []
        total = 0
        for item in files:
            name = Path(str(item.get("name") or "")).name
            suffix = Path(name).suffix.lower()
            if not name or suffix not in ALLOWED_SUFFIXES:
                raise WebRagflowError(f"不支持文件 {name or '未命名文件'} 的格式。")
            try:
                content = base64.b64decode(str(item.get("base64") or ""), validate=True)
            except ValueError as exc:
                raise WebRagflowError(f"文件 {name} 内容无效。") from exc
            if not content or len(content) > MAX_UPLOAD_FILE_BYTES:
                raise WebRagflowError(f"文件 {name} 为空或超过大小限制。")
            total += len(content)
            if total > MAX_UPLOAD_FILE_BYTES * 2:
                raise WebRagflowError("本次上传文件总大小超过限制。")
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            multipart.append(("file", (name, content, mime)))

        uploaded = self.request("POST", f"/datasets/{dataset_id}/documents", files=multipart)
        document_ids = [str(item.get("id")) for item in uploaded or [] if item.get("id")]
        if document_ids:
            self.request(
                "POST",
                f"/datasets/{dataset_id}/documents/parse",
                json={"document_ids": document_ids},
            )
        return uploaded or []

    def import_snapshot(
        self,
        target_dataset_id: str,
        snapshot_dataset_id: str,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> dict[str, int]:
        if not target_dataset_id:
            raise WebRagflowError("请先选择导入目标知识库。")
        rows = snapshot_documents(snapshot_dataset_id)
        current = self.list_documents(target_dataset_id)
        existing = {
            str(item.get("name") or "")
            for item in (current.get("docs", []) if isinstance(current, dict) else [])
        }
        pending = [row for row in rows if str(row.get("name") or "") not in existing]
        uploaded_count = 0
        skipped_count = len(rows) - len(pending)
        for offset in range(0, len(pending), 8):
            batch = pending[offset : offset + 8]
            multipart = []
            for row in batch:
                path = safe_snapshot_blob(str(row.get("blob_path") or ""))
                mime = str(row.get("content_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                multipart.append(("file", (str(row.get("name") or path.name), path.read_bytes(), mime)))
            uploaded = self.request("POST", f"/datasets/{target_dataset_id}/documents", files=multipart) or []
            document_ids = [str(item.get("id")) for item in uploaded if item.get("id")]
            if document_ids:
                self.request(
                    "POST",
                    f"/datasets/{target_dataset_id}/documents/parse",
                    json={"document_ids": document_ids},
                )
            uploaded_count += len(uploaded)
            if progress:
                progress(uploaded_count, skipped_count, len(rows))
        return {"uploaded": uploaded_count, "skipped": skipped_count, "total": len(rows)}


def client_from_payload(payload: dict[str, Any]) -> tuple[WebRagflowClient, dict[str, str]]:
    connection = parse_connection(payload)
    return WebRagflowClient(connection["base_url"], connection["api_key"]), connection


def snapshot_catalog() -> list[dict[str, Any]]:
    manifest_path = KNOWLEDGE_BASE_ROOT / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WebRagflowError("项目知识库快照不可用。") from exc
    return [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or "未命名快照"),
            "documents": int(item.get("documents") or 0),
            "chunks": int(item.get("chunks") or 0),
        }
        for item in manifest.get("datasets", [])
        if item.get("id")
    ]


def snapshot_documents(dataset_id: str) -> list[dict[str, Any]]:
    if dataset_id not in {item["id"] for item in snapshot_catalog()}:
        raise WebRagflowError("未找到所选项目知识库快照。")
    path = KNOWLEDGE_BASE_ROOT / "datasets" / dataset_id / "documents.jsonl"
    rows = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError) as exc:
        raise WebRagflowError("无法读取项目知识库快照。") from exc
    return rows


def safe_snapshot_blob(relative: str) -> Path:
    path = (KNOWLEDGE_BASE_ROOT / relative).resolve()
    root = KNOWLEDGE_BASE_ROOT.resolve()
    if root not in path.parents or not path.is_file():
        raise WebRagflowError("知识库快照包含无效文件路径。")
    return path
