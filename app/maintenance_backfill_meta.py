"""Slowly backfill missing video duration/play count metadata."""
import time

from db import get_db
from scheduler import backfill_missing_video_meta


def main():
    with get_db() as db:
        up_ids = [row[0] for row in db.execute("SELECT id FROM up_masters ORDER BY id").fetchall()]

    print("start slow meta backfill", flush=True)
    for up_id in up_ids:
        total = 0
        while True:
            changed = backfill_missing_video_meta(up_id, limit=8)
            total += changed
            print(f"up_id={up_id} batch={changed} total={total}", flush=True)
            if changed <= 0:
                break
            time.sleep(12)
    print("done slow meta backfill", flush=True)


if __name__ == "__main__":
    main()
