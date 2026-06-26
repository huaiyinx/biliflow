"""Upgrade existing BiliFlow notes to the latest learning-oriented template.

The script is intentionally slow and resumable. It only reprocesses notes that
do not already contain all enhanced learning sections.
"""
import argparse
import os
import time
from pathlib import Path

from config import config
from db import get_db
from pipeline import ProgressTracker, process_one_video


REQUIRED_SECTIONS = [
    "学习目标与核心问题",
    "私人导师讲解",
    "核心知识卡",
    "独立思考与边界",
    "回看与复习入口",
]


def has_enhanced_sections(note_path: str) -> bool:
    try:
        text = Path(note_path).read_text(encoding="utf-8")
    except Exception:
        return False
    return all(section in text for section in REQUIRED_SECTIONS)


def refresh_up_counts(up_id: int):
    with get_db() as db:
        db.execute(
            """
            UPDATE up_masters SET
                total_videos = (SELECT COUNT(*) FROM videos WHERE up_id = ?),
                processed_videos = (
                    SELECT COUNT(*) FROM videos
                    WHERE up_id = ? AND status IN ('ok', 'done')
                ),
                failed_videos = (
                    SELECT COUNT(*) FROM videos
                    WHERE up_id = ? AND status IN ('fail', 'failed')
                )
            WHERE id = ?
            """,
            (up_id, up_id, up_id, up_id),
        )


def find_targets(limit: int | None = None, up_name: str | None = None) -> list[dict]:
    query = """
        SELECT
            v.id, v.bvid, v.title, v.note_path, v.up_id,
            v.status AS old_status,
            v.source AS old_source,
            v.error_msg AS old_error_msg,
            u.name AS up_name
        FROM videos v
        JOIN up_masters u ON u.id = v.up_id
        WHERE v.note_path != ''
          AND v.status IN ('ok', 'done')
        ORDER BY u.id ASC, v.id ASC
    """
    params: tuple = ()
    if up_name:
        query = query.replace("ORDER BY", "AND u.name = ? ORDER BY")
        params = (up_name,)

    with get_db() as db:
        rows = [dict(row) for row in db.execute(query, params).fetchall()]

    targets = [row for row in rows if not has_enhanced_sections(row["note_path"])]
    if limit is not None and limit > 0:
        return targets[:limit]
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max notes to upgrade; 0 means all.")
    parser.add_argument("--sleep", type=float, default=3.0, help="Seconds between notes.")
    parser.add_argument("--up", default="", help="Only upgrade one UP master by name.")
    parser.add_argument("--dry-run", action="store_true", help="Only print target count.")
    args = parser.parse_args()

    lock_path = Path(config.DB_PATH).with_name("maintenance_upgrade_notes.lock")
    if lock_path.exists() and not args.dry_run:
        print(f"lock exists: {lock_path}", flush=True)
        return

    targets = find_targets(
        limit=args.limit if args.limit > 0 else None,
        up_name=args.up or None,
    )
    print(f"targets={len(targets)}", flush=True)
    if args.dry_run:
        for row in targets[:20]:
            print(f"{row['up_name']} | {row['bvid']} | {row['title']}", flush=True)
        return

    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    project_dir = os.path.join(config.PROJECTS_DIR, "_maintenance_note_upgrade")
    audio_dir = os.path.join(project_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    progress = ProgressTracker("maintenance-note-upgrade", project_dir)
    progress.update({"total": len(targets), "current": 0, "pct": 0})

    ok = fail = 0
    try:
        for idx, row in enumerate(targets, start=1):
            print(
                f"[{idx}/{len(targets)}] {row['up_name']} | {row['bvid']} | {row['title']}",
                flush=True,
            )
            status, source = process_one_video(
                row["bvid"],
                row["title"],
                row["note_path"],
                audio_dir,
                progress,
            )
            if status in ("ok", "done", "skip"):
                ok += 1
                error_msg = None
                with get_db() as db:
                    db.execute(
                        """
                        UPDATE videos
                        SET status = ?, source = ?, error_msg = ?, processed_at = datetime('now','localtime')
                        WHERE id = ?
                        """,
                        (status, source, error_msg, row["id"]),
                    )
            else:
                fail += 1
                print(
                    f"preserve old status after upgrade failure: {row['bvid']} "
                    f"old={row['old_status']} new={status}/{source}",
                    flush=True,
                )
            refresh_up_counts(row["up_id"])
            progress.update({
                "current": idx,
                "pct": round(idx / max(len(targets), 1) * 100),
                "ok": ok,
                "fail": fail,
                "last": row["title"][:40],
                "last_status": status,
                "last_src": source,
            })
            time.sleep(args.sleep)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        progress.update({
            "done": True,
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last": "upgrade complete",
        })
        print(f"done ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
