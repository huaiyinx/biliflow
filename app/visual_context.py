"""
Lightweight visual context for AI Watch notes.

Level 1 extracts sparse keyframes and OCRs screen/PPT text. It is intentionally
cheap: no full video multimodal call, no permanent video archive.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "video").strip("_")[:80]


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _download_preview_video(bvid: str, work_dir: str) -> str | None:
    """Download a low-res video-only preview suitable for frame OCR."""
    os.makedirs(work_dir, exist_ok=True)
    output_tpl = os.path.join(work_dir, f"{_safe_name(bvid)}.%(ext)s")
    url = f"https://www.bilibili.com/video/{bvid}"
    args = [
        "yt-dlp",
        url,
        "-f",
        "worstvideo[ext=mp4]/worstvideo/bestvideo[height<=480][ext=mp4]/bestvideo[height<=480]",
        "--no-playlist",
        "--socket-timeout",
        "20",
        "--no-warnings",
        "-o",
        output_tpl,
    ]
    result = _run(args, timeout=240)
    if not result or result.returncode != 0:
        return None
    for path in sorted(Path(work_dir).glob(f"{_safe_name(bvid)}.*")):
        if path.suffix.lower() in {".mp4", ".m4v", ".webm", ".flv"} and path.stat().st_size > 1024:
            return str(path)
    return None


def _extract_frames(video_path: str, frames_dir: str, interval_seconds: int, max_frames: int) -> list[str]:
    os.makedirs(frames_dir, exist_ok=True)
    for old in Path(frames_dir).glob("frame_*.jpg"):
        try:
            old.unlink()
        except Exception:
            pass
    pattern = os.path.join(frames_dir, "frame_%03d.jpg")
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vf",
        f"fps=1/{max(10, interval_seconds)},scale=960:-1",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "3",
        pattern,
        "-y",
    ]
    result = _run(args, timeout=180)
    if not result or result.returncode != 0:
        return []
    return [str(p) for p in sorted(Path(frames_dir).glob("frame_*.jpg"))]


def _ocr_frame(frame_path: str) -> str:
    if not shutil.which("tesseract"):
        return ""
    result = _run(
        ["tesseract", frame_path, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
        timeout=30,
    )
    if not result or result.returncode != 0:
        return ""
    text = re.sub(r"\s+", " ", result.stdout or "").strip()
    # Drop tiny/noisy OCR fragments.
    if len(text) < 8:
        return ""
    return text[:500]


def build_visual_context(
    bvid: str,
    project_dir: str,
    interval_seconds: int = 45,
    max_frames: int = 30,
) -> dict:
    """Return sparse OCR context for a Bilibili video.

    The returned dict is safe to pass into an LLM prompt. Failures are reported
    in `status` and should not fail the main note pipeline.
    """
    visual_root = os.path.join(project_dir, "visual", _safe_name(bvid))
    video_dir = os.path.join(visual_root, "video")
    frames_dir = os.path.join(visual_root, "frames")
    os.makedirs(visual_root, exist_ok=True)

    result = {
        "status": "skipped",
        "frames": [],
        "ocr_blocks": [],
        "summary_text": "",
    }

    video_path = None
    try:
        video_path = _download_preview_video(bvid, video_dir)
        if not video_path:
            result["status"] = "download_failed"
            return result

        frames = _extract_frames(video_path, frames_dir, interval_seconds, max_frames)
        if not frames:
            result["status"] = "frame_failed"
            return result

        ocr_blocks = []
        for idx, frame in enumerate(frames, start=1):
            text = _ocr_frame(frame)
            if text:
                approx_seconds = (idx - 1) * interval_seconds
                mm, ss = divmod(approx_seconds, 60)
                ocr_blocks.append({
                    "time": f"{mm:02d}:{ss:02d}",
                    "frame": frame,
                    "text": text,
                })

        result["frames"] = frames
        result["ocr_blocks"] = ocr_blocks
        if ocr_blocks:
            result["status"] = "ok"
            lines = [
                f"- [{block['time']}] {block['text']}"
                for block in ocr_blocks[:max_frames]
            ]
            result["summary_text"] = "\n".join(lines)[:6000]
        else:
            result["status"] = "no_ocr"
        return result
    except Exception as exc:
        result["status"] = f"error:{type(exc).__name__}"
        return result
    finally:
        if video_path:
            try:
                os.remove(video_path)
            except Exception:
                pass
