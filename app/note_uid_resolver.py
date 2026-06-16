#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Optional

import requests

SPACE_RE = re.compile(r"space\.bilibili\.com/(\d+)")
BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
UP_RE = re.compile(r'^up:\s*"?(.+?)"?$', re.IGNORECASE)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bilibili.com/",
}


def iter_markdown_files(path: Path):
    if path.is_file() and path.suffix.lower() == '.md':
        yield path
        return
    if path.is_dir():
        for p in sorted(path.rglob('*.md')):
            yield p


def fetch_owner_from_bvid(bvid: str) -> Optional[dict]:
    r = requests.get(
        'https://api.bilibili.com/x/web-interface/view',
        params={'bvid': bvid},
        headers=HEADERS,
        timeout=20,
    )
    if not r.ok:
        return None
    data = r.json().get('data') or {}
    owner = data.get('owner') or {}
    if not owner.get('mid'):
        return None
    return {
        'uid': str(owner['mid']),
        'up_name': owner.get('name', ''),
        'title': data.get('title', ''),
        'bvid': bvid,
    }


def resolve_from_notes(path: Path) -> dict:
    found = {
        'path': str(path),
        'uid': None,
        'up_name': None,
        'sample_bvid': None,
        'sample_title': None,
        'matched_space_url': None,
        'matched_file': None,
        'match_source': None,
    }

    candidate_bvids = []

    for md in iter_markdown_files(path):
        try:
            text = md.read_text(encoding='utf-8')
        except Exception:
            continue

        if not found['up_name']:
            for line in text.splitlines()[:40]:
                m = UP_RE.match(line.strip())
                if m:
                    found['up_name'] = m.group(1).strip()
                    break

        m = SPACE_RE.search(text)
        if m:
            found['uid'] = m.group(1)
            found['matched_space_url'] = f'https://space.bilibili.com/{m.group(1)}'
            found['matched_file'] = str(md)
            found['match_source'] = 'space_url'
            return found

        for bvid in BVID_RE.findall(text):
            if bvid not in candidate_bvids:
                candidate_bvids.append(bvid)
                if not found['sample_bvid']:
                    found['sample_bvid'] = bvid
                    found['matched_file'] = str(md)

    for bvid in candidate_bvids[:8]:
        owner = fetch_owner_from_bvid(bvid)
        if owner:
            found['uid'] = owner['uid']
            found['up_name'] = found['up_name'] or owner['up_name']
            found['sample_bvid'] = bvid
            found['sample_title'] = owner['title']
            found['matched_space_url'] = f'https://space.bilibili.com/{owner["uid"]}'
            found['match_source'] = 'bvid_lookup'
            return found

    return found


def add_to_biliflow(space_url: str, base_url: str) -> dict:
    r = requests.post(f'{base_url.rstrip("/")}/api/up', files={'url': (None, space_url)}, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {'raw': r.text}
    return {'status_code': r.status_code, 'response': data}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--add', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:8866')
    args = parser.parse_args()

    resolved = resolve_from_notes(Path(args.path))
    if args.add and resolved.get('matched_space_url'):
        resolved['add_result'] = add_to_biliflow(resolved['matched_space_url'], args.base_url)
    print(json.dumps(resolved, ensure_ascii=False, indent=2))

