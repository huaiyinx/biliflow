"""
Cloud AI Watch provider execution.

This layer only sends public image URLs to cloud visual models. The VPS does not
download video files, extract frames, or run local OCR here.
"""
from __future__ import annotations

import time
from typing import Any, Literal
from urllib.parse import urlparse

import requests

from config import config
from provider_registry import recommended_models


TaskName = Literal["ocr", "vision"]


DEFAULT_PROMPTS: dict[TaskName, str] = {
    "ocr": (
        "请识别图片里的中文/英文文字，保留层级、标题、列表和关键数字。"
        "如果像课程截图，请输出适合整理进学习笔记的 Markdown。"
    ),
    "vision": (
        "请理解这张课程或职场学习截图，提取画面中的主题、关键概念、"
        "可执行步骤和可能需要补充解释的点，输出 Markdown。"
    ),
}


class AIWatchProviderError(RuntimeError):
    """Raised when all provider attempts fail."""

    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def _assert_image_source(image_url: str) -> str:
    value = (image_url or "").strip()
    if value.startswith("data:image/") and ";base64," in value[:80]:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("image_url 必须是 http/https 图片地址或 data:image base64")
    return value


def _provider_settings(provider: str) -> tuple[str, str, dict[str, str]]:
    if provider == "siliconflow":
        api_key = config.SILICONFLOW_VISUAL_KEY or config.SF_KEY
        headers = {"Authorization": f"Bearer {api_key}"}
        return config.SF_BASE.rstrip("/"), api_key, headers

    if provider == "openrouter":
        api_key = config.OPENROUTER_KEY
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": f"https://{config.DOMAIN}",
            "X-Title": "BiliFlow AI Watch",
        }
        return config.OPENROUTER_BASE.rstrip("/"), api_key, headers

    raise ValueError(f"暂不支持 provider: {provider}")


def _chat_completion(
    *,
    base_url: str,
    headers: dict[str, str],
    model: str,
    image_url: str,
    prompt: str,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "temperature": 0.2,
        "max_tokens": 1400,
    }
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )
    if not str(content).strip():
        raise RuntimeError("模型返回为空")
    return {
        "content": str(content).strip(),
        "usage": data.get("usage") or {},
        "raw_id": data.get("id", ""),
    }


def run_ai_watch_image(
    *,
    task: TaskName,
    image_url: str,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Try the recommended cloud providers for an OCR/vision image task."""
    clean_url = _assert_image_source(image_url)
    task = task if task in {"ocr", "vision"} else "vision"
    final_prompt = (prompt or "").strip() or DEFAULT_PROMPTS[task]
    attempts: list[dict[str, Any]] = []

    for candidate in recommended_models(task):
        provider = candidate["provider"]
        model = candidate["model"]
        started = time.perf_counter()
        attempt = {
            "provider": provider,
            "model": model,
            "status": "failed",
            "elapsed_ms": 0,
            "error": "",
        }

        try:
            base_url, api_key, headers = _provider_settings(provider)
            if not api_key:
                raise RuntimeError("API key 未配置")
            result = _chat_completion(
                base_url=base_url,
                headers=headers,
                model=model,
                image_url=clean_url,
                prompt=final_prompt,
            )
            attempt["status"] = "ok"
            attempt["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            attempts.append(attempt)
            return {
                "status": "ok",
                "task": task,
                "provider": provider,
                "model": model,
                "elapsed_ms": attempt["elapsed_ms"],
                "content": result["content"],
                "usage": result["usage"],
                "attempts": attempts,
            }
        except Exception as exc:
            attempt["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            attempt["error"] = str(exc)
            attempts.append(attempt)

    raise AIWatchProviderError("没有可用的云端 AI看 provider", attempts)
