"""
Obsidian 输出同步辅助：
1. 继续维护 VPS 侧 Vault 镜像，供 BiliFlow 本地读取/续跑。
2. 同步把最新笔记投递到 agent-ops，交给本机 Obsidian 真正落盘。
"""
import json
import os
import uuid
from datetime import datetime, timezone

from config import config


def ensure_vault_dirs(up_name: str | None = None) -> str:
    vault_biki = os.path.join(config.VAULT_ROOT, config.VAULT_BIKI_DIR)
    os.makedirs(vault_biki, exist_ok=True)
    if up_name:
        up_dir = os.path.join(vault_biki, up_name)
        os.makedirs(up_dir, exist_ok=True)
        return up_dir
    return vault_biki


def _rel_vault_path(path: str) -> str:
    rel_path = os.path.relpath(path, config.VAULT_ROOT)
    if rel_path.startswith(".."):
        return ""
    return rel_path.replace("\\", "/")


def _agent_ops_enabled() -> bool:
    return (
        config.ENABLE_AGENT_OPS_MIRROR
        and bool(config.OBSIDIAN_AGENT_OPS_DIR)
        and os.path.isdir(config.OBSIDIAN_AGENT_OPS_DIR)
    )


def enqueue_agent_write(path: str, content: str, created_by: str = "bili-flow") -> str | None:
    if not _agent_ops_enabled():
        return None

    rel_path = _rel_vault_path(path)
    if not rel_path:
        return None

    pending_dir = os.path.join(config.OBSIDIAN_AGENT_OPS_DIR, "pending")
    os.makedirs(pending_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    op_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": op_id,
        "type": "write",
        "path": rel_path,
        "source": "",
        "destination": "",
        "content": content,
        "append_separator": "\n\n",
        "payload": {},
        "created_by": created_by,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "status": "pending",
        "attempts": 0,
    }

    tmp_path = os.path.join(pending_dir, f"{op_id}.json.tmp")
    file_path = os.path.join(pending_dir, f"{op_id}.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, file_path)
    return op_id


def write_vault_file(path: str, content: str, created_by: str = "bili-flow") -> bool:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    unchanged = False
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                unchanged = f.read() == content
        except Exception:
            unchanged = False

    if not unchanged:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        enqueue_agent_write(path, content, created_by=created_by)

    return not unchanged
