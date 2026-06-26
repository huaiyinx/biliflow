"""
B站 API 封装 — 基于 bili CLI (bilibili-cli)
"""
import html
import json
import os
import re
import subprocess
import time
from typing import Optional

import requests


def _run_bili_raw(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    """运行 bili CLI，保留原始 stdout/stderr 便于判断风控与降级。"""
    try:
        return subprocess.run(
            ["bili"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None


def _parse_bili_stdout(stdout: str) -> dict | list | str | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _run_bili(args: list[str], timeout: int = 30) -> dict | list | str | None:
    """运行 bili CLI 并返回解析后的 JSON 结果。"""
    result = _run_bili_raw(args, timeout=timeout)
    if not result or result.returncode != 0:
        return None
    return _parse_bili_stdout(result.stdout)


def _looks_like_risk_control(text: str) -> bool:
    text = (text or "").lower()
    markers = [
        "412",
        "访问受限",
        "forbidden",
        "risk",
        "风控",
        "请稍后再试",
        "sorry",
        "captcha",
    ]
    return any(marker in text for marker in markers)


def _normalize_videos(vlist: list[dict]) -> list[dict]:
    videos = []
    seen: set[str] = set()
    for v in vlist or []:
        bvid = v.get("bvid") or v.get("id") or ""
        if not bvid or bvid in seen:
            continue
        seen.add(bvid)
        videos.append({
            "bvid": bvid,
            "title": html.unescape((v.get("title") or "").replace("/", "／")),
            "duration": fmt_duration(v.get("duration") or v.get("duration_seconds") or ""),
            "play_count": v.get("stats", {}).get("view", v.get("play", 0)),
        })
    return videos


def get_up_info(uid: str) -> Optional[dict]:
    """通过 UID 获取 UP主信息"""
    try:
        data = _run_bili(["user", uid, "--json"])
        if isinstance(data, dict):
            user = data.get("data", {}).get("user", data)
            name = user.get("name", user.get("username", ""))
            avatar = _get_avatar(uid)
            return {
                "uid": uid,
                "name": name,
                "avatar": avatar,
            }
    except Exception:
        pass
    return None


def _get_avatar(uid: str) -> str:
    """获取 UP主 头像 URL"""
    # 优先采用免 Cookie 且防风控性能强的 Card API
    try:
        r = requests.get(
            f"https://api.bilibili.com/x/web-interface/card?mid={uid}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            },
            timeout=10,
        )
        if r.status_code == 200:
            res = r.json()
            if res.get("code") == 0:
                face = res.get("data", {}).get("card", {}).get("face", "")
                if face:
                    return face
    except Exception:
        pass

    # 降级备用方案：原有的 space/acc/info 接口（依赖登录凭证）
    try:
        cred_path = os.path.expanduser("~/.bilibili-cli/credential.json")
        if os.path.exists(cred_path):
            cred = json.load(open(cred_path))
            cookie = f"SESSDATA={cred['sessdata']}"
            r = requests.get(
                f"https://api.bilibili.com/x/space/acc/info?mid={uid}",
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://space.bilibili.com/",
                    "Cookie": cookie,
                },
                timeout=10,
            )
            if r.status_code == 200:
                face = r.json().get("data", {}).get("face", "")
                if face:
                    return face
    except Exception:
        pass
    return ""


def _fallback_search_videos(uid: str, up_name: str, max_items: int) -> list[dict]:
    """当 user-videos 被风控/返回空时，退回 bili search 聚合。"""
    keywords = [up_name]
    seen: set[str] = set()
    collected: list[dict] = []
    max_pages = max(4, min((max_items + 19) // 20 + 4, 12))
    empty_pages = 0

    for keyword in keywords:
        for page in range(1, max_pages + 1):
            result = _run_bili(
                ["search", "--type", "video", "--page", str(page), "-n", "20", keyword, "--json"],
                timeout=30,
            )
            if isinstance(result, dict):
                items = result.get("data", [])
            elif isinstance(result, list):
                items = result
            else:
                items = []

            matched = []
            for item in items:
                author = html.unescape((item.get("author") or "").strip())
                bvid = item.get("bvid") or item.get("id") or ""
                if author != up_name or not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                matched.append(item)

            if matched:
                empty_pages = 0
                collected.extend(_normalize_videos(matched))
            else:
                empty_pages += 1

            if len(collected) >= max_items:
                return collected[:max_items]
            if page >= 3 and empty_pages >= 3:
                break
            time.sleep(0.6)

    return collected[:max_items]


def get_all_videos(uid: str, page_size: int = 50, up_name: str | None = None) -> list[dict]:
    """获取 UP主全部视频，优先 user-videos，遇到间歇性风控时自动冷却重试并降级。"""
    max_items = min(page_size * 20, 1000)
    args = ["user-videos", uid, "-n", str(max_items), "--json"]
    best_videos: list[dict] = []
    cooldowns = [0, 5, 20]

    for attempt, cooldown in enumerate(cooldowns):
        if cooldown:
            time.sleep(cooldown)

        raw = _run_bili_raw(args, timeout=60)
        combined = ""
        videos: list[dict] = []

        if raw:
            combined = f"{raw.stdout}\n{raw.stderr}"
            if raw.returncode == 0:
                parsed = _parse_bili_stdout(raw.stdout)
                if isinstance(parsed, dict):
                    vlist = parsed.get("data", [])
                elif isinstance(parsed, list):
                    vlist = parsed
                else:
                    vlist = []
                videos = _normalize_videos(vlist)
                if len(videos) > len(best_videos):
                    best_videos = videos

                risk_hit = _looks_like_risk_control(combined)
                if videos and len(videos) >= max_items and not risk_hit:
                    return videos
                if videos and len(videos) >= max_items:
                    return videos
                if videos and not risk_hit:
                    return videos
                if videos and attempt < len(cooldowns) - 1:
                    continue
            else:
                if not _looks_like_risk_control(combined):
                    time.sleep(1.5)

        if raw and not _looks_like_risk_control(combined):
            break

    if best_videos:
        if len(best_videos) < max_items:
            try:
                resolved_name = up_name
                if not resolved_name:
                    info = get_up_info(uid)
                    resolved_name = info.get("name", "") if info else ""
                if resolved_name:
                    extra = _fallback_search_videos(uid, resolved_name, max_items)
                    if extra:
                        merged = []
                        seen: set[str] = set()
                        for item in best_videos + extra:
                            bvid = item.get("bvid", "")
                            if not bvid or bvid in seen:
                                continue
                            seen.add(bvid)
                            merged.append(item)
                        return merged[:max_items]
            except Exception:
                pass
        return best_videos

    try:
        if not up_name:
            info = get_up_info(uid)
            up_name = info.get("name", "") if info else ""
        if up_name:
            return _fallback_search_videos(uid, up_name, max_items)
    except Exception:
        pass
    return []


def get_video_info(bvid: str) -> Optional[dict]:
    """通过单视频详情接口获取更可靠的元信息，例如真实时长。"""
    try:
        data = _run_bili(["video", bvid, "--json"], timeout=60)
        if not isinstance(data, dict):
            return None
        video = data.get("data", {}).get("video", data)
        if not isinstance(video, dict):
            return None
        return {
            "bvid": video.get("bvid") or bvid,
            "title": html.unescape((video.get("title") or "").replace("/", "／")),
            "duration": fmt_duration(video.get("duration") or video.get("duration_seconds") or ""),
            "play_count": video.get("stats", {}).get("view", 0),
            "owner_uid": str(video.get("owner", {}).get("id", "") or ""),
            "owner_name": video.get("owner", {}).get("name", "") or "",
        }
    except Exception:
        return None


def enrich_video_meta(video: dict, force: bool = False) -> dict:
    """当列表接口的时长/播放量明显异常时，用详情接口回填。"""
    current_duration = str(video.get("duration") or "")
    current_play = int(video.get("play_count") or 0)
    needs_detail = force or current_duration in ("", "?", "00:00") or current_play <= 0
    if not needs_detail:
        return video

    detail = get_video_info(video.get("bvid", ""))
    if not detail:
        return video

    merged = dict(video)
    if detail.get("title"):
        merged["title"] = detail["title"]
    if detail.get("duration") and detail["duration"] not in ("", "?"):
        merged["duration"] = detail["duration"]
    if detail.get("play_count"):
        merged["play_count"] = detail["play_count"]
    return merged


def fetch_subtitle(bvid: str) -> str | None:
    """通过 bili CLI 获取字幕（含时间戳）"""
    import yaml as _yaml
    try:
        raw = subprocess.run(
            ["bili", "video", bvid, "--subtitle-timeline", "--json"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = _yaml.safe_load(raw)
            except Exception:
                return None

        if not isinstance(data, dict):
            return None

        subtitle = data.get("data", {}).get("subtitle", {})
        if not subtitle.get("available"):
            return None

        text = subtitle.get("text", "")
        if text and len(text) > 30:
            return text

        items = subtitle.get("items", [])
        if items:
            lines = []
            for s in items:
                content = s.get("content", "").strip()
                if content:
                    frm = s.get("from", 0)
                    m, sec = divmod(int(frm), 60)
                    lines.append(f"[{m:02d}:{sec:05.2f}] {content}")
            return "\n".join(lines) if lines else None

    except Exception:
        pass
    return None


def download_audio(bvid: str, output_dir: str) -> str | None:
    """通过 bili CLI 下载完整音频。"""
    try:
        _run_bili(["audio", bvid, "--no-split", "-o", output_dir], timeout=180)
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith((".m4a", ".mp3", ".wav")):
                    path = os.path.join(root, f)
                    if os.path.getsize(path) > 500:
                        return path
    except Exception:
        pass
    return None


def download_audio_segments(bvid: str, output_dir: str) -> list[str]:
    """通过 bili CLI 下载并切分 ASR 友好的 wav 片段。"""
    try:
        _run_bili(["audio", bvid, "-o", output_dir], timeout=300)
        segs = []
        for root, dirs, files in os.walk(output_dir):
            for f in sorted(files):
                if f.endswith('.wav') and f.startswith('seg_'):
                    path = os.path.join(root, f)
                    if os.path.getsize(path) > 500:
                        segs.append(path)
        return segs
    except Exception:
        return []


def get_new_videos(uid: str, known_bvids: set[str], up_name: str | None = None) -> list[dict]:
    all_videos = get_all_videos(uid, up_name=up_name)
    return [v for v in all_videos if v["bvid"] not in known_bvids]


def extract_uid_from_url(url: str) -> Optional[str]:
    for p in [r"space\.bilibili\.com/(\d+)", r"bilibili\.com/(\d+)"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def fmt_duration(val) -> str:
    if not val:
        return "?"
    if isinstance(val, str) and ":" in val:
        return val
    try:
        s = int(val)
        h, m = divmod(s, 3600)
        m, s = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except (ValueError, TypeError):
        return str(val)


def load_bili_cookie() -> Optional[str]:
    """检查 bili CLI 是否已登录"""
    try:
        r = _run_bili(["status"], timeout=5)
        if isinstance(r, dict) and r.get("logged_in"):
            return "bili-cli"
    except Exception:
        pass
    return None


_cached_my_info = None
_cached_my_info_time = 0.0

def get_my_info() -> Optional[dict]:
    """获取当前登录用户信息 (带 5分钟 内存缓存)"""
    global _cached_my_info, _cached_my_info_time
    now = time.time()
    if _cached_my_info is not None and (now - _cached_my_info_time) < 300:
        return _cached_my_info if _cached_my_info != "logged_out" else None

    try:
        data = _run_bili(["whoami", "--json"], timeout=10)
        if isinstance(data, dict) and data.get("data", {}).get("user", {}):
            user = data.get("data", {}).get("user", {})
            _cached_my_info = {
                "uid": user.get("id", ""),
                "name": user.get("name", user.get("username", "")),
                "level": user.get("level", 0),
                "sign": user.get("sign", ""),
            }
            _cached_my_info_time = now
            return _cached_my_info
        else:
            _cached_my_info = "logged_out"
            _cached_my_info_time = now
    except Exception:
        # 发生异常时，短缓存 15 秒以防重复发起进程卡死服务
        _cached_my_info = "logged_out"
        _cached_my_info_time = now - 285
    return None


def search_up_uid_by_name(name: str) -> Optional[str]:
    """通过名字搜索 UP主，返回精确匹配的 UID 或最匹配的第一个 UID"""
    try:
        clean_name = name.strip()
        data = _run_bili(["search", "--type", "user", clean_name, "--json"])
        if isinstance(data, dict) and data.get("ok"):
            items = data.get("data", [])
            if not items:
                return None
            
            # 1. 优先精确匹配
            for item in items:
                item_name = (item.get("name") or "").strip()
                if item_name.lower() == clean_name.lower():
                    return str(item.get("id"))
            
            # 2. 如果没有精确匹配，返回第一个结果的 id
            return str(items[0].get("id"))
    except Exception:
        pass
    return None

