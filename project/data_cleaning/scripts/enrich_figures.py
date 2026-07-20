"""用 VLM（视觉大模型）给 MinerU 抽的图生成 description，升级 figures.json 的 caption。

复用组员 enrich_visual_units.py 的 VLM 调用思路（SiliconFlow Qwen3-VL），适配我们的
figures 结构。让 RAGFlow 检索命中图的真实内容（VLM 描述），而不是粗的上文标题 caption。

流程：读 figures.json → 找图 → VLM 生成 description → 更新 caption（sha256 缓存，图没变不重跑）。
"""
import os
import re
import json
import base64
import hashlib
import mimetypes
import argparse
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # project/
ENV_PATH = PROJECT_ROOT / ".env"
MINERU_OUTPUT = PROJECT_ROOT / "data_cleaning" / "mineru_output"
CACHE_PATH = MINERU_OUTPUT / "vlm_cache.json"
DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"


def load_env():
    """读 project/.env 的 SiliconFlow 配置（UTF-8，避开 Windows GBK 坑）。"""
    vals = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    key = vals.get("SILICONFLOW_API_KEY") or os.environ.get("SILICONFLOW_API_KEY", "")
    base = vals.get("SILICONFLOW_API_BASE") or os.environ.get("SILICONFLOW_API_BASE", DEFAULT_API_BASE)
    model = vals.get("VISUAL_MODEL") or os.environ.get("VISUAL_MODEL", DEFAULT_MODEL)
    return key, base, model


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_vlm_json(content):
    """从 VLM 响应解析 JSON（处理 ```json fence）。失败返回空 dict。"""
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    candidate = fenced.group(1) if fenced else content[content.find("{"):content.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {}


def enrich_figure(figure, image_path, api_key, api_base, model, timeout=180):
    """base64 图 → Qwen3-VL → description（拼成检索友好的 caption 替换原 caption）。"""
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    prompt = (
        "你正在为暨南大学学生事务知识库描述一张图。\n"
        f"原有图注：{figure.get('caption', '') or '无'}\n"
        f"附近正文：{figure.get('context', '') or '无'}\n\n"
        "请只根据图片中确实可见的信息，输出一个 JSON 对象：\n"
        "description：1-3句准确说明图片展示了什么；\n"
        "visible_text：对学生检索有价值的界面文字、表头或字段，无法辨认则留空；\n"
        "retrieval_keywords：5-12个适合中文检索的关键词数组。\n"
        "不得猜测被遮挡内容，不得抄录密码、二维码、身份证号、手机号等敏感信息。只输出 JSON。"
    )
    resp = requests.post(
        api_base.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]}], "temperature": 0.1, "max_tokens": 600},
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    result = parse_vlm_json(content)
    desc = (result.get("description") or "").strip()
    if not desc:
        raise RuntimeError("VLM 返回空 description")
    parts = [desc]
    vt = result.get("visible_text")
    if vt:
        if isinstance(vt, list):
            vt = " ".join(str(x) for x in vt)
        parts.append("图中文字：" + str(vt))
    kw = result.get("retrieval_keywords")
    if kw:
        if isinstance(kw, str):
            kw = [kw]
        parts.append("检索词：" + "、".join(str(x) for x in kw))
    return "\n".join(parts)


def find_image_for_figure(figure, image_dir):
    """figure.path = 'images/xxx.jpg'（MinerU 相对），图实际在 image_dir/xxx.jpg。"""
    name = os.path.basename(figure.get("path", ""))
    if not name:
        return None
    p = Path(image_dir) / name
    return p if p.is_file() else None


def enrich_figures_file(figures_json, image_dir, api_key, api_base, model, cache, refresh=False):
    """读 figures.json + 找图 + VLM enrich + 写回。返回 enrich 数。"""
    figures = json.loads(Path(figures_json).read_text(encoding="utf-8"))
    count = 0
    for fig in figures:
        img = find_image_for_figure(fig, image_dir)
        if not img:
            print("  跳过（找不到图）：", fig.get("path"), flush=True)
            continue
        sha = file_sha256(img)
        if not refresh and cache.get(sha):
            fig["caption"] = cache[sha]
            continue
        try:
            fig["caption"] = enrich_figure(fig, img, api_key, api_base, model)
            cache[sha] = fig["caption"]
            count += 1
            print("  [OK] 图", fig.get("n"), ":", fig["caption"][:40].replace("\n", " "), flush=True)
        except Exception as e:
            print("  [FAIL] 图", fig.get("n"), ":", type(e).__name__, str(e)[:80], flush=True)
    Path(figures_json).write_text(json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8")
    return count


def main():
    ap = argparse.ArgumentParser(description="VLM 给 figures.json 的图生成 description，升级 caption")
    ap.add_argument("--out-dir", help="clean_pdf 输出目录（含 <name>_figures.json + images/<name>/）。不指定则扫描 verify_*/")
    ap.add_argument("--refresh", action="store_true", help="强制重跑（忽略缓存）")
    args = ap.parse_args()

    key, base, model = load_env()
    if not key:
        raise SystemExit("SILICONFLOW_API_KEY 未配置（填 .env）")
    print("VLM:", model, "@", base, flush=True)

    cache = {}
    if CACHE_PATH.exists() and not args.refresh:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    if args.out_dir:
        targets = [Path(args.out_dir)]
    else:
        targets = [MINERU_OUTPUT / d for d in os.listdir(MINERU_OUTPUT)
                   if d.startswith("verify_") and (MINERU_OUTPUT / d).is_dir()]

    total = 0
    for out_dir in targets:
        for fj in sorted(out_dir.glob("*_figures.json")):
            stem = fj.name[:-len("_figures.json")]
            image_dir = out_dir / "images" / stem
            if not image_dir.is_dir():
                continue
            print("===", fj.name, flush=True)
            total += enrich_figures_file(fj, image_dir, key, base, model, cache, args.refresh)
            CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print("完成，共 enrich", total, "张图", flush=True)


if __name__ == "__main__":
    main()
