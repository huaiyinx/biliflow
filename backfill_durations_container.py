import time
import sqlite3
from bili_api import enrich_video_meta

DB_PATH = '/app/data/bili.db'
UP_IDS = [17, 16, 15, 13, 10, 9]

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
placeholders = ','.join('?' for _ in UP_IDS)
query = f"""
select id,bvid,title,duration,play_count,up_id
from videos
where up_id in ({placeholders}) and duration in ('00:00','','?')
order by up_id desc, id desc
"""
rows = conn.execute(query, UP_IDS).fetchall()
print('targets', len(rows))
updated = 0
for idx, row in enumerate(rows, 1):
    item = {
        'bvid': row['bvid'],
        'title': row['title'],
        'duration': row['duration'],
        'play_count': row['play_count'],
    }
    new_item = enrich_video_meta(item, force=True)
    duration = str(new_item.get('duration') or '')
    if duration and duration not in ('00:00', '', '?'):
        conn.execute(
            'update videos set title=?, duration=?, play_count=? where id=?',
            (
                new_item.get('title', row['title']),
                duration,
                int(new_item.get('play_count') or row['play_count'] or 0),
                row['id'],
            ),
        )
        updated += 1
    if idx % 20 == 0:
        conn.commit()
        print('progress', idx, 'updated', updated)
        time.sleep(1)
conn.commit()
print('done updated', updated)
for up_id in UP_IDS:
    c = conn.execute(
        "select count(*) from videos where up_id=? and duration in ('00:00','','?')",
        (up_id,),
    ).fetchone()[0]
    print('remaining', up_id, c)
conn.close()
