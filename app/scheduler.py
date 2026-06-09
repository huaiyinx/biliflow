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
    from bili_api import get_new_videos, get_all_videos

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
            with get_db() as db:
                known = set(
                    r[0] for r in db.execute(
                        "SELECT bvid FROM videos WHERE up_id = ?", (up_id,)
                    ).fetchall()
                )

            new_videos = get_new_videos(uid, known)

            if new_videos:
                logger.info(f"[{name}] 发现 {len(new_videos)} 个新视频")

                # 创建壳笔记并插入数据库
                shell_notes = create_shell_notes_batch(name, uid, up_id, new_videos)

                # 启动处理
                if shell_notes:
                    import threading
                    t = threading.Thread(
                        target=run_pipeline_for_up,
                        args=(name, up_id, shell_notes),
                        daemon=True,
                    )
                    t.start()
            else:
                # 更新最后扫描时间
                with get_db() as db:
                    db.execute(
                        "UPDATE up_masters SET last_scan_at = ? WHERE id = ?",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), up_id),
                    )

        except Exception as e:
            logger.error(f"[{name}] 检查更新失败: {e}")


def create_shell_notes_batch(up_name: str, uid: str, up_id: int,
                             videos: list[dict]) -> list[dict]:
    """批量创建壳笔记并写入数据库"""
    from db import get_db
    import os

    vault_biki = os.path.join(config.VAULT_ROOT, config.VAULT_BIKI_DIR)
    up_dir = os.path.join(vault_biki, up_name)
    os.makedirs(up_dir, exist_ok=True)

    shell_notes = []

    for v in videos:
        bvid = v["bvid"]
        title = v["title"]
        safe_title = title.replace("/", "／").replace(":", "：")
        filename = f"{up_name}_{safe_title}.md"
        filepath = os.path.join(up_dir, filename)

        # 壳笔记内容
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
        # ⚠️ 保护：如果已有完整笔记，永不覆盖
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                if '## ⏱️ 30秒速通' in f.read(2000):
                    continue  # 跳过，保留已完成笔记
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(note)

        # 写入数据库
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

    # 更新/创建 MOC
    update_moc(up_name, up_dir)

    # 更新 UP主统计
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
    import os
    from db import get_db

    moc_path = os.path.join(up_dir, f"{up_name}_MOC.md")

    # 统计
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
    import os
    from pipeline import process_up_videos
    from db import get_db

    mark_processing(up_name, True)

    try:
        # 更新状态
        with get_db() as db:
            db.execute(
                "UPDATE up_masters SET status = 'processing' WHERE id = ?",
                (up_id,),
            )

        project_dir = os.path.join(config.PROJECTS_DIR, up_name)
        vault_dir = os.path.join(config.VAULT_ROOT, config.VAULT_BIKI_DIR, up_name)

        result = process_up_videos(up_name, video_list, vault_dir, project_dir)

        # 更新状态
        with get_db() as db:
            db.execute(
                """UPDATE up_masters SET
                    status = 'done',
                    processed_videos = ?,
                    failed_videos = ?,
                    last_scan_at = ?
                   WHERE id = ?""",
                (result["ok"], result["fail"],
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), up_id),
            )

        # 更新 MOC
        update_moc(up_name, vault_dir)

    except Exception as e:
        logger.error(f"[{up_name}] 流水线异常: {e}")
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
        next_run_time=None,  # 启动时不立即执行
    )
    scheduler.start()
    logger.info(f"⏰ 定时检查已启动: 每 {interval} 小时")
