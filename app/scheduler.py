"""
定时任务调度器: 自动检查 UP主更新
"""
import os
import threading
import time
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from config import config

logger = logging.getLogger("bili-flow.scheduler")

scheduler = BackgroundScheduler()
_processing_lock = threading.Lock()
_processing_set: set[str] = set()  # 正在处理的 UP主名


def is_processing(up_name: str) -> bool:
    """检查是否正在处理（查数据库状态）"""
    from db import get_db
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT status FROM up_masters WHERE name=?", (up_name,)
            ).fetchone()
            return row and row["status"] == "processing"
    except Exception:
        return up_name in _processing_set  # fallback


def mark_processing(up_name: str, processing: bool):
    if processing:
        _processing_set.add(up_name)
    else:
        _processing_set.discard(up_name)


def check_and_process(up_name: str = None):
    """
    检查指定或所有 UP主的新视频，自动创建壳笔记并处理
    在后台线程中执行，避免阻塞 Web 请求
    """
    from db import get_db
    from bili_api import get_new_videos, get_up_info

    with get_db() as db:
        if up_name:
            rows = db.execute(
                "SELECT * FROM up_masters WHERE name = ?", (up_name,)
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM up_masters").fetchall()

    for row in rows:
        name = row["name"]
        uid = row["uid"]
        up_id = row["id"]

        if name in _processing_set:
            continue

        try:
            info = get_up_info(uid)
            if info:
                name = info.get("name", name) or name
                avatar = info.get("avatar", "")
                with get_db() as db:
                    db.execute(
                        "UPDATE up_masters SET name = ?, avatar = COALESCE(NULLIF(?, ''), avatar) WHERE id = ?",
                        (name, avatar, up_id),
                    )

            with get_db() as db:
                known = set(
                    r[0] for r in db.execute(
                        "SELECT bvid FROM videos WHERE up_id = ?", (up_id,)
                    ).fetchall()
                )

            new_videos = get_new_videos(uid, known, up_name=name)

            if new_videos:
                logger.info(f"[{name}] 发现 {len(new_videos)} 个新视频")

                shell_notes = create_shell_notes_batch(
                    name, uid, up_id, new_videos
                )

                if shell_notes:
                    t = threading.Thread(
                        target=run_pipeline_for_up,
                        args=(name, up_id, shell_notes),
                        daemon=True,
                    )
                    t.start()
            else:
                with get_db() as db:
                    db.execute(
                        "UPDATE up_masters SET last_scan_at = ? WHERE id = ?",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), up_id),
                    )

        except Exception as e:
            logger.error(f"[{name}] 检查更新失败: {e}")


def _rewrite_note_navigation(note_path: str, newer: dict | None, older: dict | None):
    """为单篇笔记补充较新/较旧导航，增强 Obsidian 图谱连接。"""
    if not os.path.exists(note_path):
        return

    try:
        lines = open(note_path, encoding="utf-8").read().splitlines()
    except Exception:
        return

    title_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title_idx = i
            break
    if title_idx == -1:
        return

    block_start = None
    block_end = None
    for i in range(title_idx + 1, len(lines)):
        if lines[i].startswith(">"):
            block_start = i
            break
        if lines[i].strip():
            break

    if block_start is None:
        insert_at = title_idx + 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        quote_block = []
        suffix = lines[insert_at:]
        prefix = lines[:insert_at]
    else:
        block_end = block_start
        while block_end < len(lines) and lines[block_end].startswith(">"):
            block_end += 1
        prefix = lines[:block_start]
        quote_block = lines[block_start:block_end]
        suffix = lines[block_end:]

    cleaned_block = []
    for line in quote_block:
        if line.startswith("> **较新**:") or line.startswith("> **较旧**:"):
            continue
        cleaned_block.append(line)

    nav_lines = []
    if newer:
        nav_lines.append(f"> **较新**: [[{newer['note_name']}|{newer['title']}]]")
    if older:
        nav_lines.append(f"> **较旧**: [[{older['note_name']}|{older['title']}]]")

    if cleaned_block and nav_lines:
        new_block = cleaned_block + nav_lines
    elif nav_lines:
        new_block = nav_lines
    else:
        new_block = cleaned_block

    rebuilt = prefix + new_block + suffix
    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rebuilt) + "\n")


def refresh_note_navigation(up_name: str, up_id: int, up_dir: str):
    """按采集时间近似顺序，把同一 UP 的视频笔记串成双向链。"""
    from db import get_db

    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, title, note_path, note_file, created_at
            FROM videos
            WHERE up_id = ? AND note_path != ''
            ORDER BY datetime(created_at) DESC, id ASC
            """,
            (up_id,),
        ).fetchall()

    notes = []
    for row in rows:
        note_path = row["note_path"]
        note_file = row["note_file"] or os.path.basename(note_path)
        note_name = note_file[:-3] if note_file.endswith(".md") else note_file
        if note_path:
            notes.append({
                "title": row["title"],
                "note_path": note_path,
                "note_name": note_name,
            })

    for idx, note in enumerate(notes):
        newer = notes[idx - 1] if idx > 0 else None
        older = notes[idx + 1] if idx + 1 < len(notes) else None
        _rewrite_note_navigation(note["note_path"], newer, older)


def create_shell_notes_batch(up_name: str, uid: str, up_id: int,
                             videos: list[dict]) -> list[dict]:
    """批量创建壳笔记并写入数据库"""
    from db import get_db
    from bili_api import enrich_video_meta

    vault_biki = os.path.join(config.VAULT_ROOT, config.VAULT_BIKI_DIR)
    up_dir = os.path.join(vault_biki, up_name)
    os.makedirs(up_dir, exist_ok=True)

    shell_notes = []

    for raw_video in videos:
        v = enrich_video_meta(raw_video)
        bvid = v["bvid"]
        title = v["title"]
        safe_title = title.translate(str.maketrans({
            '<': '＜', '>': '＞', ':': '：', '"': '”', '/': '／', '\\': '＼', '|': '｜', '?': '？', '*': '＊'
        }))
        filename = f"{up_name}_{safe_title}.md"
        filepath = os.path.join(up_dir, filename)

        note = f"""---
type: bilibili
tags: [B站, {up_name}]
up: "{up_name}"
bvid: "{bvid}"
duration: "{v.get('duration', '?')}"
play_count: {v.get('play_count', 0)}
status: pending
created: {datetime.now().strftime("%Y-%m-%d")}
---

# {title}

> **BV**: `{bvid}` | **时长**: {v.get('duration', '?')} | **播放**: {v.get('play_count', 0)}
> **UP主**: [[{up_name}_MOC|{up_name}]]
"""
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                if '## ⏱️ 30秒速通' in f.read(2000):
                    continue
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(note)

        with get_db() as db:
            existing = db.execute(
                "SELECT id FROM videos WHERE bvid = ? AND up_id = ?",
                (bvid, up_id),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE videos SET title=?, duration=?, play_count=?, note_path=?, note_file=? WHERE id=?",
                    (title, v.get("duration", "?"), v.get("play_count", 0),
                     filepath, filename, existing["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO videos (bvid, up_id, title, duration, play_count, note_path, note_file) VALUES (?,?,?,?,?,?,?)",
                    (bvid, up_id, title, v.get("duration", "?"),
                     v.get("play_count", 0), filepath, filename),
                )

        shell_notes.append({
            "bvid": bvid,
            "title": title,
            "note_path": filepath,
            "note_file": filename,
        })

    refresh_note_navigation(up_name, up_id, up_dir)
    update_moc(up_name, up_dir)

    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM videos WHERE up_id = ?", (up_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE up_masters SET total_videos = ?, shell_notes_created = ?, last_scan_at = ? WHERE id = ?",
            (total, total, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), up_id),
        )

    return shell_notes


def update_moc(up_name: str, up_dir: str):
    """更新 MOC 索引页"""
    moc_path = os.path.join(up_dir, f"{up_name}_MOC.md")

    done_count = 0
    pending_count = 0
    done_links = []
    pending_links = []

    for fn in sorted(os.listdir(up_dir)):
        if not fn.endswith(".md") or fn.endswith("_MOC.md"):
            continue
        fp = os.path.join(up_dir, fn)
        try:
            with open(fp, encoding="utf-8") as f:
                content = f.read(500)
                title = fn.replace(".md", "")
                if 'status: "done"' in content or 'status: "ok"' in content or "status: done" in content:
                    done_count += 1
                    done_links.append(f"- [[{title}]] ✅")
                else:
                    pending_count += 1
                    pending_links.append(f"- [[{title}]] ⏳")
        except Exception:
            pending_count += 1
            pending_links.append(f"- [[{fn.replace('.md', '')}]]")

    total = done_count + pending_count
    pct = round(done_count / total * 100) if total > 0 else 0

    moc = f"""---
type: moc
tags: [B站, {up_name}]
created: {datetime.now().strftime("%Y-%m-%d")}
---

# {up_name} · 视频笔记 MOC

> 📊 **进度**: {done_count}/{total} ({pct}%) ✅
> ```
> {"█" * (pct // 5)}{"░" * (20 - pct // 5)} {pct}%
> ```

## ✅ 已处理 ({done_count})
{chr(10).join(done_links) if done_links else '> 暂无'}

## ⏳ 待处理 ({pending_count})
{chr(10).join(pending_links) if pending_links else '> 暂无'}
"""
    with open(moc_path, "w", encoding="utf-8") as f:
        f.write(moc)


def run_pipeline_for_up(up_name: str, up_id: int, video_list: list[dict]):
    """在独立线程中运行流水线"""
    from pipeline import process_up_videos
    from db import get_db

    mark_processing(up_name, True)

    try:
        with get_db() as db:
            db.execute(
                "UPDATE up_masters SET status = 'processing' WHERE id = ?",
                (up_id,),
            )

        project_dir = os.path.join(config.PROJECTS_DIR, up_name)
        vault_dir = os.path.join(config.VAULT_ROOT, config.VAULT_BIKI_DIR, up_name)

        process_up_videos(up_name, video_list, vault_dir, project_dir)

        with get_db() as db:
            db.execute(
                """UPDATE up_masters SET
                    status = 'done',
                    processed_videos = (SELECT COUNT(*) FROM videos WHERE up_id = ? AND status IN ('ok', 'done')),
                    failed_videos = (SELECT COUNT(*) FROM videos WHERE up_id = ? AND status IN ('fail', 'failed')),
                    last_scan_at = ?
                   WHERE id = ?""",
                (up_id, up_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), up_id),
            )

        refresh_note_navigation(up_name, up_id, vault_dir)
        update_moc(up_name, vault_dir)

    except Exception as e:
        logger.error(f"[{up_name}] 流水线异常: {e}")
        from db import get_db
        with get_db() as db:
            db.execute(
                "UPDATE up_masters SET status = 'error' WHERE id = ?",
                (up_id,),
            )
    finally:
        mark_processing(up_name, False)


def start_scheduler():
    """启动定时任务"""
    from db import init_db
    init_db()

    interval = config.CHECK_INTERVAL_HOURS
    scheduler.add_job(
        check_and_process,
        "interval",
        hours=interval,
        id="check_updates",
    )
    scheduler.start()
    logger.info(f"⏰ 定时检查已启动: 每 {interval} 小时")
