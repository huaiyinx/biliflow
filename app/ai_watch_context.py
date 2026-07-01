"""
Visual context normalization for AI Watch.

This module turns multiple OCR/vision frame outputs into a compact Markdown
block that can be injected into the note generation prompt later.
"""
from __future__ import annotations

from typing import Any

import requests

from config import config


VISUAL_CONTEXT_PROMPT = """# 角色与任务
你是 BiliFlow 的视频关键帧整理器。用户给你多张视频关键帧的 OCR/视觉识别结果。
请把它们压缩成可插入视频笔记提示词的 Markdown 视觉上下文。

# 要求
1. 不要编造画面，只整理输入里明确出现的信息。
2. 去掉明显重复、无意义箭头、页面噪声和 OCR 乱码。
3. 保留时间点、课件标题、工具界面文字、步骤、参数、代码/命令/数字。
4. 如果画面像软件教学，请提取操作步骤。
5. 输出控制在 1200 字以内。

# 输出格式
## visual_context

### 画面总览
- 

### 时间点线索
- `[00:00]` 

### 课件/屏幕文字
- 

### 可用于笔记生成的补充判断
- 

---
关键帧输入：
{frames_text}
"""


def _format_time(seconds: float | int | None) -> str:
    try:
        value = max(float(seconds or 0), 0)
    except Exception:
        value = 0
    minutes = int(value // 60)
    secs = int(value % 60)
    return f"{minutes:02d}:{secs:02d}"


def _sanitize_content(text: str, limit: int = 1600) -> str:
    value = (text or "").strip()
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in value.split("\n") if line.strip()]
    compact = "\n".join(lines)
    return compact[:limit]


def _frames_to_text(frames: list[dict[str, Any]]) -> str:
    chunks = []
    for item in frames[:12]:
        timestamp = _format_time(item.get("timestamp"))
        content = _sanitize_content(str(item.get("content") or ""))
        provider = item.get("provider") or ""
        model = item.get("model") or ""
        chunks.append(
            "\n".join([
                f"### Frame {item.get('index', '?')} [{timestamp}]",
                f"Provider: {provider} / {model}".strip(),
                content,
            ]).strip()
        )
    return "\n\n".join(chunks)


def _fallback_visual_context(frames: list[dict[str, Any]]) -> str:
    lines = ["## visual_context", "", "### 时间点线索"]
    for item in frames[:12]:
        timestamp = _format_time(item.get("timestamp"))
        content = _sanitize_content(str(item.get("content") or ""), 500)
        if content:
            lines.append(f"- `[{timestamp}]` {content}")
    lines.extend([
        "",
        "### 可用于笔记生成的补充判断",
        "- 以上为关键帧 OCR/视觉结果，生成正文时只能引用这些画面线索，不要编造未出现的画面细节。",
    ])
    return "\n".join(lines).strip()


def build_visual_context(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Build compact visual_context Markdown from multiple frame results."""
    usable_frames = [
        item for item in frames[:12]
        if str(item.get("content") or "").strip()
    ]
    if not usable_frames:
        return {
            "status": "empty",
            "source": "fallback",
            "frame_count": 0,
            "visual_context": "",
        }

    frames_text = _frames_to_text(usable_frames)[:16000]
    fallback = _fallback_visual_context(usable_frames)

    if not config.GEMINI_KEY:
        return {
            "status": "ok",
            "source": "fallback",
            "frame_count": len(usable_frames),
            "visual_context": fallback,
        }

    try:
        response = requests.post(
            f"{config.GEMINI_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.GEMINI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.CHAT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": VISUAL_CONTEXT_PROMPT.format(frames_text=frames_text),
                    }
                ],
                "max_tokens": 1400,
                "temperature": 0.2,
            },
            timeout=90,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not str(content).strip():
            raise RuntimeError("empty visual_context")
        return {
            "status": "ok",
            "source": "llm",
            "frame_count": len(usable_frames),
            "visual_context": str(content).strip(),
            "usage": data.get("usage") or {},
        }
    except Exception as exc:
        return {
            "status": "ok",
            "source": "fallback",
            "frame_count": len(usable_frames),
            "visual_context": fallback,
            "warning": str(exc),
        }
