from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


WORKFLOW_STATUS_VALUES = {
    "PENDING",
    "ASSIGNED",
    "RUNNING",
    "VALIDATING",
    "PASSED",
    "FAILED",
    "REPAIRING",
    "NEEDS_HUMAN",
    "DONE",
    "ARCHIVED",
}

TASK_STATUS_VALUES = {"PENDING", "RUNNING", "PASSED", "FAILED", "SKIPPED"}

FAILURE_CATEGORY_VALUES = {
    "ENV_ERROR",
    "DATA_ERROR",
    "SCHEMA_ERROR",
    "QUALITY_ERROR",
    "POLICY_ERROR",
    "PERMISSION_ERROR",
}


class WorkflowStateStore:
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
        CREATE TABLE IF NOT EXISTS workflow_run (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            workflow_path TEXT NOT NULL,
            workflow_json TEXT NOT NULL,
            topic TEXT NOT NULL,
            platforms_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            run_dir TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            current_step_id TEXT,
            failure_task_id TEXT,
            failure_category TEXT,
            failure_message TEXT
        );
        CREATE TABLE IF NOT EXISTS task_ledger (
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            execution_mode TEXT,
            log_path TEXT,
            artifact_paths_json TEXT NOT NULL,
            failure_category TEXT,
            failure_message TEXT,
            record_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, step_id, attempt)
        );
        CREATE INDEX IF NOT EXISTS idx_task_ledger_run_step ON task_ledger(run_id, step_id, attempt);
        CREATE INDEX IF NOT EXISTS idx_task_ledger_run_status ON task_ledger(run_id, status);
        """
        with self._connect() as conn:
            conn.executescript(schema)

    def save_workflow_run(
        self,
        snapshot: dict[str, Any],
        *,
        workflow_path: str,
        run_dir: str,
        current_step_id: str | None = None,
        failure_task_id: str | None = None,
        failure_category: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        run_id = str(snapshot["run_id"])
        workflow = snapshot.get("workflow", {})
        payload = {
            "run_id": run_id,
            "workflow_id": str(snapshot["workflow_id"]),
            "workflow_path": workflow_path,
            "workflow_json": _dumps(workflow),
            "topic": str(snapshot.get("topic", "")),
            "platforms_json": _dumps(snapshot.get("platforms", [])),
            "status": str(snapshot.get("status", "PENDING")),
            "created_at": str(snapshot.get("created_at", "")),
            "updated_at": str(snapshot.get("updated_at", "")),
            "run_dir": run_dir,
            "snapshot_json": _dumps(snapshot),
            "current_step_id": current_step_id,
            "failure_task_id": failure_task_id,
            "failure_category": failure_category,
            "failure_message": failure_message,
        }
        _validate_workflow_status(payload["status"])
        if failure_category is not None:
            _validate_failure_category(failure_category)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_run (
                    run_id, workflow_id, workflow_path, workflow_json, topic,
                    platforms_json, status, created_at, updated_at, run_dir,
                    snapshot_json, current_step_id, failure_task_id, failure_category, failure_message
                ) VALUES (
                    :run_id, :workflow_id, :workflow_path, :workflow_json, :topic,
                    :platforms_json, :status, :created_at, :updated_at, :run_dir,
                    :snapshot_json, :current_step_id, :failure_task_id, :failure_category, :failure_message
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    workflow_id=excluded.workflow_id,
                    workflow_path=excluded.workflow_path,
                    workflow_json=excluded.workflow_json,
                    topic=excluded.topic,
                    platforms_json=excluded.platforms_json,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    run_dir=excluded.run_dir,
                    snapshot_json=excluded.snapshot_json,
                    current_step_id=excluded.current_step_id,
                    failure_task_id=excluded.failure_task_id,
                    failure_category=excluded.failure_category,
                    failure_message=excluded.failure_message
                """,
                payload,
            )

    def save_task_attempt(self, record: dict[str, Any]) -> None:
        payload = {
            "run_id": str(record["run_id"]),
            "step_id": str(record["step_id"]),
            "attempt": int(record["attempt"]),
            "task_id": str(record["task_id"]),
            "agent": str(record["agent"]),
            "status": str(record["status"]),
            "started_at": str(record["started_at"]),
            "ended_at": record.get("ended_at"),
            "execution_mode": record.get("execution_mode"),
            "log_path": record.get("log_path"),
            "artifact_paths_json": _dumps(record.get("artifact_paths", [])),
            "failure_category": record.get("failure_category"),
            "failure_message": record.get("failure_message"),
            "record_json": _dumps(record.get("record", {})),
            "created_at": str(record.get("created_at", record["started_at"])),
            "updated_at": str(record.get("updated_at", record.get("ended_at") or record["started_at"])),
        }
        _validate_task_status(payload["status"])
        if payload["failure_category"] is not None:
            _validate_failure_category(payload["failure_category"])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_ledger (
                    run_id, step_id, attempt, task_id, agent, status, started_at,
                    ended_at, execution_mode, log_path, artifact_paths_json,
                    failure_category, failure_message, record_json, created_at, updated_at
                ) VALUES (
                    :run_id, :step_id, :attempt, :task_id, :agent, :status, :started_at,
                    :ended_at, :execution_mode, :log_path, :artifact_paths_json,
                    :failure_category, :failure_message, :record_json, :created_at, :updated_at
                )
                ON CONFLICT(run_id, step_id, attempt) DO UPDATE SET
                    task_id=excluded.task_id,
                    agent=excluded.agent,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    execution_mode=excluded.execution_mode,
                    log_path=excluded.log_path,
                    artifact_paths_json=excluded.artifact_paths_json,
                    failure_category=excluded.failure_category,
                    failure_message=excluded.failure_message,
                    record_json=excluded.record_json,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                payload,
            )

    def next_attempt(self, run_id: str, step_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM task_ledger WHERE run_id = ? AND step_id = ?",
                (run_id, step_id),
            ).fetchone()
        return int(row["max_attempt"]) + 1

    def load_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflow_run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return _row_to_workflow_run(row)

    def load_task_attempts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_ledger WHERE run_id = ? ORDER BY step_id, attempt",
                (run_id,),
            ).fetchall()
        return [_row_to_task_attempt(row) for row in rows]

    def load_latest_task_attempts(self, run_id: str) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.load_task_attempts(run_id):
            latest[row["step_id"]] = row
        return latest


def _row_to_workflow_run(row: sqlite3.Row) -> dict[str, Any]:
    snapshot = _loads(row["snapshot_json"])
    snapshot["workflow"] = _loads(row["workflow_json"])
    snapshot["platforms"] = _loads(row["platforms_json"])
    result = {
        "run_id": row["run_id"],
        "workflow_id": row["workflow_id"],
        "workflow_path": row["workflow_path"],
        "workflow": snapshot["workflow"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "topic": row["topic"],
        "platforms": snapshot["platforms"],
        "snapshot": snapshot,
        "run_dir": row["run_dir"],
        "current_step_id": row["current_step_id"],
        "failure_task_id": row["failure_task_id"],
        "failure_category": row["failure_category"],
        "failure_message": row["failure_message"],
    }
    for key in [
        "tasks",
        "task_runs",
        "artifacts",
        "failures",
        "retry_policy",
        "retry_events",
        "repair_log",
        "input_attachments",
        "note",
    ]:
        if key in snapshot:
            result[key] = snapshot[key]
    return result


def _row_to_task_attempt(row: sqlite3.Row) -> dict[str, Any]:
    record = _loads(row["record_json"])
    return {
        "run_id": row["run_id"],
        "step_id": row["step_id"],
        "attempt": row["attempt"],
        "task_id": row["task_id"],
        "agent": row["agent"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "execution_mode": row["execution_mode"],
        "log_path": row["log_path"],
        "artifact_paths": _loads(row["artifact_paths_json"]),
        "failure_category": row["failure_category"],
        "failure_message": row["failure_message"],
        "record": record,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_workflow_status(status: str) -> None:
    if status not in WORKFLOW_STATUS_VALUES:
        raise ValueError(f"Unsupported workflow status: {status}")


def _validate_task_status(status: str) -> None:
    if status not in TASK_STATUS_VALUES:
        raise ValueError(f"Unsupported task status: {status}")


def _validate_failure_category(category: str) -> None:
    if category not in FAILURE_CATEGORY_VALUES:
        raise ValueError(f"Unsupported failure category: {category}")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str) -> Any:
    return json.loads(value)
