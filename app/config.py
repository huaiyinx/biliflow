"""
BiliFlow 配置管理
"""
import os


class Config:
    # B站 Cookie
    BILI_SESSDATA: str = os.getenv("BILI_SESSDATA", "")
    BILI_JCT: str = os.getenv("BILI_JCT", "")
    BILI_DEDEUSERID: str = os.getenv("BILI_DEDEUSERID", "")

    # SiliconFlow (SenseVoice ASR)
    SF_KEY: str = os.getenv("SILICONFLOW_KEY", "")
    SF_BASE: str = os.getenv("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1")

    # Cloud visual/OCR providers
    OPENROUTER_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE: str = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
    SILICONFLOW_VISUAL_KEY: str = os.getenv("SILICONFLOW_VISUAL_KEY", SF_KEY)
    AI_WATCH_MAX_VISUAL_COST_CNY: float = float(os.getenv("AI_WATCH_MAX_VISUAL_COST_CNY", "0.20"))
    AI_WATCH_REQUIRE_FREE_FIRST: bool = os.getenv("AI_WATCH_REQUIRE_FREE_FIRST", "1").lower() not in {
        "0", "false", "no", "off"
    }

    # Gemini (via NewAPI)
    GEMINI_KEY: str = os.getenv("GEMINI_KEY", "")
    GEMINI_BASE: str = os.getenv("GEMINI_BASE", "https://litellm.19991023.xyz/v1")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "gemini-3.5-flash")

    # Domain
    DOMAIN: str = os.getenv("DOMAIN", "bill.19991023.xyz")

    # Vault
    VAULT_ROOT: str = os.getenv("VAULT_ROOT", "/data/obsidian-vault")
    VAULT_BIKI_DIR: str = os.getenv("VAULT_BIKI_DIR", "10-B站笔记")
    OBSIDIAN_AGENT_OPS_DIR: str = os.getenv("OBSIDIAN_AGENT_OPS_DIR", "/data/obsidian-agent-ops")
    ENABLE_AGENT_OPS_MIRROR: bool = os.getenv("ENABLE_AGENT_OPS_MIRROR", "1").lower() not in {
        "0", "false", "no", "off"
    }

    # Scheduler
    CHECK_INTERVAL_HOURS: int = int(os.getenv("CHECK_INTERVAL_HOURS", "6"))

    # Paths
    PROJECTS_DIR: str = "/app/projects"
    DATA_DIR: str = "/app/data"
    DB_PATH: str = "/app/data/bili.db"

    # Bili CLI auth
    BILI_CRED_FILE: str = os.path.expanduser("~/.bilibili-cli/credential.json")


config = Config()
