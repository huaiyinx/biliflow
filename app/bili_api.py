"""
B站 API 封装 — 基于 bili CLI (bilibili-cli)
"""
import json
import os
import re
import subprocess
from typing import Optional

import requests


def _run_bili(args: list[str], timeout: int = 30) -> dict | str | None:
    """运行 bili CLI 并返回 JSON 结果"""
    try:
        r = subprocess.run(
            ["bili"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return None
        # 尝试 JSON
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return r.stdout.strip()
    except Exception:
        return None


def get_up_info(uid: str) -> Optional[dict]:
    """通过 UID 获取 UP主信息"""
    try:
        data = _run_bili(["user", uid, "--json"])
        if isinstance(data, dict):
            user = data.get("data", {}).get("user", data)
            name = user.get("name", user.get("username", ""))
            # avatar: bili CLI 不返回 face，从 credential 调用 B站 API 获取
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
    try:
        # 用 bili CLI 的 cookie 访问 B站 API
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


def get_all_videos(uid: str, page_size: int = 50) -> list[dict]:
    """获取 UP主全部视频（bili CLI 一次返回指定数量）"""
    try:
        result = _run_bili(["user-videos", uid, "-n", str(min(page_size * 20, 1000)), "--json"], timeout=30)
        if isinstance(result, dict):
            vlist = result.get("data", [])
        else:
            vlist = result if isinstance(result, list) else []
        videos = []
        for v in vlist:
            videos.append({
                "bvid": v.get("bvid", ""),
                "title": v.get("title", "").replace("/", "／"),
                "duration": fmt_duration(v.get("duration", "")),
                "play_count": v.get("stats", {}).get("view", v.get("play", 0)),
            })
        return videos
    except Exception:
        pass
    return []


def fetch_subtitle(bvid: str) -> str | None:
    """通过 bili CLI 获取字幕（含时间戳）"""
    import yaml as _yaml
    try:
        # 先试 JSON
        raw = subprocess.run(
            ["bili", "video", bvid, "--subtitle-timeline", "--json"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 降级：YAML
            try:
                data = _yaml.safe_load(raw)
            except Exception:
                return None

        if not isinstance(data, dict):
            return None

        # 提取字幕
        subtitle = data.get("data", {}).get("subtitle", {})
        if not subtitle.get("available"):
            return None

        text = subtitle.get("text", "")
        if text and len(text) > 30:
            return text

        # timeline 格式：从 items 构建
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
    """通过 bili CLI 下载音频"""
    import os
    try:
        _run_bili(["audio", bvid, "--no-split", "-o", output_dir], timeout=120)
        # 查找输出文件
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith((".m4a", ".mp3", ".wav")):
                    path = os.path.join(root, f)
                    if os.path.getsize(path) > 500:
                        return path
    except Exception:
        pass
    return None


def get_new_videos(uid: str, known_bvids: set[str]) -> list[dict]:
    all_videos = get_all_videos(uid)
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
            return "bili-cli"  # 返回非空标记
    except Exception:
        pass
    return None


def get_my_info() -> Optional[dict]:
    """获取当前登录用户信息"""
    try:
        data = _run_bili(["whoami", "--json"], timeout=10)
        if isinstance(data, dict):
            user = data.get("data", {}).get("user", {})
            return {
                "uid": user.get("id", ""),
                "name": user.get("name", user.get("username", "")),
                "level": user.get("level", 0),
                "sign": user.get("sign", ""),
            }
    except Exception:
        pass
    return None
