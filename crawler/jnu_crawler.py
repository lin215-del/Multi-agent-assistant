from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "seeds.json"
RAW_DIR = ROOT / "data" / "raw"
FILES_DIR = ROOT / "data" / "files"
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"


@dataclass(frozen=True)
class QueueItem:
    url: str
    depth: int
    seed_name: str
    department: str
    category_hint: str


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def allowed_url(url: str, allowed_domains: Iterable[str], excluded_domains: Iterable[str] = ()) -> bool:
    host = urlparse(url).hostname or ""
    if any(host == domain or host.endswith("." + domain) for domain in excluded_domains):
        return False
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


def safe_name(url: str, suffix: str = ".html") -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    path = unquote(urlparse(url).path).strip("/").replace("/", "_")
    path = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", path)[:80] or "index"
    return f"{path}_{digest}{suffix}"


def is_attachment(url: str, extensions: Iterable[str]) -> bool:
    lower_path = unquote(urlparse(url).path).lower()
    return any(lower_path.endswith(ext) for ext in extensions)


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(" ", strip=True)
    h1 = soup.find(["h1", "h2", "h3"])
    return h1.get_text(" ", strip=True) if h1 else ""


def response_html(response: requests.Response) -> str:
    if response.apparent_encoding:
        response.encoding = response.apparent_encoding
    return response.text


def extract_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        links.append(normalize_url(urljoin(base_url, href)))
    return links


def download_attachment(session: requests.Session, url: str, referer: str | None = None) -> dict:
    headers = {
        "Accept": "application/msword, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/pdf, */*"
    }
    if referer:
        headers["Referer"] = referer
    response = session.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    suffix = Path(unquote(urlparse(url).path)).suffix or ".bin"
    target = FILES_DIR / safe_name(url, suffix=suffix)
    target.write_bytes(response.content)
    return {
        "url": url,
        "local_path": str(target.relative_to(ROOT)),
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type", ""),
    }


def crawl(max_pages: int, max_depth: int, max_pages_per_seed: int | None = None) -> None:
    config = load_config()
    allowed_domains = config["allowed_domains"]
    excluded_domains = config.get("excluded_domains", [])
    extensions = config["attachment_extensions"]
    rate_limit = float(config.get("rate_limit_seconds", 1.0))

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    queue: deque[QueueItem] = deque(
        QueueItem(seed["url"], 0, seed["name"], seed["department"], seed["category_hint"])
        for seed in config["seeds"]
    )
    visited: set[str] = set()
    downloaded_attachments: set[str] = set()
    pages_saved = 0
    pages_by_seed: Counter[str] = Counter()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "JNUStudentAssistantCrawler/0.1 (+student project; respectful low-rate crawl)"
        }
    )

    previous_records = []
    if MANIFEST_PATH.exists():
        for line in MANIFEST_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                previous_records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    with MANIFEST_PATH.open("w", encoding="utf-8") as manifest:
        while queue and pages_saved < max_pages:
            item = queue.popleft()
            if max_pages_per_seed and pages_by_seed[item.seed_name] >= max_pages_per_seed:
                continue
            url = normalize_url(item.url)
            if url in visited or not allowed_url(url, allowed_domains, excluded_domains):
                continue
            visited.add(url)

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                manifest.write(json.dumps({"url": url, "error": "request_failed", "detail": str(exc).replace("\n", " ")}, ensure_ascii=False) + "\n")
                continue

            content_type = response.headers.get("content-type", "")
            if is_attachment(url, extensions):
                try:
                    attachment = download_attachment(session, url)
                    manifest.write(json.dumps({"kind": "attachment", **attachment}, ensure_ascii=False) + "\n")
                except requests.RequestException as exc:
                    manifest.write(json.dumps({"url": url, "error": "request_failed", "detail": str(exc).replace("\n", " ")}, ensure_ascii=False) + "\n")
                time.sleep(rate_limit)
                continue

            html = response_html(response)
            if "text/html" not in content_type and not html.lstrip().startswith("<"):
                continue

            local_path = RAW_DIR / safe_name(url)
            local_path.write_text(html, encoding="utf-8")
            links = extract_links(url, html)
            attachments = [
                link
                for link in links
                if is_attachment(link, extensions) and allowed_url(link, allowed_domains, excluded_domains)
            ]

            manifest.write(
                json.dumps(
                    {
                        "kind": "page",
                        "url": url,
                        "title": page_title(html),
                        "local_path": str(local_path.relative_to(ROOT)),
                        "seed_name": item.seed_name,
                        "department": item.department,
                        "category_hint": item.category_hint,
                        "depth": item.depth,
                        "attachments": attachments,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            pages_saved += 1
            pages_by_seed[item.seed_name] += 1

            for attachment_url in attachments:
                if attachment_url in downloaded_attachments:
                    continue
                try:
                    attachment = download_attachment(session, attachment_url, referer=url)
                    manifest.write(json.dumps({"kind": "attachment", **attachment}, ensure_ascii=False) + "\n")
                    downloaded_attachments.add(attachment_url)
                except requests.RequestException as exc:
                    manifest.write(
                        json.dumps(
                            {
                                "url": attachment_url,
                                "error": "attachment_download_failed",
                                "detail": str(exc).replace("\n", " "),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

            if item.depth < max_depth:
                for link in links:
                    if link not in visited and allowed_url(link, allowed_domains, excluded_domains):
                        queue.append(
                            QueueItem(
                                link,
                                item.depth + 1,
                                item.seed_name,
                                item.department,
                                item.category_hint,
                            )
                        )

            time.sleep(rate_limit)

        retained = 0
        for record in previous_records:
            url = record.get("url")
            local_path = record.get("local_path")
            if not url or url in visited or not local_path or not (ROOT / local_path).exists():
                continue
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            retained += 1

    print(f"Saved {pages_saved} pages. Manifest: {MANIFEST_PATH}")
    print(f"Retained {retained} unchanged pages from the previous manifest.")
    print("Pages by seed:")
    for seed_name, count in pages_by_seed.most_common():
        print(f"  {seed_name}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl public Jinan University student-service pages.")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max-pages-per-seed", type=int)
    args = parser.parse_args()
    crawl(
        max_pages=args.max_pages,
        max_depth=args.depth,
        max_pages_per_seed=args.max_pages_per_seed,
    )


if __name__ == "__main__":
    main()
