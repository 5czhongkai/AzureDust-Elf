from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class GeneratedMaterializedAssets:
    images: dict[str, bytes]
    manifest: dict[str, Any]
    readme_text: str


def generate_materialized_assets(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    asset_tasks: dict[str, Any],
    broll_list: list[dict[str, Any]],
    manifest_path: str,
    readme_path: str,
) -> GeneratedMaterializedAssets:
    broll_tasks = [
        task
        for task in asset_tasks.get("tasks", [])
        if isinstance(task, dict)
        and task.get("platform") == platform
        and task.get("asset_type") == "broll"
    ]
    broll_by_asset_id = {
        str(item.get("asset_id")): item
        for item in broll_list
        if isinstance(item, dict) and item.get("asset_id")
    }
    images: dict[str, bytes] = {}
    materialized_assets: list[dict[str, Any]] = []
    for index, task in enumerate(broll_tasks, start=1):
        asset_id = _asset_id_from_task(task, platform, index)
        source_broll = broll_by_asset_id.get(asset_id, {})
        reference_path = f"assets/{platform}/materials/{asset_id}_reference.png"
        image_bytes = _render_reference_image(
            topic=topic,
            platform=platform,
            platform_label=platform_label,
            asset_id=asset_id,
            description=str(source_broll.get("description") or task.get("prompt") or "B-roll reference asset."),
            usage=str(source_broll.get("usage") or task.get("usage") or "Use as supporting visual reference."),
            aspect_ratio="16:9" if platform == "bilibili" else "9:16",
        )
        images[reference_path] = image_bytes
        materialized_assets.append(
            {
                "asset_id": asset_id,
                "task_id": task.get("task_id"),
                "platform": platform,
                "platform_label": platform_label,
                "asset_type": "broll_reference",
                "source_task_asset_type": "broll",
                "reference_path": reference_path,
                "planned_target_path": task.get("target_path"),
                "bytes": len(image_bytes),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "description": str(source_broll.get("description") or task.get("prompt") or ""),
                "usage": str(source_broll.get("usage") or task.get("usage") or ""),
                "generation_status": "generated_reference_pending_review",
                "rights_status": "self_created_reference_pending_human_review",
                "licensed_final_media_required": True,
                "manual_review_required": True,
                "review_notes": [
                    "Generated local reference PNG only; it is not final licensed B-roll footage.",
                    "Human review must confirm visual fit and rights before replacing B-roll placeholders.",
                    "No external asset search, download, import, upload, or publishing action was performed.",
                ],
            }
        )

    validation_status = "PASSED" if materialized_assets else "NEEDS_REVIEW"
    manifest = {
        "schema_version": "phase4.materialized_assets_manifest.v1",
        "artifact_type": "materialized_assets",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-asset-materialization-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "readme_path": readme_path,
        "source_artifacts": [
            "assets/asset_generation_tasks.json",
            f"{platform}/broll_list.json",
        ],
        "materialized_assets": materialized_assets,
        "summary": {
            "materialized_count": len(materialized_assets),
            "broll_reference_count": len(materialized_assets),
            "licensed_final_media_required_count": len(
                [asset for asset in materialized_assets if asset["licensed_final_media_required"]]
            ),
        },
        "export_boundary": {
            "asset_materialization": "performed_locally_reference_only",
            "asset_download": "not_performed",
            "external_asset_search": "not_performed",
            "editing_software": "not_opened",
            "upload": "not_performed",
            "publishing": "not_performed",
        },
        "validation": {
            "status": validation_status,
            "materialized_count": len(materialized_assets),
            "all_reference_files_declared": bool(materialized_assets),
            "licensed_final_media_required": True,
        },
        "generation_status": "generated_local_asset_references_pending_human_review",
        "manual_review_required": True,
        "review_required": True,
    }
    return GeneratedMaterializedAssets(
        images=images,
        manifest=manifest,
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
    )


def _asset_id_from_task(task: dict[str, Any], platform: str, index: int) -> str:
    task_id = str(task.get("task_id") or "")
    prefix = f"{platform}_"
    suffix = "_import"
    if task_id.startswith(prefix) and task_id.endswith(suffix):
        return task_id[len(prefix) : -len(suffix)]
    return f"broll_{index:02d}"


def _render_reference_image(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    asset_id: str,
    description: str,
    usage: str,
    aspect_ratio: str,
) -> bytes:
    width, height = (1280, 720) if aspect_ratio == "16:9" else (1080, 1920)
    palette = _palette(platform)
    image = Image.new("RGB", (width, height), palette["background"])
    draw = ImageDraw.Draw(image)
    margin = max(42, width // 16)
    _draw_grid(draw, width, height, palette)

    title_font = _font(max(34, width // 18), bold=True)
    label_font = _font(max(22, width // 38), bold=True)
    body_font = _font(max(22, width // 42), bold=False)
    small_font = _font(max(16, width // 58), bold=False)

    badge = f"{platform_label} B-roll reference"
    draw.rounded_rectangle((margin, margin, width - margin, margin + 76), radius=28, fill=palette["accent"])
    draw.text((margin + 26, margin + 22), badge, fill=palette["badge_text"], font=label_font)

    y = margin + 118
    for line in _wrap_text(draw, topic, title_font, width - margin * 2)[:3]:
        draw.text((margin, y), line, fill=palette["title"], font=title_font)
        y += _line_height(draw, line, title_font) + 12

    card_top = y + 34
    card_bottom = height - margin - 140
    draw.rounded_rectangle(
        (margin, card_top, width - margin, card_bottom),
        radius=28,
        fill=palette["panel"],
        outline=palette["line"],
        width=3,
    )
    cursor = card_top + 34
    sections = [
        ("Asset", asset_id),
        ("Reference", description),
        ("Usage", usage),
        ("Boundary", "Local self-created reference only. Replace with licensed final footage after review."),
    ]
    for heading, text in sections:
        draw.text((margin + 34, cursor), heading, fill=palette["accent"], font=label_font)
        cursor += _line_height(draw, heading, label_font) + 12
        for line in _wrap_text(draw, text, body_font, width - margin * 2 - 68)[:5]:
            draw.text((margin + 34, cursor), line, fill=palette["body"], font=body_font)
            cursor += _line_height(draw, line, body_font) + 8
        cursor += 20

    footer = "Generated locally - pending human review - no external asset download"
    draw.text((margin, height - margin - 54), footer, fill=palette["muted"], font=small_font)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _palette(platform: str) -> dict[str, tuple[int, int, int]]:
    palettes = {
        "douyin": {
            "background": (245, 248, 250),
            "panel": (255, 255, 255),
            "line": (57, 76, 96),
            "title": (20, 31, 45),
            "body": (35, 47, 62),
            "muted": (96, 111, 128),
            "accent": (29, 181, 167),
            "badge_text": (255, 255, 255),
        },
        "shipinhao": {
            "background": (245, 250, 247),
            "panel": (255, 255, 255),
            "line": (61, 92, 74),
            "title": (24, 46, 35),
            "body": (39, 63, 50),
            "muted": (92, 119, 102),
            "accent": (42, 157, 113),
            "badge_text": (255, 255, 255),
        },
        "bilibili": {
            "background": (247, 249, 252),
            "panel": (255, 255, 255),
            "line": (57, 75, 112),
            "title": (20, 35, 65),
            "body": (38, 52, 81),
            "muted": (91, 108, 139),
            "accent": (67, 126, 213),
            "badge_text": (255, 255, 255),
        },
    }
    return palettes.get(platform, palettes["douyin"])


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    step = max(44, width // 18)
    line = tuple(max(0, value - 10) for value in palette["background"])
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=line, width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=line, width=1)


def _font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _line_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text or "Ag", font=font)
    return box[3] - box[1]


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Materialized Assets",
        "",
        f"- Topic: {topic}",
        f"- Platform: {platform_label}",
        f"- Validation: {manifest['validation']['status']}",
        "",
        "## Reference Assets",
        "",
    ]
    for asset in manifest["materialized_assets"]:
        lines.extend(
            [
                f"- `{asset['reference_path']}`",
                f"  - Asset ID: {asset['asset_id']}",
                f"  - Usage: {asset['usage']}",
                "  - Boundary: reference only; licensed final media is still required.",
            ]
        )
    lines.extend(
        [
            "",
            "No external asset search, download, editing software, upload, or publishing action was performed.",
            "Review required: true",
            "",
        ]
    )
    return "\n".join(lines)
