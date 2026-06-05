from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


@dataclass(frozen=True)
class GeneratedCover:
    image_bytes: bytes
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GeneratedStoryboardFrame:
    image_bytes: bytes
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GeneratedStoryboardPreview:
    image_bytes: bytes
    metadata: dict[str, Any]


def generate_cover_image(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    prompt: str,
    aspect_ratio: str,
    target_path: str,
    source_image_bytes: bytes | None = None,
    source_artifacts: list[str] | None = None,
) -> GeneratedCover:
    width, height = _dimensions_for_ratio(aspect_ratio)
    palette = _palette(platform)
    image = _background_canvas(width, height, palette, source_image_bytes)
    draw = ImageDraw.Draw(image)

    title_font = _font(max(38, width // 14), bold=True)
    label_font = _font(max(22, width // 30), bold=True)
    body_font = _font(max(22, width // 34), bold=False)
    small_font = _font(max(18, width // 44), bold=False)

    margin = max(42, width // 16)
    _draw_background_grid(draw, width, height, palette)
    _draw_orchestrator_panel(draw, width, height, margin, palette, label_font, body_font)

    title = _short_title(topic)
    title_lines = _wrap_text(draw, title, title_font, width - margin * 2)
    title_y = margin
    for line in title_lines[:3]:
        draw.text((margin, title_y), line, fill=palette["title"], font=title_font)
        title_y += _line_height(draw, line, title_font) + 8

    badge_text = f"{platform_label} 封面草图"
    badge_box = draw.textbbox((0, 0), badge_text, font=label_font)
    badge_width = badge_box[2] - badge_box[0] + 36
    badge_height = badge_box[3] - badge_box[1] + 22
    draw.rounded_rectangle(
        (margin, title_y + 14, margin + badge_width, title_y + 14 + badge_height),
        radius=badge_height // 2,
        fill=palette["accent"],
    )
    draw.text((margin + 18, title_y + 25), badge_text, fill=palette["badge_text"], font=label_font)

    hook_text = _prompt_to_hook(prompt)
    hook_y = height - margin - 170
    hook_lines = _wrap_text(draw, hook_text, body_font, width - margin * 2)
    draw.rounded_rectangle(
        (margin, hook_y - 26, width - margin, height - margin),
        radius=24,
        fill=palette["panel"],
        outline=palette["line"],
        width=2,
    )
    y = hook_y
    for line in hook_lines[:4]:
        draw.text((margin + 26, y), line, fill=palette["body"], font=body_font)
        y += _line_height(draw, line, body_font) + 8

    footer = "Generated locally · pending human review · no upload"
    draw.text((margin + 26, height - margin - 34), footer, fill=palette["muted"], font=small_font)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    image_bytes = buffer.getvalue()
    metadata = {
        "schema_version": "phase4.cover_image_metadata.v1",
        "asset_type": "cover_image",
        "platform": platform,
        "platform_label": platform_label,
        "path": target_path,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "adapter": "local-pillow-cover-adapter",
        "adapter_version": "0.1.0",
        "generation_status": "generated_pending_review",
        "rights_status": "pending_human_review",
        "manual_review_required": True,
        "source_prompt": prompt,
        "run_id": run_id,
        "source_artifacts": source_artifacts or [],
        "review_notes": [
            "Generated image is a local draft cover asset.",
            "Human review must confirm text, factual safety, asset rights, and platform fit before use.",
            "When available, the cover may incorporate a resolved library or image-generation source before local overlay composition.",
            "No upload, sync, or publishing action was performed.",
        ],
    }
    return GeneratedCover(image_bytes=image_bytes, metadata=metadata)


def generate_storyboard_frame_image(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    frame_index: int,
    shot_id: str,
    scene: str,
    purpose: str,
    visual: str,
    voiceover: str,
    duration_seconds: int,
    aspect_ratio: str,
    target_path: str,
    source_image_bytes: bytes | None = None,
    source_artifacts: list[str] | None = None,
) -> GeneratedStoryboardFrame:
    width, height = _dimensions_for_ratio(aspect_ratio)
    palette = _palette(platform)
    image = _background_canvas(width, height, palette, source_image_bytes)
    draw = ImageDraw.Draw(image)

    title_font = _font(max(30, width // 22), bold=True)
    label_font = _font(max(18, width // 44), bold=True)
    body_font = _font(max(20, width // 42), bold=False)
    small_font = _font(max(16, width // 58), bold=False)
    margin = max(38, width // 18)

    _draw_background_grid(draw, width, height, palette)
    _draw_storyboard_frame(
        draw=draw,
        width=width,
        height=height,
        margin=margin,
        palette=palette,
        title_font=title_font,
        label_font=label_font,
        body_font=body_font,
        small_font=small_font,
        frame_index=frame_index,
        platform_label=platform_label,
        shot_id=shot_id,
        scene=scene,
        purpose=purpose,
        visual=visual,
        voiceover=voiceover,
        duration_seconds=duration_seconds,
        topic=topic,
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    image_bytes = buffer.getvalue()
    metadata = {
        "schema_version": "phase4.storyboard_frame_metadata.v1",
        "asset_type": "storyboard_frame",
        "platform": platform,
        "platform_label": platform_label,
        "path": target_path,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "adapter": "local-pillow-storyboard-preview-adapter",
        "adapter_version": "0.1.0",
        "generation_status": "generated_pending_review",
        "rights_status": "pending_human_review",
        "manual_review_required": True,
        "run_id": run_id,
        "frame_index": frame_index,
        "shot_id": shot_id,
        "linked_shot_id": shot_id,
        "scene": scene,
        "purpose": purpose,
        "visual": visual,
        "voiceover": voiceover,
        "duration_seconds": duration_seconds,
        "source_topic": topic,
        "source_artifacts": source_artifacts or [],
        "review_notes": [
            "Generated image is a local storyboard keyframe preview.",
            "Human review must confirm visual fit, readable text, factual safety, asset rights, and platform fit before use.",
            "When available, the storyboard frame may incorporate a resolved library or image-generation source before local overlay composition.",
            "No editing, upload, sync, or publishing action was performed.",
        ],
    }
    return GeneratedStoryboardFrame(image_bytes=image_bytes, metadata=metadata)


def generate_storyboard_preview_sheet(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    aspect_ratio: str,
    target_path: str,
    frames: list[GeneratedStoryboardFrame],
) -> GeneratedStoryboardPreview:
    palette = _palette(platform)
    columns = 3 if aspect_ratio == "16:9" else 2
    thumb_width = 360 if aspect_ratio == "16:9" else 260
    thumb_height = 203 if aspect_ratio == "16:9" else 462
    gap = 26
    margin = 46
    header_height = 138
    rows = max(1, (len(frames) + columns - 1) // columns)
    width = margin * 2 + columns * thumb_width + (columns - 1) * gap
    height = header_height + margin + rows * (thumb_height + 70) + max(0, rows - 1) * gap + margin
    image = Image.new("RGB", (width, height), palette["background"])
    draw = ImageDraw.Draw(image)

    title_font = _font(34, bold=True)
    label_font = _font(22, bold=True)
    small_font = _font(18, bold=False)
    _draw_background_grid(draw, width, height, palette)

    title = f"{platform_label} Storyboard Preview"
    draw.text((margin, margin), title, fill=palette["title"], font=title_font)
    subtitle = f"{len(frames)} keyframes - generated locally - pending human review"
    draw.text((margin, margin + 48), subtitle, fill=palette["muted"], font=small_font)
    draw.rounded_rectangle(
        (width - margin - 180, margin, width - margin, margin + 52),
        radius=22,
        fill=palette["accent"],
    )
    draw.text((width - margin - 152, margin + 15), "preview sheet", fill=palette["badge_text"], font=small_font)

    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    y = header_height
    for index, frame in enumerate(frames):
        row = index // columns
        column = index % columns
        x = margin + column * (thumb_width + gap)
        y = header_height + row * (thumb_height + 70 + gap)
        with Image.open(BytesIO(frame.image_bytes)) as frame_image:
            thumbnail = frame_image.convert("RGB").resize((thumb_width, thumb_height), resample)
        draw.rounded_rectangle(
            (x - 8, y - 8, x + thumb_width + 8, y + thumb_height + 8),
            radius=18,
            fill=palette["panel"],
            outline=palette["line"],
            width=2,
        )
        image.paste(thumbnail, (x, y))
        shot_label = f"{index + 1:02d} {frame.metadata.get('shot_id', '')}"
        draw.text((x, y + thumb_height + 18), shot_label, fill=palette["title"], font=label_font)
        scene = str(frame.metadata.get("scene") or "")[:28]
        draw.text((x, y + thumb_height + 45), scene, fill=palette["muted"], font=small_font)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    metadata = {
        "schema_version": "phase4.storyboard_preview_metadata.v1",
        "asset_type": "storyboard_preview",
        "platform": platform,
        "platform_label": platform_label,
        "path": target_path,
        "width": width,
        "height": height,
        "aspect_ratio": "preview_sheet",
        "source_aspect_ratio": aspect_ratio,
        "adapter": "local-pillow-storyboard-preview-adapter",
        "adapter_version": "0.1.0",
        "generation_status": "generated_pending_review",
        "rights_status": "pending_human_review",
        "manual_review_required": True,
        "run_id": run_id,
        "topic": topic,
        "frame_count": len(frames),
        "frames": [frame.metadata for frame in frames],
        "review_notes": [
            "Preview sheet is generated from local storyboard keyframe drafts.",
            "Human review must approve visual consistency, rights, text readability, and platform fit before editing or publishing.",
            "No editing, upload, sync, or publishing action was performed.",
        ],
    }
    return GeneratedStoryboardPreview(image_bytes=buffer.getvalue(), metadata=metadata)


def _dimensions_for_ratio(aspect_ratio: str) -> tuple[int, int]:
    return (1280, 720) if aspect_ratio == "16:9" else (720, 1280)


def _background_canvas(
    width: int,
    height: int,
    palette: dict[str, tuple[int, int, int]],
    source_image_bytes: bytes | None,
) -> Image.Image:
    if source_image_bytes:
        try:
            with Image.open(BytesIO(source_image_bytes)) as source_image:
                resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                return ImageOps.fit(source_image.convert("RGB"), (width, height), method=resample)
        except Exception:
            pass
    return Image.new("RGB", (width, height), palette["background"])


def _palette(platform: str) -> dict[str, tuple[int, int, int]]:
    palettes = {
        "douyin": {
            "background": (248, 250, 252),
            "panel": (255, 255, 255),
            "accent": (15, 23, 42),
            "title": (12, 18, 28),
            "body": (31, 41, 55),
            "muted": (100, 116, 139),
            "line": (203, 213, 225),
            "badge_text": (255, 255, 255),
            "card": (226, 245, 255),
            "card_alt": (254, 226, 226),
        },
        "shipinhao": {
            "background": (247, 252, 249),
            "panel": (255, 255, 255),
            "accent": (22, 101, 52),
            "title": (20, 40, 30),
            "body": (31, 55, 43),
            "muted": (91, 112, 101),
            "line": (187, 221, 200),
            "badge_text": (255, 255, 255),
            "card": (220, 252, 231),
            "card_alt": (236, 253, 245),
        },
        "bilibili": {
            "background": (250, 252, 255),
            "panel": (255, 255, 255),
            "accent": (2, 132, 199),
            "title": (12, 32, 48),
            "body": (30, 58, 76),
            "muted": (92, 115, 130),
            "line": (191, 219, 254),
            "badge_text": (255, 255, 255),
            "card": (224, 242, 254),
            "card_alt": (239, 246, 255),
        },
    }
    return palettes.get(platform, palettes["douyin"])


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


def _draw_background_grid(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    step = max(42, width // 18)
    line = tuple(max(0, value - 8) for value in palette["background"])
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=line, width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=line, width=1)


def _draw_orchestrator_panel(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    margin: int,
    palette: dict[str, tuple[int, int, int]],
    label_font: ImageFont.ImageFont,
    body_font: ImageFont.ImageFont,
) -> None:
    panel_w = width - margin * 2
    panel_h = min(height // 3, 360)
    panel_x = margin
    panel_y = max(height // 3, margin + 240)
    orchestrator_font = _font(max(18, width // 48), bold=True)
    draw.rounded_rectangle(
        (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
        radius=32,
        fill=palette["panel"],
        outline=palette["line"],
        width=3,
    )
    center_w = min(panel_w // 2, 360)
    center_x = panel_x + (panel_w - center_w) // 2
    center_y = panel_y + 42
    draw.rounded_rectangle(
        (center_x, center_y, center_x + center_w, center_y + 88),
        radius=24,
        fill=palette["accent"],
    )
    orchestrator_label = "Global Orchestrator"
    if draw.textbbox((0, 0), orchestrator_label, font=orchestrator_font)[2] - draw.textbbox((0, 0), orchestrator_label, font=orchestrator_font)[0] > center_w - 40:
        orchestrator_label = "Orchestrator"
    draw.text((center_x + 28, center_y + 26), orchestrator_label, fill=palette["badge_text"], font=orchestrator_font)

    card_labels = ["Research", "Outline", "Assets", "Video Pack"]
    card_w = max(112, (panel_w - 84) // 4)
    card_y = center_y + 150
    for index, label in enumerate(card_labels):
        card_x = panel_x + 24 + index * (card_w + 12)
        fill = palette["card"] if index % 2 == 0 else palette["card_alt"]
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + 82),
            radius=18,
            fill=fill,
            outline=palette["line"],
            width=2,
        )
        draw.line((center_x + center_w // 2, center_y + 88, card_x + card_w // 2, card_y), fill=palette["line"], width=3)
        draw.text((card_x + 18, card_y + 24), label, fill=palette["body"], font=body_font)


def _draw_storyboard_frame(
    *,
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    margin: int,
    palette: dict[str, tuple[int, int, int]],
    title_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
    body_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    frame_index: int,
    platform_label: str,
    shot_id: str,
    scene: str,
    purpose: str,
    visual: str,
    voiceover: str,
    duration_seconds: int,
    topic: str,
) -> None:
    header_h = max(104, height // 11)
    footer_h = max(220, height // 5)
    stage_y = margin + header_h + 24
    stage_bottom = height - margin - footer_h
    stage_h = max(260, stage_bottom - stage_y)

    header_title = f"Keyframe {frame_index:02d} - {platform_label}"
    draw.text((margin, margin), header_title, fill=palette["title"], font=title_font)
    meta = f"{shot_id} / {scene} / {duration_seconds}s"
    draw.text((margin, margin + 52), meta, fill=palette["muted"], font=small_font)
    badge = "storyboard preview"
    badge_box = draw.textbbox((0, 0), badge, font=small_font)
    badge_w = badge_box[2] - badge_box[0] + 34
    badge_x = width - margin - badge_w
    draw.rounded_rectangle(
        (badge_x, margin + 4, width - margin, margin + 48),
        radius=20,
        fill=palette["accent"],
    )
    draw.text((badge_x + 17, margin + 17), badge, fill=palette["badge_text"], font=small_font)

    draw.rounded_rectangle(
        (margin, stage_y, width - margin, stage_y + stage_h),
        radius=28,
        fill=palette["panel"],
        outline=palette["line"],
        width=3,
    )
    accent_h = 16
    draw.rounded_rectangle(
        (margin + 24, stage_y + 24, width - margin - 24, stage_y + 24 + accent_h),
        radius=accent_h // 2,
        fill=palette["accent"],
    )

    card_y = stage_y + 62
    card_gap = 18
    card_count = 3
    card_w = max(120, (width - margin * 2 - 48 - card_gap * (card_count - 1)) // card_count)
    card_h = min(98, max(76, stage_h // 5))
    cards = [
        ("Topic", _short_title(topic)),
        ("Purpose", purpose),
        ("Duration", f"{duration_seconds}s"),
    ]
    for index, (label, value) in enumerate(cards):
        card_x = margin + 24 + index * (card_w + card_gap)
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=18,
            fill=palette["card"] if index % 2 == 0 else palette["card_alt"],
            outline=palette["line"],
            width=2,
        )
        draw.text((card_x + 18, card_y + 14), label, fill=palette["muted"], font=small_font)
        _draw_wrapped_text(
            draw,
            str(value),
            label_font,
            (card_x + 18, card_y + 42),
            card_w - 36,
            palette["body"],
            max_lines=1,
        )

    visual_box_top = card_y + card_h + 28
    visual_box_bottom = stage_y + stage_h - 34
    visual_box_h = max(110, visual_box_bottom - visual_box_top)
    draw.rounded_rectangle(
        (margin + 24, visual_box_top, width - margin - 24, visual_box_top + visual_box_h),
        radius=22,
        fill=palette["background"],
        outline=palette["line"],
        width=2,
    )
    draw.text((margin + 48, visual_box_top + 24), "Visual", fill=palette["muted"], font=small_font)
    _draw_wrapped_text(
        draw,
        visual,
        body_font,
        (margin + 48, visual_box_top + 60),
        width - margin * 2 - 96,
        palette["body"],
        max_lines=max(3, visual_box_h // 40),
    )

    footer_top = height - margin - footer_h + 30
    draw.rounded_rectangle(
        (margin, footer_top, width - margin, height - margin),
        radius=24,
        fill=palette["panel"],
        outline=palette["line"],
        width=2,
    )
    draw.text((margin + 24, footer_top + 22), "Voiceover", fill=palette["muted"], font=small_font)
    _draw_wrapped_text(
        draw,
        voiceover,
        body_font,
        (margin + 24, footer_top + 58),
        width - margin * 2 - 48,
        palette["body"],
        max_lines=3,
    )
    note = "Generated locally - pending human review - no upload"
    draw.text((margin + 24, height - margin - 36), note, fill=palette["muted"], font=small_font)


def _short_title(topic: str) -> str:
    compact = " ".join(topic.split())
    return compact[:34] if len(compact) > 34 else compact


def _prompt_to_hook(prompt: str) -> str:
    marker = "Title idea:"
    if marker in prompt:
        return prompt.split(marker, 1)[1].strip()[:72]
    return prompt.strip()[:72]


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


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    xy: tuple[int, int],
    max_width: int,
    fill: tuple[int, int, int],
    *,
    max_lines: int,
    line_gap: int = 7,
) -> int:
    lines = _wrap_text(draw, text, font, max_width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        if len(lines[-1]) > 3:
            lines[-1] = lines[-1][:-3] + "..."
    x, y = xy
    for line in lines[:max_lines]:
        draw.text((x, y), line, fill=fill, font=font)
        y += _line_height(draw, line, font) + line_gap
    return y


def _resize_filter() -> int:
    resampling = getattr(Image, "Resampling", None)
    return resampling.LANCZOS if resampling else Image.LANCZOS
