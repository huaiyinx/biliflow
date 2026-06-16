import sqlite3
from bili_api import enrich_video_meta

conn = sqlite3.connect('/app/data/bili.db', timeout=30)
conn.row_factory = sqlite3.Row
rows = conn.execute("select id,bvid,title,duration,play_count from videos where up_id=15 and duration in ('00:00','','?') order by id").fetchall()
print('targets', len(rows))
updated = 0
for row in rows:
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
conn.commit()
print('updated', updated)
print('remaining', conn.execute("select count(*) from videos where up_id=15 and duration in ('00:00','','?')").fetchone()[0])
for row in conn.execute("select bvid,title,duration,play_count from videos where up_id=15 order by id limit 5"):
    print(tuple(row))
conn.close()
