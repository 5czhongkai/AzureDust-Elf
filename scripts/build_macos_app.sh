#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="自媒体内容创作"
APP_DIR="$ROOT/${APP_NAME}.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
SOURCE_FILE="$ROOT/desktop/macos/ContentAgentLauncher/main.swift"
EXECUTABLE="$MACOS_DIR/$APP_NAME"
ICON_SOURCE_SVG="$ROOT/desktop/macos/ContentAgentLauncher/Resources/content_creator_logo.svg"
ICONSET_DIR="$RESOURCES_DIR/ContentAgentIcon.iconset"
ICON_FILE="$RESOURCES_DIR/ContentAgentIcon.icns"
ICON_BASE_PNG="$RESOURCES_DIR/ContentAgentIcon-1024.png"
MODULE_CACHE_DIR="$ROOT/.build/swift-module-cache"

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc is required to build the macOS desktop app." >&2
  exit 1
fi

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$MODULE_CACHE_DIR"

swiftc "$SOURCE_FILE" \
  -module-cache-path "$MODULE_CACHE_DIR" \
  -framework Cocoa \
  -framework WebKit \
  -o "$EXECUTABLE"

chmod +x "$EXECUTABLE"

cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleExecutable</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>ContentAgentIcon</string>
  <key>CFBundleIdentifier</key>
  <string>local.content-agent-os.desktop</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.5.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

if [[ -f "$ICON_SOURCE_SVG" ]]; then
  cp "$ICON_SOURCE_SVG" "$RESOURCES_DIR/content_creator_logo.svg"
  swift -module-cache-path "$MODULE_CACHE_DIR" - "$ICON_SOURCE_SVG" "$ICON_BASE_PNG" <<'SWIFT'
import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("Usage: render_icon.swift <input.svg> <output.png>\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: arguments[1])
let outputURL = URL(fileURLWithPath: arguments[2])
guard let image = NSImage(contentsOf: inputURL) else {
    fputs("Unable to render SVG icon: \(inputURL.path)\n", stderr)
    exit(3)
}

let size = NSSize(width: 1024, height: 1024)
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: Int(size.width),
    pixelsHigh: Int(size.height),
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("Unable to allocate icon bitmap.\n", stderr)
    exit(4)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
NSColor.clear.setFill()
NSRect(origin: .zero, size: size).fill()
image.draw(
    in: NSRect(origin: .zero, size: size),
    from: NSRect(origin: .zero, size: image.size),
    operation: .sourceOver,
    fraction: 1.0
)
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Unable to encode icon PNG.\n", stderr)
    exit(5)
}
try png.write(to: outputURL)
SWIFT

  mkdir -p "$ICONSET_DIR"
  sips -z 16 16 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_BASE_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null

  python3 - "$ICONSET_DIR" "$ICON_FILE" <<'PY'
from __future__ import annotations

import struct
import sys
from pathlib import Path


iconset = Path(sys.argv[1])
output = Path(sys.argv[2])
items = [
    ("icp4", "icon_16x16.png"),
    ("icp5", "icon_32x32.png"),
    ("icp6", "icon_32x32@2x.png"),
    ("ic07", "icon_128x128.png"),
    ("ic08", "icon_256x256.png"),
    ("ic09", "icon_512x512.png"),
    ("ic10", "icon_512x512@2x.png"),
]

chunks = []
for code, filename in items:
    data = (iconset / filename).read_bytes()
    chunks.append(code.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

body = b"".join(chunks)
output.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
PY
  echo "Generated $ICON_FILE from $ICON_SOURCE_SVG"
fi

touch "$APP_DIR"
echo "Built $APP_DIR"
