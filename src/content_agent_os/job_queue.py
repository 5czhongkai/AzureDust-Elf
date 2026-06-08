from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .api_key_store import apply_stored_api_keys
from .runner import DEFAULT_PLATFORMS, DEFAULT_OUTPUT_ROOT, resume_workflow, run_workflow


JOB_STATUS_VALUES = {"QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED"}
JOB_KIND_VALUES = {"run", "resume"}
DEFAULT_STALE_RUNNING_SECONDS = 3600
DEFAULT_JOB_RETENTION_DAYS = 30
DEFAULT_AUDIT_RETENTION_DAYS = 90
CLEANUP_CONFIRMATION = "CLEANUP JOBS"
TERMINAL_JOB_STATUSES = {"DONE", "FAILED", "CANCELED"}


def job_db_path(output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    return output_root / "_state" / "console_jobs.sqlite"


class DurableJobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        schema = """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS console_job (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            workflow_path TEXT,
            topic TEXT,
            platforms_json TEXT NOT NULL,
            run_id TEXT,
            run_dir TEXT,
            worker_id TEXT,
            error TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_console_job_status_created ON console_job(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_console_job_updated ON console_job(updated_at);
        CREATE TABLE IF NOT EXISTS console_job_audit (
            audit_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            message TEXT,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_console_job_audit_job_created ON console_job_audit(job_id, created_at);
        """
        with self._connect() as conn:
            conn.executescript(schema)

    def create_run_job(
        self,
        *,
        workflow_path: Path,
        topic: str,
        platforms: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is required")
        return self._create_job(
            kind="run",
            workflow_path=workflow_path,
            topic=topic,
            platforms=platforms or DEFAULT_PLATFORMS,
            run_id=None,
            attachments=attachments or [],
        )

    def create_resume_job(self, *, run_id: str) -> dict[str, Any]:
        run_id = run_id.strip()
        if not run_id:
            raise ValueError("run_id is required")
        return self._create_job(
            kind="resume",
            workflow_path=None,
            topic=None,
            platforms=[],
            run_id=run_id,
            attachments=[],
        )

    def list_jobs(self, limit: int = 50, *, status: str | None = None) -> list[dict[str, Any]]:
        where = ""
        values: tuple[Any, ...]
        if status:
            _validate_status(status)
            where = "WHERE status = ?"
            values = (status,)
        else:
            values = ()
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM console_job {where} ORDER BY created_at DESC LIMIT ?",
                values + (limit,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def queue_health(self, *, stale_running_seconds: int = DEFAULT_STALE_RUNNING_SECONDS) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        counts = {status: 0 for status in sorted(JOB_STATUS_VALUES)}
        with self._connect() as conn:
            for row in conn.execute("SELECT status, COUNT(*) AS count FROM console_job GROUP BY status").fetchall():
                counts[str(row["status"])] = int(row["count"])
            oldest_queued = conn.execute(
                "SELECT created_at FROM console_job WHERE status = 'QUEUED' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            running_rows = conn.execute(
                "SELECT job_id, started_at, updated_at FROM console_job WHERE status = 'RUNNING'"
            ).fetchall()
        oldest_queued_age_seconds = None
        if oldest_queued is not None:
            oldest_queued_age_seconds = _age_seconds(str(oldest_queued["created_at"]), now)
        stale_running_jobs = []
        for row in running_rows:
            timestamp = str(row["started_at"] or row["updated_at"] or "")
            age = _age_seconds(timestamp, now)
            if age is not None and age >= stale_running_seconds:
                stale_running_jobs.append({"job_id": row["job_id"], "age_seconds": age})
        status = "bad" if counts.get("FAILED", 0) or stale_running_jobs else "warn" if counts.get("QUEUED", 0) else "ok"
        return {
            "schema_version": "phase5.queue_health.v1",
            "generated_at": _utc_now_iso(),
            "job_db_path": str(self.db_path),
            "status": status,
            "counts": counts,
            "oldest_queued_age_seconds": oldest_queued_age_seconds,
            "stale_running_seconds": stale_running_seconds,
            "stale_running_count": len(stale_running_jobs),
            "stale_running_jobs": stale_running_jobs[:20],
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM console_job WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row is not None else None

    def audit_log(self, *, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where = ""
        values: tuple[Any, ...]
        if job_id:
            where = "WHERE job_id = ?"
            values = (job_id,)
        else:
            values = ()
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM console_job_audit {where} ORDER BY created_at DESC LIMIT ?",
                values + (limit,),
            ).fetchall()
        return [_row_to_audit(row) for row in rows]

    def cleanup_dry_run(
        self,
        *,
        job_retention_days: int = DEFAULT_JOB_RETENTION_DAYS,
        audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS,
    ) -> dict[str, Any]:
        return self._cleanup_plan(
            job_retention_days=job_retention_days,
            audit_retention_days=audit_retention_days,
        )

    def cleanup(
        self,
        *,
        confirmation: str,
        actor: str = "operator",
        job_retention_days: int = DEFAULT_JOB_RETENTION_DAYS,
        audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS,
    ) -> dict[str, Any]:
        if confirmation.strip() != CLEANUP_CONFIRMATION:
            raise ValueError(f"cleanup confirmation must be exactly: {CLEANUP_CONFIRMATION}")
        plan = self._cleanup_plan(
            job_retention_days=job_retention_days,
            audit_retention_days=audit_retention_days,
        )
        now = _utc_now_iso()
        job_cutoff = str(plan["job_cutoff"])
        audit_cutoff = str(plan["audit_cutoff"])
        with self._connect() as conn:
            deleted_jobs = conn.execute(
                """
                DELETE FROM console_job
                WHERE status IN ('DONE', 'FAILED', 'CANCELED')
                  AND updated_at < ?
                """,
                (job_cutoff,),
            ).rowcount
            deleted_audit = conn.execute(
                """
                DELETE FROM console_job_audit
                WHERE created_at < ?
                """,
                (audit_cutoff,),
            ).rowcount
            conn.execute(
                """
                INSERT INTO console_job_audit (
                    audit_id, job_id, action, actor, message, before_json, after_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"audit_{_utc_now_compact()}_{uuid.uuid4().hex[:8]}",
                    "_queue",
                    "cleanup",
                    actor,
                    f"deleted_jobs={deleted_jobs}, deleted_audit={deleted_audit}",
                    _dumps(plan),
                    None,
                    now,
                ),
            )
        result = dict(plan)
        result.update(
            {
                "dry_run": False,
                "will_delete": True,
                "deleted_job_count": int(deleted_jobs),
                "deleted_audit_count": int(deleted_audit),
                "confirmation": CLEANUP_CONFIRMATION,
            }
        )
        return result

    def claim_job(self, job_id: str, *, worker_id: str) -> dict[str, Any] | None:
        return self._claim(where_sql="job_id = ?", where_values=(job_id,), worker_id=worker_id)

    def claim_next(self, *, worker_id: str) -> dict[str, Any] | None:
        return self._claim(where_sql="status = 'QUEUED'", where_values=(), worker_id=worker_id)

    def cancel_job(self, job_id: str, *, actor: str = "operator", message: str = "") -> dict[str, Any]:
        before = self.get_job(job_id)
        if before is None:
            raise KeyError(job_id)
        if before["status"] != "QUEUED":
            raise ValueError("only QUEUED jobs can be canceled")
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE console_job
                SET status = 'CANCELED',
                    error = ?,
                    updated_at = ?,
                    ended_at = ?
                WHERE job_id = ? AND status = 'QUEUED'
                """,
                (message or "canceled by operator", now, now, job_id),
            )
        after = self.get_job(job_id)
        if after is None:
            raise KeyError(job_id)
        self._write_audit(job_id, action="cancel", actor=actor, message=message, before=before, after=after)
        return after

    def mark_running_failed(self, job_id: str, *, actor: str = "operator", message: str = "") -> dict[str, Any]:
        before = self.get_job(job_id)
        if before is None:
            raise KeyError(job_id)
        if before["status"] != "RUNNING":
            raise ValueError("only RUNNING jobs can be marked failed")
        after = self.mark_failed(job_id, error=message or "marked failed by operator", actor=actor, action="mark_failed")
        return after

    def retry_job(self, job_id: str, *, actor: str = "operator", message: str = "") -> dict[str, Any]:
        before = self.get_job(job_id)
        if before is None:
            raise KeyError(job_id)
        if before["status"] not in {"FAILED", "CANCELED"}:
            raise ValueError("only FAILED or CANCELED jobs can be retried")
        if before["kind"] == "run":
            retry = self.create_run_job(
                workflow_path=Path(str(before.get("workflow_path") or "")),
                topic=str(before.get("topic") or ""),
                platforms=list(before.get("platforms") or DEFAULT_PLATFORMS),
                attachments=list(before.get("attachments") or []),
            )
        elif before["kind"] == "resume":
            retry = self.create_resume_job(run_id=str(before.get("run_id") or ""))
        else:
            raise ValueError(f"unknown job kind: {before.get('kind')}")
        self._write_audit(
            job_id,
            action="retry",
            actor=actor,
            message=message or f"created retry job {retry['job_id']}",
            before=before,
            after=retry,
        )
        self._write_audit(
            str(retry["job_id"]),
            action="created_from_retry",
            actor=actor,
            message=f"retry of {job_id}",
            before=None,
            after=retry,
        )
        return retry

    def mark_done(self, job_id: str, *, run_dir: Path | None = None) -> dict[str, Any]:
        before = self.get_job(job_id)
        now = _utc_now_iso()
        run_id = run_dir.name if run_dir is not None else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE console_job
                SET status = 'DONE',
                    run_id = COALESCE(?, run_id),
                    run_dir = COALESCE(?, run_dir),
                    error = NULL,
                    updated_at = ?,
                    ended_at = ?
                WHERE job_id = ?
                """,
                (run_id, str(run_dir) if run_dir is not None else None, now, now, job_id),
            )
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        self._write_audit(job_id, action="done", actor=str(job.get("worker_id") or "worker"), message="", before=before, after=job)
        return job

    def mark_failed(self, job_id: str, *, error: str, actor: str | None = None, action: str = "failed") -> dict[str, Any]:
        before = self.get_job(job_id)
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE console_job
                SET status = 'FAILED',
                    error = ?,
                    updated_at = ?,
                    ended_at = ?
                WHERE job_id = ?
                """,
                (error, now, now, job_id),
            )
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        self._write_audit(job_id, action=action, actor=actor or str(job.get("worker_id") or "worker"), message=error, before=before, after=job)
        return job

    def _create_job(
        self,
        *,
        kind: str,
        workflow_path: Path | None,
        topic: str | None,
        platforms: list[str],
        run_id: str | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        _validate_kind(kind)
        now = _utc_now_iso()
        job_id = f"job_{_utc_now_compact()}_{uuid.uuid4().hex[:8]}"
        attachment_list = attachments or []
        payload = {
            "job_id": job_id,
            "kind": kind,
            "status": "QUEUED",
            "workflow_path": str(workflow_path) if workflow_path is not None else None,
            "topic": topic,
            "platforms": platforms,
            "attachments": attachment_list,
            "run_id": run_id,
            "run_dir": None,
            "worker_id": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "ended_at": None,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO console_job (
                    job_id, kind, status, workflow_path, topic, platforms_json,
                    run_id, run_dir, worker_id, error, payload_json,
                    created_at, updated_at, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    "QUEUED",
                    payload["workflow_path"],
                    topic,
                    _dumps(platforms),
                    run_id,
                    None,
                    None,
                    None,
                    _dumps(payload),
                    now,
                    now,
                    None,
                    None,
                ),
            )
        self._write_audit(job_id, action="enqueue", actor="system", message="", before=None, after=payload)
        return payload

    def _claim(self, *, where_sql: str, where_values: tuple[Any, ...], worker_id: str) -> dict[str, Any] | None:
        now = _utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT * FROM console_job WHERE {where_sql} AND status = 'QUEUED' ORDER BY created_at ASC LIMIT 1",
                where_values,
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE console_job
                SET status = 'RUNNING',
                    worker_id = ?,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?)
                WHERE job_id = ? AND status = 'QUEUED'
                """,
                (worker_id, now, now, row["job_id"]),
            )
            conn.commit()
            job = self.get_job(str(row["job_id"]))
            if job is not None:
                self._write_audit(str(job["job_id"]), action="claim", actor=worker_id, message="", before=_row_to_job(row), after=job)
            return job
        finally:
            conn.close()

    def _write_audit(
        self,
        job_id: str,
        *,
        action: str,
        actor: str,
        message: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO console_job_audit (
                    audit_id, job_id, action, actor, message, before_json, after_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"audit_{_utc_now_compact()}_{uuid.uuid4().hex[:8]}",
                    job_id,
                    action,
                    actor,
                    message,
                    _dumps(before) if before is not None else None,
                    _dumps(after) if after is not None else None,
                    now,
                ),
            )

    def _cleanup_plan(self, *, job_retention_days: int, audit_retention_days: int) -> dict[str, Any]:
        if job_retention_days < 0 or audit_retention_days < 0:
            raise ValueError("retention days must be >= 0")
        now = datetime.now(timezone.utc)
        job_cutoff = (now - timedelta(days=job_retention_days)).isoformat()
        audit_cutoff = (now - timedelta(days=audit_retention_days)).isoformat()
        with self._connect() as conn:
            job_rows = conn.execute(
                """
                SELECT job_id, status, updated_at
                FROM console_job
                WHERE status IN ('DONE', 'FAILED', 'CANCELED')
                  AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (job_cutoff,),
            ).fetchall()
            protected_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM console_job WHERE status IN ('QUEUED', 'RUNNING') GROUP BY status"
            ).fetchall()
            audit_rows = conn.execute(
                """
                SELECT audit_id, job_id, action, created_at
                FROM console_job_audit
                WHERE created_at < ?
                ORDER BY created_at ASC
                """,
                (audit_cutoff,),
            ).fetchall()
        protected_counts = {"QUEUED": 0, "RUNNING": 0}
        for row in protected_rows:
            protected_counts[str(row["status"])] = int(row["count"])
        return {
            "schema_version": "phase5.queue_cleanup_plan.v1",
            "generated_at": _utc_now_iso(),
            "dry_run": True,
            "will_delete": False,
            "job_retention_days": job_retention_days,
            "audit_retention_days": audit_retention_days,
            "job_cutoff": job_cutoff,
            "audit_cutoff": audit_cutoff,
            "eligible_statuses": sorted(TERMINAL_JOB_STATUSES),
            "protected_statuses": ["QUEUED", "RUNNING"],
            "protected_counts": protected_counts,
            "delete_job_count": len(job_rows),
            "delete_audit_count": len(audit_rows),
            "jobs": [
                {"job_id": row["job_id"], "status": row["status"], "updated_at": row["updated_at"]}
                for row in job_rows[:100]
            ],
            "audit": [
                {
                    "audit_id": row["audit_id"],
                    "job_id": row["job_id"],
                    "action": row["action"],
                    "created_at": row["created_at"],
                }
                for row in audit_rows[:100]
            ],
            "entry_limit": 100,
            "confirmation": CLEANUP_CONFIRMATION,
        }


def execute_claimed_job(store: DurableJobStore, job: dict[str, Any], *, output_root: Path) -> dict[str, Any]:
    try:
        apply_stored_api_keys(output_root)
        if job["kind"] == "run":
            workflow_path = Path(str(job.get("workflow_path") or ""))
            topic = str(job.get("topic") or "")
            platforms = list(job.get("platforms") or DEFAULT_PLATFORMS)
            run_dir = run_workflow(
                workflow_path=workflow_path,
                topic=topic,
                platforms=platforms,
                output_root=output_root,
                input_attachments=list(job.get("attachments") or []),
            )
            attachments = list(job.get("attachments") or [])
            if attachments:
                manifest_path = run_dir / "input_attachments_manifest.json"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "phase5.input_attachments.v1",
                            "job_id": job.get("job_id"),
                            "run_id": run_dir.name,
                            "attachments": attachments,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
        elif job["kind"] == "resume":
            run_id = str(job.get("run_id") or "")
            run_dir = resume_workflow(run_id=run_id, output_root=output_root)
        else:
            raise ValueError(f"unknown job kind: {job.get('kind')}")
        return store.mark_done(str(job["job_id"]), run_dir=run_dir)
    except Exception as exc:
        return store.mark_failed(str(job["job_id"]), error=str(exc))


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    platforms = _loads(row["platforms_json"])
    payload = _loads(row["payload_json"])
    attachments = payload.get("attachments", []) if isinstance(payload, dict) else []
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "status": row["status"],
        "workflow_path": row["workflow_path"],
        "topic": row["topic"],
        "platforms": platforms if isinstance(platforms, list) else [],
        "attachments": attachments if isinstance(attachments, list) else [],
        "run_id": row["run_id"],
        "run_dir": row["run_dir"],
        "worker_id": row["worker_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
    }


def _row_to_audit(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "audit_id": row["audit_id"],
        "job_id": row["job_id"],
        "action": row["action"],
        "actor": row["actor"],
        "message": row["message"],
        "before": _loads(row["before_json"]) if row["before_json"] else None,
        "after": _loads(row["after_json"]) if row["after_json"] else None,
        "created_at": row["created_at"],
    }


def _validate_kind(kind: str) -> None:
    if kind not in JOB_KIND_VALUES:
        raise ValueError(f"invalid job kind: {kind}")


def _validate_status(status: str) -> None:
    if status not in JOB_STATUS_VALUES:
        raise ValueError(f"invalid job status: {status}")


def _age_seconds(timestamp: str, now: datetime) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds()))


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str) -> Any:
    return json.loads(value) if value else None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
