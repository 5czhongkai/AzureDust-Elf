from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class ResolvedVisualSource:
    mode: str
    provider: str
    image_bytes: bytes
    content_type: str = "image/png"
    source_path: str | None = None
    source_reference: str | None = None
    source_library_root: str | None = None
    revised_prompt: str | None = None
    source_metadata: dict[str, Any] | None = None


def resolve_visual_source(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    asset_type: str,
    prompt: str,
    aspect_ratio: str,
    task: dict[str, Any] | None = None,
    target_size: tuple[int, int] | None = None,
) -> ResolvedVisualSource | None:
    candidate = _resolve_library_source(
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        asset_type=asset_type,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        task=task,
    )
    if candidate is not None:
        return candidate

    openai_source = _resolve_openai_source(
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        asset_type=asset_type,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        target_size=target_size,
        task=task,
    )
    if openai_source is not None:
        return openai_source

    return None


def _resolve_library_source(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    asset_type: str,
    prompt: str,
    aspect_ratio: str,
    task: dict[str, Any] | None,
) -> ResolvedVisualSource | None:
    for library_root in _asset_library_roots():
        if not library_root.exists():
            continue
        candidate = _find_library_candidate(
            library_root=library_root,
            topic=topic,
            platform=platform,
            platform_label=platform_label,
            asset_type=asset_type,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            task=task,
        )
        if candidate is None:
            continue
        image_path, metadata = candidate
        try:
            image_bytes = image_path.read_bytes()
        except OSError:
            continue
        if not _looks_like_image(image_path, image_bytes):
            continue
        return ResolvedVisualSource(
            mode="asset_library",
            provider="local-asset-library",
            image_bytes=image_bytes,
            content_type=_content_type_for_path(image_path),
            source_path=str(image_path),
            source_reference=str(image_path.relative_to(library_root)),
            source_library_root=str(library_root),
            source_metadata=metadata,
        )
    return None


def _resolve_openai_source(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    asset_type: str,
    prompt: str,
    aspect_ratio: str,
    target_size: tuple[int, int] | None,
    task: dict[str, Any] | None,
) -> ResolvedVisualSource | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("CONTENT_AGENT_OS_IMAGE_MODEL", "").strip() or "gpt-image-1"
    size = _openai_size_for_aspect_ratio(aspect_ratio, target_size)
    request_prompt = _openai_prompt(
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        asset_type=asset_type,
        prompt=prompt,
        task=task,
    )
    request_body = {
        "model": model,
        "prompt": request_prompt,
        "size": size,
        "n": 1,
        "output_format": "png",
        "quality": "high",
        "background": "opaque",
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return None

    first = data[0] if isinstance(data[0], dict) else {}
    image_bytes: bytes | None = None
    if isinstance(first, dict) and isinstance(first.get("b64_json"), str) and first["b64_json"].strip():
        try:
            image_bytes = base64.b64decode(first["b64_json"])
        except (ValueError, TypeError):
            image_bytes = None
    elif isinstance(first, dict) and isinstance(first.get("url"), str) and first["url"].strip():
        image_bytes = _fetch_image_from_url(first["url"])

    if not image_bytes:
        return None

    revised_prompt = None
    if isinstance(first, dict) and isinstance(first.get("revised_prompt"), str):
        revised_prompt = first["revised_prompt"]

    return ResolvedVisualSource(
        mode="openai_image_api",
        provider="openai-images-api",
        image_bytes=image_bytes,
        content_type="image/png",
        source_reference="openai://images/generations",
        revised_prompt=revised_prompt,
        source_metadata={
            "model": model,
            "size": payload.get("size") or size,
            "quality": payload.get("quality") or "high",
            "output_format": payload.get("output_format") or "png",
        },
    )


def _asset_library_roots() -> list[Path]:
    roots: list[Path] = [Path("outputs/runs")]
    for env_name in [
        "CONTENT_AGENT_OS_ASSET_LIBRARY_ROOT",
        "ASSET_LIBRARY_ROOT",
        "MEDIA_ASSET_LIBRARY_ROOT",
    ]:
        raw = os.environ.get(env_name, "").strip()
        if raw:
            roots.append(Path(raw).expanduser())
    return roots


def _find_library_candidate(
    *,
    library_root: Path,
    topic: str,
    platform: str,
    platform_label: str,
    asset_type: str,
    prompt: str,
    aspect_ratio: str,
    task: dict[str, Any] | None,
) -> tuple[Path, dict[str, Any]] | None:
    keywords = _tokenize(
        " ".join(
            [
                topic,
                platform,
                platform_label,
                asset_type,
                aspect_ratio,
                prompt,
                str(task.get("task_id")) if isinstance(task, dict) else "",
                str(task.get("linked_shot_id")) if isinstance(task, dict) else "",
                str(task.get("usage")) if isinstance(task, dict) else "",
            ]
        )
    )
    best_score = 0
    best_candidate: tuple[Path, dict[str, Any]] | None = None
    paths = list(_iter_library_image_paths(library_root, asset_type=asset_type))
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        metadata = _read_candidate_metadata(path)
        score = _score_candidate(
            path=path,
            metadata=metadata,
            keywords=keywords,
            platform=platform,
            platform_label=platform_label,
            asset_type=asset_type,
            aspect_ratio=aspect_ratio,
        )
        if score > best_score:
            best_score = score
            best_candidate = (path, metadata)
    return best_candidate if best_score > 0 else None


def _iter_library_image_paths(library_root: Path, *, asset_type: str) -> list[Path]:
    if not library_root.exists():
        return []
    if library_root.name == "runs":
        run_dirs = [path for path in library_root.glob("run_*") if path.is_dir()]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        run_dirs = run_dirs[:12]
        paths: list[Path] = []
        for run_dir in run_dirs:
            if asset_type == "cover_image":
                paths.extend(run_dir.glob("assets/*/cover/cover.*"))
                paths.extend(run_dir.glob("assets/*/cover/*.png"))
            elif asset_type == "storyboard_frame":
                paths.extend(run_dir.glob("assets/*/storyboard/*.png"))
            else:
                paths.extend(run_dir.glob("assets/*/*/*.png"))
                paths.extend(run_dir.glob("assets/*/*/*.jpg"))
                paths.extend(run_dir.glob("assets/*/*/*.jpeg"))
        return paths
    return list(library_root.rglob("*"))


def _score_candidate(
    *,
    path: Path,
    metadata: dict[str, Any],
    keywords: set[str],
    platform: str,
    platform_label: str,
    asset_type: str,
    aspect_ratio: str,
) -> int:
    text_parts: list[str] = [
        path.stem,
        str(path.parent),
        json.dumps(metadata, ensure_ascii=False, sort_keys=True) if metadata else "",
    ]
    haystack = _tokenize(" ".join(text_parts))
    score = 0
    score += 8 if asset_type in haystack else 0
    score += 6 if platform in haystack else 0
    score += 4 if _normalize(platform_label) in " ".join(text_parts).lower() else 0
    score += 3 if aspect_ratio.replace(":", "") in haystack or aspect_ratio in haystack else 0
    if isinstance(metadata, dict):
        for key in ["platform", "asset_type", "topic", "description", "title", "prompt", "usage"]:
            value = metadata.get(key)
            if isinstance(value, str) and _normalize(value) in " ".join(text_parts).lower():
                score += 2
        for key in ["tags", "keywords"]:
            value = metadata.get(key)
            if isinstance(value, list):
                score += 2 * len({token for token in map(_normalize, value) if token in keywords})
    score += len(keywords.intersection(haystack))
    return score


def _read_candidate_metadata(image_path: Path) -> dict[str, Any]:
    candidates = [
        image_path.with_suffix(".json"),
        image_path.with_name(f"{image_path.stem}.metadata.json"),
        image_path.with_name(f"{image_path.stem}.info.json"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _looks_like_image(path: Path, image_bytes: bytes) -> bool:
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return True
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        return True
    except Exception:
        return False


def _fetch_image_from_url(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": "content-agent-os/0.0.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.URLError:
        return None


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def _openai_size_for_aspect_ratio(aspect_ratio: str, target_size: tuple[int, int] | None) -> str:
    if target_size and target_size[0] >= target_size[1]:
        return "1536x1024"
    if aspect_ratio == "16:9":
        return "1536x1024"
    if aspect_ratio == "9:16":
        return "1024x1536"
    return "1024x1024"


def _openai_prompt(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    asset_type: str,
    prompt: str,
    task: dict[str, Any] | None,
) -> str:
    prompt_lines = [
        f"Create a clean, high-detail image for a Chinese content-production asset on {platform_label} ({platform}).",
        f"Topic: {topic}",
        f"Asset type: {asset_type}",
        "Avoid watermarks, logos, private data, and unreadable embedded text.",
        "Leave safe negative space for later overlay text and interface framing.",
    ]
    if asset_type == "cover_image":
        prompt_lines.append("Make the composition editorial and strong enough to support a bold title overlay.")
    elif asset_type == "storyboard_frame":
        prompt_lines.append("Make the composition cinematic and suitable as a storyboard keyframe reference.")
    if isinstance(task, dict):
        for key in ["task_id", "linked_shot_id", "usage"]:
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                prompt_lines.append(f"{key.replace('_', ' ').title()}: {value}")
    prompt_lines.append(f"Source prompt: {prompt}")
    return "\n".join(prompt_lines)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())


def _tokenize(text: str) -> set[str]:
    raw_tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower())
    tokens = {_normalize(token) for token in raw_tokens}
    return {token for token in tokens if token}
