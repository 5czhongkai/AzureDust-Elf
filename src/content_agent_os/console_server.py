from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import shutil
import sys
import threading
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .job_queue import (
    CLEANUP_CONFIRMATION,
    DEFAULT_AUDIT_RETENTION_DAYS,
    DEFAULT_JOB_RETENTION_DAYS,
    DurableJobStore,
    execute_claimed_job,
    job_db_path,
)
from .runner import DEFAULT_PLATFORMS
from .supervision import generate_supervision_outputs


DEFAULT_WORKFLOW_PATH = Path("workflows/one_topic_multi_platform.yaml")
DEFAULT_BACKUP_ROOT = Path("backups")
SECRET_ENV_KEYS = [
    "OPENAI_API_KEY",
    "SILICONFLOW_API_KEY",
    "CONTENT_AGENT_OS_TTS_API_KEY",
]
RUNTIME_ENV_KEYS = [
    "CONTENT_AGENT_ENV",
    "CONTENT_AGENT_TIMEZONE",
    "CONTENT_AGENT_OUTPUT_ROOT",
    "CONTENT_AGENT_BACKUP_ROOT",
    "CONTENT_AGENT_OS_TTS_PROVIDER",
    "CONTENT_AGENT_OS_TTS_MODEL",
    "CONTENT_AGENT_OS_TTS_VOICE",
]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOADS_PER_REQUEST = 8
TEXT_EXTENSIONS = {".csv", ".json", ".md", ".srt", ".txt", ".yaml", ".yml"}
PLATFORM_LABELS = {
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "shipinhao": "视频号",
    "bilibili": "B站",
}
PLATFORM_PRIMARY_FILES = {
    "wechat": ["wechat/article.md", "wechat/title_options.json"],
    "xiaohongshu": ["xiaohongshu/note.json", "xiaohongshu/cover_prompt.md"],
    "douyin": ["douyin/script.md", "douyin/subtitles.srt", "douyin/cover_prompt.md"],
    "shipinhao": ["shipinhao/script.md", "shipinhao/subtitles.srt", "shipinhao/cover_prompt.md"],
    "bilibili": ["bilibili/script.md", "bilibili/description.md", "bilibili/chapters.json"],
}


@dataclass(frozen=True)
class ConsoleConfig:
    workflow_path: Path
    output_root: Path
    backup_root: Path
    default_platforms: list[str]
    execute_inline_jobs: bool = True
    job_retention_days: int = DEFAULT_JOB_RETENTION_DAYS
    audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS


class ConsoleRuntime:
    def __init__(self, config: ConsoleConfig) -> None:
        self.config = config
        self.job_store = DurableJobStore(job_db_path(config.output_root))

    def health(self) -> dict[str, Any]:
        return {
            "schema_version": "phase5.console_health.v1",
            "status": "ok" if self.config.workflow_path.exists() else "degraded",
            "generated_at": _utc_now_iso(),
            "workflow_path": str(self.config.workflow_path),
            "workflow_exists": self.config.workflow_path.exists(),
            "output_root": str(self.config.output_root),
            "output_root_exists": self.config.output_root.exists(),
            "backup_root": str(self.config.backup_root),
            "default_platforms": self.config.default_platforms,
            "job_db_path": str(job_db_path(self.config.output_root)),
            "execute_inline_jobs": self.config.execute_inline_jobs,
            "job_retention_days": self.config.job_retention_days,
            "audit_retention_days": self.config.audit_retention_days,
            "secret_policy": "presence-only; secret values are never returned by the console API",
        }

    def local_runtime_status(self) -> dict[str, Any]:
        project_root = self._project_root()
        jobs_db = job_db_path(self.config.output_root)
        worker_ready = self.config.output_root.exists() and jobs_db.parent.exists()
        scheduler_default_dry_run = _truthy(os.environ.get("CONTENT_AGENT_SCHEDULER_DRY_RUN", "1"))
        docker_available = shutil.which("docker") is not None
        commands = [
            {
                "label": "Local console",
                "command": "make console",
                "required": True,
                "ready": self.config.workflow_path.exists(),
            },
            {
                "label": "One-shot worker",
                "command": "make worker-once",
                "required": True,
                "ready": worker_ready,
            },
            {
                "label": "Long-running worker",
                "command": "make worker",
                "required": True,
                "ready": worker_ready,
            },
            {
                "label": "Dry-run scheduler tick",
                "command": "make scheduler-once",
                "required": True,
                "ready": self.config.workflow_path.exists(),
            },
            {
                "label": "Long-running scheduler",
                "command": "make scheduler",
                "required": True,
                "ready": self.config.workflow_path.exists(),
            },
            {
                "label": "Optional Docker console",
                "command": "docker compose up console",
                "required": False,
                "ready": docker_available,
            },
        ]
        blockers = [
            item["label"]
            for item in commands
            if item["required"] and not bool(item["ready"])
        ]
        return {
            "schema_version": "phase5.local_runtime_status.v1",
            "generated_at": _utc_now_iso(),
            "status": "bad" if blockers else "ok",
            "project_root": str(project_root),
            "docker_required": False,
            "docker_available": docker_available,
            "inline_jobs": self.config.execute_inline_jobs,
            "scheduler_default_dry_run": scheduler_default_dry_run,
            "job_db_path": str(jobs_db),
            "worker_queue_ready": worker_ready,
            "commands": commands,
            "blockers": blockers,
            "message": "Local Python commands are the primary runtime path; Docker is optional.",
        }

    def environment_status(self) -> dict[str, Any]:
        secrets = [
            {
                "name": key,
                "present": bool(os.environ.get(key, "").strip()),
                "value": None,
            }
            for key in SECRET_ENV_KEYS
        ]
        runtime = [
            {
                "name": key,
                "present": key in os.environ and bool(os.environ.get(key, "").strip()),
                "value": os.environ.get(key, ""),
            }
            for key in RUNTIME_ENV_KEYS
        ]
        return {
            "schema_version": "phase5.environment_status.v1",
            "generated_at": _utc_now_iso(),
            "secrets": secrets,
            "runtime": runtime,
            "secret_policy": "Only boolean presence is exposed for secret variables.",
        }

    def setup_check(self) -> dict[str, Any]:
        env_status = self.environment_status()
        project_root = self._project_root()
        state_db = self.config.output_root / "_state" / "workflow_state.sqlite"
        jobs_db = job_db_path(self.config.output_root)
        backups = self.list_backups(limit=1)["backups"]
        missing_secrets = [item["name"] for item in env_status["secrets"] if not item["present"]]
        compose_path = project_root / "docker-compose.yml"
        compose_text = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
        compose_profiles_ready = (
            "worker:" in compose_text
            and "scheduler:" in compose_text
            and 'profiles: ["worker"]' in compose_text
            and 'profiles: ["scheduler"]' in compose_text
        )
        expected_platforms = list(DEFAULT_PLATFORMS)
        configured_platforms = list(self.config.default_platforms)
        platform_complete = configured_platforms == expected_platforms
        checks: list[dict[str, Any]] = []

        def add_check(
            check_id: str,
            label: str,
            status: str,
            message: str,
            *,
            path: Path | None = None,
            command: str | None = None,
        ) -> None:
            checks.append(
                {
                    "id": check_id,
                    "label": label,
                    "status": status,
                    "message": message,
                    "path": str(path) if path else None,
                    "command": command,
                }
            )

        add_check(
            "python",
            "Python runtime",
            "ok" if sys.version_info >= (3, 10) else "bad",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
        add_check(
            "workflow",
            "Workflow definition",
            "ok" if self.config.workflow_path.exists() else "bad",
            "workflow file found" if self.config.workflow_path.exists() else "workflow file is missing",
            path=self.config.workflow_path,
            command="make validate",
        )
        add_check(
            "platforms",
            "Platform set",
            "ok" if platform_complete else "bad",
            ",".join(configured_platforms) if platform_complete else f"expected {','.join(expected_platforms)}",
        )
        add_check(
            "env_example",
            ".env template",
            "ok" if (project_root / ".env.example").exists() else "warn",
            "template found" if (project_root / ".env.example").exists() else "recreate local .env from .env.example when available",
            path=project_root / ".env.example",
        )
        add_check(
            "compose_profiles",
            "Optional Compose profiles",
            "ok" if compose_profiles_ready else "warn",
            "optional worker and scheduler profiles found"
            if compose_profiles_ready
            else "optional Docker profiles not detected; local make commands still work",
            path=compose_path,
            command="make validate-phase5-profiles",
        )
        local_runtime = self.local_runtime_status()
        add_check(
            "local_runtime",
            "Local runtime commands",
            local_runtime["status"],
            "console, worker, and scheduler make commands are ready"
            if local_runtime["status"] == "ok"
            else f"blocked: {', '.join(local_runtime['blockers'])}",
            command="make validate-phase5-local-runtime",
        )
        add_check(
            "output_root",
            "Outputs directory",
            "ok" if self.config.output_root.exists() else "warn",
            "outputs root found" if self.config.output_root.exists() else "missing on this machine; ok for fresh setup",
            path=self.config.output_root,
            command="mkdir -p outputs/runs",
        )
        add_check(
            "backup_root",
            "Backups directory",
            "ok" if self.config.backup_root.exists() else "warn",
            "backup root found" if self.config.backup_root.exists() else "missing until a backup is created or migrated",
            path=self.config.backup_root,
            command="mkdir -p backups",
        )
        add_check(
            "resume_state_db",
            "Resume state database",
            "ok" if state_db.exists() else "warn",
            "state database found" if state_db.exists() else "fresh setup or missing migration state",
            path=state_db,
        )
        add_check(
            "job_queue_db",
            "Durable job queue",
            self.job_store.queue_health()["status"] if jobs_db.exists() else "warn",
            _queue_health_message(self.job_store.queue_health()) if jobs_db.exists() else "no console job queue has been created yet",
            path=jobs_db,
            command="make validate-phase5-job-queue",
        )
        add_check(
            "latest_backup",
            "Latest backup",
            "ok" if backups else "warn",
            str(backups[0]["name"]) if backups else "no local backup found yet",
            path=self.config.backup_root,
            command="make console",
        )
        add_check(
            "secrets",
            "Secret presence",
            "ok" if not missing_secrets else "warn",
            "all configured secrets are present"
            if not missing_secrets
            else f"missing: {', '.join(missing_secrets)}",
        )
        add_check(
            "secret_policy",
            "Secret boundary",
            "ok",
            "setup check reports only secret names and presence, never values",
        )

        bad_count = sum(1 for item in checks if item["status"] == "bad")
        warn_count = sum(1 for item in checks if item["status"] == "warn")
        status = "bad" if bad_count else "warn" if warn_count else "ok"
        commands = [
            {"label": "Base validation", "command": "make validate", "required": True},
            {"label": "Console validation", "command": "make validate-phase5-console", "required": True},
            {"label": "Migration validation", "command": "make validate-phase5-migration", "required": True},
            {"label": "Setup validation", "command": "make validate-phase5-setup", "required": True},
            {"label": "Profile validation", "command": "make validate-phase5-profiles", "required": True},
            {"label": "Job queue validation", "command": "make validate-phase5-job-queue", "required": True},
            {
                "label": "Local runtime validation",
                "command": "make validate-phase5-local-runtime",
                "required": True,
            },
            {"label": "Start local console", "command": "make console", "required": True},
            {"label": "Optional Docker check", "command": "docker compose up console", "required": False},
        ]
        return {
            "schema_version": "phase5.setup_check.v1",
            "generated_at": _utc_now_iso(),
            "status": status,
            "bad_count": bad_count,
            "warn_count": warn_count,
            "project_root": str(project_root),
            "checks": checks,
            "commands": commands,
            "secret_policy": "Only boolean presence is exposed for secret variables.",
        }

    def list_runs(self, limit: int = 20) -> dict[str, Any]:
        runs = []
        if self.config.output_root.exists():
            candidates = [
                path
                for path in self.config.output_root.iterdir()
                if path.is_dir() and (path / "workflow_run.json").exists()
            ]
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            runs = [_run_card(path) for path in candidates[:limit]]
        return {
            "schema_version": "phase5.run_index.v1",
            "generated_at": _utc_now_iso(),
            "output_root": str(self.config.output_root),
            "runs": runs,
        }

    def run_summary(self, run_id: str, *, refresh: bool = False) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(run_id)
        if refresh:
            generate_supervision_outputs(run_id=run_id, output_root=self.config.output_root)
        workflow_run = _load_json(run_dir / "workflow_run.json")
        snapshot = _load_json(run_dir / "monitor/supervision_snapshot.json")
        return {
            "schema_version": "phase5.run_summary.v1",
            "generated_at": _utc_now_iso(),
            "run_dir": str(run_dir),
            "workflow_run": workflow_run,
            "supervision": snapshot,
            "files": {
                "workflow_run": "workflow_run.json",
                "supervision_snapshot": "monitor/supervision_snapshot.json",
                "supervision_report": "monitor/supervision_report.md",
                "failure_dashboard": "monitor/failure_dashboard.html",
                "content_package": "final/content_package_manifest.json",
                "video_production_package": "final/video_production_package.json",
                "artifact_store": "artifact_store/artifact_store_manifest.json",
            },
        }

    def upload_inputs(self, files: list[dict[str, Any]]) -> dict[str, Any]:
        if len(files) > MAX_UPLOADS_PER_REQUEST:
            raise ValueError(f"最多一次上传 {MAX_UPLOADS_PER_REQUEST} 个文件")
        upload_root = self.config.output_root / "_uploads" / f"upload_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
        saved = []
        for index, item in enumerate(files, start=1):
            name = _safe_upload_name(str(item.get("name") or f"attachment_{index}"))
            mime_type = str(item.get("mime_type") or item.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream")
            if not _allowed_upload(name, mime_type):
                raise ValueError(f"不支持的文件类型: {name}")
            raw_base64 = str(item.get("data_base64") or item.get("data") or "")
            try:
                data = base64.b64decode(raw_base64, validate=True)
            except Exception as exc:
                raise ValueError(f"文件数据不是有效 base64: {name}") from exc
            if not data:
                raise ValueError(f"文件为空: {name}")
            if len(data) > MAX_UPLOAD_BYTES:
                raise ValueError(f"单个文件不能超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB: {name}")
            upload_root.mkdir(parents=True, exist_ok=True)
            target = upload_root / name
            target.write_bytes(data)
            saved.append(
                {
                    "id": f"attachment_{index}_{uuid.uuid4().hex[:8]}",
                    "name": name,
                    "mime_type": mime_type,
                    "kind": _upload_kind(name, mime_type),
                    "size_bytes": len(data),
                    "path": str(target),
                }
            )
        manifest = {
            "schema_version": "phase5.upload_manifest.v1",
            "created_at": _utc_now_iso(),
            "upload_root": str(upload_root),
            "files": saved,
        }
        if saved:
            _write_json(upload_root / "upload_manifest.json", manifest)
        return manifest

    def platform_content(self, run_id: str, platform: str) -> dict[str, Any]:
        self._validate_platform(platform)
        run_dir = self._resolve_run_dir(run_id)
        workflow_run = _load_json(run_dir / "workflow_run.json")
        files = []
        for relative in PLATFORM_PRIMARY_FILES[platform]:
            path = _safe_run_file(run_dir, relative)
            if path is None or not path.exists() or not path.is_file():
                continue
            files.append(_content_file_card(run_dir, path))
        manifest = _load_json(run_dir / "final/content_package_manifest.json")
        artifacts = [
            artifact
            for artifact in manifest.get("artifacts", [])
            if isinstance(artifact, dict) and artifact.get("platform") == platform
        ]
        return {
            "schema_version": "phase5.platform_content.v1",
            "generated_at": _utc_now_iso(),
            "run_id": run_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS[platform],
            "topic": workflow_run.get("topic"),
            "status": workflow_run.get("status"),
            "files": files,
            "artifact_count": len(artifacts),
            "download_url": f"/api/runs/{run_id}/platforms/{platform}/download",
        }

    def platform_download(self, run_id: str, platform: str) -> tuple[str, bytes, str]:
        content = self.platform_content(run_id, platform)
        lines = [
            f"# {content['platform_label']}生成内容",
            "",
            f"- 运行记录: {run_id}",
            f"- 选题: {content.get('topic') or ''}",
            f"- 状态: {content.get('status') or ''}",
            "",
        ]
        for item in content["files"]:
            lines.extend(
                [
                    f"## {item['label']}",
                    "",
                    f"文件: `{item['path']}`",
                    "",
                    str(item.get("content") or ""),
                    "",
                ]
            )
        if not content["files"]:
            lines.append("暂无可下载的平台主内容。")
        filename = f"{run_id}_{platform}_content.md"
        return filename, ("\n".join(lines) + "\n").encode("utf-8"), "text/markdown; charset=utf-8"

    def start_run(self, topic: str, platforms: list[str], attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is required")
        selected_platforms = platforms or self.config.default_platforms
        job = self.job_store.create_run_job(
            workflow_path=self.config.workflow_path,
            topic=topic,
            platforms=selected_platforms,
            attachments=attachments or [],
        )
        if self.config.execute_inline_jobs:
            thread = threading.Thread(target=self._execute_job, args=(str(job["job_id"]), "console-inline"), daemon=True)
            thread.start()
        return job

    def start_resume(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        job = self.job_store.create_resume_job(run_id=run_id)
        if self.config.execute_inline_jobs:
            thread = threading.Thread(target=self._execute_job, args=(str(job["job_id"]), "console-inline"), daemon=True)
            thread.start()
        return job

    def list_jobs(self, *, status: str | None = None) -> dict[str, Any]:
        health = self.job_store.queue_health()
        return {
            "schema_version": "phase5.job_index.v1",
            "generated_at": _utc_now_iso(),
            "job_db_path": str(job_db_path(self.config.output_root)),
            "queue_health": health,
            "jobs": self.job_store.list_jobs(limit=50, status=status),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.job_store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def queue_health(self) -> dict[str, Any]:
        return self.job_store.queue_health()

    def job_audit_log(self, job_id: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": "phase5.job_audit_index.v1",
            "generated_at": _utc_now_iso(),
            "job_id": job_id,
            "audit": self.job_store.audit_log(job_id=job_id, limit=80),
        }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.job_store.cancel_job(job_id, actor="console", message="canceled from console")

    def retry_job(self, job_id: str) -> dict[str, Any]:
        return self.job_store.retry_job(job_id, actor="console", message="retry requested from console")

    def mark_job_failed(self, job_id: str) -> dict[str, Any]:
        return self.job_store.mark_running_failed(job_id, actor="console", message="marked failed from console")

    def cleanup_jobs_dry_run(self) -> dict[str, Any]:
        return self.job_store.cleanup_dry_run(
            job_retention_days=self.config.job_retention_days,
            audit_retention_days=self.config.audit_retention_days,
        )

    def cleanup_jobs(self, confirmation: str) -> dict[str, Any]:
        return self.job_store.cleanup(
            confirmation=confirmation,
            actor="console",
            job_retention_days=self.config.job_retention_days,
            audit_retention_days=self.config.audit_retention_days,
        )

    def create_backup(self) -> dict[str, Any]:
        self.config.backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.config.backup_root / f"content_agent_os_backup_{timestamp}_{uuid.uuid4().hex[:8]}.zip"
        source_root = self.config.output_root
        files = [path for path in sorted(source_root.rglob("*")) if path.is_file()] if source_root.exists() else []
        total_bytes = sum(path.stat().st_size for path in files)
        manifest = {
            "schema_version": "phase5.backup_manifest.v1",
            "created_at": _utc_now_iso(),
            "source_output_root": str(source_root),
            "backup_path": str(backup_path),
            "file_count": len(files),
            "total_bytes": total_bytes,
            "secret_policy": "Environment variables and secret values are not included.",
            "restore_note": "Unzip this archive at the project root to restore outputs/runs contents.",
        }
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("backup_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for path in files:
                archive.write(path, _backup_arcname(source_root, path))
        manifest["backup_size_bytes"] = backup_path.stat().st_size
        return manifest

    def restore_dry_run(self, backup_name: str) -> dict[str, Any]:
        backup_path = self._resolve_backup_path(backup_name)
        manifest, entries, unsafe_entries = self._inspect_backup(backup_path)
        return {
            "schema_version": "phase5.restore_dry_run.v1",
            "generated_at": _utc_now_iso(),
            "dry_run": True,
            "will_extract": False,
            "backup_name": backup_path.name,
            "backup_path": str(backup_path),
            "restore_root": str(self.config.output_root),
            "backup_manifest": manifest,
            "file_count": len(entries),
            "total_bytes": sum(int(item["size_bytes"]) for item in entries),
            "would_overwrite_count": sum(1 for item in entries if item["would_overwrite"]),
            "safe_to_restore": not unsafe_entries,
            "unsafe_entries": unsafe_entries,
            "entries": entries[:100],
            "entry_limit": 100,
            "restore_note": "Dry-run only. No archive files were extracted.",
        }

    def restore_backup(self, backup_name: str, confirmation: str) -> dict[str, Any]:
        backup_path = self._resolve_backup_path(backup_name)
        expected_confirmation = f"RESTORE {backup_path.name}"
        if confirmation.strip() != expected_confirmation:
            raise ValueError(f"restore confirmation must be exactly: {expected_confirmation}")
        manifest, entries, unsafe_entries = self._inspect_backup(backup_path)
        if unsafe_entries:
            raise ValueError(f"backup contains unsafe restore paths: {unsafe_entries[:5]}")

        restored_entries = []
        self.config.output_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_path) as archive:
            for entry in entries:
                archive_path = str(entry["archive_path"])
                target_path = _restore_target_path(self.config.output_root, archive_path)
                if target_path is None:
                    raise ValueError(f"unsafe restore path: {archive_path}")
                would_overwrite = target_path.exists()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(archive_path) as source, target_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                restored_entries.append(
                    {
                        "archive_path": archive_path,
                        "target_path": str(target_path),
                        "size_bytes": int(entry["size_bytes"]),
                        "overwrote": would_overwrite,
                    }
                )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        restore_log_path = self.config.output_root / "_restore_logs" / f"restore_{timestamp}_{uuid.uuid4().hex[:8]}.json"
        result = {
            "schema_version": "phase5.restore_result.v1",
            "generated_at": _utc_now_iso(),
            "dry_run": False,
            "will_extract": True,
            "backup_name": backup_path.name,
            "backup_path": str(backup_path),
            "restore_root": str(self.config.output_root),
            "backup_manifest": manifest,
            "file_count": len(restored_entries),
            "total_bytes": sum(int(item["size_bytes"]) for item in restored_entries),
            "overwrote_count": sum(1 for item in restored_entries if item["overwrote"]),
            "restore_log_path": str(restore_log_path),
            "entries": restored_entries[:100],
            "entry_limit": 100,
        }
        _write_json(restore_log_path, result)
        return result

    def list_backups(self, limit: int | None = None) -> dict[str, Any]:
        backups = []
        if self.config.backup_root.exists():
            for path in sorted(self.config.backup_root.glob("content_agent_os_backup_*.zip"), reverse=True):
                backups.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "size_bytes": path.stat().st_size,
                        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                    }
                )
                if limit is not None and len(backups) >= limit:
                    break
        return {
            "schema_version": "phase5.backup_index.v1",
            "generated_at": _utc_now_iso(),
            "backup_root": str(self.config.backup_root),
            "backups": backups,
        }

    def _resolve_backup_path(self, backup_name: str) -> Path:
        name = backup_name.strip()
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("backup name is required")
        if not name.startswith("content_agent_os_backup_") or not name.endswith(".zip"):
            raise ValueError("unknown backup name format")
        backup_path = self.config.backup_root / name
        if not backup_path.exists():
            raise FileNotFoundError(f"backup not found: {name}")
        backup_root = self.config.backup_root.resolve()
        resolved = backup_path.resolve()
        if backup_root not in resolved.parents:
            raise ValueError("backup path escapes backup root")
        return backup_path

    def _inspect_backup(self, backup_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        entries = []
        unsafe_entries = []
        manifest: dict[str, Any] = {}
        try:
            with zipfile.ZipFile(backup_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.filename == "backup_manifest.json":
                        manifest = _load_json_from_zip(archive, info.filename)
                        continue
                    target_path = _restore_target_path(self.config.output_root, info.filename)
                    if target_path is None:
                        unsafe_entries.append(info.filename)
                        continue
                    entries.append(
                        {
                            "archive_path": info.filename,
                            "target_path": str(target_path),
                            "size_bytes": info.file_size,
                            "would_overwrite": target_path.exists(),
                        }
                    )
        except zipfile.BadZipFile as exc:
            raise ValueError(f"invalid backup zip: {backup_path.name}") from exc
        return manifest, entries, unsafe_entries

    def _execute_job(self, job_id: str, worker_id: str) -> None:
        job = self.job_store.claim_job(job_id, worker_id=worker_id)
        if job is None:
            return
        execute_claimed_job(self.job_store, job, output_root=self.config.output_root)

    def _resolve_run_dir(self, run_id: str) -> Path:
        self._validate_run_id(run_id)
        run_dir = self.config.output_root / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        return run_dir

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
            raise ValueError("invalid run id")

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in PLATFORM_LABELS:
            raise ValueError(f"unknown platform: {platform}")

    def _project_root(self) -> Path:
        workflow_parent = self.config.workflow_path.parent
        if workflow_parent.name == "workflows":
            return workflow_parent.parent
        return Path.cwd()


def make_console_handler(runtime: ConsoleRuntime) -> type[BaseHTTPRequestHandler]:
    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "ContentAgentOSConsole/0.1"

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                parts = _path_parts(parsed.path)
                query = parse_qs(parsed.query)
                if parsed.path == "/":
                    self._send_html(render_console_html(runtime))
                    return
                if parsed.path in {"/admin", "/admin/"}:
                    self._send_html(render_admin_console_html(runtime))
                    return
                if parsed.path == "/healthz":
                    self._send_json(runtime.health())
                    return
                if parts == ["api", "env"]:
                    self._send_json(runtime.environment_status())
                    return
                if parts == ["api", "setup-check"]:
                    self._send_json(runtime.setup_check())
                    return
                if parts == ["api", "local-runtime"]:
                    self._send_json(runtime.local_runtime_status())
                    return
                if parts == ["api", "runs"]:
                    limit = _positive_int(query.get("limit", ["20"])[0], default=20, maximum=100)
                    self._send_json(runtime.list_runs(limit=limit))
                    return
                if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                    refresh = query.get("refresh", ["false"])[0].lower() == "true"
                    self._send_json(runtime.run_summary(parts[2], refresh=refresh))
                    return
                if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3] == "platforms":
                    self._send_json(runtime.platform_content(parts[2], parts[4]))
                    return
                if len(parts) == 6 and parts[:2] == ["api", "runs"] and parts[3] == "platforms" and parts[5] == "download":
                    filename, body, content_type = runtime.platform_download(parts[2], parts[4])
                    self._send_bytes(body, filename=filename, content_type=content_type)
                    return
                if parts == ["api", "jobs"]:
                    status = query.get("status", [None])[0]
                    self._send_json(runtime.list_jobs(status=status))
                    return
                if parts == ["api", "queue-health"]:
                    self._send_json(runtime.queue_health())
                    return
                if parts == ["api", "jobs", "cleanup-dry-run"]:
                    self._send_json(runtime.cleanup_jobs_dry_run())
                    return
                if parts == ["api", "job-audit"]:
                    job_id = query.get("job_id", [None])[0]
                    self._send_json(runtime.job_audit_log(job_id=job_id))
                    return
                if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                    self._send_json(runtime.get_job(parts[2]))
                    return
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "audit":
                    self._send_json(runtime.job_audit_log(job_id=parts[2]))
                    return
                if parts == ["api", "backups"]:
                    self._send_json(runtime.list_backups())
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "not found")
            except Exception as exc:
                self._send_exception(exc)

        def do_POST(self) -> None:
            try:
                parts = _path_parts(urlparse(self.path).path)
                if parts == ["api", "runs"]:
                    payload = self._read_json_body()
                    platforms = _platforms_from_payload(payload, runtime.config.default_platforms)
                    attachments = _attachments_from_payload(payload)
                    job = runtime.start_run(str(payload.get("topic") or ""), platforms, attachments=attachments)
                    self._send_json(job, status=HTTPStatus.ACCEPTED)
                    return
                if parts == ["api", "uploads"]:
                    payload = self._read_json_body()
                    files = payload.get("files", [])
                    if not isinstance(files, list):
                        raise ValueError("files must be a list")
                    self._send_json(runtime.upload_inputs(files), status=HTTPStatus.CREATED)
                    return
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume":
                    job = runtime.start_resume(parts[2])
                    self._send_json(job, status=HTTPStatus.ACCEPTED)
                    return
                if parts == ["api", "backups"]:
                    self._send_json(runtime.create_backup(), status=HTTPStatus.CREATED)
                    return
                if parts == ["api", "restore-dry-run"]:
                    payload = self._read_json_body()
                    backup_name = str(payload.get("backup") or payload.get("backup_name") or "")
                    self._send_json(runtime.restore_dry_run(backup_name))
                    return
                if parts == ["api", "restore"]:
                    payload = self._read_json_body()
                    backup_name = str(payload.get("backup") or payload.get("backup_name") or "")
                    confirmation = str(payload.get("confirmation") or "")
                    self._send_json(runtime.restore_backup(backup_name, confirmation), status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
                    self._send_json(runtime.cancel_job(parts[2]), status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "retry":
                    self._send_json(runtime.retry_job(parts[2]), status=HTTPStatus.CREATED)
                    return
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "mark-failed":
                    self._send_json(runtime.mark_job_failed(parts[2]), status=HTTPStatus.ACCEPTED)
                    return
                if parts == ["api", "jobs", "cleanup-dry-run"]:
                    self._send_json(runtime.cleanup_jobs_dry_run())
                    return
                if parts == ["api", "jobs", "cleanup"]:
                    payload = self._read_json_body()
                    confirmation = str(payload.get("confirmation") or "")
                    self._send_json(runtime.cleanup_jobs(confirmation), status=HTTPStatus.ACCEPTED)
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "not found")
            except Exception as exc:
                self._send_exception(exc)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                loaded = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON body: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError("JSON body must be an object")
            return loaded

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html_body: str) -> None:
            body = html_body.encode("utf-8")
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, body: bytes, *, filename: str, content_type: str) -> None:
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message, "status": int(status)}, status=status)

        def _send_exception(self, exc: Exception) -> None:
            if isinstance(exc, (ValueError, KeyError)):
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if isinstance(exc, FileNotFoundError):
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    return ConsoleHandler


def render_console_html(runtime: ConsoleRuntime) -> str:
    health = runtime.health()
    job_index = runtime.list_jobs()
    initial_state = {
        "schema_version": "phase5.creator_workspace.initial_state.v1",
        "generated_at": _utc_now_iso(),
        "health": health,
        "runs": runtime.list_runs(limit=12)["runs"],
        "jobs": job_index["jobs"][:20],
        "queue_health": job_index["queue_health"],
        "platforms": [
            {"id": platform, "label": PLATFORM_LABELS.get(platform, platform)}
            for platform in DEFAULT_PLATFORMS
        ],
        "default_platforms": list(DEFAULT_PLATFORMS),
        "limits": {
            "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
            "max_uploads": MAX_UPLOADS_PER_REQUEST,
        },
    }
    html_body = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>自媒体内容创作工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f5f4;
      --surface: #ffffff;
      --surface-soft: #f8faf9;
      --ink: #17201c;
      --muted: #65706b;
      --line: #dbe2df;
      --line-strong: #b9c5c0;
      --accent: #14765b;
      --accent-strong: #0f5d48;
      --accent-soft: #e6f4ef;
      --blue: #2368a2;
      --blue-soft: #e7f0f8;
      --amber: #9c6100;
      --amber-soft: #fff3d8;
      --red: #a43a32;
      --red-soft: #fdecea;
      --shadow: 0 14px 34px rgba(23, 32, 28, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background:
        linear-gradient(90deg, rgba(20, 118, 91, .06) 1px, transparent 1px),
        linear-gradient(180deg, rgba(20, 118, 91, .05) 1px, transparent 1px),
        var(--bg);
      background-size: 44px 44px;
      color: var(--ink);
      font: 14px/1.5 "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea, select { font: inherit; letter-spacing: 0; }
    button, a.button {
      min-height: 36px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary, a.button.secondary {
      background: #fff;
      color: var(--accent-strong);
      border-color: var(--line-strong);
    }
    button.icon {
      width: 36px;
      padding: 0;
      font-size: 22px;
      line-height: 1;
    }
    button.danger { border-color: var(--red); background: var(--red); }
    button:disabled, a.button[aria-disabled="true"] { opacity: .58; cursor: wait; }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .92);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .brand-mark {
      width: 34px;
      height: 34px;
      border: 2px solid var(--ink);
      border-radius: 7px;
      display: grid;
      place-items: center;
      background: #fff;
      box-shadow: 4px 4px 0 var(--accent);
      font-weight: 900;
    }
    h1 { margin: 0; font-size: 20px; line-height: 1.2; }
    h2 { margin: 0; font-size: 16px; line-height: 1.25; }
    h3 { margin: 0; font-size: 14px; line-height: 1.3; }
    .meta { color: var(--muted); font-size: 12px; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }
    main {
      display: grid;
      grid-template-columns: minmax(310px, 430px) minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      max-width: 1480px;
      margin: 0 auto;
    }
    .column { display: grid; gap: 16px; align-content: start; }
    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .composer {
      display: grid;
      gap: 12px;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      margin-bottom: 6px;
    }
    textarea, input[type="text"] {
      width: 100%;
      border: 1px solid var(--line-strong);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 10px 11px;
      outline: none;
    }
    textarea {
      min-height: 154px;
      resize: vertical;
    }
    textarea:focus, input[type="text"]:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(20, 118, 91, .14);
    }
    .composer-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .attachment-list {
      display: grid;
      gap: 8px;
      margin-top: 2px;
    }
    .attachment {
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      background: var(--surface-soft);
    }
    .file-kind {
      width: 30px;
      height: 30px;
      border-radius: 6px;
      display: grid;
      place-items: center;
      background: var(--blue-soft);
      color: var(--blue);
      font-weight: 900;
      font-size: 12px;
    }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #edf1ef;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .status.ok, .status.done, .status.present, .status.set, .status.ready {
      background: var(--accent-soft);
      color: var(--accent-strong);
    }
    .status.warn, .status.running, .status.queued, .status.unavailable {
      background: var(--amber-soft);
      color: var(--amber);
    }
    .status.bad, .status.failed, .status.missing, .status.canceled {
      background: var(--red-soft);
      color: var(--red);
    }
    .status-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: var(--surface-soft);
      min-width: 0;
    }
    .metric strong {
      display: block;
      font-size: 22px;
      line-height: 1;
      margin-bottom: 4px;
    }
    .job-list, .run-list, .ops-list { display: grid; gap: 8px; }
    .job-row, .run-row, .ops-row {
      display: grid;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }
    .job-row {
      grid-template-columns: minmax(0, 1.4fr) auto;
      align-items: center;
    }
    .row-title {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 3px;
    }
    .row-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 6px;
    }
    .tabs {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding-bottom: 2px;
    }
    .tab {
      border-color: var(--line-strong);
      background: #fff;
      color: var(--ink);
    }
    .tab.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .preview-shell {
      display: grid;
      gap: 12px;
    }
    .preview-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .content-files {
      display: grid;
      gap: 10px;
    }
    .content-file {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
    }
    .content-file header {
      position: static;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-soft);
    }
    pre {
      margin: 0;
      padding: 12px;
      max-height: 520px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    details {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }
    summary {
      cursor: pointer;
      padding: 11px 12px;
      font-weight: 800;
      background: var(--surface-soft);
    }
    .details-body {
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .command-list { display: grid; gap: 7px; }
    .command {
      display: grid;
      grid-template-columns: minmax(110px, 180px) minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      padding: 8px 0;
      border-top: 1px solid var(--line);
    }
    .command:first-child { border-top: 0; padding-top: 0; }
    .toast {
      min-height: 24px;
      color: var(--accent-strong);
      font-weight: 750;
    }
    .empty {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      padding: 16px;
      color: var(--muted);
      background: var(--surface-soft);
      text-align: center;
    }
    .hidden { display: none !important; }
    @media (max-width: 980px) {
      header { grid-template-columns: 1fr; }
      main { grid-template-columns: 1fr; padding: 12px; }
      .status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .job-row { grid-template-columns: 1fr; }
      .row-actions { justify-content: flex-start; }
      .command { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <script id="initial-state" type="application/json">__INITIAL_STATE__</script>
  <header>
    <div class="brand">
      <div class="brand-mark">创</div>
      <div>
        <h1>自媒体内容创作工作台</h1>
        <div class="meta">输入选题，上传素材，查看队列，并按平台预览生成内容。</div>
      </div>
    </div>
    <div class="row-actions">
      <span id="health-pill" class="status">加载中</span>
      <a class="button secondary" href="/admin">后端控制台</a>
      <button class="secondary" type="button" id="refresh-button">刷新</button>
    </div>
  </header>

  <main>
    <div class="column">
      <section>
        <div class="section-head">
          <div>
            <h2>创作输入</h2>
            <div class="meta">一次生成微信公众号、小红书、抖音、视频号、B站五个平台内容。</div>
          </div>
        </div>
        <form id="run-form" class="composer">
          <div>
            <label for="topic">选题 / 创作要求</label>
            <textarea id="topic" name="topic" required placeholder="例如：用通俗、有案例的方式讲清楚 AI 自动化如何帮助本地生活商家做内容矩阵。"></textarea>
          </div>
          <div>
            <label>素材附件</label>
            <div class="composer-actions">
              <div class="row-actions">
                <button class="secondary icon" type="button" id="add-attachment" aria-label="上传素材" title="上传文本、图片或视频素材">+</button>
                <span class="meta">支持文本、图片、视频；单个文件不超过 <span id="max-upload-mb"></span>MB。</span>
              </div>
              <button type="submit" id="submit-run">加入生成队列</button>
            </div>
            <input id="attachment-input" class="hidden" type="file" multiple accept=".txt,.md,.json,.csv,.srt,.yaml,.yml,text/*,image/*,video/*">
            <div id="attachment-list" class="attachment-list"></div>
          </div>
        </form>
        <div id="composer-toast" class="toast"></div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h2>最近生成</h2>
            <div class="meta">已完成的任务可直接查看平台内容。</div>
          </div>
        </div>
        <div id="run-list" class="run-list"></div>
      </section>

    </div>

    <div class="column">
      <section>
        <div class="section-head">
          <div>
            <h2>队列状态</h2>
            <div class="meta">排队、生成中、完成和失败会自动刷新；完成后点击“查看”。</div>
          </div>
          <div class="row-actions">
            <button class="secondary" type="button" data-job-filter="">全部</button>
            <button class="secondary" type="button" data-job-filter="QUEUED">排队中</button>
            <button class="secondary" type="button" data-job-filter="RUNNING">生成中</button>
            <button class="secondary" type="button" data-job-filter="FAILED">失败</button>
          </div>
        </div>
        <div id="queue-metrics" class="status-strip"></div>
        <div id="job-list" class="job-list"></div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h2>生成内容预览</h2>
            <div id="preview-subtitle" class="meta">选择一个已完成任务后查看。</div>
          </div>
          <a id="download-button" class="button secondary" href="#" aria-disabled="true">下载当前内容</a>
        </div>
        <div class="preview-shell">
          <div id="platform-tabs" class="tabs"></div>
          <div id="content-files" class="content-files">
            <div class="empty">暂无选中的生成结果。</div>
          </div>
        </div>
      </section>

    </div>
  </main>

  <script>
    const initialState = JSON.parse(document.querySelector('#initial-state').textContent);
    const state = {
      platforms: initialState.platforms || [],
      defaultPlatforms: initialState.default_platforms || [],
      runs: initialState.runs || [],
      jobs: initialState.jobs || [],
      queueHealth: initialState.queue_health || {},
      attachments: [],
      selectedRunId: null,
      selectedPlatform: 'wechat',
      jobFilter: ''
    };

    const labels = {
      QUEUED: '排队中',
      RUNNING: '生成中',
      DONE: '已完成',
      FAILED: '失败',
      CANCELED: '已取消',
      ok: '正常',
      warn: '提醒',
      bad: '异常',
      ready: '就绪',
      unavailable: '不可用',
      run: '生成任务',
      resume: '继续任务'
    };

    const els = {
      healthPill: document.querySelector('#health-pill'),
      refreshButton: document.querySelector('#refresh-button'),
      runForm: document.querySelector('#run-form'),
      topic: document.querySelector('#topic'),
      addAttachment: document.querySelector('#add-attachment'),
      attachmentInput: document.querySelector('#attachment-input'),
      attachmentList: document.querySelector('#attachment-list'),
      submitRun: document.querySelector('#submit-run'),
      composerToast: document.querySelector('#composer-toast'),
      runList: document.querySelector('#run-list'),
      queueMetrics: document.querySelector('#queue-metrics'),
      jobList: document.querySelector('#job-list'),
      platformTabs: document.querySelector('#platform-tabs'),
      contentFiles: document.querySelector('#content-files'),
      previewSubtitle: document.querySelector('#preview-subtitle'),
      downloadButton: document.querySelector('#download-button'),
      maxUploadMb: document.querySelector('#max-upload-mb')
    };

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }

    function statusClass(status) {
      const normalized = String(status || '').toLowerCase();
      if (['done', 'ok', 'present', 'set', 'ready'].includes(normalized)) return 'ok';
      if (['failed', 'bad', 'missing', 'canceled'].includes(normalized)) return 'bad';
      if (['queued', 'running', 'warn', 'unavailable'].includes(normalized)) return 'warn';
      return normalized;
    }

    function statusPill(status) {
      const key = String(status || 'unknown');
      const label = labels[key] || labels[key.toUpperCase()] || key;
      return `<span class="status ${statusClass(key)}">${escapeHtml(label)}</span>`;
    }

    function showComposer(message) {
      els.composerToast.textContent = message || '';
    }

    function fileSizeLabel(bytes) {
      const size = Number(bytes || 0);
      if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
      if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${size} B`;
    }

    function kindLabel(kind) {
      if (kind === 'image') return '图';
      if (kind === 'video') return '视';
      if (kind === 'text') return '文';
      return '件';
    }

    function jobKindLabel(kind) {
      const translated = {
        run: '生成任务',
        resume: '继续任务'
      };
      return translated[kind] || kind || '';
    }

    function renderShell() {
      const healthStatus = initialState.health?.status || 'warn';
      els.healthPill.className = `status ${statusClass(healthStatus)}`;
      els.healthPill.textContent = `系统${labels[healthStatus] || healthStatus}`;
      els.maxUploadMb.textContent = initialState.limits?.max_upload_mb || '';
      renderPlatformTabs();
      renderAttachments();
      renderRuns();
      renderQueue();
    }

    function renderAttachments() {
      if (!state.attachments.length) {
        els.attachmentList.innerHTML = '<div class="empty">还没有上传素材。</div>';
        return;
      }
      els.attachmentList.innerHTML = state.attachments.map((file, index) => `
        <div class="attachment">
          <div class="file-kind">${escapeHtml(kindLabel(file.kind))}</div>
          <div>
            <strong>${escapeHtml(file.name)}</strong>
            <div class="meta">${escapeHtml(file.mime_type)} · ${escapeHtml(fileSizeLabel(file.size_bytes))}</div>
          </div>
          <button class="secondary" type="button" data-remove-attachment="${index}">移除</button>
        </div>
      `).join('');
      for (const button of els.attachmentList.querySelectorAll('[data-remove-attachment]')) {
        button.addEventListener('click', () => {
          state.attachments.splice(Number(button.dataset.removeAttachment), 1);
          renderAttachments();
        });
      }
    }

    function renderRuns() {
      const doneRuns = state.runs.filter((run) => String(run.status || '').toUpperCase() === 'DONE');
      const rows = (state.runs || []).slice(0, 8).map((run) => {
        const status = String(run.status || 'unknown').toUpperCase();
        const progress = run.completed_steps == null || run.total_steps == null
          ? '进度未记录'
          : `${run.completed_steps}/${run.total_steps}${run.progress_percent == null ? '' : ` (${run.progress_percent}%)`}`;
        const canView = status === 'DONE';
        return `
          <div class="run-row">
            <div class="row-title">
              <strong>${escapeHtml(run.topic || run.run_id)}</strong>
              ${statusPill(status)}
            </div>
            <div class="meta mono">${escapeHtml(run.run_id || '')}</div>
            <div class="meta">${escapeHtml(progress)} · ${escapeHtml(run.updated_at || '')}</div>
            <div class="row-actions">
              ${canView ? `<button type="button" data-view-run="${escapeHtml(run.run_id)}">查看</button>` : `<button class="secondary" type="button" data-resume-run="${escapeHtml(run.run_id)}">继续生成</button>`}
            </div>
          </div>
        `;
      }).join('');
      els.runList.innerHTML = rows || '<div class="empty">暂无生成记录。</div>';
      for (const button of els.runList.querySelectorAll('[data-view-run]')) {
        button.addEventListener('click', () => selectRun(button.dataset.viewRun));
      }
      for (const button of els.runList.querySelectorAll('[data-resume-run]')) {
        button.addEventListener('click', async () => {
          button.disabled = true;
          await postJson(`/api/runs/${encodeURIComponent(button.dataset.resumeRun)}/resume`, {});
          await refreshData();
          button.disabled = false;
        });
      }
      if (!state.selectedRunId && doneRuns.length) {
        selectRun(doneRuns[0].run_id, { quiet: true });
      }
    }

    function renderQueue() {
      const counts = state.queueHealth?.counts || {};
      const metrics = [
        ['QUEUED', '排队中'],
        ['RUNNING', '生成中'],
        ['DONE', '已完成'],
        ['FAILED', '失败'],
        ['CANCELED', '已取消']
      ];
      els.queueMetrics.innerHTML = metrics.map(([key, label]) => `
        <div class="metric">
          <strong>${escapeHtml(counts[key] || 0)}</strong>
          <span class="meta">${escapeHtml(label)}</span>
        </div>
      `).join('');
      const jobs = state.jobs || [];
      els.jobList.innerHTML = jobs.map((job) => {
        const status = String(job.status || 'unknown').toUpperCase();
        const runId = job.run_id || '';
        const actions = [];
        if (status === 'DONE' && runId) actions.push(`<button type="button" data-view-run="${escapeHtml(runId)}">查看</button>`);
        const attachmentCount = Array.isArray(job.attachments) ? job.attachments.length : 0;
        return `
          <div class="job-row">
            <div>
              <div class="row-title">
                <strong>${escapeHtml(job.topic || jobKindLabel(job.kind) || job.job_id)}</strong>
                ${statusPill(status)}
              </div>
              <div class="meta mono">${escapeHtml(job.job_id || '')}</div>
              <div class="meta">
                ${escapeHtml(jobKindLabel(job.kind))}
                ${runId ? ` · 运行记录 ${escapeHtml(runId)}` : ''}
                ${attachmentCount ? ` · ${attachmentCount} 个附件` : ''}
                ${job.worker_id ? ` · 执行器 ${escapeHtml(job.worker_id)}` : ''}
              </div>
              ${job.error ? `<div class="meta">${escapeHtml(job.error)}</div>` : ''}
            </div>
            <div class="row-actions">${actions.join('')}</div>
          </div>
        `;
      }).join('') || '<div class="empty">当前没有队列任务。</div>';
      for (const button of els.jobList.querySelectorAll('[data-view-run]')) {
        button.addEventListener('click', () => selectRun(button.dataset.viewRun));
      }
    }

    function renderPlatformTabs() {
      els.platformTabs.innerHTML = state.platforms.map((platform) => `
        <button class="tab ${platform.id === state.selectedPlatform ? 'active' : ''}" type="button" data-platform="${escapeHtml(platform.id)}">${escapeHtml(platform.label)}</button>
      `).join('');
      for (const button of els.platformTabs.querySelectorAll('[data-platform]')) {
        button.addEventListener('click', () => {
          state.selectedPlatform = button.dataset.platform;
          renderPlatformTabs();
          loadPlatformContent();
        });
      }
    }

    async function selectRun(runId, options = {}) {
      state.selectedRunId = runId;
      if (!options.quiet) {
        document.querySelector('#content-files')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      await loadPlatformContent();
    }

    async function loadPlatformContent() {
      if (!state.selectedRunId) {
        els.previewSubtitle.textContent = '选择一个已完成任务后查看。';
        els.downloadButton.setAttribute('aria-disabled', 'true');
        els.downloadButton.href = '#';
        els.contentFiles.innerHTML = '<div class="empty">暂无选中的生成结果。</div>';
        return;
      }
      els.previewSubtitle.textContent = `正在加载 ${state.selectedRunId} 的平台内容...`;
      els.contentFiles.innerHTML = '<div class="empty">正在读取生成文件。</div>';
      try {
        const payload = await getJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}/platforms/${encodeURIComponent(state.selectedPlatform)}`);
        els.previewSubtitle.textContent = `${payload.platform_label} · ${payload.topic || state.selectedRunId}`;
        els.downloadButton.href = payload.download_url || `/api/runs/${encodeURIComponent(state.selectedRunId)}/platforms/${encodeURIComponent(state.selectedPlatform)}/download`;
        els.downloadButton.removeAttribute('aria-disabled');
        if (!payload.files?.length) {
          els.contentFiles.innerHTML = '<div class="empty">这个平台还没有可预览的主内容文件。</div>';
          return;
        }
        els.contentFiles.innerHTML = payload.files.map((file) => `
          <article class="content-file">
            <header>
              <strong>${escapeHtml(file.label || file.path)}</strong>
              <span class="meta mono">${escapeHtml(file.path)} · ${escapeHtml(fileSizeLabel(file.size_bytes))}</span>
            </header>
            <pre>${escapeHtml(file.content || '')}${file.truncated ? '\\n\\n（内容过长，已截断显示；下载可获取当前可读主内容。）' : ''}</pre>
          </article>
        `).join('');
      } catch (error) {
        els.previewSubtitle.textContent = '读取失败';
        els.contentFiles.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    async function getJson(path) {
      const response = await fetch(path, { headers: { 'Accept': 'application/json' } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
      return payload;
    }

    async function postJson(path, payload) {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
      return body;
    }

    async function refreshData() {
      const [runs, jobs] = await Promise.all([
        getJson('/api/runs?limit=12'),
        getJson(state.jobFilter ? `/api/jobs?status=${encodeURIComponent(state.jobFilter)}` : '/api/jobs')
      ]);
      state.runs = runs.runs || [];
      state.jobs = jobs.jobs || [];
      state.queueHealth = jobs.queue_health || {};
      renderRuns();
      renderQueue();
    }

    function readFileAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const value = String(reader.result || '');
          resolve(value.includes(',') ? value.split(',').pop() : value);
        };
        reader.onerror = () => reject(reader.error || new Error('读取文件失败'));
        reader.readAsDataURL(file);
      });
    }

    els.addAttachment.addEventListener('click', () => els.attachmentInput.click());
    els.attachmentInput.addEventListener('change', async () => {
      const files = Array.from(els.attachmentInput.files || []);
      if (!files.length) return;
      els.addAttachment.disabled = true;
      showComposer('正在上传素材...');
      try {
        const payload = {
          files: await Promise.all(files.map(async (file) => ({
            name: file.name,
            mime_type: file.type || 'application/octet-stream',
            size_bytes: file.size,
            data_base64: await readFileAsBase64(file)
          })))
        };
        const upload = await postJson('/api/uploads', payload);
        state.attachments.push(...(upload.files || []));
        renderAttachments();
        showComposer(`已上传 ${upload.files?.length || 0} 个素材。`);
      } catch (error) {
        showComposer(error.message);
      } finally {
        els.attachmentInput.value = '';
        els.addAttachment.disabled = false;
      }
    });

    els.runForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const topic = els.topic.value.trim();
      if (!topic) {
        showComposer('请先输入选题。');
        return;
      }
      els.submitRun.disabled = true;
      showComposer('正在加入生成队列...');
      try {
        const job = await postJson('/api/runs', {
          topic,
          platforms: state.defaultPlatforms,
          attachments: state.attachments
        });
        showComposer(`已加入队列：${job.job_id}`);
        state.attachments = [];
        renderAttachments();
        await refreshData();
      } catch (error) {
        showComposer(error.message);
      } finally {
        els.submitRun.disabled = false;
      }
    });

    els.refreshButton.addEventListener('click', async () => {
      els.refreshButton.disabled = true;
      await refreshData();
      if (state.selectedRunId) await loadPlatformContent();
      els.refreshButton.disabled = false;
    });

    for (const button of document.querySelectorAll('[data-job-filter]')) {
      button.addEventListener('click', async () => {
        state.jobFilter = button.dataset.jobFilter || '';
        await refreshData();
      });
    }

    renderShell();
    window.setInterval(refreshData, 3000);
  </script>
</body>
</html>
"""
    return html_body.replace("__INITIAL_STATE__", _script_json(initial_state))


def render_admin_console_html(runtime: ConsoleRuntime) -> str:
    health = runtime.health()
    setup = runtime.setup_check()
    local_runtime = runtime.local_runtime_status()
    env_status = runtime.environment_status()
    job_index = runtime.list_jobs()
    initial_state = {
        "schema_version": "phase5.admin_console.initial_state.v1",
        "generated_at": _utc_now_iso(),
        "health": health,
        "setup": setup,
        "local_runtime": local_runtime,
        "env": env_status,
        "runs": runtime.list_runs(limit=12)["runs"],
        "jobs": job_index["jobs"][:30],
        "queue_health": job_index["queue_health"],
        "backups": runtime.list_backups(limit=8)["backups"],
        "retention": {
            "job_retention_days": runtime.config.job_retention_days,
            "audit_retention_days": runtime.config.audit_retention_days,
            "cleanup_confirmation": CLEANUP_CONFIRMATION,
        },
        "workflow_path": str(runtime.config.workflow_path),
    }
    html_body = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>后端控制台 - 自媒体内容创作</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef2f0;
      --surface: #ffffff;
      --surface-soft: #f7f9f8;
      --ink: #151f1b;
      --muted: #65726d;
      --line: #d7e0dc;
      --line-strong: #adbbb5;
      --accent: #115e4b;
      --accent-strong: #0b4638;
      --accent-soft: #e3f2ed;
      --blue: #215f99;
      --blue-soft: #e8f1f9;
      --amber: #956100;
      --amber-soft: #fff2d6;
      --red: #a3372f;
      --red-soft: #fdecea;
      --shadow: 0 14px 32px rgba(21, 31, 27, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background:
        linear-gradient(90deg, rgba(17, 94, 75, .055) 1px, transparent 1px),
        linear-gradient(180deg, rgba(17, 94, 75, .045) 1px, transparent 1px),
        var(--bg);
      background-size: 42px 42px;
      color: var(--ink);
      font: 14px/1.5 "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      letter-spacing: 0;
    }
    button, input, select { font: inherit; letter-spacing: 0; }
    button, a.button {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 6px 11px;
      background: var(--accent);
      color: #fff;
      font-weight: 760;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary, a.button.secondary {
      background: #fff;
      color: var(--accent-strong);
      border-color: var(--line-strong);
    }
    button.danger { border-color: var(--red); background: var(--red); }
    button:disabled { opacity: .58; cursor: wait; }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .94);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .brand-mark {
      width: 34px;
      height: 34px;
      border: 2px solid var(--ink);
      border-radius: 7px;
      display: grid;
      place-items: center;
      background: #fff;
      box-shadow: 4px 4px 0 var(--accent);
      font-weight: 900;
    }
    h1 { margin: 0; font-size: 20px; line-height: 1.2; }
    h2 { margin: 0; font-size: 16px; line-height: 1.25; }
    h3 { margin: 0; font-size: 14px; line-height: 1.3; }
    .meta { color: var(--muted); font-size: 12px; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }
    main {
      display: grid;
      gap: 16px;
      max-width: 1500px;
      margin: 0 auto;
      padding: 16px;
    }
    .overview-grid {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .metric strong {
      display: block;
      font-size: 24px;
      line-height: 1;
      margin-bottom: 5px;
    }
    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(320px, 440px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .column { display: grid; gap: 16px; align-content: start; }
    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .row-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 7px;
    }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #edf1ef;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
    }
    .status.ok, .status.done, .status.present, .status.set, .status.ready {
      background: var(--accent-soft);
      color: var(--accent-strong);
    }
    .status.warn, .status.running, .status.queued, .status.unavailable {
      background: var(--amber-soft);
      color: var(--amber);
    }
    .status.bad, .status.failed, .status.missing, .status.canceled, .status.unset {
      background: var(--red-soft);
      color: var(--red);
    }
    .stack-list, .job-list, .run-list, .backup-list, .env-list { display: grid; gap: 8px; }
    .info-row, .job-row, .run-row, .backup-row, .env-row {
      display: grid;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }
    .job-row {
      grid-template-columns: minmax(0, 1.4fr) auto;
      align-items: center;
    }
    .row-title {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 2px;
    }
    .command {
      display: grid;
      grid-template-columns: minmax(120px, 190px) minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      padding: 8px 0;
      border-top: 1px solid var(--line);
    }
    .command:first-child { border-top: 0; padding-top: 0; }
    .split {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .pill-line {
      display: flex;
      align-items: center;
      gap: 7px;
      flex-wrap: wrap;
    }
    .filter-bar {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding-bottom: 2px;
    }
    .filter-bar button.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .toast {
      min-height: 24px;
      color: var(--accent-strong);
      font-weight: 760;
    }
    .empty {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      padding: 16px;
      color: var(--muted);
      background: var(--surface-soft);
      text-align: center;
    }
    @media (max-width: 1100px) {
      header { grid-template-columns: 1fr; }
      .dashboard-grid { grid-template-columns: 1fr; }
      .overview-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      main { padding: 12px; }
      .overview-grid, .split { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .job-row, .command { grid-template-columns: 1fr; }
      .row-actions { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <script id="admin-state" type="application/json">__ADMIN_INITIAL_STATE__</script>
  <header>
    <div class="brand">
      <div class="brand-mark">控</div>
      <div>
        <h1>后端控制台</h1>
        <div class="meta">本机状态、配置检查、队列维护、备份恢复和环境变量安全状态。</div>
      </div>
    </div>
    <div class="row-actions">
      <span id="admin-health-pill" class="status">加载中</span>
      <a class="button secondary" href="/">创作工作台</a>
      <button class="secondary" type="button" id="admin-refresh">刷新</button>
    </div>
  </header>

  <main>
    <div id="overview-metrics" class="overview-grid"></div>

    <div class="dashboard-grid">
      <div class="column">
        <section>
          <div class="section-head">
            <div>
              <h2>本机状态</h2>
              <div class="meta">Local Runtime：Python + make commands 是主路径，Docker optional。</div>
            </div>
            <span id="local-runtime-pill" class="status">加载中</span>
          </div>
          <div id="local-runtime-summary" class="stack-list"></div>
          <div id="local-runtime-commands" class="stack-list"></div>
        </section>

        <section>
          <div class="section-head">
            <div>
              <h2>配置检查</h2>
              <div class="meta">Setup Check 会检查 workflow、五平台集合、目录、备份、durable job queue 和 secret presence。</div>
            </div>
            <span id="setup-pill" class="status">加载中</span>
          </div>
          <div id="setup-checks" class="stack-list"></div>
          <div id="setup-commands" class="stack-list"></div>
        </section>

        <section>
          <div class="section-head">
            <div>
              <h2>环境变量</h2>
              <div class="meta">Secret 只显示 present/missing，不显示真实值。</div>
            </div>
          </div>
          <div id="env-list" class="env-list"></div>
        </section>
      </div>

      <div class="column">
        <section>
          <div class="section-head">
            <div>
              <h2>队列维护</h2>
              <div class="meta">保留策略、清理预览和确认清理都在这里管理。</div>
            </div>
            <div class="row-actions">
              <button class="secondary" type="button" id="cleanup-dry-run">清理预览</button>
              <button class="danger" type="button" id="cleanup-confirm">确认清理</button>
            </div>
          </div>
          <div id="queue-maintenance-summary" class="split"></div>
          <div id="ops-toast" class="toast"></div>
        </section>

        <section>
          <div class="section-head">
            <div>
              <h2>队列任务</h2>
              <div class="meta">查看 durable job queue，处理取消、重试和标记失败。</div>
            </div>
            <div class="filter-bar">
              <button class="secondary active" type="button" data-admin-job-filter="">全部</button>
              <button class="secondary" type="button" data-admin-job-filter="QUEUED">排队中</button>
              <button class="secondary" type="button" data-admin-job-filter="RUNNING">生成中</button>
              <button class="secondary" type="button" data-admin-job-filter="FAILED">失败</button>
              <button class="secondary" type="button" data-admin-job-filter="CANCELED">已取消</button>
            </div>
          </div>
          <div id="jobs-list" class="job-list"></div>
        </section>

        <section>
          <div class="section-head">
            <div>
              <h2>备份恢复</h2>
              <div class="meta">备份 `outputs/runs/`，恢复必须输入精确确认短语。</div>
            </div>
            <button type="button" id="create-backup">创建备份</button>
          </div>
          <div id="backups-list" class="backup-list"></div>
        </section>

        <section>
          <div class="section-head">
            <div>
              <h2>运行记录</h2>
              <div class="meta">未完成的 run 可以重新加入队列继续执行。</div>
            </div>
          </div>
          <div id="runs-list" class="run-list"></div>
        </section>
      </div>
    </div>
  </main>

  <script>
    const initialState = JSON.parse(document.querySelector('#admin-state').textContent);
    const state = {
      health: initialState.health || {},
      setup: initialState.setup || {},
      localRuntime: initialState.local_runtime || {},
      env: initialState.env || {},
      runs: initialState.runs || [],
      jobs: initialState.jobs || [],
      queueHealth: initialState.queue_health || {},
      backups: initialState.backups || [],
      retention: initialState.retention || {},
      jobFilter: ''
    };

    const labels = {
      ok: '正常',
      warn: '提醒',
      bad: '异常',
      present: '已配置',
      missing: '缺失',
      set: '已设置',
      unset: '未设置',
      ready: '就绪',
      unavailable: '不可用',
      required: '必需',
      optional: '可选',
      available: '可用',
      unknown: '未知',
      QUEUED: '排队中',
      RUNNING: '生成中',
      DONE: '已完成',
      FAILED: '失败',
      CANCELED: '已取消',
      run: '生成任务',
      resume: '继续任务'
    };

    const commandLabels = {
      'Local console': '本地控制台',
      'One-shot worker': '单次执行器',
      'Long-running worker': '常驻执行器',
      'Dry-run scheduler tick': '调度器预演',
      'Long-running scheduler': '常驻调度器',
      'Optional Docker console': 'Docker 控制台',
      'Base validation': '基础验收',
      'Console validation': '控制台验收',
      'Migration validation': '迁移验收',
      'Setup validation': '配置向导验收',
      'Profile validation': 'Profiles 验收',
      'Job queue validation': '队列交接验收',
      'Local runtime validation': '本机运行验收',
      'Start local console': '启动本地控制台',
      'Optional Docker check': 'Docker 可选检查'
    };

    const els = {
      healthPill: document.querySelector('#admin-health-pill'),
      refresh: document.querySelector('#admin-refresh'),
      overviewMetrics: document.querySelector('#overview-metrics'),
      localRuntimePill: document.querySelector('#local-runtime-pill'),
      localRuntimeSummary: document.querySelector('#local-runtime-summary'),
      localRuntimeCommands: document.querySelector('#local-runtime-commands'),
      setupPill: document.querySelector('#setup-pill'),
      setupChecks: document.querySelector('#setup-checks'),
      setupCommands: document.querySelector('#setup-commands'),
      queueMaintenanceSummary: document.querySelector('#queue-maintenance-summary'),
      jobsList: document.querySelector('#jobs-list'),
      backupsList: document.querySelector('#backups-list'),
      runsList: document.querySelector('#runs-list'),
      envList: document.querySelector('#env-list'),
      opsToast: document.querySelector('#ops-toast'),
      cleanupDryRun: document.querySelector('#cleanup-dry-run'),
      cleanupConfirm: document.querySelector('#cleanup-confirm'),
      createBackup: document.querySelector('#create-backup')
    };

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }

    function statusClass(status) {
      const normalized = String(status || '').toLowerCase();
      if (['done', 'ok', 'present', 'set', 'ready', 'available'].includes(normalized)) return 'ok';
      if (['failed', 'bad', 'missing', 'canceled', 'unset'].includes(normalized)) return 'bad';
      if (['queued', 'running', 'warn', 'unavailable'].includes(normalized)) return 'warn';
      return normalized || 'warn';
    }

    function statusPill(status) {
      const key = String(status || 'unknown');
      const label = labels[key] || labels[key.toUpperCase()] || key;
      return `<span class="status ${statusClass(key)}">${escapeHtml(label)}</span>`;
    }

    function showOps(message) {
      els.opsToast.textContent = message || '';
    }

    function bytesLabel(bytes) {
      const size = Number(bytes || 0);
      if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
      if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${size} B`;
    }

    function commandLabel(label) {
      return commandLabels[label] || label || '';
    }

    function jobKindLabel(kind) {
      return labels[kind] || kind || '';
    }

    function renderAll() {
      renderHeader();
      renderOverview();
      renderLocalRuntime();
      renderSetup();
      renderQueueMaintenance();
      renderJobs();
      renderBackups();
      renderRuns();
      renderEnv();
    }

    function renderHeader() {
      const healthStatus = state.health.status || 'warn';
      els.healthPill.className = `status ${statusClass(healthStatus)}`;
      els.healthPill.textContent = `系统${labels[healthStatus] || healthStatus}`;
    }

    function renderOverview() {
      const counts = state.queueHealth.counts || {};
      const items = [
        ['系统状态', labels[state.health.status] || state.health.status || '未知'],
        ['本机运行', labels[state.localRuntime.status] || state.localRuntime.status || '未知'],
        ['排队中', counts.QUEUED || 0],
        ['生成中', counts.RUNNING || 0],
        ['已完成', counts.DONE || 0],
        ['失败', counts.FAILED || 0],
        ['已取消', counts.CANCELED || 0]
      ];
      els.overviewMetrics.innerHTML = items.map(([label, value]) => `
        <div class="metric">
          <strong>${escapeHtml(value)}</strong>
          <span class="meta">${escapeHtml(label)}</span>
        </div>
      `).join('');
    }

    function renderLocalRuntime() {
      const local = state.localRuntime || {};
      els.localRuntimePill.outerHTML = statusPill(local.status || 'warn').replace('<span', '<span id="local-runtime-pill"');
      els.localRuntimePill = document.querySelector('#local-runtime-pill');
      const dockerLabel = local.docker_available ? 'available' : 'unavailable';
      const runtimeMessage = local.docker_required
        ? '当前运行路径需要 Docker。'
        : '本机 Python 命令是主要运行路径；Docker 是可选项。';
      els.localRuntimeSummary.innerHTML = `
        <div class="info-row">
          <div class="row-title">${statusPill(local.status || 'warn')} <strong>本机运行</strong></div>
          <div class="meta">${escapeHtml(runtimeMessage)}</div>
          <div class="pill-line">
            <span class="meta">Docker</span>${statusPill(dockerLabel)}
            <span class="meta">内联任务</span>${statusPill(local.inline_jobs ? 'ready' : 'unavailable')}
            <span class="meta">调度器预演</span>${statusPill(local.scheduler_default_dry_run ? 'ready' : 'warn')}
          </div>
          <div class="meta mono">${escapeHtml(local.project_root || '')}</div>
          <div class="meta mono">队列数据库：${escapeHtml(local.job_db_path || '')}</div>
        </div>
      `;
      els.localRuntimeCommands.innerHTML = (local.commands || []).map((command) => `
        <div class="command">
          <div>
            <strong>${escapeHtml(commandLabel(command.label))}</strong>
            <div class="pill-line">${statusPill(command.required ? 'required' : 'optional')}${statusPill(command.ready ? 'ready' : 'unavailable')}</div>
          </div>
          <div class="mono">${escapeHtml(command.command)}</div>
        </div>
      `).join('');
    }

    function renderSetup() {
      const setup = state.setup || {};
      els.setupPill.outerHTML = statusPill(setup.status || 'warn').replace('<span', '<span id="setup-pill"');
      els.setupPill = document.querySelector('#setup-pill');
      els.setupChecks.innerHTML = (setup.checks || []).map((check) => `
        <div class="info-row">
          <div class="row-title">
            <strong>${escapeHtml(check.label || check.id)}</strong>
            ${statusPill(check.status || 'warn')}
          </div>
          <div class="meta">${escapeHtml(check.message || '')}</div>
          ${check.path ? `<div class="meta mono">${escapeHtml(check.path)}</div>` : ''}
          ${check.command ? `<div class="meta mono">${escapeHtml(check.command)}</div>` : ''}
        </div>
      `).join('');
      els.setupCommands.innerHTML = (setup.commands || []).map((command) => `
        <div class="command">
          <div>
            <strong>${escapeHtml(commandLabel(command.label))}</strong>
            ${statusPill(command.required ? 'required' : 'optional')}
          </div>
          <div class="mono">${escapeHtml(command.command)}</div>
        </div>
      `).join('');
    }

    function renderQueueMaintenance() {
      const health = state.queueHealth || {};
      const retention = state.retention || {};
      els.queueMaintenanceSummary.innerHTML = `
        <div class="metric">
          <strong>${escapeHtml(retention.job_retention_days ?? '')} 天</strong>
          <span class="meta">保留策略：任务历史</span>
        </div>
        <div class="metric">
          <strong>${escapeHtml(retention.audit_retention_days ?? '')} 天</strong>
          <span class="meta">保留策略：审计日志</span>
        </div>
        <div class="metric">
          <strong>${escapeHtml(health.stale_running_count || 0)}</strong>
          <span class="meta">疑似卡住的 RUNNING</span>
        </div>
        <div class="metric">
          <strong class="mono">${escapeHtml(retention.cleanup_confirmation || 'CLEANUP JOBS')}</strong>
          <span class="meta">确认清理短语</span>
        </div>
        <div class="metric" style="grid-column: 1 / -1;">
          <strong class="mono">${escapeHtml(health.job_db_path || '')}</strong>
          <span class="meta">队列数据库</span>
        </div>
      `;
    }

    function renderJobs() {
      const jobs = state.jobs || [];
      if (!jobs.length) {
        els.jobsList.innerHTML = '<div class="empty">当前没有队列任务。</div>';
        return;
      }
      els.jobsList.innerHTML = jobs.map((job) => {
        const status = String(job.status || 'unknown').toUpperCase();
        const actions = [];
        if (status === 'QUEUED') {
          actions.push(`<button class="secondary" type="button" data-admin-job-action="cancel" data-admin-job-id="${escapeHtml(job.job_id)}">取消</button>`);
        }
        if (status === 'RUNNING') {
          actions.push(`<button class="secondary" type="button" data-admin-job-action="mark-failed" data-admin-job-id="${escapeHtml(job.job_id)}">标记失败</button>`);
        }
        if (status === 'FAILED' || status === 'CANCELED') {
          actions.push(`<button class="secondary" type="button" data-admin-job-action="retry" data-admin-job-id="${escapeHtml(job.job_id)}">重试</button>`);
        }
        actions.push(`<a class="button secondary" href="/api/jobs/${encodeURIComponent(job.job_id)}/audit">审计</a>`);
        const runId = job.run_id || '';
        return `
          <div class="job-row">
            <div>
              <div class="row-title">
                <strong>${escapeHtml(job.topic || jobKindLabel(job.kind) || job.job_id)}</strong>
                ${statusPill(status)}
              </div>
              <div class="meta mono">${escapeHtml(job.job_id || '')}</div>
              <div class="meta">
                ${escapeHtml(jobKindLabel(job.kind))}
                ${runId ? ` · 运行记录 ${escapeHtml(runId)}` : ''}
                ${job.worker_id ? ` · 执行器 ${escapeHtml(job.worker_id)}` : ''}
                ${job.attempt_count ? ` · 尝试 ${escapeHtml(job.attempt_count)}` : ''}
              </div>
              ${job.error ? `<div class="meta">${escapeHtml(job.error)}</div>` : ''}
            </div>
            <div class="row-actions">${actions.join('')}</div>
          </div>
        `;
      }).join('');
    }

    function renderBackups() {
      if (!state.backups.length) {
        els.backupsList.innerHTML = '<div class="empty">还没有本地备份。</div>';
        return;
      }
      els.backupsList.innerHTML = state.backups.map((backup) => `
        <div class="backup-row">
          <div class="row-title"><strong class="mono">${escapeHtml(backup.name)}</strong></div>
          <div class="meta">${escapeHtml(bytesLabel(backup.size_bytes))} · ${escapeHtml(backup.updated_at || '')}</div>
          <div class="row-actions">
            <button class="secondary" type="button" data-admin-restore-dry-run="${escapeHtml(backup.name)}">恢复预览</button>
            <button class="secondary" type="button" data-admin-restore-confirm="${escapeHtml(backup.name)}">恢复</button>
          </div>
        </div>
      `).join('');
    }

    function renderRuns() {
      if (!state.runs.length) {
        els.runsList.innerHTML = '<div class="empty">暂无运行记录。</div>';
        return;
      }
      els.runsList.innerHTML = state.runs.map((run) => {
        const status = String(run.status || 'unknown').toUpperCase();
        const progress = run.completed_steps == null || run.total_steps == null
          ? '进度未记录'
          : `${run.completed_steps}/${run.total_steps}${run.progress_percent == null ? '' : ` (${run.progress_percent}%)`}`;
        return `
          <div class="run-row">
            <div class="row-title">
              <strong>${escapeHtml(run.topic || run.run_id)}</strong>
              ${statusPill(status)}
            </div>
            <div class="meta mono">${escapeHtml(run.run_id || '')}</div>
            <div class="meta">${escapeHtml(progress)} · ${escapeHtml(run.updated_at || '')}</div>
            <div class="row-actions">
              ${status !== 'DONE' ? `<button class="secondary" type="button" data-admin-resume-run="${escapeHtml(run.run_id)}">继续执行</button>` : `<a class="button secondary" href="/api/runs/${encodeURIComponent(run.run_id)}">查看 JSON</a>`}
            </div>
          </div>
        `;
      }).join('');
    }

    function renderEnv() {
      const secrets = (state.env.secrets || []).map((item) => ({ ...item, secret: true }));
      const runtime = (state.env.runtime || []).map((item) => ({ ...item, secret: false }));
      const rows = [...secrets, ...runtime];
      els.envList.innerHTML = rows.map((item) => `
        <div class="env-row">
          <div class="row-title">
            <strong class="mono">${escapeHtml(item.name)}</strong>
            ${statusPill(item.present ? (item.secret ? 'present' : 'set') : (item.secret ? 'missing' : 'unset'))}
          </div>
          <div class="meta">${item.secret ? 'secret 值已隐藏' : escapeHtml(item.value || '')}</div>
        </div>
      `).join('') || '<div class="empty">暂无环境变量状态。</div>';
    }

    async function getJson(path) {
      const response = await fetch(path, { headers: { 'Accept': 'application/json' } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
      return payload;
    }

    async function postJson(path, payload = {}) {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
      return body;
    }

    async function refreshAdminData() {
      const jobsPath = state.jobFilter ? `/api/jobs?status=${encodeURIComponent(state.jobFilter)}` : '/api/jobs';
      const [health, setup, localRuntime, env, runs, jobs, backups] = await Promise.all([
        getJson('/healthz'),
        getJson('/api/setup-check'),
        getJson('/api/local-runtime'),
        getJson('/api/env'),
        getJson('/api/runs?limit=12'),
        getJson(jobsPath),
        getJson('/api/backups')
      ]);
      state.health = health;
      state.setup = setup;
      state.localRuntime = localRuntime;
      state.env = env;
      state.runs = runs.runs || [];
      state.jobs = jobs.jobs || [];
      state.queueHealth = jobs.queue_health || {};
      state.backups = (backups.backups || []).slice(0, 8);
      renderAll();
    }

    els.refresh.addEventListener('click', async () => {
      els.refresh.disabled = true;
      try {
        await refreshAdminData();
        showOps('后台控制台已刷新。');
      } catch (error) {
        showOps(error.message);
      } finally {
        els.refresh.disabled = false;
      }
    });

    document.addEventListener('click', async (event) => {
      const target = event.target.closest('button');
      if (!target) return;
      const jobFilter = target.getAttribute('data-admin-job-filter');
      if (jobFilter !== null) {
        for (const button of document.querySelectorAll('[data-admin-job-filter]')) button.classList.remove('active');
        target.classList.add('active');
        state.jobFilter = jobFilter || '';
        await refreshAdminData();
        return;
      }

      const jobAction = target.getAttribute('data-admin-job-action');
      if (jobAction) {
        target.disabled = true;
        try {
          const jobId = target.getAttribute('data-admin-job-id');
          const payload = await postJson(`/api/jobs/${encodeURIComponent(jobId)}/${jobAction}`);
          showOps(`${labels[payload.status] || payload.status}: ${payload.job_id}`);
          await refreshAdminData();
        } catch (error) {
          showOps(error.message);
        } finally {
          target.disabled = false;
        }
        return;
      }

      const restoreDryRun = target.getAttribute('data-admin-restore-dry-run');
      if (restoreDryRun) {
        target.disabled = true;
        try {
          const payload = await postJson('/api/restore-dry-run', { backup: restoreDryRun });
          showOps(`恢复预览：${payload.file_count} 个文件，${payload.would_overwrite_count} 个覆盖，${payload.safe_to_restore ? '可恢复' : '已阻止'}`);
        } catch (error) {
          showOps(error.message);
        } finally {
          target.disabled = false;
        }
        return;
      }

      const restoreConfirm = target.getAttribute('data-admin-restore-confirm');
      if (restoreConfirm) {
        const confirmation = window.prompt(`输入 RESTORE ${restoreConfirm} 确认恢复`);
        if (confirmation === null) return;
        target.disabled = true;
        try {
          const payload = await postJson('/api/restore', { backup: restoreConfirm, confirmation });
          showOps(`恢复完成：${payload.file_count} 个文件，覆盖 ${payload.overwrote_count} 个。`);
          await refreshAdminData();
        } catch (error) {
          showOps(error.message);
        } finally {
          target.disabled = false;
        }
        return;
      }

      const resumeRun = target.getAttribute('data-admin-resume-run');
      if (resumeRun) {
        target.disabled = true;
        try {
          const payload = await postJson(`/api/runs/${encodeURIComponent(resumeRun)}/resume`);
          showOps(`已加入队列：${payload.job_id}`);
          await refreshAdminData();
        } catch (error) {
          showOps(error.message);
        } finally {
          target.disabled = false;
        }
      }
    });

    els.cleanupDryRun.addEventListener('click', async () => {
      els.cleanupDryRun.disabled = true;
      try {
        const payload = await postJson('/api/jobs/cleanup-dry-run');
        showOps(`清理预览：将删除 ${payload.delete_job_count} 个历史任务、${payload.delete_audit_count} 条审计日志。`);
      } catch (error) {
        showOps(error.message);
      } finally {
        els.cleanupDryRun.disabled = false;
      }
    });

    els.cleanupConfirm.addEventListener('click', async () => {
      const expected = state.retention.cleanup_confirmation || 'CLEANUP JOBS';
      const confirmation = window.prompt(`输入 ${expected} 确认清理历史队列`);
      if (confirmation === null) return;
      els.cleanupConfirm.disabled = true;
      try {
        const payload = await postJson('/api/jobs/cleanup', { confirmation });
        showOps(`确认清理完成：删除 ${payload.deleted_job_count} 个历史任务、${payload.deleted_audit_count} 条审计日志。`);
        await refreshAdminData();
      } catch (error) {
        showOps(error.message);
      } finally {
        els.cleanupConfirm.disabled = false;
      }
    });

    els.createBackup.addEventListener('click', async () => {
      els.createBackup.disabled = true;
      try {
        const payload = await postJson('/api/backups');
        showOps(`备份已创建：${payload.backup_path}`);
        await refreshAdminData();
      } catch (error) {
        showOps(error.message);
      } finally {
        els.createBackup.disabled = false;
      }
    });

    renderAll();
    window.setInterval(refreshAdminData, 5000);
  </script>
</body>
</html>
"""
    return html_body.replace("__ADMIN_INITIAL_STATE__", _script_json(initial_state))


def _render_legacy_console_html(runtime: ConsoleRuntime) -> str:
    health = runtime.health()
    env_status = runtime.environment_status()
    setup = runtime.setup_check()
    runs = runtime.list_runs(limit=12)["runs"]
    job_index = runtime.list_jobs()
    jobs = job_index["jobs"][:12]
    queue_health = job_index["queue_health"]
    backups = runtime.list_backups()["backups"][:5]
    status_class = "ok" if health.get("status") == "ok" else "warn"
    platform_checks = "\n".join(
        (
            f'<label><input type="checkbox" value="{html.escape(platform)}" checked disabled> '
            f'{html.escape(platform)}<input type="hidden" name="platforms" value="{html.escape(platform)}"></label>'
        )
        for platform in runtime.config.default_platforms
    )
    secret_rows = "\n".join(
        f"<tr><td>{html.escape(item['name'])}</td><td>{_status_pill('present' if item['present'] else 'missing')}</td><td>hidden</td></tr>"
        for item in env_status["secrets"]
    )
    runtime_rows = "\n".join(
        f"<tr><td>{html.escape(item['name'])}</td><td>{_status_pill('set' if item['present'] else 'unset')}</td><td>{html.escape(str(item['value'] or ''))}</td></tr>"
        for item in env_status["runtime"]
    )
    run_rows = "\n".join(_run_row(run) for run in runs) or '<tr><td colspan="6">No runs yet.</td></tr>'
    job_rows = "\n".join(_job_row(job) for job in jobs) or '<tr><td colspan="8">No durable jobs yet.</td></tr>'
    queue_health_cards = _queue_health_cards(queue_health)
    backup_rows = "\n".join(_backup_row(backup) for backup in backups) or '<tr><td colspan="4">No backups yet.</td></tr>'
    setup_rows = "\n".join(_setup_check_row(check) for check in setup["checks"])
    setup_commands = "\n".join(_setup_command(command) for command in setup["commands"])
    local_runtime = runtime.local_runtime_status()
    local_runtime_rows = "\n".join(_local_runtime_command(command) for command in local_runtime["commands"])
    docker_note = "available" if local_runtime["docker_available"] else "not installed; local runtime does not require it"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Content Agent OS Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f5f2;
      --panel: #ffffff;
      --ink: #1c1d1f;
      --muted: #646a73;
      --line: #d8d2c7;
      --ok: #1f7a4d;
      --warn: #b45f06;
      --bad: #b42318;
      --accent: #2866a6;
      --accent-strong: #184a78;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: #fffdf8;
    }}
    h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
    h2 {{ margin: 0 0 12px; font-size: 15px; font-weight: 700; }}
    main {{
      display: grid;
      grid-template-columns: minmax(280px, 360px) 1fr;
      gap: 18px;
      padding: 18px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .stack {{ display: grid; gap: 14px; align-content: start; }}
    .meta {{ color: var(--muted); font-size: 12px; }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #ece8df;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .status.ok, .status.done, .status.present, .status.set {{ background: #e7f3ec; color: var(--ok); }}
    .status.warn, .status.running, .status.queued {{ background: #fff0d9; color: var(--warn); }}
    .status.bad, .status.failed, .status.missing {{ background: #fde8e6; color: var(--bad); }}
    label {{ display: block; margin: 0 0 8px; color: var(--muted); font-weight: 650; }}
    input[type="text"], textarea {{
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--ink);
      background: #fff;
      font: inherit;
    }}
    textarea {{ min-height: 92px; resize: vertical; }}
    .checks {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px 10px;
      margin: 10px 0 14px;
    }}
    .checks label {{ margin: 0; color: var(--ink); font-weight: 500; }}
    button {{
      min-height: 36px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{ background: #fff; color: var(--accent-strong); }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{
      padding: 8px 6px;
      border-bottom: 1px solid #ebe7df;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{ color: var(--muted); font-size: 12px; font-weight: 750; }}
    .wide {{ display: grid; gap: 14px; align-content: start; }}
    .path {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
    .commands {{ display: grid; gap: 6px; margin-top: 12px; }}
    .health-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin: 6px 0 12px;
    }}
    .metric {{
      border: 1px solid #ebe7df;
      border-radius: 6px;
      padding: 8px;
      background: #fffdf8;
    }}
    .metric strong {{ display: block; font-size: 18px; line-height: 1.1; }}
    .command {{
      display: grid;
      grid-template-columns: minmax(90px, 140px) 1fr;
      gap: 8px;
      align-items: start;
      padding: 7px 0;
      border-top: 1px solid #ebe7df;
    }}
    .command:first-child {{ border-top: 0; }}
    #toast {{ min-height: 18px; color: var(--accent-strong); font-weight: 700; }}
    @media (max-width: 860px) {{
      main {{ grid-template-columns: 1fr; padding: 12px; }}
      header {{ align-items: flex-start; flex-direction: column; }}
      .checks {{ grid-template-columns: 1fr; }}
      .command {{ grid-template-columns: 1fr; }}
      .health-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Content Agent OS Console</h1>
      <div class="meta">Workflow: {html.escape(str(runtime.config.workflow_path))}</div>
    </div>
    <span class="status {status_class}">{html.escape(str(health.get("status")))}</span>
  </header>
  <main>
    <div class="stack">
      <section>
        <div class="actions" style="justify-content: space-between;">
          <h2>Setup Check</h2>
          {_status_pill(str(setup.get("status") or "unknown"))}
        </div>
        <table>
          <thead><tr><th>Check</th><th>Status</th><th>Message</th></tr></thead>
          <tbody>{setup_rows}</tbody>
        </table>
        <div class="commands">{setup_commands}</div>
      </section>
      <section>
        <div class="actions" style="justify-content: space-between;">
          <h2>Local Runtime</h2>
          {_status_pill(str(local_runtime.get("status") or "unknown"))}
        </div>
        <div class="meta">Docker: {html.escape(docker_note)}</div>
        <div class="meta">Inline jobs: {html.escape(str(local_runtime.get("inline_jobs")))}</div>
        <div class="meta">Scheduler dry-run default: {html.escape(str(local_runtime.get("scheduler_default_dry_run")))}</div>
        <div class="commands">{local_runtime_rows}</div>
      </section>
      <section>
        <h2>New Run</h2>
        <form id="run-form">
          <label for="topic">Topic</label>
          <textarea id="topic" name="topic" required>AI content automation system</textarea>
          <div class="checks">{platform_checks}</div>
          <div class="actions">
            <button type="submit">Start Run</button>
            <button class="secondary" type="button" id="refresh">Refresh</button>
          </div>
        </form>
      </section>
      <section>
        <h2>Environment</h2>
        <table>
          <thead><tr><th>Name</th><th>Status</th><th>Value</th></tr></thead>
          <tbody>{secret_rows}{runtime_rows}</tbody>
        </table>
      </section>
      <section>
        <h2>Backups</h2>
        <div class="actions"><button type="button" id="backup">Create Backup</button></div>
        <table>
          <thead><tr><th>Name</th><th>Size</th><th>Updated</th><th>Action</th></tr></thead>
          <tbody>{backup_rows}</tbody>
        </table>
      </section>
    </div>
    <div class="wide">
      <section>
        <div class="actions" style="justify-content: space-between;">
          <h2>Runs</h2>
          <div id="toast"></div>
        </div>
        <table>
          <thead><tr><th>Run</th><th>Topic</th><th>Status</th><th>Progress</th><th>Updated</th><th>Action</th></tr></thead>
          <tbody>{run_rows}</tbody>
        </table>
      </section>
      <section>
        <div class="actions" style="justify-content: space-between;">
          <h2>Jobs</h2>
          <div class="actions">
            <button class="secondary" type="button" data-job-filter="">All</button>
            <button class="secondary" type="button" data-job-filter="QUEUED">Queued</button>
            <button class="secondary" type="button" data-job-filter="RUNNING">Running</button>
            <button class="secondary" type="button" data-job-filter="FAILED">Failed</button>
          </div>
        </div>
        <div class="meta path">Job DB: {html.escape(str(queue_health.get("job_db_path") or ""))}</div>
        <div class="meta">
          Retention: jobs {int(runtime.config.job_retention_days)} days, audit {int(runtime.config.audit_retention_days)} days
        </div>
        <div class="health-grid">{queue_health_cards}</div>
        <div class="actions" style="margin-bottom: 10px;">
          <button class="secondary" type="button" id="cleanup-dry-run">Cleanup Dry-Run</button>
          <button class="secondary" type="button" id="cleanup-confirm">Confirm Cleanup</button>
        </div>
        <table>
          <thead><tr><th>Job</th><th>Kind</th><th>Status</th><th>Worker</th><th>Run</th><th>Timing</th><th>Error</th><th>Action</th></tr></thead>
          <tbody>{job_rows}</tbody>
        </table>
      </section>
    </div>
  </main>
  <script>
    const toast = document.querySelector('#toast');
    function show(message) {{ toast.textContent = message; }}
    document.querySelector('#refresh').addEventListener('click', () => location.reload());
    document.querySelector('#backup').addEventListener('click', async (event) => {{
      event.target.disabled = true;
      show('Creating backup...');
      const response = await fetch('/api/backups', {{ method: 'POST' }});
      const payload = await response.json();
      show(response.ok ? `Backup created: ${{payload.backup_path}}` : payload.error);
      event.target.disabled = false;
    }});
    document.querySelector('#run-form').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const form = new FormData(event.target);
      const platforms = form.getAll('platforms');
      show('Queueing run...');
      const response = await fetch('/api/runs', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ topic: form.get('topic'), platforms }})
      }});
      const payload = await response.json();
      show(response.ok ? `Queued ${{payload.job_id}}` : payload.error);
    }});
    for (const button of document.querySelectorAll('[data-resume]')) {{
      button.addEventListener('click', async () => {{
        button.disabled = true;
        const runId = button.getAttribute('data-resume');
        const response = await fetch(`/api/runs/${{runId}}/resume`, {{ method: 'POST' }});
        const payload = await response.json();
        show(response.ok ? `Queued ${{payload.job_id}}` : payload.error);
        button.disabled = false;
      }});
    }}
    for (const button of document.querySelectorAll('[data-job-filter]')) {{
      button.addEventListener('click', async () => {{
        const status = button.getAttribute('data-job-filter');
        const suffix = status ? `?status=${{encodeURIComponent(status)}}` : '';
        const response = await fetch(`/api/jobs${{suffix}}`);
        const payload = await response.json();
        show(response.ok ? `Jobs loaded: ${{payload.jobs.length}}` : payload.error);
      }});
    }}
    for (const button of document.querySelectorAll('[data-job-action]')) {{
      button.addEventListener('click', async () => {{
        button.disabled = true;
        const jobId = button.getAttribute('data-job-id');
        const action = button.getAttribute('data-job-action');
        const response = await fetch(`/api/jobs/${{jobId}}/${{action}}`, {{ method: 'POST' }});
        const payload = await response.json();
        if (response.ok) {{
          show(`${{action}}: ${{payload.job_id}} ${{payload.status}}`);
          window.setTimeout(() => location.reload(), 350);
        }} else {{
          show(payload.error);
        }}
        button.disabled = false;
      }});
    }}
    document.querySelector('#cleanup-dry-run').addEventListener('click', async (event) => {{
      event.target.disabled = true;
      const response = await fetch('/api/jobs/cleanup-dry-run', {{ method: 'POST' }});
      const payload = await response.json();
      if (response.ok) {{
        show(`Cleanup dry-run: ${{payload.delete_job_count}} jobs, ${{payload.delete_audit_count}} audit entries`);
      }} else {{
        show(payload.error);
      }}
      event.target.disabled = false;
    }});
    document.querySelector('#cleanup-confirm').addEventListener('click', async (event) => {{
      const confirmation = window.prompt('Type {CLEANUP_CONFIRMATION} to cleanup old job history');
      if (confirmation === null) return;
      event.target.disabled = true;
      const response = await fetch('/api/jobs/cleanup', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ confirmation }})
      }});
      const payload = await response.json();
      if (response.ok) {{
        show(`Cleanup deleted: ${{payload.deleted_job_count}} jobs, ${{payload.deleted_audit_count}} audit entries`);
        window.setTimeout(() => location.reload(), 350);
      }} else {{
        show(payload.error);
      }}
      event.target.disabled = false;
    }});
    for (const button of document.querySelectorAll('[data-restore-dry-run]')) {{
      button.addEventListener('click', async () => {{
        button.disabled = true;
        const backup = button.getAttribute('data-restore-dry-run');
        show('Checking restore...');
        const response = await fetch('/api/restore-dry-run', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ backup }})
        }});
        const payload = await response.json();
        if (response.ok) {{
          const safe = payload.safe_to_restore ? 'safe' : 'blocked';
          show(`Restore dry-run: ${{payload.file_count}} files, ${{payload.would_overwrite_count}} overwrites, ${{safe}}`);
        }} else {{
          show(payload.error);
        }}
        button.disabled = false;
      }});
    }}
    for (const button of document.querySelectorAll('[data-restore-confirm]')) {{
      button.addEventListener('click', async () => {{
        const backup = button.getAttribute('data-restore-confirm');
        const confirmation = window.prompt(`Type RESTORE ${{backup}} to restore this backup`);
        if (confirmation === null) return;
        button.disabled = true;
        show('Restoring backup...');
        const response = await fetch('/api/restore', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ backup, confirmation }})
        }});
        const payload = await response.json();
        if (response.ok) {{
          show(`Restored ${{payload.file_count}} files, ${{payload.overwrote_count}} overwritten`);
        }} else {{
          show(payload.error);
        }}
        button.disabled = false;
      }});
    }}
  </script>
</body>
</html>
"""


def run_console_server(
    *,
    host: str,
    port: int,
    workflow_path: Path,
    output_root: Path,
    backup_root: Path,
    default_platforms: list[str],
    execute_inline_jobs: bool = True,
    job_retention_days: int = DEFAULT_JOB_RETENTION_DAYS,
    audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS,
) -> None:
    runtime = ConsoleRuntime(
        ConsoleConfig(
            workflow_path=workflow_path,
            output_root=output_root,
            backup_root=backup_root,
            default_platforms=default_platforms,
            execute_inline_jobs=execute_inline_jobs,
            job_retention_days=job_retention_days,
            audit_retention_days=audit_retention_days,
        )
    )
    handler = make_console_handler(runtime)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Content Agent OS console listening on http://{host}:{server.server_port}")
    print(f"Output root: {output_root}")
    print(f"Backup root: {backup_root}")
    print(f"Inline jobs: {execute_inline_jobs}")
    print(f"Retention: jobs={job_retention_days}d audit={audit_retention_days}d")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Console stopped.")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Content Agent OS local console.")
    parser.add_argument("--host", default=os.environ.get("CONTENT_AGENT_CONSOLE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CONTENT_AGENT_CONSOLE_PORT", "8080")))
    parser.add_argument(
        "--workflow",
        default=os.environ.get("CONTENT_AGENT_WORKFLOW", str(DEFAULT_WORKFLOW_PATH)),
        help="Workflow definition path.",
    )
    parser.add_argument(
        "--output-root",
        default=os.environ.get("CONTENT_AGENT_OUTPUT_ROOT", "outputs/runs"),
        help="Workflow run output root.",
    )
    parser.add_argument(
        "--backup-root",
        default=os.environ.get("CONTENT_AGENT_BACKUP_ROOT", str(DEFAULT_BACKUP_ROOT)),
        help="Local backup directory.",
    )
    parser.add_argument(
        "--inline-jobs",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("CONTENT_AGENT_CONSOLE_INLINE_JOBS", "1")),
        help="Execute queued console jobs in this console process.",
    )
    parser.add_argument(
        "--job-retention-days",
        type=int,
        default=int(os.environ.get("CONTENT_AGENT_JOB_RETENTION_DAYS", str(DEFAULT_JOB_RETENTION_DAYS))),
    )
    parser.add_argument(
        "--audit-retention-days",
        type=int,
        default=int(os.environ.get("CONTENT_AGENT_AUDIT_RETENTION_DAYS", str(DEFAULT_AUDIT_RETENTION_DAYS))),
    )
    parser.add_argument("--platforms", default=os.environ.get("CONTENT_AGENT_PLATFORMS", ",".join(DEFAULT_PLATFORMS)))
    args = parser.parse_args()
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    run_console_server(
        host=args.host,
        port=args.port,
        workflow_path=Path(args.workflow),
        output_root=Path(args.output_root),
        backup_root=Path(args.backup_root),
        default_platforms=platforms or DEFAULT_PLATFORMS,
        execute_inline_jobs=args.inline_jobs,
        job_retention_days=args.job_retention_days,
        audit_retention_days=args.audit_retention_days,
    )
    return 0


def _run_card(run_dir: Path) -> dict[str, Any]:
    workflow_run = _load_json(run_dir / "workflow_run.json")
    snapshot = _load_json(run_dir / "monitor/supervision_snapshot.json")
    summary = snapshot.get("summary", {}) if isinstance(snapshot, dict) else {}
    return {
        "run_id": workflow_run.get("run_id") or run_dir.name,
        "topic": workflow_run.get("topic"),
        "status": workflow_run.get("status"),
        "progress_percent": summary.get("progress_percent"),
        "completed_steps": summary.get("completed_steps"),
        "total_steps": summary.get("total_steps"),
        "updated_at": workflow_run.get("updated_at"),
        "run_dir": str(run_dir),
        "artifact_count": len(workflow_run.get("artifacts", [])) if isinstance(workflow_run.get("artifacts"), list) else 0,
    }


def _setup_check_row(check: dict[str, Any]) -> str:
    details = html.escape(str(check.get("message") or ""))
    path = check.get("path")
    command = check.get("command")
    if path:
        details += f'<div class="path">{html.escape(str(path))}</div>'
    if command:
        details += f'<div class="path">{html.escape(str(command))}</div>'
    return (
        "<tr>"
        f"<td>{html.escape(str(check.get('label') or ''))}</td>"
        f"<td>{_status_pill(str(check.get('status') or 'unknown'))}</td>"
        f"<td>{details}</td>"
        "</tr>"
    )


def _setup_command(command: dict[str, Any]) -> str:
    required = "required" if command.get("required") else "optional"
    return (
        '<div class="command">'
        f"<div>{html.escape(str(command.get('label') or ''))} {_status_pill(required)}</div>"
        f"<div class=\"path\">{html.escape(str(command.get('command') or ''))}</div>"
        "</div>"
    )


def _local_runtime_command(command: dict[str, Any]) -> str:
    required = "required" if command.get("required") else "optional"
    ready = "ready" if command.get("ready") else "unavailable"
    return (
        '<div class="command">'
        f"<div>{html.escape(str(command.get('label') or ''))} {_status_pill(required)} {_status_pill(ready)}</div>"
        f"<div class=\"path\">{html.escape(str(command.get('command') or ''))}</div>"
        "</div>"
    )


def _queue_health_message(health: dict[str, Any]) -> str:
    counts = health.get("counts", {}) if isinstance(health.get("counts"), dict) else {}
    return (
        f"queued={counts.get('QUEUED', 0)}, "
        f"running={counts.get('RUNNING', 0)}, "
        f"failed={counts.get('FAILED', 0)}, "
        f"stale={health.get('stale_running_count', 0)}"
    )


def _run_row(run: dict[str, Any]) -> str:
    run_id = str(run.get("run_id") or "")
    status = str(run.get("status") or "unknown").lower()
    progress = _progress_label(run)
    action = ""
    if status != "done":
        action = f'<button class="secondary" type="button" data-resume="{html.escape(run_id)}">Resume</button>'
    return (
        "<tr>"
        f"<td class=\"path\">{html.escape(run_id)}</td>"
        f"<td>{html.escape(str(run.get('topic') or ''))}</td>"
        f"<td>{_status_pill(status)}</td>"
        f"<td>{html.escape(progress)}</td>"
        f"<td>{html.escape(str(run.get('updated_at') or ''))}</td>"
        f"<td>{action}</td>"
        "</tr>"
    )


def _job_row(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "unknown").lower()
    job_id = str(job.get("job_id") or "")
    actions = []
    if status == "queued":
        actions.append(f'<button class="secondary" type="button" data-job-action="cancel" data-job-id="{html.escape(job_id)}">Cancel</button>')
    if status == "running":
        actions.append(f'<button class="secondary" type="button" data-job-action="mark-failed" data-job-id="{html.escape(job_id)}">Mark Failed</button>')
    if status in {"failed", "canceled"}:
        actions.append(f'<button class="secondary" type="button" data-job-action="retry" data-job-id="{html.escape(job_id)}">Retry</button>')
    timing = "<br>".join(
        html.escape(str(value))
        for value in [job.get("started_at"), job.get("ended_at"), job.get("updated_at")]
        if value
    )
    return (
        "<tr>"
        f"<td class=\"path\">{html.escape(job_id)}</td>"
        f"<td>{html.escape(str(job.get('kind') or ''))}</td>"
        f"<td>{_status_pill(status)}</td>"
        f"<td class=\"path\">{html.escape(str(job.get('worker_id') or ''))}</td>"
        f"<td class=\"path\">{html.escape(str(job.get('run_id') or ''))}</td>"
        f"<td>{timing}</td>"
        f"<td>{html.escape(str(job.get('error') or ''))}</td>"
        f"<td><div class=\"actions\">{''.join(actions)}</div></td>"
        "</tr>"
    )


def _queue_health_cards(health: dict[str, Any]) -> str:
    counts = health.get("counts", {}) if isinstance(health.get("counts"), dict) else {}
    items = [
        ("Queued", counts.get("QUEUED", 0)),
        ("Running", counts.get("RUNNING", 0)),
        ("Failed", counts.get("FAILED", 0)),
        ("Canceled", counts.get("CANCELED", 0)),
        ("Stale", health.get("stale_running_count", 0)),
    ]
    return "".join(
        '<div class="metric">'
        f"<strong>{html.escape(str(value))}</strong>"
        f"<span class=\"meta\">{html.escape(label)}</span>"
        "</div>"
        for label, value in items
    )


def _backup_row(backup: dict[str, Any]) -> str:
    name = str(backup.get("name") or "")
    return (
        "<tr>"
        f"<td class=\"path\">{html.escape(name)}</td>"
        f"<td>{int(backup.get('size_bytes') or 0)}</td>"
        f"<td>{html.escape(str(backup.get('updated_at') or ''))}</td>"
        f"<td><div class=\"actions\">"
        f"<button class=\"secondary\" type=\"button\" data-restore-dry-run=\"{html.escape(name)}\">Dry-Run Restore</button>"
        f"<button class=\"secondary\" type=\"button\" data-restore-confirm=\"{html.escape(name)}\">Restore</button>"
        f"</div></td>"
        "</tr>"
    )


def _status_pill(label: str) -> str:
    normalized = label.lower()
    css = normalized
    if normalized in {"done", "passed", "ok", "present", "set"}:
        css = "ok"
    elif normalized in {"failed", "missing", "error"}:
        css = "bad"
    elif normalized in {"running", "queued", "needs_human", "validating"}:
        css = "warn"
    return f'<span class="status {css}">{html.escape(label)}</span>'


def _progress_label(run: dict[str, Any]) -> str:
    if run.get("completed_steps") is None or run.get("total_steps") is None:
        return "n/a"
    percent = run.get("progress_percent")
    suffix = "" if percent is None else f" ({percent}%)"
    return f"{run.get('completed_steps')}/{run.get('total_steps')}{suffix}"


def _platforms_from_payload(payload: dict[str, Any], default_platforms: list[str]) -> list[str]:
    raw = payload.get("platforms")
    if raw is None:
        return default_platforms
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        raise ValueError("platforms must be a list or comma-separated string")
    allowed = set(DEFAULT_PLATFORMS)
    unknown = [item for item in values if item not in allowed]
    if unknown:
        raise ValueError(f"unknown platform(s): {', '.join(unknown)}")
    selected = values or default_platforms
    required_platforms = list(DEFAULT_PLATFORMS)
    missing = [item for item in required_platforms if item not in selected]
    extra = [item for item in selected if item not in required_platforms]
    if missing or extra:
        raise ValueError(
            "Phase 5 console run requires the full workflow platform set "
            f"to preserve the Phase 4 delivery contract; missing={missing}, extra={extra}"
        )
    return selected


def _attachments_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("attachments") or []
    if not isinstance(raw, list):
        raise ValueError("attachments must be a list")
    attachments = []
    for item in raw[:MAX_UPLOADS_PER_REQUEST]:
        if not isinstance(item, dict):
            continue
        attachments.append(
            {
                "id": str(item.get("id") or ""),
                "name": _safe_upload_name(str(item.get("name") or "attachment")),
                "mime_type": str(item.get("mime_type") or "application/octet-stream"),
                "kind": str(item.get("kind") or "file"),
                "size_bytes": int(item.get("size_bytes") or 0),
                "path": str(item.get("path") or ""),
            }
        )
    return attachments


def _safe_upload_name(name: str) -> str:
    base = Path(name).name.strip().replace("\x00", "")
    if not base or base in {".", ".."}:
        base = "attachment"
    cleaned = "".join(ch if (ch.isalnum() or ch in " ._()-[]{}#+，。") else "_" for ch in base)
    cleaned = cleaned.strip(" .") or "attachment"
    return cleaned[:160]


def _allowed_upload(name: str, mime_type: str) -> bool:
    suffix = Path(name).suffix.lower()
    normalized = mime_type.lower()
    return normalized.startswith(("text/", "image/", "video/")) or suffix in TEXT_EXTENSIONS


def _upload_kind(name: str, mime_type: str) -> str:
    normalized = mime_type.lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("text/") or Path(name).suffix.lower() in TEXT_EXTENSIONS:
        return "text"
    return "file"


def _safe_run_file(run_dir: Path, relative_path: str) -> Path | None:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    target = run_dir / Path(*path.parts)
    try:
        target.resolve().relative_to(run_dir.resolve())
    except ValueError:
        return None
    return target


def _content_file_card(run_dir: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(run_dir).as_posix()
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    return {
        "path": relative,
        "label": _content_file_label(relative),
        "kind": "json" if suffix == ".json" else "text",
        "size_bytes": path.stat().st_size,
        "content": text[:300000],
        "truncated": len(text) > 300000,
    }


def _content_file_label(relative_path: str) -> str:
    labels = {
        "wechat/article.md": "公众号正文",
        "wechat/title_options.json": "公众号标题备选",
        "xiaohongshu/note.json": "小红书笔记",
        "xiaohongshu/cover_prompt.md": "小红书封面提示词",
        "douyin/script.md": "抖音脚本",
        "douyin/subtitles.srt": "抖音字幕",
        "douyin/cover_prompt.md": "抖音封面提示词",
        "shipinhao/script.md": "视频号脚本",
        "shipinhao/subtitles.srt": "视频号字幕",
        "shipinhao/cover_prompt.md": "视频号封面提示词",
        "bilibili/script.md": "B站脚本",
        "bilibili/description.md": "B站简介",
        "bilibili/chapters.json": "B站章节",
    }
    return labels.get(relative_path, relative_path)


def _path_parts(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def _positive_int(value: str, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(1, min(parsed, maximum))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _script_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_json_from_zip(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        loaded = json.loads(archive.read(name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _backup_arcname(output_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(output_root)
    except ValueError:
        relative = path.name
    return str(Path("outputs/runs") / relative)


def _restore_target_path(output_root: Path, archive_name: str) -> Path | None:
    path = PurePosixPath(archive_name)
    if path.is_absolute() or ".." in path.parts:
        return None
    if len(path.parts) < 3 or path.parts[0] != "outputs" or path.parts[1] != "runs":
        return None
    relative = Path(*path.parts[2:])
    target = output_root / relative
    try:
        target.resolve().relative_to(output_root.resolve())
    except ValueError:
        return None
    return target


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
