#!/usr/bin/env python3
"""HelloMedia media capability constants and POST-preflight validation (stdlib)."""

from __future__ import annotations

from typing import Any

# Image aspects for capabilities + API docs. Layout extras (4:5, 5:4, 21:9) live in
# generate.SEMANTIC_RATIO_OPTIONS which is derived from this set plus layout-only ratios.
IMAGE_ASPECT_RATIOS = (
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20",
    "4:5", "5:4", "21:9", "auto",
)
VIDEO_ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")
VIDEO_RESOLUTIONS = ("480p", "720p", "1080p")
IMAGE_RESOLUTIONS_GROK = ("1k", "2k")
VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15
VIDEO_REFERENCE_DURATION_MAX = 10
VIDEO_REFERENCE_COUNT_MIN = 1
VIDEO_REFERENCE_COUNT_MAX = 7
VIDEO_PROMPT_MAX_CHARACTERS = 1000
IMAGE_OUTPUT_COUNT_MIN = 1
IMAGE_OUTPUT_COUNT_MAX = 10


class ValidationError(ValueError):
    def __init__(self, message: str, *, suggestions: list[str] | None = None, code: str | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []
        self.code = code or "invalid_parameter"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": False, "error": str(self), "code": self.code}
        if self.suggestions:
            out["suggestions"] = self.suggestions
        return out


def _ratio_parts(value: str) -> tuple[float, float] | None:
    try:
        a, b = value.replace("：", ":").split(":", 1)
        return float(a), float(b)
    except Exception:
        return None


def closest_aspect_ratios(value: str, supported: tuple[str, ...], limit: int = 2) -> list[str]:
    parts = _ratio_parts(value)
    if not parts or parts[1] == 0:
        return list(supported[:limit])
    target = parts[0] / parts[1]
    scored: list[tuple[float, str]] = []
    for item in supported:
        if item == "auto":
            continue
        p = _ratio_parts(item)
        if not p or p[1] == 0:
            continue
        scored.append((abs((p[0] / p[1]) - target), item))
    scored.sort(key=lambda x: x[0])
    return [s for _, s in scored[:limit]]


def parse_aspect_ratio(value: str | None, supported: tuple[str, ...], label: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().replace("：", ":")
    if normalized in supported:
        return normalized
    suggestions = closest_aspect_ratios(normalized, supported)
    suggestion_text = f" Try: {', '.join(suggestions)}." if suggestions else ""
    raise ValidationError(
        f"unsupported {label} aspect ratio '{value}'.{suggestion_text}",
        suggestions=suggestions,
        code="unsupported_aspect_ratio",
    )


def capabilities_dict() -> dict[str, Any]:
    return {
        "operation": "capabilities",
        "image": {
            "aspect_ratio": list(IMAGE_ASPECT_RATIOS),
            "resolution_grok": list(IMAGE_RESOLUTIONS_GROK),
            "n": {"minimum": IMAGE_OUTPUT_COUNT_MIN, "maximum": IMAGE_OUTPUT_COUNT_MAX},
            "routes": [
                "POST /v1/images/generations",
                "POST /v1/images/edits",
                "POST /v1/responses (image_generation tool)",
            ],
        },
        "video": {
            "route": "POST /v1/videos/generations",
            "edit_route": "POST /v1/videos/edits",
            "extend_route": "POST /v1/videos/extensions",
            "prompt_max_characters": VIDEO_PROMPT_MAX_CHARACTERS,
            "duration": {"minimum": VIDEO_DURATION_MIN, "maximum": VIDEO_DURATION_MAX},
            "aspect_ratio": list(VIDEO_ASPECT_RATIOS),
            "resolution": list(VIDEO_RESOLUTIONS),
            "modes": {
                "text_to_video": {
                    "prompt": "required",
                    "resolution": ["480p", "720p"],
                    "default_model": "grok-imagine-video",
                },
                "image_to_video": {
                    "image_count": 1,
                    "prompt": "required",
                    "resolution": list(VIDEO_RESOLUTIONS),
                    "resolution_1080p": "requires grok-imagine-video-1.5",
                    "aspect_ratio_default": "omit field to preserve source image ratio",
                    "default_model": "grok-imagine-video-1.5",
                },
                "reference_to_video": {
                    "prompt": "required",
                    "reference_image_count": {
                        "minimum": VIDEO_REFERENCE_COUNT_MIN,
                        "maximum": VIDEO_REFERENCE_COUNT_MAX,
                    },
                    "duration_maximum": VIDEO_REFERENCE_DURATION_MAX,
                    "resolution": ["480p", "720p"],
                    "unsupported_model": "grok-imagine-video-1.5",
                    "default_model": "grok-imagine-video",
                },
                "edit": {"requires_channel_flag": "video_edit"},
                "extend": {"requires_channel_flag": "video_extend"},
            },
        },
    }


def default_video_model(tool_mode: str, channel_model: str | None = None, explicit: str | None = None) -> str:
    """Pick video model by tool mode.

    Priority:
    1. Explicit CLI ``--model``
    2. For ``image_to_video``: always ``grok-imagine-video-1.5`` unless the channel
       *intentionally* pins a 1.5 model id (substring ``1.5``). A generic channel
       default like ``grok-imagine-video`` must NOT suppress the I2V 1.5 default
       (channel_creds always fills that generic fallback).
    3. Otherwise channel model, else ``grok-imagine-video``.
    """
    if explicit:
        return explicit
    if tool_mode == "image_to_video":
        if channel_model and "1.5" in str(channel_model):
            return channel_model
        return "grok-imagine-video-1.5"
    return channel_model or "grok-imagine-video"


def validate_video_request(
    *,
    tool_mode: str,
    duration: int,
    resolution: str,
    aspect_ratio: str | None,
    model: str,
    n_refs: int = 0,
    has_image: bool = False,
    has_video: bool = False,
    prompt: str = "",
    aspect_explicit: bool = True,
    video_edit: bool = True,
    video_extend: bool = True,
) -> dict[str, Any]:
    """Validate video params. Returns normalized fields. Raises ValidationError."""
    mode = tool_mode
    if mode in {"edit", "extend"}:
        if mode == "edit" and not video_edit:
            raise ValidationError(
                "video edit is disabled for this channel (set video_edit: true if API supports /v1/videos/edits)",
                code="video_edit_disabled",
            )
        if mode == "extend" and not video_extend:
            raise ValidationError(
                "video extend is disabled for this channel (set video_extend: true if API supports /v1/videos/extensions)",
                code="video_extend_disabled",
            )
        if not has_video:
            raise ValidationError(f"{mode} requires a source --video", code="missing_video")
        if not (prompt or "").strip():
            raise ValidationError("prompt is required", code="missing_prompt")
        return {
            "tool_mode": mode,
            "duration": None,
            "resolution": None,
            "aspect_ratio": None,
            "model": model,
            "omit_aspect_ratio": True,
        }

    if mode == "image_to_video" and mode == "reference_to_video":
        raise ValidationError("internal mode error", code="invalid_mode")

    if mode == "image_to_video" and not has_image:
        raise ValidationError("image_to_video requires --image", code="missing_image")
    if mode == "reference_to_video":
        if n_refs < VIDEO_REFERENCE_COUNT_MIN:
            raise ValidationError("reference_to_video requires at least 1 --reference", code="missing_reference")
        if n_refs > VIDEO_REFERENCE_COUNT_MAX:
            raise ValidationError(
                f"reference_to_video supports at most {VIDEO_REFERENCE_COUNT_MAX} images",
                code="too_many_references",
            )
        if "1.5" in (model or ""):
            raise ValidationError(
                "reference_to_video requires model grok-imagine-video (not grok-imagine-video-1.5)",
                code="unsupported_model",
            )
    if mode == "text_to_video" and (has_image or n_refs):
        raise ValidationError("text_to_video must not include --image/--reference", code="invalid_inputs")
    if has_image and n_refs:
        raise ValidationError("Cannot combine --image and --reference", code="conflicting_inputs")

    if not (prompt or "").strip() and mode != "image_to_video":
        raise ValidationError("prompt is required", code="missing_prompt")
    if len(prompt or "") > VIDEO_PROMPT_MAX_CHARACTERS:
        raise ValidationError(
            f"prompt exceeds {VIDEO_PROMPT_MAX_CHARACTERS} characters",
            code="prompt_too_long",
        )

    max_dur = VIDEO_REFERENCE_DURATION_MAX if mode == "reference_to_video" else VIDEO_DURATION_MAX
    if duration < VIDEO_DURATION_MIN or duration > max_dur:
        raise ValidationError(
            f"duration must be {VIDEO_DURATION_MIN}-{max_dur} for mode {mode}",
            code="invalid_duration",
        )

    res = (resolution or "480p").lower()
    if res not in VIDEO_RESOLUTIONS:
        raise ValidationError(f"unsupported resolution '{resolution}'", code="invalid_resolution")
    if res == "1080p":
        if mode != "image_to_video" or "1.5" not in (model or ""):
            raise ValidationError(
                "1080p is only allowed for image_to_video with grok-imagine-video-1.5",
                code="invalid_resolution_combo",
            )
    if mode == "reference_to_video" and res not in ("480p", "720p"):
        raise ValidationError("reference_to_video only supports 480p or 720p", code="invalid_resolution")
    if mode == "text_to_video" and res not in ("480p", "720p"):
        raise ValidationError("text_to_video only supports 480p or 720p", code="invalid_resolution")

    omit_aspect = False
    aspect_out: str | None = aspect_ratio
    if mode == "image_to_video" and not aspect_explicit:
        omit_aspect = True
        aspect_out = None
    elif aspect_ratio is not None:
        aspect_out = parse_aspect_ratio(aspect_ratio, VIDEO_ASPECT_RATIOS, "video")

    return {
        "tool_mode": mode,
        "duration": duration,
        "resolution": res,
        "aspect_ratio": aspect_out,
        "model": model,
        "omit_aspect_ratio": omit_aspect,
    }
