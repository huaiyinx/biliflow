"""
BiliFlow — B站视频笔记自动化系统
FastAPI 主应用
"""
import os
import json
import time
import threading
import requests
import base64
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uuid
import shutil
import subprocess

from config import config
from db import get_db, init_db
from ai_watch_context import build_visual_context
from ai_watch_providers import AIWatchProviderError, run_ai_watch_image
from provider_registry import get_provider_status, recommended_models
from bili_api import (
    extract_bvid_from_url,
    extract_uid_from_url,
    get_all_videos,
    get_my_info,
    get_up_info,
    get_video_info,
    load_bili_cookie,
)
from scheduler import (
    start_scheduler, check_and_process, is_processing,
    create_shell_notes_batch, run_pipeline_for_up, update_moc,
    mark_processing,
)
from pipeline import process_document_pipeline

app = FastAPI(title="BiliFlow", version="1.0.0")

NOTE_PROFILES = {
    "ai_watch_l0": "字幕版",
    "ai_watch_l1": "字幕+关键帧OCR",
    "ai_watch_l2": "字幕+OCR+关键帧视觉",
    "ai_watch_l3": "全视频理解",
}

PROVIDER_STRATEGIES = {
    "auto_low_cost": "自动低成本",
    "bili_free_first": "B站免费优先",
    "gemini_youtube_first": "YouTube Gemini优先",
    "baidu_qianfan_first": "百度千帆优先",
    "manual": "手动/暂不自动选择",
}

AI_WATCH_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
AI_WATCH_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


def normalize_note_profile(value: str | None) -> str:
    value = (value or "ai_watch_l1").strip()
    return value if value in NOTE_PROFILES else "ai_watch_l1"


def normalize_provider_strategy(value: str | None) -> str:
    value = (value or "auto_low_cost").strip()
    return value if value in PROVIDER_STRATEGIES else "auto_low_cost"


class ProviderTestRequest(BaseModel):
    task: str = "ocr"
    image_url: str
    prompt: str | None = None


class VisualFrameResult(BaseModel):
    index: int
    timestamp: float = 0
    provider: str | None = None
    model: str | None = None
    content: str


class VisualContextRequest(BaseModel):
    frames: list[VisualFrameResult]
    bvid: str | None = None
    save: bool = False

# 静态文件 + 模板
os.makedirs("/app/static", exist_ok=True)
os.makedirs("/app/templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="/app/static"), name="static")
templates = Jinja2Templates(directory="/app/templates")

# 启动时初始化
@app.on_event("startup")
async def startup():
    init_db()
    # 清理残留状态 & 同步计数
    with get_db() as db:
        db.execute("UPDATE up_masters SET status='idle' WHERE status='processing'")
        # 同步 processed/failed 计数
        db.execute("""
            UPDATE up_masters SET
                processed_videos = (SELECT COUNT(*) FROM videos WHERE up_id = up_masters.id AND status IN ('ok','done')),
                failed_videos = (SELECT COUNT(*) FROM videos WHERE up_id = up_masters.id AND status = 'fail')
        """)
    start_scheduler()


# ===== 页面路由 =====

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """总控面板"""
    with get_db() as db:
        ups = db.execute(
            "SELECT * FROM up_masters ORDER BY created_at DESC"
        ).fetchall()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "ups": ups,
        "domain": config.DOMAIN,
        "note_profiles": NOTE_PROFILES,
        "provider_strategies": PROVIDER_STRATEGIES,
    })


@app.get("/add", response_class=HTMLResponse)
async def add_page(request: Request):
    """添加 UP主 页面"""
    return templates.TemplateResponse("add.html", {
        "request": request,
        "domain": config.DOMAIN,
        "note_profiles": NOTE_PROFILES,
        "provider_strategies": PROVIDER_STRATEGIES,
    })


@app.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    """AI Watch provider pool and budget guard page."""
    providers = get_provider_status()
    return templates.TemplateResponse("providers.html", {
        "request": request,
        "domain": config.DOMAIN,
        "providers": providers,
        "budget_cny": config.AI_WATCH_MAX_VISUAL_COST_CNY,
        "require_free_first": config.AI_WATCH_REQUIRE_FREE_FIRST,
    })


@app.get("/up/{up_name}", response_class=HTMLResponse)
async def project_page(request: Request, up_name: str):
    """单 UP主 详情页"""
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")

        videos = db.execute(
            "SELECT * FROM videos WHERE up_id = ? ORDER BY created_at DESC",
            (up["id"],),
        ).fetchall()

    # 读取进度
    progress = {}
    progress_file = os.path.join(config.PROJECTS_DIR, up_name, "progress.json")
    if os.path.exists(progress_file):
        try:
            progress = json.load(open(progress_file, encoding="utf-8"))
        except Exception:
            pass

    return templates.TemplateResponse("project.html", {
        "request": request,
        "up": up,
        "videos": videos,
        "progress": progress,
        "domain": config.DOMAIN,
        "note_profiles": NOTE_PROFILES,
        "provider_strategies": PROVIDER_STRATEGIES,
    })


@app.get("/up/{up_name}/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, up_name: str):
    """实时进度看板 (独立 HTML)"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "up_name": up_name,
        "domain": config.DOMAIN,
    })


# ===== API 路由 =====

@app.get("/api/stats")
async def api_stats():
    """全局统计"""
    with get_db() as db:
        total_ups = db.execute("SELECT COUNT(*) FROM up_masters").fetchone()[0]
        total_videos = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        done = db.execute(
            "SELECT COUNT(*) FROM videos WHERE status IN ('ok', 'done')"
        ).fetchone()[0]
        failed = db.execute(
            "SELECT COUNT(*) FROM videos WHERE status = 'fail'"
        ).fetchone()[0]
        processing = db.execute(
            "SELECT COUNT(*) FROM up_masters WHERE status = 'processing'"
        ).fetchone()[0]
    return {
        "total_ups": total_ups,
        "total_videos": total_videos,
        "done_videos": done,
        "failed_videos": failed,
        "processing_ups": processing,
        "pct": round(done / total_videos * 100) if total_videos else 0,
    }


@app.get("/api/up/{up_id}/avatar")
async def api_up_avatar(up_id: int):
    """服务端代理头像，避免浏览器直连 hdslb 被 403。"""
    with get_db() as db:
        row = db.execute("SELECT avatar FROM up_masters WHERE id = ?", (up_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "头像不存在")

    avatar_url = row[0]
    try:
        r = requests.get(
            avatar_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://space.bilibili.com/",
            },
            timeout=20,
        )
        if r.status_code != 200:
            raise HTTPException(r.status_code, "头像拉取失败")
        media_type = r.headers.get("content-type", "image/jpeg")
        return Response(
            content=r.content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"头像代理失败: {e}")


@app.get("/api/up")
async def api_list_ups():
    """列出所有 UP主"""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM up_masters ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/providers")
async def api_providers():
    """Return provider pool status without exposing API keys."""
    return {
        "budget_cny": config.AI_WATCH_MAX_VISUAL_COST_CNY,
        "require_free_first": config.AI_WATCH_REQUIRE_FREE_FIRST,
        "providers": get_provider_status(),
        "recommended": {
            "ocr": recommended_models("ocr"),
            "vision": recommended_models("vision"),
            "youtube_video": recommended_models("youtube_video"),
        },
    }


@app.post("/api/providers/test")
async def api_providers_test(req: ProviderTestRequest):
    """Run a small cloud OCR/vision smoke test against the provider pool."""
    task = req.task if req.task in {"ocr", "vision"} else "vision"
    try:
        return run_ai_watch_image(
            task=task,
            image_url=req.image_url,
            prompt=req.prompt,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except AIWatchProviderError as e:
        return JSONResponse(
            status_code=502,
            content={
                "status": "failed",
                "message": str(e),
                "attempts": e.attempts,
            },
        )
    except Exception as e:
        raise HTTPException(500, f"provider test failed: {e}")


@app.post("/api/providers/test-file")
async def api_providers_test_file(
    task: str = Form("ocr"),
    prompt: str | None = Form(None),
    file: UploadFile = File(...),
):
    """Run cloud OCR/vision on a small uploaded image without storing it."""
    task = task if task in {"ocr", "vision"} else "vision"
    content_type = (file.content_type or "").lower()
    if content_type not in AI_WATCH_IMAGE_TYPES:
        raise HTTPException(400, "只支持 jpg/png/webp/gif 图片")

    data = await file.read()
    if not data:
        raise HTTPException(400, "图片为空")
    if len(data) > AI_WATCH_MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片不能超过 5MB")

    image_data_url = (
        f"data:{content_type};base64,"
        f"{base64.b64encode(data).decode('ascii')}"
    )
    try:
        result = run_ai_watch_image(
            task=task,
            image_url=image_data_url,
            prompt=prompt,
        )
        result["source"] = "upload"
        result["filename"] = file.filename
        return result
    except AIWatchProviderError as e:
        return JSONResponse(
            status_code=502,
            content={
                "status": "failed",
                "message": str(e),
                "attempts": e.attempts,
            },
        )
    except Exception as e:
        raise HTTPException(500, f"provider file test failed: {e}")


@app.post("/api/providers/visual-context")
async def api_providers_visual_context(req: VisualContextRequest):
    """Compress multiple frame OCR/vision outputs into Markdown visual_context."""
    if not req.frames:
        raise HTTPException(400, "frames 不能为空")
    if len(req.frames) > 12:
        raise HTTPException(400, "一次最多合并 12 帧")
    bvid = (req.bvid or "").strip()
    video_id = None
    if req.save and bvid:
        with get_db() as db:
            row = db.execute(
                "SELECT id FROM videos WHERE bvid = ? ORDER BY id DESC LIMIT 1",
                (bvid,),
            ).fetchone()
            if not row:
                raise HTTPException(404, f"未找到视频 {bvid}")
            video_id = row["id"]
    frames = [
        frame.model_dump() if hasattr(frame, "model_dump") else frame.dict()
        for frame in req.frames
    ]
    result = build_visual_context(frames)
    if video_id and result.get("visual_context"):
        with get_db() as db:
            db.execute(
                """
                UPDATE videos
                   SET visual_context = ?,
                       visual_context_source = ?,
                       visual_context_frame_count = ?,
                       visual_context_updated_at = datetime('now','localtime')
                 WHERE id = ?
                """,
                (
                    result["visual_context"],
                    result.get("source", ""),
                    result.get("frame_count", 0),
                    video_id,
                ),
            )
        result["saved"] = True
        result["bvid"] = bvid
    return result


@app.post("/api/up")
async def api_add_up(
    url: str = Form(...),
    note_profile: str = Form("ai_watch_l1"),
    provider_strategy: str = Form("auto_low_cost"),
    background_tasks: BackgroundTasks = None,
):
    """添加 UP主"""
    input_str = url.strip()
    note_profile = normalize_note_profile(note_profile)
    provider_strategy = normalize_provider_strategy(provider_strategy)
    uid = None

    bvid = extract_bvid_from_url(input_str)
    if bvid:
        video = get_video_info(bvid)
        if not video:
            raise HTTPException(400, f"无法获取视频信息: {bvid}")

        uid = video.get("owner_uid", "")
        if not uid:
            raise HTTPException(400, f"视频 {bvid} 缺少 UP 主信息，暂无法入库")

        info = get_up_info(uid) or {}
        name = info.get("name") or video.get("owner_name") or uid
        avatar = info.get("avatar", "")

        with get_db() as db:
            existing = db.execute(
                "SELECT * FROM up_masters WHERE uid = ?", (uid,)
            ).fetchone()
            if existing:
                up_id = existing["id"]
                db.execute(
                    "UPDATE up_masters SET name = ?, avatar = COALESCE(NULLIF(?, ''), avatar), note_profile = ?, provider_strategy = ? WHERE id = ?",
                    (name, avatar, note_profile, provider_strategy, up_id),
                )
            else:
                db.execute(
                    "INSERT INTO up_masters (uid, name, avatar, status, note_profile, provider_strategy) VALUES (?,?,?,'idle',?,?)",
                    (uid, name, avatar, note_profile, provider_strategy),
                )
                up_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            existing_video = db.execute(
                "SELECT id, status, title, note_path, note_file, note_profile, provider_strategy, visual_context, visual_context_source FROM videos WHERE up_id = ? AND bvid = ?",
                (up_id, bvid),
            ).fetchone()

        if existing_video and existing_video["note_path"]:
            shell_notes = [{
                "bvid": bvid,
                "title": existing_video["title"] or video["title"],
                "note_path": existing_video["note_path"],
                "note_file": existing_video["note_file"],
                "note_profile": existing_video["note_profile"] or note_profile,
                "provider_strategy": existing_video["provider_strategy"] or provider_strategy,
                "visual_context": existing_video["visual_context"] or "",
                "visual_context_source": existing_video["visual_context_source"] or "",
            }]
        else:
            shell_notes = create_shell_notes_batch(name, uid, up_id, [video])
        if shell_notes and not is_processing(name):
            t = threading.Thread(
                target=run_pipeline_for_up,
                args=(name, up_id, shell_notes),
                daemon=True,
            )
            t.start()

        return {
            "status": "video_updated" if existing_video else "video_created",
            "up_name": name,
            "bvid": bvid,
            "new_videos": 0 if existing_video else 1,
            "url": f"https://{config.DOMAIN}/up/{name}",
            "message": "已识别为单个视频链接，并加入 BiliFlow 处理。",
        }
    
    if "bilibili.com" in input_str or input_str.startswith("http"):
        uid = extract_uid_from_url(input_str)
        if not uid:
            raise HTTPException(400, "无法解析链接中的 UID 或 BV号，请检查链接")
    else:
        from bili_api import search_up_uid_by_name
        uid = search_up_uid_by_name(input_str)
        if not uid:
            raise HTTPException(400, f"未找到名为 '{input_str}' 的 UP主")

    # 获取 UP主 信息

    info = get_up_info(uid)
    if not info:
        cookie_ok = bool(load_bili_cookie())
        msg = (
            "已登录但仍无法获取？请检查UID是否正确" if cookie_ok
            else "请先 <a href='/login'>扫码登录 B站</a>"
        )
        raise HTTPException(400, msg)

    name = info["name"]
    avatar = info.get("avatar", "")

    # 检查是否已存在
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM up_masters WHERE uid = ?", (uid,)
        ).fetchone()
        if existing:
            # 已存在，顺手刷新名称/头像，再扫描新视频
            db.execute(
                "UPDATE up_masters SET name = ?, avatar = COALESCE(NULLIF(?, ''), avatar), note_profile = ?, provider_strategy = ? WHERE id = ?",
                (name, avatar, note_profile, provider_strategy, existing["id"]),
            )
            known = set(
                r[0] for r in db.execute(
                    "SELECT bvid FROM videos WHERE up_id = ?", (existing["id"],)
                ).fetchall()
            )
            from bili_api import get_new_videos
            new_videos = get_new_videos(uid, known, up_name=name)
            if new_videos:
                shell_notes = create_shell_notes_batch(
                    name, uid, existing["id"], new_videos
                )
                if shell_notes:
                    if is_processing(name) or existing["status"] == "processing":
                        return {
                            "status": "updated_busy",
                            "up_name": name,
                            "new_videos": len(new_videos),
                            "url": f"https://{config.DOMAIN}/up/{name}",
                            "message": f"已扫描到 {len(new_videos)} 个新视频。由于该 UP 主正在处理中，新视频已加入排队。",
                        }
                    t = threading.Thread(
                        target=run_pipeline_for_up,
                        args=(name, existing["id"], shell_notes),
                        daemon=True,
                    )
                    t.start()
                return {
                    "status": "updated",
                    "up_name": name,
                    "new_videos": len(new_videos),
                    "url": f"https://{config.DOMAIN}/up/{name}",
                }
            return {
                "status": "exists",
                "up_name": name,
                "url": f"https://{config.DOMAIN}/up/{name}",
            }

        # 新 UP主
        db.execute(
            "INSERT INTO up_masters (uid, name, avatar, status, note_profile, provider_strategy) VALUES (?,?,?,'scanning',?,?)",
            (uid, name, avatar, note_profile, provider_strategy),
        )
        up_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 后台扫描视频
    def scan_and_create():
        try:
            videos = get_all_videos(uid)
            if videos:
                shell_notes = create_shell_notes_batch(name, uid, up_id, videos)
                with get_db() as db:
                    db.execute(
                        "UPDATE up_masters SET status='idle' WHERE id=?",
                        (up_id,),
                    )
                # 自动开始处理
                if shell_notes:
                    run_pipeline_for_up(name, up_id, shell_notes)
            else:
                with get_db() as db:
                    db.execute(
                        "UPDATE up_masters SET status='idle' WHERE id=?",
                        (up_id,),
                    )
        except Exception as e:
            print(f"首次扫描 UP主 {name} 失败: {e}")
            with get_db() as db:
                db.execute(
                    "UPDATE up_masters SET status='idle' WHERE id=?",
                    (up_id,),
                )

    t = threading.Thread(target=scan_and_create, daemon=True)
    t.start()

    return {
        "status": "created",
        "up_name": name,
        "uid": uid,
        "url": f"https://{config.DOMAIN}/up/{name}",
    }


@app.post("/api/up/{up_name}/scan")
async def api_scan_up(up_name: str):
    """扫描 UP主 新视频"""
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")

    if is_processing(up_name):
        return {"status": "busy", "message": f"{up_name} 正在处理中"}

    # 后台扫描
    def do_scan():
        with get_db() as db:
            up_row = db.execute(
                "SELECT * FROM up_masters WHERE name = ?", (up_name,)
            ).fetchone()
        if not up_row:
            return
        check_and_process(up_name)

    t = threading.Thread(target=do_scan, daemon=True)
    t.start()

    return {"status": "scanning", "up_name": up_name}


@app.post("/api/up/{up_name}/process")
async def api_process_up(up_name: str):
    """启动/重启处理 UP主 视频"""
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")

        # 获取所有 pending 视频
        videos = db.execute(
            "SELECT bvid, title, note_path, note_file, note_profile, provider_strategy, visual_context, visual_context_source FROM videos WHERE up_id = ? AND status = 'pending'",
            (up["id"],),
        ).fetchall()

    if not videos:
        return {"status": "nothing", "message": "没有待处理的视频"}

    if is_processing(up_name):
        return {"status": "busy", "message": f"{up_name} 正在处理中"}

    video_list = [
        {"bvid": v["bvid"], "title": v["title"], "note_path": v["note_path"]}
        | {
            "note_profile": v["note_profile"] or up["note_profile"],
            "provider_strategy": v["provider_strategy"] or up["provider_strategy"],
            "visual_context": v["visual_context"] or "",
            "visual_context_source": v["visual_context_source"] or "",
        }
        for v in videos
    ]

    t = threading.Thread(
        target=run_pipeline_for_up,
        args=(up_name, up["id"], video_list),
        daemon=True,
    )
    t.start()

    return {"status": "started", "up_name": up_name, "count": len(video_list)}


@app.get("/api/up/{up_name}/progress")
async def api_get_progress(up_name: str):
    """获取处理进度"""
    progress_file = os.path.join(config.PROJECTS_DIR, up_name, "progress.json")
    if os.path.exists(progress_file):
        try:
            return json.load(open(progress_file, encoding="utf-8"))
        except Exception:
            pass

    # 从数据库推算
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")
        done = up["processed_videos"]
        fail = up["failed_videos"]
        total = up["total_videos"]
    return {
        "up": up_name,
        "total": total,
        "ok": done,
        "fail": fail,
        "current": done + fail,
        "pct": round((done + fail) / max(total, 1) * 100),
        "done": done + fail >= total,
    }


@app.post("/api/up/{up_name}/settings")
async def api_update_up_settings(
    up_name: str,
    note_profile: str = Form(...),
    provider_strategy: str = Form(...),
    apply_pending: str = Form("1"),
):
    """更新 UP 主默认 AI看策略，并可同步到未处理视频。"""
    note_profile = normalize_note_profile(note_profile)
    provider_strategy = normalize_provider_strategy(provider_strategy)
    should_apply_pending = str(apply_pending).lower() not in {"0", "false", "no", "off"}

    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")

        db.execute(
            "UPDATE up_masters SET note_profile = ?, provider_strategy = ? WHERE id = ?",
            (note_profile, provider_strategy, up["id"]),
        )

        changed = 0
        if should_apply_pending:
            cur = db.execute(
                """
                UPDATE videos
                   SET note_profile = ?, provider_strategy = ?
                 WHERE up_id = ?
                   AND status IN ('pending', 'fail', 'failed')
                """,
                (note_profile, provider_strategy, up["id"]),
            )
            changed = cur.rowcount or 0

    return {
        "status": "ok",
        "note_profile": note_profile,
        "provider_strategy": provider_strategy,
        "pending_updated": changed,
    }


@app.delete("/api/up/{up_name}")
async def api_delete_up(up_name: str):
    """删除 UP主（保留笔记文件）"""
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")
        db.execute("DELETE FROM videos WHERE up_id = ?", (up["id"],))
        db.execute("DELETE FROM process_logs WHERE up_id = ?", (up["id"],))
        db.execute("DELETE FROM up_masters WHERE id = ?", (up["id"],))
    return {"status": "deleted", "up_name": up_name}


@app.post("/api/up/{up_name}/retry-failed")
async def api_retry_failed(up_name: str):
    """重试失败的视频"""
    with get_db() as db:
        up = db.execute(
            "SELECT * FROM up_masters WHERE name = ?", (up_name,)
        ).fetchone()
        if not up:
            raise HTTPException(404, "UP主不存在")

        failed = db.execute(
            "SELECT bvid, title, note_path, note_profile, provider_strategy, visual_context, visual_context_source FROM videos WHERE up_id = ? AND status IN ('fail', 'failed')",
            (up["id"],),
        ).fetchall()

    if not failed:
        return {"status": "nothing", "message": "没有失败的视频"}

    if is_processing(up_name):
        return {"status": "busy"}

    video_list = [
        {"bvid": v["bvid"], "title": v["title"], "note_path": v["note_path"]}
        | {
            "note_profile": v["note_profile"] or up["note_profile"],
            "provider_strategy": v["provider_strategy"] or up["provider_strategy"],
            "visual_context": v["visual_context"] or "",
            "visual_context_source": v["visual_context_source"] or "",
        }
        for v in failed
    ]

    t = threading.Thread(
        target=run_pipeline_for_up,
        args=(up_name, up["id"], video_list),
        daemon=True,
    )
    t.start()

    return {"status": "started", "up_name": up_name, "count": len(video_list)}


# ===== 登录管理 =====

_login_process = None
_login_qrcode = ""
_login_status = {"logged_in": False, "message": "未登录"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """扫码登录页面"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "domain": config.DOMAIN,
    })


@app.post("/api/login/start")
async def api_login_start():
    """启动扫码登录，返回二维码文本"""
    global _login_process, _login_qrcode, _login_status
    import subprocess, threading

    try:
        # 启动 bili login 进程
        proc = subprocess.Popen(
            ["bili", "login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # 读取二维码输出（前几秒的内容）
        output = []
        def read_qr():
            global _login_qrcode, _login_status
            for line in iter(proc.stdout.readline, ""):
                output.append(line)
                if "扫码后" in line:
                    break
            _login_qrcode = "".join(output)

            # 等待进程结束
            proc.wait()
            if proc.returncode == 0:
                _login_status = {"logged_in": True, "message": "登录成功！"}
            else:
                _login_status = {"logged_in": False, "message": f"登录失败: {proc.stderr.read()[:200]}"}

        threading.Thread(target=read_qr, daemon=True).start()
        _login_process = proc

        # 等待几秒获取二维码
        import time
        time.sleep(3)

        return {"status": "ok", "qrcode": _login_qrcode or "二维码生成中..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/login/status")
async def api_login_status():
    """检查登录状态"""
    global _login_status
    # 也检查实际 CLI 状态
    import subprocess
    try:
        r = subprocess.run(["bili", "status"], capture_output=True, text=True, timeout=5)
        if "ok: true" in r.stdout:
            _login_status = {"logged_in": True, "message": "已登录"}
            return _login_status
    except Exception:
        pass
    return _login_status


@app.get("/api/me")
async def api_me():
    """当前 B站 用户信息"""
    info = get_my_info()
    if info:
        return {"logged_in": True, **info}
    return {"logged_in": False}


# ===== 文档/书籍处理模块 =====

@app.get("/library", response_class=HTMLResponse)
async def docs_page(request: Request):
    """文档/书籍上传页面"""
    with get_db() as db:
        docs = db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return templates.TemplateResponse("docs.html", {
        "request": request,
        "docs": docs,
        "domain": config.DOMAIN,
    })


@app.post("/api/docs/upload")
async def api_docs_upload(file: UploadFile = File(...)):
    """上传 PDF/书籍 文件"""
    os.makedirs(os.path.join(config.PROJECTS_DIR, "docs"), exist_ok=True)
    filename = file.filename
    file_path = os.path.join(config.PROJECTS_DIR, "docs", filename)
    
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    with get_db() as db:
        existing = db.execute("SELECT id FROM documents WHERE filename = ?", (filename,)).fetchone()
        if not existing:
            db.execute("INSERT INTO documents (filename, status) VALUES (?,'scanning')", (filename,))
            doc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            doc_id = existing["id"]
            db.execute("UPDATE documents SET status='scanning' WHERE id=?", (doc_id,))

    # 启动后台任务处理文档 process_document_pipeline
    import threading
    t = threading.Thread(target=process_document_pipeline, args=(doc_id, filename, file_path), daemon=True)
    t.start()

    return {"status": "uploaded", "doc_id": doc_id, "filename": filename}


@app.get("/api/docs")
async def api_list_docs():
    """列出所有已上传的文档"""
    with get_db() as db:
        docs = db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(d) for d in docs]


GITHUB_TEMP_DIR = "/app/projects/github_scans"
_github_scans = {}

class GithubScanRequest(BaseModel):
    repo_url: str

def do_git_clone_async(scan_id, repo_url, target_dir):
    _github_scans[scan_id] = {"status": "cloning", "log": ["准备开始克隆..."], "files": []}
    cmd = ["git", "clone", "--progress", "--depth", "1", repo_url, target_dir]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ''):
            if line:
                _github_scans[scan_id]["log"].append(line.strip())
                if len(_github_scans[scan_id]["log"]) > 10:
                    _github_scans[scan_id]["log"].pop(0)
        
        proc.wait()
        if proc.returncode != 0:
            _github_scans[scan_id]["status"] = "error"
            _github_scans[scan_id]["log"].append(f"Git Clone 失败 (code {proc.returncode})")
            return
            
        # Scan for documents
        docs = []
        allowed_exts = {".pdf", ".md", ".epub", ".docx", ".txt"}
        for root, dirs, files in os.walk(target_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in allowed_exts:
                    rel_path = os.path.relpath(os.path.join(root, f), target_dir)
                    rel_path = rel_path.replace("\\", "/")
                    docs.append({"path": rel_path, "name": f, "ext": ext})
        
        docs.sort(key=lambda x: x["path"])
        _github_scans[scan_id]["status"] = "success"
        _github_scans[scan_id]["files"] = docs
        _github_scans[scan_id]["log"].append("克隆并扫描完成")
        
    except Exception as e:
        _github_scans[scan_id]["status"] = "error"
        _github_scans[scan_id]["log"].append(f"内部错误: {str(e)}")

@app.post("/api/docs/github/scan")
async def api_github_scan(req: GithubScanRequest):
    os.makedirs(GITHUB_TEMP_DIR, exist_ok=True)
    scan_id = str(uuid.uuid4())
    target_dir = os.path.join(GITHUB_TEMP_DIR, scan_id)
    
    import re
    # 格式化 repo url
    repo_url = req.repo_url.strip()
    match = re.match(r"(https?://github\.com/[^/]+/[^/]+)", repo_url)
    if match:
        repo_url = match.group(1)
        
    t = threading.Thread(target=do_git_clone_async, args=(scan_id, repo_url, target_dir), daemon=True)
    t.start()
    
    return {"status": "started", "scan_id": scan_id}

@app.get("/api/docs/github/scan/status/{scan_id}")
async def api_github_scan_status(scan_id: str):
    if scan_id not in _github_scans:
        raise HTTPException(404, "扫描任务未找到或已过期")
    return _github_scans[scan_id]

class GithubProcessRequest(BaseModel):
    scan_id: str
    selected_files: list[str]

@app.post("/api/docs/github/process")
async def api_github_process(req: GithubProcessRequest):
    source_dir = os.path.join(GITHUB_TEMP_DIR, req.scan_id)
    if not os.path.exists(source_dir):
        raise HTTPException(404, "扫描会话未找到或已过期")
    
    os.makedirs(os.path.join(config.PROJECTS_DIR, "docs"), exist_ok=True)
    
    processed = []
    for rel_path in req.selected_files:
        src_path = os.path.join(source_dir, rel_path)
        if os.path.exists(src_path):
            filename = os.path.basename(rel_path)
            # 避免覆盖重名文件，加上文件夹前缀
            safe_filename = rel_path.replace("/", "_").replace("\\", "_")
            dst_path = os.path.join(config.PROJECTS_DIR, "docs", safe_filename)
            shutil.copy2(src_path, dst_path)
            
            with get_db() as db:
                existing = db.execute("SELECT id FROM documents WHERE filename = ?", (safe_filename,)).fetchone()
                if not existing:
                    db.execute("INSERT INTO documents (filename, status) VALUES (?,'scanning')", (safe_filename,))
                    doc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                else:
                    doc_id = existing["id"]
                    db.execute("UPDATE documents SET status='scanning' WHERE id=?", (doc_id,))
            
            # Start pipeline
            t = threading.Thread(target=process_document_pipeline, args=(doc_id, safe_filename, dst_path), daemon=True)
            t.start()
            processed.append(safe_filename)

    # 移除立即删除逻辑，改由定时任务清理，方便用户分批次勾选处理
    # try:
    #     shutil.rmtree(source_dir)
    # except:
    #     pass

    return {"status": "started", "count": len(processed), "files": processed}


# ===== 健康检查 =====

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
