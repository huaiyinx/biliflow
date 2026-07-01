"""
Cloud provider registry for BiliFlow AI Watch.

The VPS must stay lightweight: no video downloads and no local OCR. This module
only records provider policy, key availability, budgets, and recommended order.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

from config import config


TaskType = Literal["ocr", "vision", "youtube_video"]


@dataclass(frozen=True)
class ProviderModel:
    id: str
    provider: str
    model: str
    task: TaskType
    role: str
    priority: int
    free_now: bool
    limited_free: bool
    supports_image: bool = True
    supports_video_url: bool = False
    max_cost_cny: float = 0.0
    rpm_hint: str = ""
    tpm_hint: str = ""
    notes: str = ""
    key_env: str = ""


PROVIDER_MODELS: list[ProviderModel] = [
    ProviderModel(
        id="sf-paddleocr-vl",
        provider="siliconflow",
        model="PaddlePaddle/PaddleOCR-VL-1.5",
        task="ocr",
        role="primary_ocr",
        priority=10,
        free_now=True,
        limited_free=False,
        key_env="SILICONFLOW_VISUAL_KEY",
        notes="课件/截图 OCR 首选；实测抽取最全，适合先读图中文字。",
    ),
    ProviderModel(
        id="sf-deepseek-ocr",
        provider="siliconflow",
        model="deepseek-ai/DeepSeek-OCR",
        task="ocr",
        role="limited_free_ocr",
        priority=20,
        free_now=True,
        limited_free=True,
        rpm_hint="L0 1000 RPM",
        tpm_hint="L0 80000 TPM",
        key_env="SILICONFLOW_VISUAL_KEY",
        notes="限免 OCR 候选；可吃免费红利，但不能作为唯一依赖。",
    ),
    ProviderModel(
        id="sf-qwen3-vl-8b",
        provider="siliconflow",
        model="Qwen/Qwen3-VL-8B-Instruct",
        task="vision",
        role="primary_vision",
        priority=30,
        free_now=True,
        limited_free=False,
        key_env="SILICONFLOW_VISUAL_KEY",
        notes="关键帧视觉理解首选；实测结构化输出最干净。",
    ),
    ProviderModel(
        id="or-nemotron-vl-free",
        provider="openrouter",
        model="nvidia/nemotron-nano-12b-v2-vl:free",
        task="vision",
        role="free_vision_fallback",
        priority=40,
        free_now=True,
        limited_free=True,
        key_env="OPENROUTER_API_KEY",
        notes="OpenRouter 免费视觉兜底；比 openrouter/free 自动路由更可控。",
    ),
    ProviderModel(
        id="gemini-youtube-url",
        provider="gemini",
        model="gemini-3.5-flash",
        task="youtube_video",
        role="youtube_url_primary",
        priority=50,
        free_now=True,
        limited_free=True,
        supports_image=False,
        supports_video_url=True,
        key_env="GEMINI_KEY",
        notes="公开 YouTube URL 优先；预览免费能力可能变化。",
    ),
]


def _has_key(env_name: str) -> bool:
    if env_name == "SILICONFLOW_VISUAL_KEY":
        return bool(config.SILICONFLOW_VISUAL_KEY or config.SF_KEY)
    if env_name == "OPENROUTER_API_KEY":
        return bool(config.OPENROUTER_KEY)
    return bool(getattr(config, env_name, ""))


def get_provider_status() -> list[dict]:
    rows = []
    for item in sorted(PROVIDER_MODELS, key=lambda x: x.priority):
        d = asdict(item)
        d["key_present"] = _has_key(item.key_env)
        d["budget_cny"] = config.AI_WATCH_MAX_VISUAL_COST_CNY
        d["enabled_by_policy"] = d["key_present"] and (
            item.free_now or not config.AI_WATCH_REQUIRE_FREE_FIRST
        )
        d["risk"] = "限免/可能收费" if item.limited_free else "常规免费/低价候选"
        rows.append(d)
    return rows


def recommended_models(task: TaskType) -> list[dict]:
    return [
        row for row in get_provider_status()
        if row["task"] == task and row["enabled_by_policy"]
    ]
