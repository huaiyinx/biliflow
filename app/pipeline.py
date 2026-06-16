"""
BiliFlow 核心流水线
字幕提取 → SenseVoice ASR → Gemini 重构 → Obsidian 笔记
"""
import json
import os
import re
import subprocess
import time
import requests
import threading
from pathlib import Path
from config import config
from bili_api import load_bili_cookie, fetch_subtitle, download_audio as bili_download_audio, download_audio_segments


FULL_PROMPT = """# 角色与核心任务
你是一位兼具\"顶尖人际洞察专家\"、\"资深游戏制作人\"与\"AI 视频导演\"多重身份的极客导师。
我将输入一段B站视频的语音转写文本（ASR，有口癖/错字）。
无视原文流水账顺序，提取底层逻辑，重构为高密度 Obsidian 学习笔记。同时为核心场景设计 AI 视频生成分镜。

# 硬性规则
1. 修复ASR错字，删除\"嗯 啊 对吧 对不对\"等口癖和重复废话
2. 按\"问题→认知→方法→场景\"重构，不跟时间线
3. 必须映射到职场/社交/生活的具体场景
4. 必须包含游戏开发(系统设计/Game Dev)的跨界映射脑洞
5. 必须设计2-3个纯英文AI动画分镜提示词（适合直接喂给Sora/Runway/Kling）
6. 提示词必须包含：[主体特征], [具体动作], [背景环境], [镜头运动], [艺术风格]

# 输出模板（严格遵守，不要输出任何模板之外的文字）

## ⏱️ 30秒速通 (TL;DR)
> **核心奥义**：一句话凌厉概括解决的根本问题。
- **适用场景**：
- **核心策略**：

## 🧠 核心思维/架构剖析
- **洞察 A**：
- **洞察 B**：

## 🎯 实战方法 (或关键逻辑还原)
- **策略一**：
- **策略二**：

## 🎮 场景映射 (Game Dev & Real Life Bridge)
- **现实场景**：
- **跨界灵感（游戏开发映射）**：

## 🎬 AI 动画生成提示词 (Prompt for Sora/Runway/Kling)
- **Scene 1**: `[英文提示词]`
- **Scene 2**: `[英文提示词]`

## 💬 金句摘录
- \"[提取原稿中最击中人心的话]\"

---
标题：{title}
文本：{transcript}"""


# ===== 进度管理 =====

class ProgressTracker:
    """线程安全进度追踪器"""
    def __init__(self, up_name: str, project_dir: str):
        self.up_name = up_name
        self.progress_file = os.path.join(project_dir, "progress.json")
        self.lock = threading.RLock()
        self.data = {
            "current": 0, "total": 0, "pct": 0,
            "ok": 0, "fail": 0, "sv_fallback": 0, "no_text": 0,
            "last": "", "last_status": "", "last_src": "",
            "done": False, "phase": 3, "up": up_name,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": "",
        }
        self.write()

    def update(self, d: dict):
        with self.lock:
            self.data.update(d)
            self.write()

    def write(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.progress_file), exist_ok=True)
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)

    def read(self) -> dict:
        with self.lock:
            return dict(self.data)


# ===== 字幕获取 =====

def get_bili_cookie():
    return load_bili_cookie()


def fmt_ts(s):
    m = int(s // 60)
    s = s % 60
    return f"{m:02d}:{s:05.2f}"


def fmt_timed(items):
    lines = []
    for i in items:
        content = i.get("content", "").strip()
        if content:
            lines.append(f"[{fmt_ts(i['from'])}] {content}")
    return "\n".join(lines)


def fetch_bili_subtitle(bvid: str) -> str | None:
    """通过 bili CLI 获取字幕（含时间戳）"""
    return fetch_subtitle(bvid)


def download_audio(bvid: str, audio_dir: str) -> str | None:
    """优先通过 bili CLI 下载音频，失败时再兜底 yt-dlp。"""
    for ext in ["m4a", "mp3", "wav"]:
        for root, dirs, files in os.walk(audio_dir):
            for f in files:
                if bvid in f and f.endswith(ext):
                    p = os.path.join(root, f)
                    if os.path.getsize(p) > 500:
                        return p

    result = bili_download_audio(bvid, audio_dir)
    if result:
        return result

    url = f"https://www.bilibili.com/video/{bvid}"
    tmpl = os.path.join(audio_dir, f"{bvid}.%(ext)s")
    try:
        args = [
            "yt-dlp", url, "-f", "worstaudio", "--extract-audio",
            "--audio-format", "mp3", "--audio-quality", "64K",
            "-o", tmpl, "--no-playlist", "--socket-timeout", "15", "--no-warnings",
        ]
        subprocess.run(args, capture_output=True, text=True, timeout=60)
        for ext in ["m4a", "mp3"]:
            p = os.path.join(audio_dir, f"{bvid}.{ext}")
            if os.path.exists(p) and os.path.getsize(p) > 500:
                return p
    except Exception:
        pass
    return None


def parse_srt(srt_text: str) -> str | None:
    """解析 SRT 格式 → 时间戳文本"""
    lines = []
    for block in srt_text.strip().split("\n\n"):
        parts = block.strip().split("\n")
        if len(parts) >= 3:
            m = re.match(r"(\d{2}):(\d{2}):(\d{2})[.,](\d+)", parts[1])
            if m:
                h, mm, s, ms = m.groups()
                t = int(h) * 3600 + int(mm) * 60 + int(s) + int(ms) / 1000
                lines.append(f"[{fmt_ts(t)}] {' '.join(parts[2:])}")
    return "\n".join(lines) if lines else None


def sensevoice(audio_path: str) -> str | None:
    """通过 SiliconFlow SenseVoice 转写。"""
    size_mb = os.path.getsize(audio_path) / 1024 / 1024
    if size_mb > 25:
        return None

    ext = audio_path.split(".")[-1].lower()
    mime = {
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
    }.get(ext, "audio/mpeg")

    for fmt in ["srt", "verbose_json", "vtt"]:
        for _ in range(2):
            try:
                with open(audio_path, "rb") as f:
                    r = requests.post(
                        f"{config.SF_BASE}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {config.SF_KEY}"},
                        files={"file": (os.path.basename(audio_path), f, mime)},
                        data={
                            "model": "FunAudioLLM/SenseVoiceSmall",
                            "response_format": fmt,
                        },
                        timeout=90,
                    )
                if r.status_code != 200:
                    time.sleep(2)
                    continue
                raw = r.text.strip()
                if raw and len(raw) > 30:
                    if fmt == "srt":
                        parsed = parse_srt(raw)
                        if parsed:
                            return parsed
                    return raw
            except Exception:
                time.sleep(2)

    for _ in range(2):
        try:
            with open(audio_path, "rb") as f:
                r = requests.post(
                    f"{config.SF_BASE}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {config.SF_KEY}"},
                    files={"file": (os.path.basename(audio_path), f, mime)},
                    data={"model": "FunAudioLLM/SenseVoiceSmall"},
                    timeout=90,
                )
            if r.status_code == 200:
                return r.json().get("text", "")
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


def sensevoice_segments(segment_paths: list[str]) -> str | None:
    """将 bili CLI 切分后的 wav 片段逐段转写并拼接。"""
    transcripts = []
    for idx, seg in enumerate(segment_paths):
        part = sensevoice(seg)
        if not part or len(part.strip()) < 10:
            continue
        offset = idx * 25
        prefix = f"[{fmt_ts(offset)}] "
        cleaned = part.strip()
        if cleaned.startswith('['):
            transcripts.append(cleaned)
        else:
            transcripts.append(prefix + cleaned)
    return "\n".join(transcripts) if transcripts else None


def call_llm(prompt: str, max_tokens: int = 2500) -> str | None:
    """调用 Gemini LLM 重构笔记"""
    for _ in range(3):
        try:
            r = requests.post(
                f"{config.GEMINI_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.GEMINI_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.4,
                },
                timeout=90,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


def parse_note_content(content: str) -> dict:
    result = {
        "title": "", "bvid": "", "raw_transcript": "",
        "frontmatter": "", "header_lines": [],
    }
    fm_end = content.find("---", 4)
    result["frontmatter"] = content[:fm_end + 3] if fm_end != -1 else ""

    lines = content.split("\n")
    ti = -1
    for i, line in enumerate(lines):
        if line.startswith("# "):
            result["title"] = line[2:].strip()
            ti = i
            break
        m = re.search(r"BV[a-zA-Z0-9]+", line)
        if m:
            result["bvid"] = m.group()

    if ti >= 0:
        for line in lines[ti + 1:]:
            if line.startswith(">"):
                result["header_lines"].append(line)
            elif result["header_lines"]:
                break

    for marker in ["## 📝 原始转录", "## 📜 原始讲稿"]:
        if marker in content:
            parts = content.split(marker, 1)
            if len(parts) > 1:
                txt = parts[1]
                for sep in ["## ", "---"]:
                    if sep in txt:
                        txt = txt.split(sep, 1)[0]
                result["raw_transcript"] = txt.strip()
                break

    return result


def update_note_frontmatter(note_path: str, updates: dict):
    try:
        with open(note_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return

        fm_end = content.find("---", 4)
        if fm_end == -1:
            return

        fm = content[4:fm_end]
        body = content[fm_end + 3:]

        for key, value in updates.items():
            if isinstance(value, list):
                v_str = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, str):
                v_str = f'"{value}"'
            else:
                v_str = str(value)

            if re.search(rf"^{key}:", fm, re.MULTILINE):
                fm = re.sub(
                    rf"^{key}:.*$",
                    f"{key}: {v_str}",
                    fm, flags=re.MULTILINE
                )
            else:
                fm += f"\n{key}: {v_str}"

        with open(note_path, "w", encoding="utf-8") as f:
            f.write(f"---\n{fm}\n---{body}")

    except Exception:
        pass


def has_timestamp(text: str) -> bool:
    return bool(re.search(r"\[\d{2}:\d{2}", text))


def process_one_video(
    bvid: str, title: str, note_path: str,
    audio_dir: str, progress: ProgressTracker,
) -> tuple[str, str]:
    if os.path.exists(note_path):
        existing = open(note_path, encoding="utf-8").read()
        required_sections = [
            "30秒速通", "核心思维", "实战方法",
            "场景映射", "AI 动画生成提示词", "金句摘录",
        ]
        if all(s in existing for s in required_sections):
            return "ok", "cached"

    transcript = ""
    source = "raw"
    need_fetch = True

    if os.path.exists(note_path):
        parsed = parse_note_content(open(note_path, encoding="utf-8").read())
        transcript = parsed.get("raw_transcript", "")
        if transcript and len(transcript) > 50 and has_timestamp(transcript):
            need_fetch = False
            source = "raw"

    if need_fetch and bvid:
        new_t = fetch_bili_subtitle(bvid)
        if new_t:
            transcript = new_t
            source = "CLI"
            need_fetch = False

    if need_fetch or not transcript or len(transcript) < 30:
        audio_path = download_audio(bvid, audio_dir)
        new_t = None
        if audio_path:
            if os.path.getsize(audio_path) / 1024 / 1024 > 25:
                segment_dir = os.path.join(audio_dir, f"{bvid}_segments")
                segments = download_audio_segments(bvid, segment_dir)
                if segments:
                    new_t = sensevoice_segments(segments)
                    for seg in segments:
                        try:
                            os.remove(seg)
                        except Exception:
                            pass
                    try:
                        os.rmdir(segment_dir)
                    except Exception:
                        pass
            else:
                new_t = sensevoice(audio_path)
            try:
                os.remove(audio_path)
            except Exception:
                pass
            if new_t:
                transcript = new_t
                source = "SV"
                progress.update({"sv_fallback": progress.data["sv_fallback"] + 1})
            else:
                progress.update({"no_text": progress.data["no_text"] + 1})
                return "fail", "no_text"
        elif not transcript or len(transcript) < 30:
            return "fail", "no_dl"

    if not transcript or len(transcript) < 30:
        return "fail", "short"

    prompt = FULL_PROMPT.format(title=title, transcript=transcript[:4000])
    result = call_llm(prompt, 2500)
    if not result:
        return "fail", "llm"

    clean = result.strip()
    if clean.startswith("---"):
        parts = clean.split("---", 2)
        if len(parts) >= 3:
            clean = parts[2].strip()
    if clean.startswith("# "):
        clean = "\n".join(clean.split("\n")[1:]).strip()

    if os.path.exists(note_path):
        parsed = parse_note_content(open(note_path, encoding="utf-8").read())
    else:
        parsed = {"title": title, "bvid": bvid,
                  "frontmatter": "---\ntype: bilibili\n---\n",
                  "header_lines": []}

    fm_lines = parsed["frontmatter"].split("\n")
    new_fm = []
    has_title = False
    for line in fm_lines:
        if line.startswith("title:"):
            new_fm.append(f'title: "{title}"')
            has_title = True
        elif line.startswith("status:"):
            new_fm.append('status: "done"')
        elif line.startswith("processed:"):
            new_fm.append(f'processed: "{time.strftime("%Y-%m-%d")}"')
        elif line.startswith("source:"):
            new_fm.append(f'source: "{source}"')
        else:
            new_fm.append(line)
    if not has_title and new_fm:
        new_fm.insert(1, f'title: "{title}"')

    body_parts = [
        "\n".join(new_fm),
        "",
        f"# {title}",
    ]
    if parsed["header_lines"]:
        body_parts.append("")
        body_parts.extend(parsed["header_lines"])
    body_parts.append("")
    body_parts.append(clean)
    body_parts.append("")
    body_parts.append("---")
    body_parts.append("")
    body_parts.append("## 📜 原始讲稿备份（含完整时间戳）")
    body_parts.append("")
    body_parts.append(transcript.strip())

    os.makedirs(os.path.dirname(note_path), exist_ok=True)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(body_parts))

    return "ok", source


def process_up_videos(up_name: str, video_list: list[dict], vault_dir: str,
                      project_dir: str, progress_callback=None):
    audio_dir = os.path.join(project_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    progress = ProgressTracker(up_name, project_dir)
    total = len(video_list)
    progress.update({
        "total": total, "current": 0, "pct": 0,
        "ok": 0, "fail": 0, "done": False,
    })

    ok = fail = sv = 0

    for i, v in enumerate(video_list):
        status, source = process_one_video(
            v["bvid"], v["title"], v["note_path"],
            audio_dir, progress,
        )

        if status == "ok":
            ok += 1
        elif status == "skip":
            ok += 1
        else:
            fail += 1
        if source == "SV":
            sv += 1

        try:
            from db import get_db
            with get_db() as db:
                db.execute(
                    "UPDATE videos SET status=?, source=?, error_msg=?, processed_at=datetime('now','localtime') WHERE bvid=?",
                    (status, source, None if status in ("ok", "done", "skip") else source, v["bvid"]),
                )
                db.execute(
                    "UPDATE up_masters SET processed_videos=?, failed_videos=? WHERE name=?",
                    (ok, fail, up_name),
                )
        except Exception:
            pass

        progress.update({
            "current": i + 1,
            "pct": round((i + 1) / total * 100),
            "ok": ok, "fail": fail,
            "sv_fallback": sv,
            "last": v["title"][:40],
            "last_status": status,
            "last_src": source,
        })

        if progress_callback:
            progress_callback(v, status, source)

        time.sleep(0.3)

    progress.update({
        "done": True,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last": "完成!",
    })

    return {"ok": ok, "fail": fail, "sv_fallback": sv}
