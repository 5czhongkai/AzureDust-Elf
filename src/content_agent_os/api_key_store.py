from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PLATFORM_API_KEY_ENV_KEYS = {
    "wechat": "CONTENT_AGENT_WECHAT_API_KEY",
    "xiaohongshu": "CONTENT_AGENT_XIAOHONGSHU_API_KEY",
    "douyin": "CONTENT_AGENT_DOUYIN_API_KEY",
    "shipinhao": "CONTENT_AGENT_SHIPINHAO_API_KEY",
    "bilibili": "CONTENT_AGENT_BILIBILI_API_KEY",
}


def api_key_store_path(output_root: Path) -> Path:
    return output_root / "_state" / "api_keys.json"


def load_api_key_store(output_root: Path) -> dict[str, str]:
    path = api_key_store_path(output_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid API key store JSON: {path}") from exc
    raw_keys = data.get("keys", {}) if isinstance(data, dict) else {}
    if not isinstance(raw_keys, dict):
        return {}
    return {
        str(target_id): str(value)
        for target_id, value in raw_keys.items()
        if str(target_id) in PLATFORM_API_KEY_ENV_KEYS and str(value).strip()
    }


def write_api_key_store(output_root: Path, keys: dict[str, str], *, updated_at: str) -> None:
    path = api_key_store_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "phase5.api_keys.v1",
        "updated_at": updated_at,
        "keys": keys,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def apply_stored_api_keys(output_root: Path) -> dict[str, str]:
    stored = load_api_key_store(output_root)
    for target_id, value in stored.items():
        env_key = PLATFORM_API_KEY_ENV_KEYS.get(target_id)
        if env_key and value.strip():
            os.environ[env_key] = value.strip()
    return stored


def is_api_key_store_file(output_root: Path, path: Path) -> bool:
    try:
        return path.resolve() == api_key_store_path(output_root).resolve()
    except OSError:
        return False
