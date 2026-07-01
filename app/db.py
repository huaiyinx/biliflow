"""
SQLite 数据库操作封装
"""
import sqlite3
import os
from contextlib import contextmanager
from config import config


def get_db_path():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    return config.DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表"""
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS up_masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            status TEXT DEFAULT 'idle',
            last_scan_at TEXT,
            total_videos INTEGER DEFAULT 0,
            processed_videos INTEGER DEFAULT 0,
            failed_videos INTEGER DEFAULT 0,
            shell_notes_created INTEGER DEFAULT 0,
            note_profile TEXT DEFAULT 'ai_watch_l1',
            provider_strategy TEXT DEFAULT 'auto_low_cost',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bvid TEXT NOT NULL,
            up_id INTEGER REFERENCES up_masters(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            duration TEXT DEFAULT '',
            play_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            note_path TEXT DEFAULT '',
            note_file TEXT DEFAULT '',
            source TEXT DEFAULT '',
            note_profile TEXT DEFAULT 'ai_watch_l1',
            provider_strategy TEXT DEFAULT 'auto_low_cost',
            error_msg TEXT,
            processed_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(bvid, up_id)
        );

        CREATE TABLE IF NOT EXISTS process_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            up_id INTEGER,
            video_id INTEGER,
            event TEXT DEFAULT '',
            status TEXT DEFAULT '',
            source TEXT DEFAULT '',
            message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_videos_up_id ON videos(up_id);
        CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
        CREATE INDEX IF NOT EXISTS idx_videos_bvid ON videos(bvid);
        CREATE INDEX IF NOT EXISTS idx_logs_up_id ON process_logs(up_id);

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'idle',
            total_chapters INTEGER DEFAULT 0,
            processed_chapters INTEGER DEFAULT 0,
            failed_chapters INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS doc_chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            chapter_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            note_path TEXT DEFAULT '',
            note_file TEXT DEFAULT '',
            error_msg TEXT,
            processed_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(doc_id, chapter_index)
        );

        CREATE INDEX IF NOT EXISTS idx_doc_chapters_doc_id ON doc_chapters(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_chapters_status ON doc_chapters(status);
        """)

        for table, column, ddl in [
            ("up_masters", "note_profile", "TEXT DEFAULT 'ai_watch_l1'"),
            ("up_masters", "provider_strategy", "TEXT DEFAULT 'auto_low_cost'"),
            ("videos", "note_profile", "TEXT DEFAULT 'ai_watch_l1'"),
            ("videos", "provider_strategy", "TEXT DEFAULT 'auto_low_cost'"),
        ]:
            cols = [r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
            if column not in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
