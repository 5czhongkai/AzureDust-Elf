from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .retry_policy import summarize_retry_policy
from .stale_detector import summarize_task_health
from .state_store import WorkflowStateStore


MONITOR_DIR = Path("monitor")
SUPERVISION_SNAPSHOT = MONITOR_DIR / "supervision_snapshot.json"
SUPERVISION_REPORT = MONITOR_DIR / "supervision_report.md"
FAILURE_DASHBOARD = MONITOR_DIR / "failure_dashboard.html"


def generate_supervision_outputs(
    *,
    run_id: str | None,
    output_root: Path,
) -> tuple[Path, dict[str, Path], dict[str, Any]]:
    run_dir = resolve_run_dir(run_id, output_root)
    workflow_run = _load_json(run_dir / "workflow_run.json")
    attempts = _load_task_attempts(run_dir, workflow_run)
    paths = write_supervision_outputs(run_dir, workflow_run, attempts)
    snapshot = _load_json(paths["snapshot"])
    return run_dir, paths, snapshot


def write_supervision_outputs(
    run_dir: Path,
    workflow_run: dict[str, Any],
    task_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    attempts = task_attempts if task_attempts is not None else _load_task_attempts(run_dir, workflow_run)
    snapshot = build_supervision_snapshot(run_dir, workflow_run, attempts)
    monitor_dir = run_dir / MONITOR_DIR
    monitor_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = run_dir / SUPERVISION_SNAPSHOT
    report_path = run_dir / SUPERVISION_REPORT
    dashboard_path = run_dir / FAILURE_DASHBOARD
    _write_json(snapshot_path, snapshot)
    report_path.write_text(render_supervision_report(snapshot), encoding="utf-8")
    dashboard_path.write_text(render_failure_dashboard(snapshot), encoding="utf-8")
    return {
        "snapshot": snapshot_path,
        "report": report_path,
        "dashboard": dashboard_path,
    }


def resolve_run_dir(run_id: str | None, output_root: Path) -> Path:
    if run_id:
        candidate = Path(run_id)
        if candidate.exists():
            return candidate
        candidate = output_root / run_id
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Workflow run directory not found: {run_id}")

    runs = sorted(output_root.glob("run_*"))
    if not runs:
        raise FileNotFoundError(f"No workflow run directories found under {output_root}")
    return runs[-1]


def build_supervision_snapshot(
    run_dir: Path,
    workflow_run: dict[str, Any],
    task_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    steps = list(workflow_run.get("workflow", {}).get("steps", []))
    task_runs_by_step = {
        str(task_run.get("step_id")): task_run
        for task_run in workflow_run.get("task_runs", [])
        if task_run.get("step_id")
    }
    attempts_by_step: dict[str, list[dict[str, Any]]] = {}
    for attempt in task_attempts:
        attempts_by_step.setdefault(str(attempt.get("step_id")), []).append(attempt)

    task_views = [
        _task_view(index, step, task_runs_by_step.get(str(step.get("id"))), attempts_by_step.get(str(step.get("id")), []), run_dir)
        for index, step in enumerate(steps, start=1)
    ]
    health_analysis = summarize_task_health(workflow_run, task_views, mode="monitor")
    task_views = health_analysis["tasks"]
    retry_analysis = summarize_retry_policy(workflow_run, task_views)
    repair_analysis = _repair_log_view(workflow_run)
    task_statuses = [task["status"] for task in task_views]
    failures = _failure_views(workflow_run, task_views)
    current_step = _current_step(task_views, workflow_run)
    summary = _summary(workflow_run, task_statuses, failures, health_analysis, retry_analysis, repair_analysis)
    artifact_health = _artifact_health(task_views)
    generated_at = _utc_now_iso()
    snapshot = {
        "schema_version": "phase3.supervision.v1",
        "generated_at": generated_at,
        "run": {
            "run_id": workflow_run.get("run_id"),
            "workflow_id": workflow_run.get("workflow_id"),
            "topic": workflow_run.get("topic"),
            "platforms": workflow_run.get("platforms", []),
            "status": workflow_run.get("status"),
            "created_at": workflow_run.get("created_at"),
            "updated_at": workflow_run.get("updated_at"),
            "run_dir": str(run_dir),
        },
        "summary": summary,
        "current_step": current_step,
        "stale_detector": _stale_detector_view(health_analysis),
        "retry_policy": retry_analysis,
        "repair_log": repair_analysis,
        "tasks": task_views,
        "failures": failures,
        "artifact_health": artifact_health,
        "workflow_graph": _workflow_graph(task_views),
        "next_actions": _next_actions(workflow_run, task_views, failures),
        "monitor_files": {
            "snapshot": str(SUPERVISION_SNAPSHOT),
            "report": str(SUPERVISION_REPORT),
            "dashboard": str(FAILURE_DASHBOARD),
        },
    }
    return snapshot


def render_supervision_report(snapshot: dict[str, Any]) -> str:
    run = snapshot["run"]
    summary = snapshot["summary"]
    current_step = snapshot.get("current_step")
    failures = snapshot.get("failures", [])
    graph = snapshot.get("workflow_graph", {})
    detector = snapshot.get("stale_detector", {})
    detector_summary = detector.get("summary", {})
    retry_policy = snapshot.get("retry_policy", {})
    retry_summary = retry_policy.get("summary", {})
    repair_log = snapshot.get("repair_log", {})
    repair_summary = repair_log.get("summary", {})
    lines = [
        "# Run Supervision Report",
        "",
        "## Overview",
        "",
        f"- Run ID: {run.get('run_id')}",
        f"- Workflow: {run.get('workflow_id')}",
        f"- Topic: {run.get('topic')}",
        f"- Platforms: {', '.join(run.get('platforms', []))}",
        f"- Status: {run.get('status')}",
        f"- Progress: {summary.get('completed_steps')}/{summary.get('total_steps')} steps ({summary.get('progress_percent')}%)",
        f"- Generated at: {snapshot.get('generated_at')}",
        "",
        "## Current Focus",
        "",
    ]
    if current_step:
        lines.extend(
            [
                f"- Step: {current_step.get('step_id')}",
                f"- Agent: {current_step.get('agent')}",
                f"- Status: {current_step.get('status')}",
                f"- Health: {current_step.get('health_state') or 'n/a'}",
                f"- Recoverable: {'yes' if current_step.get('recoverable') else 'no'}",
            ]
        )
        if current_step.get("reason"):
            lines.append(f"- Reason: {current_step.get('reason')}")
        if current_step.get("log_path"):
            lines.append(f"- Log: {current_step.get('log_path')}")
    else:
        lines.append("- No active or failed step is currently selected.")

    lines.extend(["", "## Status Counts", ""])
    for key in ["passed", "failed", "skipped", "pending", "running"]:
        lines.append(f"- {key.upper()}: {summary.get(key, 0)}")

    lines.extend(
        [
            "",
            "## Stale Detector",
            "",
            f"- Enabled: {detector.get('config', {}).get('enabled', True)}",
            f"- Threshold: {detector_summary.get('threshold_minutes')} minutes",
            f"- Running watch: {detector_summary.get('watch_count', 0)}",
            f"- Stale tasks: {detector_summary.get('stale_count', 0)}",
            f"- Interrupted tasks: {detector_summary.get('interrupted_count', 0)}",
            f"- Recoverable faults: {detector_summary.get('recoverable_count', 0)}",
            "",
        ]
    )
    stale_tasks = detector.get("stale_tasks", [])
    if stale_tasks:
        lines.extend(["| Step | State | Age | Reason | Log |", "|---|---|---:|---|---|"])
        for task in stale_tasks:
            age = task.get("age_minutes")
            age_label = "n/a" if age is None else f"{float(age):.1f} min"
            reason = str(task.get("reason", "")).replace("|", "\\|")
            lines.append(
                f"| {task.get('step_id')} | {task.get('health_state')} | {age_label} | {reason} | {task.get('log_path') or 'n/a'} |"
            )
    else:
        lines.append("- No stale or interrupted tasks detected.")

    lines.extend(
        [
            "",
            "## Retry Policy",
            "",
            f"- Enabled: {retry_summary.get('enabled', True)}",
            f"- Max auto retries per step: {retry_summary.get('max_auto_retries', 0)}",
            f"- Retryable active failures: {retry_summary.get('retryable_failure_count', 0)}",
            f"- Auto retries scheduled: {retry_summary.get('auto_retry_count', 0)}",
            f"- Retry events: {retry_summary.get('event_count', 0)}",
            "",
        ]
    )
    retry_events = retry_policy.get("events", [])
    if retry_events:
        lines.extend(["| Stage | Step | Attempt | Decision | Reason |", "|---|---|---:|---|---|"])
        for event in retry_events:
            reason = str(event.get("reason", "")).replace("|", "\\|")
            lines.append(
                f"| {event.get('stage')} | {event.get('step_id')} | {event.get('attempt') or 'n/a'} | {event.get('decision')} | {reason} |"
            )
    else:
        lines.append("- No retry events recorded.")

    lines.extend(
        [
            "",
            "## Repair Log",
            "",
            f"- Repair plans: {repair_summary.get('repair_count', 0)}",
            f"- Manual required: {repair_summary.get('manual_required_count', 0)}",
            f"- Pending approval: {repair_summary.get('pending_approval_count', 0)}",
            f"- Approved: {repair_summary.get('approved_repair_count', 0)}",
            f"- Failed repair plans: {repair_summary.get('failed_repair_count', 0)}",
            "",
        ]
    )
    repair_entries = repair_log.get("entries", [])
    if repair_entries:
        lines.extend(["| Repair ID | Step | Category | Status | Manual | Approval | Plan |", "|---|---|---|---|---|---|---|"])
        for entry in repair_entries:
            lines.append(
                f"| {entry.get('repair_id')} | {entry.get('failed_step_id')} | {entry.get('failure_category')} | {entry.get('status')} | {'yes' if entry.get('manual_required') else 'no'} | {entry.get('approval_status') or 'n/a'} | {entry.get('plan_path') or 'n/a'} |"
            )
    else:
        lines.append("- No repair plans recorded.")

    lines.extend(
        [
            "",
            "## Failure Map",
            "",
            "```mermaid",
            *graph.get("mermaid", "").splitlines(),
            "```",
            "",
            "## Task Timeline",
            "",
            "| # | Step | Agent | Platform | Status | Health | Recoverable | Attempts | Duration | Artifacts | Failure |",
            "|---:|---|---|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for task in snapshot["tasks"]:
        failure_label = ""
        if task.get("failure"):
            failure = task["failure"]
            failure_label = f"{failure.get('category')}: {failure.get('message')}"
        health = task.get("health", {})
        lines.append(
            "| {order} | {step} | {agent} | {platform} | {status} | {health} | {recoverable} | {attempts} | {duration} | {artifacts} | {failure} |".format(
                order=task["order"],
                step=task["step_id"],
                agent=task["agent"],
                platform=task.get("platform") or "shared",
                status=task["status"],
                health=health.get("state", "unknown"),
                recoverable="yes" if health.get("recoverable") else "no",
                attempts=task["attempt_count"],
                duration=_format_duration(task.get("duration_ms")),
                artifacts=task.get("artifact_health", {}).get("status"),
                failure=failure_label.replace("|", "\\|"),
            )
        )

    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            lines.extend(
                [
                    f"### {failure.get('step_id') or failure.get('task_id')}",
                    "",
                    f"- Category: {failure.get('category')}",
                    f"- Task ID: {failure.get('task_id')}",
                    f"- Recoverable: {'yes' if failure.get('recoverable') else 'no'}",
                    f"- Recovery state: {failure.get('recovery_state') or 'n/a'}",
                    f"- Message: {failure.get('message')}",
                    f"- Log: {failure.get('log_path') or 'n/a'}",
                    f"- Repair plan: {_repair_plan_for_failure(repair_entries, failure) or 'n/a'}",
                    "",
                ]
            )
    else:
        lines.append("- No active failures.")

    lines.extend(["", "## Next Actions", ""])
    for action in snapshot.get("next_actions", []):
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def render_failure_dashboard(snapshot: dict[str, Any]) -> str:
    run = snapshot["run"]
    summary = snapshot["summary"]
    tasks = snapshot["tasks"]
    failures = snapshot["failures"]
    detector = snapshot.get("stale_detector", {})
    detector_summary = detector.get("summary", {})
    retry_policy = snapshot.get("retry_policy", {})
    retry_summary = retry_policy.get("summary", {})
    repair_log = snapshot.get("repair_log", {})
    repair_summary = repair_log.get("summary", {})
    cards = "\n".join(
        f"""
        <section class="task-card {html.escape(_dashboard_card_class(task))}">
          <div class="task-topline">
            <span class="step-id">{html.escape(task['step_id'])}</span>
            <span class="status-pill">{html.escape(task['status'])}</span>
          </div>
          <div class="agent">{html.escape(task['agent'])}</div>
          <div class="health-pill{ ' recoverable' if task.get('health', {}).get('recoverable') else '' }">
            health: {html.escape(str(task.get('health', {}).get('state', 'unknown')))}
          </div>
          <div class="meta">platform: {html.escape(task.get('platform') or 'shared')} · attempts: {task['attempt_count']} · duration: {html.escape(_format_duration(task.get('duration_ms')))}</div>
          <div class="meta">artifacts: {html.escape(task.get('artifact_health', {}).get('status', 'unknown'))}</div>
          <div class="meta">recoverable: {html.escape('yes' if task.get('health', {}).get('recoverable') else 'no')} · reason: {html.escape(str(task.get('health', {}).get('reason', 'n/a')))}</div>
          { _failure_block(task.get('failure')) }
        </section>
        """
        for task in tasks
    )
    failure_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(failure.get('step_id') or 'workflow'))}</td>
          <td>{html.escape(str(failure.get('category') or 'UNKNOWN'))}</td>
          <td>{html.escape('yes' if failure.get('recoverable') else 'no')}</td>
          <td>{html.escape(str(failure.get('message') or ''))}</td>
          <td>{html.escape(str(failure.get('log_path') or 'n/a'))}</td>
        </tr>
        """
        for failure in failures
    )
    if not failure_rows:
        failure_rows = '<tr><td colspan="5">No active failures.</td></tr>'

    next_actions = "\n".join(f"<li>{html.escape(action)}</li>" for action in snapshot.get("next_actions", []))
    retry_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(event.get('stage') or 'n/a'))}</td>
          <td>{html.escape(str(event.get('step_id') or 'n/a'))}</td>
          <td>{html.escape(str(event.get('attempt') or 'n/a'))}</td>
          <td>{html.escape(str(event.get('decision') or 'n/a'))}</td>
          <td>{html.escape(str(event.get('reason') or ''))}</td>
        </tr>
        """
        for event in retry_policy.get("events", [])
    )
    if not retry_rows:
        retry_rows = '<tr><td colspan="5">No retry events recorded.</td></tr>'
    repair_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(entry.get('repair_id') or 'n/a'))}</td>
          <td>{html.escape(str(entry.get('failed_step_id') or 'n/a'))}</td>
          <td>{html.escape(str(entry.get('failure_category') or 'n/a'))}</td>
          <td>{html.escape(str(entry.get('status') or 'n/a'))}</td>
          <td>{html.escape('yes' if entry.get('manual_required') else 'no')}</td>
          <td>{html.escape(str(entry.get('approval_status') or 'n/a'))}</td>
          <td>{html.escape(str(entry.get('plan_path') or 'n/a'))}</td>
        </tr>
        """
        for entry in repair_log.get("entries", [])
    )
    if not repair_rows:
        repair_rows = '<tr><td colspan="7">No repair plans recorded.</td></tr>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Run Failure Dashboard - {html.escape(str(run.get('run_id')))}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #18202a;
      --muted: #657183;
      --line: #dfe4eb;
      --ok: #19794f;
      --warn: #9b6800;
      --bad: #b42318;
      --idle: #596579;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 20px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    main {{ padding: 24px 32px 40px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; letter-spacing: 0; }}
    .subtle {{ color: var(--muted); margin: 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric strong {{ display: block; font-size: 24px; margin-bottom: 2px; }}
    .progress-shell {{
      width: 100%;
      height: 12px;
      background: #e8edf3;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 16px;
      border: 1px solid var(--line);
    }}
    .progress-bar {{
      height: 100%;
      width: {summary.get('progress_percent', 0)}%;
      background: #2d6cdf;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }}
    .task-card {{
      border: 1px solid var(--line);
      border-left-width: 5px;
      border-radius: 8px;
      background: var(--panel);
      padding: 14px;
      min-height: 132px;
    }}
    .task-card.passed {{ border-left-color: var(--ok); }}
    .task-card.failed {{ border-left-color: var(--bad); }}
    .task-card.skipped {{ border-left-color: var(--idle); }}
    .task-card.pending, .task-card.running {{ border-left-color: var(--warn); }}
    .task-card.watch {{ border-left-color: #cf8a00; }}
    .task-card.stale, .task-card.interrupted {{ border-left-color: var(--bad); }}
    .task-topline {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .step-id {{ font-weight: 700; overflow-wrap: anywhere; }}
    .status-pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      background: #f8fafc;
      white-space: nowrap;
    }}
    .health-pill {{
      display: inline-block;
      margin-top: 6px;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      background: #eef2f7;
      color: var(--ink);
      white-space: nowrap;
    }}
    .health-pill.recoverable {{
      background: #fff1f0;
      color: var(--bad);
      border: 1px solid #ffd2cc;
    }}
    .agent {{ color: var(--ink); font-weight: 600; margin-bottom: 6px; }}
    .meta {{ color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
    .failure {{
      margin-top: 10px;
      padding: 10px;
      border-radius: 6px;
      background: #fff1f0;
      color: var(--bad);
      border: 1px solid #ffd2cc;
      overflow-wrap: anywhere;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #eef2f7; }}
    tr:last-child td {{ border-bottom: 0; }}
    .actions {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 18px;
    }}
    code {{ background: #eef2f7; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>运行监督与故障看板</h1>
    <p class="subtle">{html.escape(str(run.get('run_id')))} · {html.escape(str(run.get('workflow_id')))} · status: {html.escape(str(run.get('status')))}</p>
    <p class="subtle">topic: {html.escape(str(run.get('topic')))} · generated: {html.escape(str(snapshot.get('generated_at')))}</p>
    <p class="subtle">stale threshold: {html.escape(str(detector_summary.get('threshold_minutes', 'n/a')))} min · recoverable faults: {html.escape(str(detector_summary.get('recoverable_count', 0)))}</p>
    <p class="subtle">retry policy: max auto retries {html.escape(str(retry_summary.get('max_auto_retries', 'n/a')))} · auto retries scheduled: {html.escape(str(retry_summary.get('auto_retry_count', 0)))}</p>
    <p class="subtle">repair plans: {html.escape(str(repair_summary.get('repair_count', 0)))} · manual required: {html.escape(str(repair_summary.get('manual_required_count', 0)))} · pending approval: {html.escape(str(repair_summary.get('pending_approval_count', 0)))}</p>
    <div class="progress-shell" aria-label="workflow progress"><div class="progress-bar"></div></div>
    <section class="metrics">
      <div class="metric"><strong>{summary.get('total_steps')}</strong><span>total steps</span></div>
      <div class="metric"><strong>{summary.get('passed')}</strong><span>passed</span></div>
      <div class="metric"><strong>{summary.get('failed')}</strong><span>failed</span></div>
      <div class="metric"><strong>{summary.get('stale_count', 0)}</strong><span>stale</span></div>
      <div class="metric"><strong>{summary.get('watch_count', 0)}</strong><span>watch</span></div>
      <div class="metric"><strong>{summary.get('auto_retry_count', 0)}</strong><span>auto retries</span></div>
      <div class="metric"><strong>{summary.get('repair_count', 0)}</strong><span>repairs</span></div>
      <div class="metric"><strong>{summary.get('pending_approval_count', 0)}</strong><span>pending approval</span></div>
      <div class="metric"><strong>{summary.get('progress_percent')}%</strong><span>progress</span></div>
    </section>
  </header>
  <main>
    <h2>Task Timeline</h2>
    <section class="grid">
      {cards}
    </section>
    <h2>Failures</h2>
    <table>
      <thead><tr><th>Step</th><th>Category</th><th>Recoverable</th><th>Message</th><th>Log</th></tr></thead>
      <tbody>{failure_rows}</tbody>
    </table>
    <h2>Retry Policy</h2>
    <table>
      <thead><tr><th>Stage</th><th>Step</th><th>Attempt</th><th>Decision</th><th>Reason</th></tr></thead>
      <tbody>{retry_rows}</tbody>
    </table>
    <h2>Repair Log</h2>
    <table>
      <thead><tr><th>ID</th><th>Step</th><th>Category</th><th>Status</th><th>Manual</th><th>Approval</th><th>Plan</th></tr></thead>
      <tbody>{repair_rows}</tbody>
    </table>
    <h2>Next Actions</h2>
    <ol class="actions">{next_actions}</ol>
  </main>
</body>
</html>
"""


def _task_view(
    index: int,
    step: dict[str, Any],
    task_run: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    latest_attempt = attempts[-1] if attempts else None
    source_run = task_run or latest_attempt or {}
    status = str(source_run.get("status", "PENDING"))
    outputs = list(step.get("outputs", []))
    artifact_status = {
        output: (run_dir / output).exists()
        for output in outputs
    }
    started_at = source_run.get("started_at")
    ended_at = source_run.get("ended_at")
    failure_category = source_run.get("failure_category")
    failure_message = source_run.get("failure_message")
    log_path = source_run.get("log_path")
    failure = None
    if failure_category or failure_message or status == "FAILED":
        failure = {
            "category": failure_category or "ENV_ERROR",
            "message": failure_message or "Task failed without a persisted message.",
        }
        if source_run.get("retry_decision"):
            failure["retry_decision"] = source_run.get("retry_decision")
    return {
        "order": index,
        "task_id": source_run.get("task_id"),
        "step_id": str(step.get("id")),
        "agent": str(step.get("agent")),
        "platform": step.get("platform"),
        "parallel_group": step.get("parallel_group"),
        "depends_on": list(step.get("depends_on", [])),
        "status": status,
        "attempt_count": len(attempts) or (1 if task_run else 0),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _duration_ms(started_at, ended_at),
        "log_path": log_path,
        "log_exists": bool(log_path and (run_dir / str(log_path)).exists()),
        "expected_outputs": outputs,
        "artifact_health": _step_artifact_health(status, artifact_status),
        "failure": failure,
        "attempts": [_attempt_summary(attempt) for attempt in attempts],
    }


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    retry_policy = attempt.get("record", {}).get("retry_policy", {})
    return {
        "attempt": attempt.get("attempt"),
        "status": attempt.get("status"),
        "started_at": attempt.get("started_at"),
        "ended_at": attempt.get("ended_at"),
        "duration_ms": _duration_ms(attempt.get("started_at"), attempt.get("ended_at")),
        "failure_category": attempt.get("failure_category"),
        "failure_message": attempt.get("failure_message"),
        "log_path": attempt.get("log_path"),
        "auto_retry": bool(retry_policy.get("auto_retry")) if isinstance(retry_policy, dict) else False,
    }


def _step_artifact_health(status: str, artifact_status: dict[str, bool]) -> dict[str, Any]:
    expected = len(artifact_status)
    present = sum(1 for exists in artifact_status.values() if exists)
    missing = [path for path, exists in artifact_status.items() if not exists]
    if expected == 0:
        health_status = "none"
    elif present == expected:
        health_status = "complete"
    elif status in {"PENDING", "RUNNING", "SKIPPED"}:
        health_status = "not_required_yet"
    else:
        health_status = "missing"
    return {
        "status": health_status,
        "expected": expected,
        "present": present,
        "missing": missing,
    }


def _failure_views(workflow_run: dict[str, Any], task_views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    task_by_id = {task["step_id"]: task for task in task_views}
    for task in task_views:
        if not task.get("failure"):
            continue
        failure = dict(task["failure"])
        failure["step_id"] = task["step_id"]
        failure["agent"] = task["agent"]
        failure["task_id"] = failure.get("task_id") or _task_id_for_step(workflow_run, task["step_id"])
        failure["category"] = failure.get("category") or "ENV_ERROR"
        failure["message"] = failure.get("message") or "Task failed without a persisted message."
        failure["log_path"] = failure.get("log_path") or task.get("log_path")
        failure["attempt_count"] = failure.get("attempt_count") or task.get("attempt_count")
        failures.append(
            failure
        )

    known = {(failure.get("task_id"), failure.get("message")) for failure in failures}
    for failure in workflow_run.get("failures", []):
        key = (failure.get("task_id"), failure.get("message"))
        if key in known:
            continue
        step_id = _step_id_from_task_id(workflow_run, str(failure.get("task_id", "")))
        task = task_by_id.get(step_id or "")
        entry = dict(failure)
        entry["step_id"] = step_id
        entry["agent"] = task.get("agent") if task else entry.get("agent")
        entry["task_id"] = failure.get("task_id")
        entry["category"] = entry.get("category") or failure.get("failure_type")
        entry["message"] = failure.get("message")
        entry["log_path"] = task.get("log_path") if task else entry.get("log_path")
        entry["attempt_count"] = task.get("attempt_count") if task else entry.get("attempt_count")
        failures.append(
            entry
        )
    return failures


def _task_id_for_step(workflow_run: dict[str, Any], step_id: str) -> str | None:
    for task in workflow_run.get("tasks", []):
        if task.get("metadata", {}).get("step_id") == step_id:
            return task.get("task_id")
    return None


def _step_id_from_task_id(workflow_run: dict[str, Any], task_id: str) -> str | None:
    for task in workflow_run.get("tasks", []):
        if task.get("task_id") == task_id:
            return task.get("metadata", {}).get("step_id")
    return None


def _current_step(task_views: list[dict[str, Any]], workflow_run: dict[str, Any]) -> dict[str, Any] | None:
    prioritized_states = [
        {"stale", "interrupted"},
        {"failed"},
        {"watch"},
        {"running"},
        {"pending"},
    ]
    for state_group in prioritized_states:
        for task in task_views:
            health_state = str(task.get("health", {}).get("state", "")).lower()
            status = str(task.get("status", "")).lower()
            if health_state in state_group or status in state_group:
                return {
                    "step_id": task["step_id"],
                    "agent": task["agent"],
                    "status": task["status"],
                    "health_state": task.get("health", {}).get("state"),
                    "recoverable": task.get("health", {}).get("recoverable"),
                    "reason": task.get("health", {}).get("reason"),
                    "log_path": task.get("log_path"),
                }
    if workflow_run.get("status") == "DONE":
        return None
    return task_views[-1] if task_views else None


def _summary(
    workflow_run: dict[str, Any],
    task_statuses: list[str],
    failures: list[dict[str, Any]],
    health_analysis: dict[str, Any],
    retry_analysis: dict[str, Any],
    repair_analysis: dict[str, Any],
) -> dict[str, Any]:
    total = len(task_statuses)
    passed = task_statuses.count("PASSED")
    skipped = task_statuses.count("SKIPPED")
    completed = passed + skipped
    progress = round((completed / total) * 100, 1) if total else 0
    detector_summary = health_analysis.get("summary", {})
    retry_summary = retry_analysis.get("summary", {})
    repair_summary = repair_analysis.get("summary", {})
    return {
        "status": workflow_run.get("status"),
        "total_steps": total,
        "completed_steps": completed,
        "passed": passed,
        "failed": task_statuses.count("FAILED"),
        "skipped": skipped,
        "pending": task_statuses.count("PENDING"),
        "running": task_statuses.count("RUNNING"),
        "failure_count": len(failures),
        "stale_count": int(detector_summary.get("stale_count", 0)),
        "interrupted_count": int(detector_summary.get("interrupted_count", 0)),
        "recoverable_count": int(detector_summary.get("recoverable_count", 0)),
        "watch_count": int(detector_summary.get("watch_count", 0)),
        "auto_retry_count": int(retry_summary.get("auto_retry_count", 0)),
        "retry_event_count": int(retry_summary.get("event_count", 0)),
        "repair_count": int(repair_summary.get("repair_count", 0)),
        "manual_repair_count": int(repair_summary.get("manual_required_count", 0)),
        "pending_approval_count": int(repair_summary.get("pending_approval_count", 0)),
        "progress_percent": progress,
    }


def _stale_detector_view(health_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": health_analysis.get("config", {}),
        "detected_at": health_analysis.get("detected_at"),
        "summary": health_analysis.get("summary", {}),
        "stale_tasks": [_compact_health_task(task) for task in health_analysis.get("stale_tasks", [])],
        "watch_tasks": [_compact_health_task(task) for task in health_analysis.get("watch_tasks", [])],
        "recoverable_faults": health_analysis.get("recoverable_faults", []),
    }


def _repair_log_view(workflow_run: dict[str, Any]) -> dict[str, Any]:
    entries = [dict(entry) for entry in workflow_run.get("repair_log", [])]
    for entry in entries:
        if entry.get("manual_required") and not entry.get("approval_status"):
            entry["approval_status"] = "APPROVED" if entry.get("approved_at") else "PENDING"
        elif not entry.get("manual_required"):
            entry["approval_status"] = entry.get("approval_status") or "NOT_REQUIRED"
    return {
        "summary": {
            "repair_count": len(entries),
            "manual_required_count": sum(1 for entry in entries if entry.get("manual_required")),
            "pending_approval_count": sum(1 for entry in entries if entry.get("manual_required") and entry.get("approval_status") == "PENDING"),
            "approved_repair_count": sum(1 for entry in entries if entry.get("approval_status") == "APPROVED"),
            "rejected_repair_count": sum(1 for entry in entries if entry.get("approval_status") == "REJECTED"),
            "failed_repair_count": sum(1 for entry in entries if entry.get("status") == "FAILED"),
        },
        "entries": entries,
    }


def _repair_plan_for_failure(repair_entries: list[dict[str, Any]], failure: dict[str, Any]) -> str | None:
    task_id = failure.get("task_id")
    step_id = failure.get("step_id")
    for entry in reversed(repair_entries):
        if task_id and entry.get("task_id") == task_id:
            return entry.get("plan_path")
        if step_id and entry.get("failed_step_id") == step_id:
            return entry.get("plan_path")
    return None


def _repair_entry_for_failure(repair_entries: list[dict[str, Any]], failure: dict[str, Any]) -> dict[str, Any] | None:
    task_id = failure.get("task_id")
    step_id = failure.get("step_id")
    for entry in reversed(repair_entries):
        if task_id and entry.get("task_id") == task_id:
            return entry
        if step_id and entry.get("failed_step_id") == step_id:
            return entry
    return None


def _compact_health_task(task: dict[str, Any]) -> dict[str, Any]:
    health = task.get("health", {})
    return {
        "task_id": task.get("task_id"),
        "step_id": task.get("step_id"),
        "agent": task.get("agent"),
        "status": task.get("status"),
        "health_state": health.get("state"),
        "recoverable": health.get("recoverable"),
        "reason": health.get("reason"),
        "age_minutes": health.get("age_minutes"),
        "threshold_minutes": health.get("threshold_minutes"),
        "log_path": task.get("log_path"),
    }


def _artifact_health(task_views: list[dict[str, Any]]) -> dict[str, Any]:
    expected = 0
    present = 0
    missing: list[str] = []
    for task in task_views:
        health = task.get("artifact_health", {})
        expected += int(health.get("expected", 0))
        present += int(health.get("present", 0))
        missing.extend(health.get("missing", []))
    return {
        "expected": expected,
        "present": present,
        "missing": missing,
        "status": "complete" if not missing else "missing",
    }


def _workflow_graph(task_views: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = {task["step_id"]: f"step_{index}" for index, task in enumerate(task_views, start=1)}
    lines = ["flowchart LR"]
    if not task_views:
        lines.append('  empty["No tasks"]')
    for task in task_views:
        node_id = nodes[task["step_id"]]
        health_state = str(task.get("health", {}).get("state", "")).lower()
        label = f"{task['step_id']}\\n{task['status']}"
        if health_state and health_state not in {task["status"].lower(), "complete", "failed", "skipped"}:
            label = f"{label}\\n{health_state}"
        lines.append(f'  {node_id}["{label}"]')
        for dep in task.get("depends_on", []):
            if dep in nodes:
                lines.append(f"  {nodes[dep]} --> {node_id}")
    lines.extend(
        [
            "  classDef passed fill:#e8f5ee,stroke:#19794f,color:#10291d",
            "  classDef failed fill:#fff1f0,stroke:#b42318,color:#5c130d",
            "  classDef skipped fill:#eef2f7,stroke:#596579,color:#222b36",
            "  classDef pending fill:#fff7e6,stroke:#9b6800,color:#382500",
            "  classDef running fill:#eaf2ff,stroke:#2d6cdf,color:#12386f",
            "  classDef watch fill:#fff7e6,stroke:#cf8a00,color:#382500",
            "  classDef stale fill:#fff1f0,stroke:#b42318,color:#5c130d",
            "  classDef interrupted fill:#fff1f0,stroke:#b42318,color:#5c130d",
        ]
    )
    for task in task_views:
        health_state = str(task.get("health", {}).get("state", "")).lower()
        status_class = task["status"].lower()
        if health_state in {"watch", "stale", "interrupted"}:
            status_class = health_state
        elif status_class not in {"passed", "failed", "skipped", "pending", "running"}:
            status_class = "pending"
        lines.append(f"  class {nodes[task['step_id']]} {status_class}")
    return {"mermaid": "\n".join(lines)}


def _next_actions(
    workflow_run: dict[str, Any],
    task_views: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> list[str]:
    run_id = workflow_run.get("run_id")
    status = workflow_run.get("status")
    if failures:
        primary = failures[0]
        repair_entries = list(workflow_run.get("repair_log", []))
        repair_plan = _repair_plan_for_failure(repair_entries, primary)
        repair_entry = _repair_entry_for_failure(repair_entries, primary)
        if repair_entry and repair_entry.get("manual_required") and repair_entry.get("approval_status") == "PENDING":
            return [
                f"repair-agent 已为 step `{primary.get('step_id')}` 生成待确认修复方案。",
                f"先查看 repair plan: {repair_plan or 'n/a'}。",
                f"人工确认后执行: make approve-repair RUN_ID=\"{run_id}\" REPAIR_ID=\"{repair_entry.get('repair_id')}\"。",
                f"批准后再执行: make resume RUN_ID=\"{run_id}\"。",
            ]
        if repair_entry and repair_entry.get("manual_required") and repair_entry.get("approval_status") == "APPROVED":
            return [
                f"repair-agent 已为 step `{primary.get('step_id')}` 的修复方案完成人工批准。",
                f"查看 repair plan: {repair_plan or 'n/a'}。",
                f"批准后重新执行: make resume RUN_ID=\"{run_id}\"。",
            ]
        if primary.get("recoverable"):
            return [
                f"stale detector 已把 step `{primary.get('step_id')}` 识别为可恢复故障。",
                f"先查看 task log: {primary.get('log_path') or 'n/a'}。",
                f"确认没有仍在运行的外部进程后执行: make resume RUN_ID=\"{run_id}\"。",
            ]
        actions = [
            f"先查看失败 step `{primary.get('step_id')}` 的 task log: {primary.get('log_path') or 'n/a'}。",
            _category_action(str(primary.get("category") or "ENV_ERROR")),
        ]
        if repair_plan:
            actions.append(f"查看 repair-agent 诊断建议: {repair_plan}。")
        actions.append(f"人工修复后执行: make resume RUN_ID=\"{run_id}\"。")
        return actions

    if status == "DONE":
        return [
            "本次 workflow 已完成，可以审阅 final/content_package_manifest.json 和各平台产物。",
            "监督报告会随每次 run/resume 自动刷新，后续可接入 Web UI 或告警通道。",
        ]

    pending = next((task for task in task_views if task["status"] in {"PENDING", "RUNNING"}), None)
    if pending:
        health = pending.get("health", {})
        if health.get("state") == "watch":
            return [
                f"当前 step `{pending['step_id']}` 仍在 stale 阈值内运行，暂时只观察。",
                f"超过 {health.get('threshold_minutes')} 分钟仍未结束时，stale detector 会把它标记为可恢复故障。",
            ]
        return [
            f"当前关注 step `{pending['step_id']}`，确认它的上游依赖和输出文件是否齐备。",
            "如果进程被中断，重新执行 resume 会把未完成尝试标记为失败并继续恢复。",
        ]
    return ["没有检测到明确的失败或待办 step，请检查 workflow_run.json 与 SQLite 状态库是否一致。"]


def _category_action(category: str) -> str:
    return {
        "DATA_ERROR": "补齐缺失的上游产物或输入数据，再恢复运行。",
        "SCHEMA_ERROR": "检查 agent 输出字段和 JSON 格式，确保满足声明的 schema。",
        "QUALITY_ERROR": "调整 agent 生成策略或人工修订低质量内容，再恢复运行。",
        "POLICY_ERROR": "移除敏感、侵权或合规风险内容，保留人工审核记录。",
        "PERMISSION_ERROR": "确认未触发登录、cookie、上传、发布等需要人工批准的动作。",
        "ENV_ERROR": "检查本地环境、文件权限和运行依赖，再恢复运行。",
    }.get(category, "按失败信息修复后再恢复运行。")


def _load_task_attempts(run_dir: Path, workflow_run: dict[str, Any]) -> list[dict[str, Any]]:
    state_db = run_dir.parent / "_state" / "workflow_state.sqlite"
    run_id = str(workflow_run.get("run_id", ""))
    if state_db.exists() and run_id:
        return WorkflowStateStore(state_db).load_task_attempts(run_id)
    return [_attempt_from_task_run(task_run) for task_run in workflow_run.get("task_runs", [])]


def _attempt_from_task_run(task_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": None,
        "step_id": task_run.get("step_id"),
        "attempt": 1,
        "task_id": task_run.get("task_id"),
        "agent": task_run.get("agent"),
        "status": task_run.get("status"),
        "started_at": task_run.get("started_at"),
        "ended_at": task_run.get("ended_at"),
        "execution_mode": task_run.get("execution_mode"),
        "log_path": task_run.get("log_path"),
        "artifact_paths": task_run.get("artifact_paths", []),
        "failure_category": task_run.get("failure_category"),
        "failure_message": task_run.get("failure_message"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _failure_block(failure: dict[str, Any] | None) -> str:
    if not failure:
        return ""
    return (
        '<div class="failure">'
        f"{html.escape(str(failure.get('category')))}: {html.escape(str(failure.get('message')))}"
        "</div>"
    )


def _dashboard_card_class(task: dict[str, Any]) -> str:
    health_state = str(task.get("health", {}).get("state", "")).lower()
    if health_state in {"watch", "stale", "interrupted"}:
        return health_state
    status = str(task.get("status", "pending")).lower()
    return status if status in {"passed", "failed", "skipped", "pending", "running"} else "pending"


def _duration_ms(started_at: Any, ended_at: Any) -> int | None:
    start = _parse_dt(started_at)
    if not start:
        return None
    end = _parse_dt(ended_at) or datetime.now(timezone.utc)
    return max(0, int((end - start).total_seconds() * 1000))


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_duration(duration_ms: Any) -> str:
    if duration_ms is None:
        return "n/a"
    try:
        millis = int(duration_ms)
    except (TypeError, ValueError):
        return "n/a"
    if millis < 1000:
        return f"{millis} ms"
    return f"{millis / 1000:.2f} s"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
