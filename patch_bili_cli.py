from pathlib import Path

path = Path('/usr/local/lib/python3.12/site-packages/bili_cli/client.py')
text = path.read_text(encoding='utf-8')
old = '''async def get_audio_url(bvid: str, credential: Credential | None = None) -> str:
    """Get the best audio stream URL for a video (DASH preferred)."""
    from bilibili_api.video import AudioQuality, VideoDownloadURLDataDetecter

    v = video.Video(bvid=bvid, credential=credential)
    download_data = await _call_api("获取下载地址", v.get_download_url(page_index=0))
    detector = VideoDownloadURLDataDetecter(download_data)
    streams = detector.detect_best_streams(
        audio_max_quality=AudioQuality._64K,
        no_dolby_audio=True,
        no_hires=True,
    )

    if detector.check_flv_mp4_stream():
        if streams and streams[0] and hasattr(streams[0], "url"):
            return streams[0].url
    else:
        # DASH: audio is at index 1
        if len(streams) >= 2 and streams[1] is not None and hasattr(streams[1], "url"):
            return streams[1].url
        # Fallback: find any stream with audio_quality
        for s in streams:
            if s is not None and hasattr(s, "audio_quality"):
                return s.url

    raise BiliError("无法获取音频流（可能是会员专属视频）")
'''
new = '''async def get_audio_url(bvid: str, credential: Credential | None = None) -> str:
    """Get the best audio stream URL for a video (DASH preferred)."""
    from bilibili_api.video import AudioQuality, VideoDownloadURLDataDetecter

    v = video.Video(bvid=bvid, credential=credential)
    download_data = await _call_api("获取下载地址", v.get_download_url(page_index=0))

    dash = (download_data or {}).get("dash") or {}
    audio_tracks = dash.get("audio") or []
    if audio_tracks:
        def _audio_sort_key(track: dict):
            return (
                int(track.get("id") or 0),
                int(track.get("bandwidth") or 0),
            )

        best_audio = sorted(audio_tracks, key=_audio_sort_key, reverse=True)[0]
        for key in ("baseUrl", "base_url"):
            if best_audio.get(key):
                return best_audio[key]
        for backup_key in ("backupUrl", "backup_url"):
            backups = best_audio.get(backup_key) or []
            if backups:
                return backups[0]

    detector = VideoDownloadURLDataDetecter(download_data)
    try:
        streams = detector.detect_best_streams(
            audio_max_quality=AudioQuality._64K,
            no_dolby_audio=True,
            no_hires=True,
        )
    except Exception as exc:
        raise BiliError(f"无法获取音频流: {exc}") from exc

    if detector.check_flv_mp4_stream():
        if streams and streams[0] and hasattr(streams[0], "url"):
            return streams[0].url
    else:
        if len(streams) >= 2 and streams[1] is not None and hasattr(streams[1], "url"):
            return streams[1].url
        for s in streams:
            if s is not None and hasattr(s, "audio_quality"):
                return s.url

    raise BiliError("无法获取音频流（可能是会员专属视频）")
'''
if old not in text:
    raise SystemExit('target function block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('patched bili_cli client.py')
