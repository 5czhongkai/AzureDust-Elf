from __future__ import annotations

import plistlib
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "自媒体内容创作"
APP_DIR = ROOT / f"{APP_NAME}.app"
EXECUTABLE = APP_DIR / "Contents" / "MacOS" / APP_NAME
PLIST = APP_DIR / "Contents" / "Info.plist"
ICON_FILE = APP_DIR / "Contents" / "Resources" / "ContentAgentIcon.icns"
ICON_BASE_PNG = APP_DIR / "Contents" / "Resources" / "ContentAgentIcon-1024.png"
SWIFT_SOURCE = ROOT / "desktop" / "macos" / "ContentAgentLauncher" / "main.swift"
ICON_SOURCE_SVG = ROOT / "desktop" / "macos" / "ContentAgentLauncher" / "Resources" / "content_creator_logo.svg"
BUILD_SCRIPT = ROOT / "scripts" / "build_macos_app.sh"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    expect(SWIFT_SOURCE.exists(), "missing macOS launcher Swift source")
    expect(ICON_SOURCE_SVG.exists(), "missing desktop app SVG icon source")
    expect(BUILD_SCRIPT.exists(), "missing macOS app build script")
    expect(shutil.which("swiftc") is not None, "swiftc is required for desktop app validation")

    source = read_text(SWIFT_SOURCE)
    icon_source = read_text(ICON_SOURCE_SVG)
    build_script = read_text(BUILD_SCRIPT)
    expect("WKWebView" in source, "desktop app must use a native WKWebView window")
    expect("make console CONSOLE_PORT=" in source, "desktop app must start the local console service")
    expect("CONTENT_AGENT_CONSOLE_PORT" in source, "desktop app must allow port override")
    expect("127.0.0.1" in source, "desktop app must default to localhost")
    expect("desktop_app_console.log" in source, "desktop app must write a local launch log")
    expect("自媒体内容创作工作台" in source, "desktop app must expose Chinese UI title")
    expect("<svg" in icon_source and "viewBox=\"0 0 512 512\"" in icon_source, "desktop app icon source must be an SVG logo")
    expect("content_creator_logo.svg" in build_script, "build script must use the uploaded SVG logo")
    expect("CFBundleIconFile" in build_script, "build script must write the app icon key")
    expect("ContentAgentIcon.icns" in build_script, "build script must generate an icns icon")

    subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=ROOT, check=True)

    expect(APP_DIR.exists(), "desktop app bundle was not built")
    expect(EXECUTABLE.exists(), "desktop app executable missing")
    expect(PLIST.exists(), "desktop app Info.plist missing")
    expect(ICON_FILE.exists(), "desktop app icon file missing")
    expect(ICON_BASE_PNG.exists(), "desktop app base icon PNG missing")
    expect(EXECUTABLE.stat().st_mode & stat.S_IXUSR, "desktop app executable is not executable")
    expect(ICON_FILE.read_bytes()[:4] == b"icns", "desktop app icon is not an icns file")

    plist = plistlib.loads(PLIST.read_bytes())
    expect(plist.get("CFBundleExecutable") == APP_NAME, "Info.plist executable mismatch")
    expect(plist.get("CFBundlePackageType") == "APPL", "Info.plist must declare an app bundle")
    expect(plist.get("CFBundleDisplayName") == APP_NAME, "Info.plist display name mismatch")
    expect(plist.get("CFBundleIconFile") == "ContentAgentIcon", "Info.plist icon file mismatch")

    ats = plist.get("NSAppTransportSecurity") or {}
    expect(ats.get("NSAllowsLocalNetworking") is True, "desktop app must allow localhost networking")
    expect(ats.get("NSAllowsArbitraryLoads") is True, "desktop app must allow local HTTP fallback")

    makefile = read_text(ROOT / "Makefile")
    expect("build-macos-app:" in makefile, "Makefile missing build-macos-app target")
    expect("validate-phase5-desktop-app:" in makefile, "Makefile missing desktop app validation target")

    readme = read_text(ROOT / "README.md")
    runbook = read_text(ROOT / "docs" / "RUNBOOK.md")
    for doc_name, doc in (("README", readme), ("RUNBOOK", runbook)):
        expect("make build-macos-app" in doc, f"{doc_name} missing desktop build command")
        expect("make validate-phase5-desktop-app" in doc, f"{doc_name} missing desktop validation command")
        expect("自媒体内容创作.app" in doc, f"{doc_name} missing app bundle name")

    print("Phase 5 desktop app validation passed.")
    print(f"Built: {APP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
