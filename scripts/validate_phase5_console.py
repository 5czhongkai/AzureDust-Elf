from __future__ import annotations

import base64
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.console_server import (  # noqa: E402
    ConsoleConfig,
    ConsoleRuntime,
    make_console_handler,
)
from content_agent_os.api_key_store import PLATFORM_API_KEY_ENV_KEYS  # noqa: E402


SECRET_SENTINEL = "phase5-secret-sentinel"
API_KEY_SENTINEL = "phase5-console-api-key-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 console validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> Any:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def http_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON response for {path}: {exc}")


def http_text(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return response.read().decode("utf-8")


def write_fake_run(output_root: Path) -> Path:
    run_dir = output_root / "run_20260602T000000Z"
    (run_dir / "monitor").mkdir(parents=True, exist_ok=True)
    (run_dir / "final").mkdir(parents=True, exist_ok=True)
    for platform in ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"]:
        (run_dir / platform).mkdir(parents=True, exist_ok=True)
    workflow_run = {
        "schema_version": "workflow_run.v1",
        "run_id": run_dir.name,
        "workflow_id": "one_topic_multi_platform",
        "topic": "Phase 5 console validation",
        "platforms": ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
        "status": "DONE",
        "created_at": "2026-06-02T00:00:00+00:00",
        "updated_at": "2026-06-02T00:01:00+00:00",
        "workflow": {"steps": []},
        "task_runs": [],
        "artifacts": ["final/content_package_manifest.json"],
    }
    snapshot = {
        "schema_version": "phase3.supervision.v1",
        "run": {
            "run_id": run_dir.name,
            "topic": "Phase 5 console validation",
            "status": "DONE",
            "run_dir": str(run_dir),
        },
        "summary": {
            "completed_steps": 1,
            "total_steps": 1,
            "progress_percent": 100,
        },
        "tasks": [],
    }
    (run_dir / "workflow_run.json").write_text(json.dumps(workflow_run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "monitor/supervision_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "wechat/article.md").write_text("# 微信公众号正文\n\n这是公众号生成内容。\n", encoding="utf-8")
    (run_dir / "wechat/title_options.json").write_text(
        json.dumps({"titles": ["Phase 5 控制台验证"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "xiaohongshu/note.json").write_text(
        json.dumps({"title": "小红书标题", "body": "这是小红书生成内容。"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "xiaohongshu/cover_prompt.md").write_text("小红书封面提示词。\n", encoding="utf-8")
    for platform, label in [("douyin", "抖音"), ("shipinhao", "视频号")]:
        (run_dir / platform / "script.md").write_text(f"# {label}脚本\n\n这是{label}生成内容。\n", encoding="utf-8")
        (run_dir / platform / "subtitles.srt").write_text(
            f"1\n00:00:00,000 --> 00:00:01,000\n{label}字幕\n",
            encoding="utf-8",
        )
        (run_dir / platform / "cover_prompt.md").write_text(f"{label}封面提示词。\n", encoding="utf-8")
    (run_dir / "bilibili/script.md").write_text("# B站脚本\n\n这是B站生成内容。\n", encoding="utf-8")
    (run_dir / "bilibili/description.md").write_text("B站简介。\n", encoding="utf-8")
    (run_dir / "bilibili/chapters.json").write_text(
        json.dumps({"chapters": [{"time": "00:00", "title": "开场"}]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "final/content_package_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "phase4.content_package_manifest.v1",
                "artifacts": [
                    {"platform": "wechat", "path": "wechat/article.md"},
                    {"platform": "xiaohongshu", "path": "xiaohongshu/note.json"},
                    {"platform": "douyin", "path": "douyin/script.md"},
                    {"platform": "shipinhao", "path": "shipinhao/script.md"},
                    {"platform": "bilibili", "path": "bilibili/script.md"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def validate_runtime_api(tmp_root: Path) -> None:
    output_root = tmp_root / "outputs/runs"
    backup_root = tmp_root / "backups"
    run_dir = write_fake_run(output_root)
    previous_secret = os.environ.get("SILICONFLOW_API_KEY")
    previous_env = os.environ.get("CONTENT_AGENT_ENV")
    previous_platform_secrets = {
        env_key: os.environ.get(env_key)
        for env_key in PLATFORM_API_KEY_ENV_KEYS.values()
    }
    os.environ["SILICONFLOW_API_KEY"] = SECRET_SENTINEL
    os.environ["CONTENT_AGENT_ENV"] = "validation"
    try:
        runtime = ConsoleRuntime(
            ConsoleConfig(
                workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
                output_root=output_root,
                backup_root=backup_root,
                default_platforms=["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
                execute_inline_jobs=False,
            )
        )
        health = runtime.health()
        expect(health.get("status") == "ok", "health should be ok")
        expect(health.get("workflow_exists") is True, "workflow must exist")

        env_status = runtime.environment_status()
        env_text = json.dumps(env_status, ensure_ascii=False)
        expect(SECRET_SENTINEL not in env_text, "environment status must not expose secret values")
        secret_rows = {item["name"]: item for item in env_status.get("secrets", [])}
        expect(secret_rows.get("SILICONFLOW_API_KEY", {}).get("present") is True, "secret presence must be reported")
        setup_check = runtime.setup_check()
        setup_text = json.dumps(setup_check, ensure_ascii=False)
        expect(setup_check.get("schema_version") == "phase5.setup_check.v1", "setup check schema mismatch")
        expect(SECRET_SENTINEL not in setup_text, "setup check must not expose secret values")

        api_status = runtime.api_key_status()
        expect(api_status.get("target_count") == 5, "API key status must include five platform targets")
        expect(API_KEY_SENTINEL not in json.dumps(api_status, ensure_ascii=False), "API key status must not expose values")
        api_save = runtime.save_api_keys({"keys": {"wechat": API_KEY_SENTINEL}})
        api_save_text = json.dumps(api_save, ensure_ascii=False)
        expect(api_save.get("updated_targets") == ["wechat"], "API key save must report updated platform")
        expect(API_KEY_SENTINEL not in api_save_text, "API key save response must not expose secret values")
        expect(os.environ.get("CONTENT_AGENT_WECHAT_API_KEY") == API_KEY_SENTINEL, "API key save must refresh process env")
        api_status = runtime.api_key_status()
        wechat_status = {item["id"]: item for item in api_status.get("targets", [])}.get("wechat", {})
        expect(wechat_status.get("configured") is True, "saved platform API key must report configured")
        env_status = runtime.environment_status()
        secret_rows = {item["name"]: item for item in env_status.get("secrets", [])}
        expect(secret_rows.get("CONTENT_AGENT_WECHAT_API_KEY", {}).get("present") is True, "saved API key must appear as present env")
        expect(API_KEY_SENTINEL not in json.dumps(env_status, ensure_ascii=False), "env endpoint must not expose saved API key")

        run_index = runtime.list_runs()
        expect(run_index.get("runs", [{}])[0].get("run_id") == run_dir.name, "run index must include fake run")
        summary = runtime.run_summary(run_dir.name)
        expect(summary.get("workflow_run", {}).get("status") == "DONE", "run summary must load workflow run")
        platform_content = runtime.platform_content(run_dir.name, "wechat")
        expect(platform_content.get("platform_label") == "微信公众号", "platform content label mismatch")
        expect(platform_content.get("files", [{}])[0].get("content", "").startswith("# 微信公众号正文"), "platform content must load primary files")
        filename, download_body, content_type = runtime.platform_download(run_dir.name, "wechat")
        expect(filename.endswith("_wechat_content.md"), "platform download filename mismatch")
        expect("微信公众号生成内容" in download_body.decode("utf-8"), "platform download body missing title")
        expect(content_type.startswith("text/markdown"), "platform download content type mismatch")

        upload = runtime.upload_inputs(
            [
                {
                    "name": "brief.txt",
                    "mime_type": "text/plain",
                    "data_base64": base64.b64encode("本地素材说明".encode("utf-8")).decode("ascii"),
                }
            ]
        )
        expect(upload.get("schema_version") == "phase5.upload_manifest.v1", "upload schema mismatch")
        upload_file = upload.get("files", [{}])[0]
        expect(upload_file.get("kind") == "text", "text upload kind mismatch")
        expect(Path(str(upload_file.get("path"))).exists(), "uploaded file must be written")
        queued = runtime.start_run(
            "带素材的选题",
            ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
            attachments=upload.get("files", []),
        )
        expect(queued.get("attachments", [{}])[0].get("name") == "brief.txt", "queued job must keep upload attachment")

        backup = runtime.create_backup()
        backup_path = Path(str(backup.get("backup_path")))
        expect(backup_path.exists(), "backup zip must be created")
        expect(backup.get("file_count", 0) >= 2, "backup must include run files")
        second_backup = runtime.create_backup()
        second_backup_path = Path(str(second_backup.get("backup_path")))
        expect(second_backup_path.exists(), "second backup zip must be created")
        expect(second_backup_path != backup_path, "same-second backups must not overwrite each other")
        with zipfile.ZipFile(backup_path) as archive:
            names = set(archive.namelist())
            expect("backup_manifest.json" in names, "backup must include manifest")
            expect("outputs/runs/run_20260602T000000Z/workflow_run.json" in names, "backup must include workflow run")
            expect("outputs/runs/_state/api_keys.json" not in names, "backup must exclude local API key store")
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".json") or name.endswith(".md")
            )
            expect(SECRET_SENTINEL not in archive_text, "backup must not include env secret values")
            expect(API_KEY_SENTINEL not in archive_text, "backup must not include saved API key values")
        restore = runtime.restore_dry_run(backup_path.name)
        expect(restore.get("dry_run") is True, "restore dry-run must identify itself")
        expect(restore.get("will_extract") is False, "restore dry-run must not extract files")
        expect(restore.get("safe_to_restore") is True, "restore dry-run should reject unsafe archive entries")
        expect(restore.get("file_count", 0) >= 2, "restore dry-run must list restorable files")
        expect(restore.get("would_overwrite_count", 0) >= 2, "restore dry-run must report overwrite count")
        try:
            runtime.restore_backup(backup_path.name, "")
        except ValueError as exc:
            expect("confirmation" in str(exc), "restore without confirmation must explain confirmation requirement")
        else:
            fail("restore without confirmation should fail")
        workflow_path = run_dir / "workflow_run.json"
        workflow_path.write_text(json.dumps({"status": "CORRUPTED"}, ensure_ascii=False) + "\n", encoding="utf-8")
        restored = runtime.restore_backup(backup_path.name, f"RESTORE {backup_path.name}")
        expect(restored.get("dry_run") is False, "confirmed restore must not be reported as dry-run")
        expect(restored.get("will_extract") is True, "confirmed restore must extract files")
        expect(restored.get("file_count", 0) >= 2, "confirmed restore must restore files")
        expect(Path(str(restored.get("restore_log_path"))).exists(), "confirmed restore must write restore log")
        expect(load_json(workflow_path).get("status") == "DONE", "confirmed restore must restore workflow file content")
    finally:
        if previous_secret is None:
            os.environ.pop("SILICONFLOW_API_KEY", None)
        else:
            os.environ["SILICONFLOW_API_KEY"] = previous_secret
        if previous_env is None:
            os.environ.pop("CONTENT_AGENT_ENV", None)
        else:
            os.environ["CONTENT_AGENT_ENV"] = previous_env
        for env_key, value in previous_platform_secrets.items():
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value


def validate_http_console(tmp_root: Path) -> None:
    output_root = tmp_root / "outputs/runs"
    backup_root = tmp_root / "backups"
    run_dir = write_fake_run(output_root)
    previous_platform_secrets = {
        env_key: os.environ.get(env_key)
        for env_key in PLATFORM_API_KEY_ENV_KEYS.values()
    }
    runtime = ConsoleRuntime(
            ConsoleConfig(
                workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
                output_root=output_root,
                backup_root=backup_root,
                default_platforms=["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
                execute_inline_jobs=False,
            )
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_console_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        html = http_text(base_url, "/")
        expect("自媒体内容创作工作台" in html, "console HTML missing Chinese workspace title")
        expect("创作输入" in html, "console HTML missing composer")
        expect("队列状态" in html, "console HTML missing queue status")
        expect("生成内容预览" not in html, "creator workspace should not render inline content preview")
        expect("加入生成队列" in html, "console HTML missing run control")
        expect("生成平台" in html, "console HTML missing platform picker")
        expect("全选五个平台" in html, "console HTML missing select-all platform control")
        expect("align-items: stretch" in html, "creator workspace must stretch columns for aligned cards")
        expect("workspace-card" in html, "creator workspace cards must use aligned card class")
        expect("下载当前内容" not in html, "creator workspace should not render inline download control")
        expect("/api/uploads" in html, "console HTML missing upload endpoint wiring")
        expect("platform-badge" in html, "console HTML missing task platform badge styling")
        expect("platformBadge(job.platforms)" in html, "job task rows must render platform label before status")
        expect("platformBadge(run.platforms)" in html, "run task rows must render platform label before status")
        expect("data-content-url" in html, "console HTML missing explicit content-open handler wiring")
        expect("scheduleContentFallback" in html, "console HTML missing content-open fallback wiring")
        expect('target="_blank"' in html, "run content link should open in a new window")
        expect("后端控制台" in html, "creator workspace missing admin console link")
        expect("本机状态" not in html, "creator workspace should not expose local runtime panel")
        expect("队列维护" not in html, "creator workspace should not expose queue maintenance panel")

        admin_html = http_text(base_url, "/admin")
        expect("后端控制台" in admin_html, "admin console HTML missing title")
        expect("创作工作台" in admin_html, "admin console HTML missing creator workspace link")
        for phrase in ["本机状态", "配置检查", "队列维护", "队列任务", "备份恢复", "环境变量"]:
            expect(phrase in admin_html, f"admin console HTML missing phrase: {phrase}")
        expect("API Key 配置" in admin_html, "admin console missing API key configuration panel")
        expect("/api/api-keys" in admin_html, "admin console missing API key endpoint wiring")
        expect("make validate-phase5-setup" in admin_html, "admin console missing setup validation command")
        expect("make worker-once" in admin_html, "admin console missing worker command")
        expect("清理预览" in admin_html, "admin console missing cleanup dry-run control")
        expect("确认清理" in admin_html, "admin console missing cleanup confirmation control")

        health = http_json(base_url, "/healthz")
        expect(health.get("status") == "ok", "HTTP health must be ok")

        runs = http_json(base_url, "/api/runs")
        expect(runs.get("runs", [{}])[0].get("run_id") == run_dir.name, "HTTP run index mismatch")

        summary = http_json(base_url, f"/api/runs/{run_dir.name}")
        expect(summary.get("workflow_run", {}).get("run_id") == run_dir.name, "HTTP run summary mismatch")
        platform_content = http_json(base_url, f"/api/runs/{run_dir.name}/platforms/wechat")
        expect(platform_content.get("schema_version") == "phase5.platform_content.v1", "HTTP platform content schema mismatch")
        expect("公众号生成内容" in platform_content.get("files", [{}])[0].get("content", ""), "HTTP platform content must include generated text")
        download_text = http_text(base_url, f"/api/runs/{run_dir.name}/platforms/wechat/download")
        expect("微信公众号生成内容" in download_text, "HTTP platform download missing content title")
        run_content_html = http_text(base_url, f"/runs/{run_dir.name}/content")
        expect("生成内容" in run_content_html, "run content page missing title")
        expect("完整生成结果" in run_content_html, "run content page missing full content heading")
        expect("下载全部内容" in run_content_html, "run content page missing all-content download button")
        expect("下载本平台" in run_content_html, "run content page missing platform download button")
        expect("微信公众号" in run_content_html, "run content page missing WeChat section")
        expect("公众号生成内容" in run_content_html, "run content page must render generated content")
        all_download_text = http_text(base_url, f"/runs/{run_dir.name}/content/download")
        expect("微信公众号生成内容" in all_download_text, "all-content download missing WeChat content")
        expect("小红书生成内容" in all_download_text, "all-content download missing Xiaohongshu content")
        upload = http_json(
            base_url,
            "/api/uploads",
            method="POST",
            payload={
                "files": [
                    {
                        "name": "brief.txt",
                        "mime_type": "text/plain",
                        "data_base64": base64.b64encode(b"creator ui brief").decode("ascii"),
                    }
                ]
            },
        )
        expect(upload.get("files", [{}])[0].get("kind") == "text", "HTTP upload should persist text file")
        queued = http_json(
            base_url,
            "/api/runs",
            method="POST",
            payload={
                "topic": "with upload",
                "platforms": ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
                "attachments": upload.get("files", []),
            },
        )
        expect(queued.get("status") == "QUEUED", "HTTP full platform run should queue")
        expect(queued.get("attachments", [{}])[0].get("name") == "brief.txt", "HTTP queued job must include attachment")

        env_status = http_json(base_url, "/api/env")
        expect("secrets" in env_status, "HTTP env endpoint missing secrets")
        expect(SECRET_SENTINEL not in json.dumps(env_status, ensure_ascii=False), "HTTP env must not expose secret value")
        setup_check = http_json(base_url, "/api/setup-check")
        expect(setup_check.get("schema_version") == "phase5.setup_check.v1", "HTTP setup check schema mismatch")
        expect("checks" in setup_check, "HTTP setup check missing checks")

        api_status = http_json(base_url, "/api/api-keys")
        expect(api_status.get("target_count") == 5, "HTTP API key status must list platform targets")
        api_save = http_json(
            base_url,
            "/api/api-keys",
            method="POST",
            payload={"keys": {"douyin": API_KEY_SENTINEL}},
        )
        expect(api_save.get("updated_targets") == ["douyin"], "HTTP API key save must report target")
        expect(API_KEY_SENTINEL not in json.dumps(api_save, ensure_ascii=False), "HTTP API key save must not expose values")
        api_status = http_json(base_url, "/api/api-keys")
        douyin_status = {item["id"]: item for item in api_status.get("targets", [])}.get("douyin", {})
        expect(douyin_status.get("configured") is True, "HTTP API key status must refresh after save")
        env_status = http_json(base_url, "/api/env")
        env_rows = {item["name"]: item for item in env_status.get("secrets", [])}
        expect(env_rows.get("CONTENT_AGENT_DOUYIN_API_KEY", {}).get("present") is True, "HTTP env must see saved platform key")
        expect(API_KEY_SENTINEL not in json.dumps(env_status, ensure_ascii=False), "HTTP env must not expose saved platform key")

        backup = http_json(base_url, "/api/backups", method="POST")
        backup_path = Path(str(backup.get("backup_path")))
        expect(backup_path.exists(), "HTTP backup must create zip")

        restore = http_json(base_url, "/api/restore-dry-run", method="POST", payload={"backup": backup_path.name})
        expect(restore.get("dry_run") is True, "HTTP restore dry-run must identify itself")
        expect(restore.get("will_extract") is False, "HTTP restore dry-run must not extract files")
        expect(restore.get("safe_to_restore") is True, "HTTP restore dry-run should be safe")
        expect(restore.get("file_count", 0) >= 2, "HTTP restore dry-run must list files")
        try:
            http_json(base_url, "/api/restore", method="POST", payload={"backup": backup_path.name})
        except urllib.error.HTTPError as exc:
            expect(exc.code == 400, "HTTP restore without confirmation should return 400")
        else:
            fail("HTTP restore without confirmation should fail")
        (run_dir / "workflow_run.json").write_text(
            json.dumps({"status": "CORRUPTED"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        restored = http_json(
            base_url,
            "/api/restore",
            method="POST",
            payload={"backup": backup_path.name, "confirmation": f"RESTORE {backup_path.name}"},
        )
        expect(restored.get("dry_run") is False, "HTTP confirmed restore must not be dry-run")
        expect(restored.get("will_extract") is True, "HTTP confirmed restore must extract")
        expect(load_json(run_dir / "workflow_run.json").get("status") == "DONE", "HTTP restore must restore file content")

        partial_job = http_json(
            base_url,
            "/api/runs",
            method="POST",
            payload={"topic": "partial platform run", "platforms": ["douyin"]},
        )
        expect(partial_job.get("status") == "QUEUED", "partial platform run should queue")
        expect(partial_job.get("platforms") == ["douyin"], "partial platform run should keep selected platform")

        try:
            http_json(
                base_url,
                "/api/runs",
                method="POST",
                payload={"topic": "empty platform run", "platforms": []},
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            expect(exc.code == 400, "empty platform run should return 400")
            expect("at least one platform" in body, "empty platform error should explain selection requirement")
        else:
            fail("empty platform run should fail")

        try:
            http_json(base_url, "/api/runs", method="POST", payload={"topic": "", "platforms": ["douyin"]})
        except urllib.error.HTTPError as exc:
            expect(exc.code == 400, "empty topic should return 400")
        else:
            fail("empty topic request should fail")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for env_key, value in previous_platform_secrets.items():
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value


def validate_compose_files() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    expect("content_agent_os.console_server" in compose, "compose must run console server")
    expect("CONTENT_AGENT_CONSOLE_PORT" in compose, "compose must expose configurable console port")
    expect("SILICONFLOW_API_KEY" in compose, "compose must pass secret presence through env")
    expect("pip install --no-cache-dir -e ." in dockerfile, "Dockerfile must install project")
    expect("CONTENT_AGENT_BACKUP_ROOT" in env_example, ".env.example missing backup root")
    expect("console:" in makefile, "Makefile missing console target")
    expect("validate-phase5-console:" in makefile, "Makefile missing phase5 validation target")
    expect("validate-phase5-setup:" in makefile, "Makefile missing phase5 setup validation target")


def main() -> int:
    validate_compose_files()
    print("Phase 5 console drill passed: compose and local targets")
    with TemporaryDirectory() as tmp:
        validate_runtime_api(Path(tmp))
    print("Phase 5 console drill passed: runtime API and backup policy")
    with TemporaryDirectory() as tmp:
        validate_http_console(Path(tmp))
    print("Phase 5 console drill passed: HTTP console")
    print("Phase 5 console validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
