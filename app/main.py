"""
BiliFlow — B站视频笔记自动化系统
FastAPI 主应用
"""
import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import config
from db import get_db, init_db
from bili_api import get_up_info, get_all_videos, extract_uid_from_url, load_bili_cookie, get_my_info
from scheduler import (
    start_scheduler, check_and_process, is_processing,
    create_shell_notes_batch, run_pipeline_for_up, update_moc,
    mark_processing,
)

app = FastAPI(title="BiliFlow", version="1.0.0")

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
    })


@app.get("/add", response_class=HTMLResponse)
async def add_page(request: Request):
    """添加 UP主 页面"""
    return templates.TemplateResponse("add.html", {
        "request": request,
        "domain": config.DOMAIN,
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


@app.get("/api/up")
async def api_list_ups():
    """列出所有 UP主"""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM up_masters ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/up")
async def api_add_up(url: str = Form(...), background_tasks: BackgroundTasks = None):
    """添加 UP主"""
    uid = extract_uid_from_url(url)
    if not uid:
        raise HTTPException(400, "无法解析 UID，请检查链接")

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
            # 已存在，扫描新视频
            known = set(
                r[0] for r in db.execute(
                    "SELECT bvid FROM videos WHERE up_id = ?", (existing["id"],)
                ).fetchall()
            )
            from bili_api import get_new_videos
            new_videos = get_new_videos(uid, known)
            if new_videos:
                shell_notes = create_shell_notes_batch(
                    name, uid, existing["id"], new_videos
                )
                if shell_notes:
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
            "INSERT INTO up_masters (uid, name, avatar, status) VALUES (?,?,?,'scanning')",
            (uid, name, avatar),
        )
        up_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 后台扫描视频
    def scan_and_create():
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
            "SELECT bvid, title, note_path, note_file FROM videos WHERE up_id = ? AND status = 'pending'",
            (up["id"],),
        ).fetchall()

    if not videos:
        return {"status": "nothing", "message": "没有待处理的视频"}

    if is_processing(up_name):
        return {"status": "busy", "message": f"{up_name} 正在处理中"}

    video_list = [
        {"bvid": v["bvid"], "title": v["title"], "note_path": v["note_path"]}
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
            "SELECT bvid, title, note_path FROM videos WHERE up_id = ? AND status = 'failed'",
            (up["id"],),
        ).fetchall()

    if not failed:
        return {"status": "nothing", "message": "没有失败的视频"}

    if is_processing(up_name):
        return {"status": "busy"}

    video_list = [
        {"bvid": v["bvid"], "title": v["title"], "note_path": v["note_path"]}
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


# ===== 健康检查 =====

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
