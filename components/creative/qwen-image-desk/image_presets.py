"""One backend-safe Qwen image-size contract shared by both browser apps."""

from __future__ import annotations


IMAGE_ALIGNMENT = 64
IMAGE_MIN_DIMENSION = 256
IMAGE_MAX_DIMENSION = 1792
IMAGE_MAX_PIXELS = 1792 * 1024
DEFAULT_IMAGE_PRESET = "landscape-standard"

# Ordered deliberately: each UI renders this exact catalogue without owning a
# second list. All dimensions are multiples of 64 and stay inside the tested
# 1.84-megapixel envelope.
IMAGE_PRESETS = {
    "landscape-draft": {"label": "Draft / Fast", "shape": "Landscape", "tier": "draft", "width": 768, "height": 448},
    "landscape-standard": {"label": "Standard", "shape": "Landscape", "tier": "standard", "width": 1024, "height": 576},
    "landscape-high": {"label": "High", "shape": "Landscape", "tier": "high", "width": 1344, "height": 768},
    "landscape-large": {"label": "1080-class", "shape": "Landscape", "tier": "large", "width": 1792, "height": 1024},
    "square-draft": {"label": "Draft / Fast", "shape": "Square", "tier": "draft", "width": 640, "height": 640},
    "square-standard": {"label": "Standard", "shape": "Square", "tier": "standard", "width": 1024, "height": 1024},
    "square-high": {"label": "High", "shape": "Square", "tier": "high", "width": 1280, "height": 1280},
    "portrait-draft": {"label": "Draft / Fast", "shape": "Portrait", "tier": "draft", "width": 448, "height": 768},
    "portrait-standard": {"label": "Standard", "shape": "Portrait", "tier": "standard", "width": 576, "height": 1024},
    "portrait-high": {"label": "High", "shape": "Portrait", "tier": "high", "width": 768, "height": 1344},
    "portrait-large": {"label": "Tall high-res", "shape": "Portrait", "tier": "large", "width": 1024, "height": 1792},
}


def image_preset_catalogue() -> list[dict]:
    return [{"id": preset_id, **settings} for preset_id, settings in IMAGE_PRESETS.items()]


def validate_image_dimensions(width, height) -> tuple[int, int]:
    try:
        width, height = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise ValueError("Custom width and height must be whole numbers") from exc
    if width < IMAGE_MIN_DIMENSION or height < IMAGE_MIN_DIMENSION:
        raise ValueError(f"Custom dimensions must be at least {IMAGE_MIN_DIMENSION}×{IMAGE_MIN_DIMENSION}")
    if width > IMAGE_MAX_DIMENSION or height > IMAGE_MAX_DIMENSION:
        raise ValueError(f"No custom dimension may exceed {IMAGE_MAX_DIMENSION} pixels")
    if width % IMAGE_ALIGNMENT or height % IMAGE_ALIGNMENT:
        raise ValueError(f"Custom dimensions must be multiples of {IMAGE_ALIGNMENT}")
    if width * height > IMAGE_MAX_PIXELS:
        raise ValueError(f"Custom size exceeds the tested {IMAGE_MAX_PIXELS:,}-pixel safety envelope")
    return width, height


def resolve_image_dimensions(preset_id: str, custom_width=None, custom_height=None) -> tuple[int, int]:
    preset_id = str(preset_id or DEFAULT_IMAGE_PRESET)
    if preset_id == "custom":
        return validate_image_dimensions(custom_width, custom_height)
    preset = IMAGE_PRESETS.get(preset_id)
    if not preset:
        raise ValueError("Unknown image resolution preset")
    return preset["width"], preset["height"]


def preset_for_dimensions(width: int, height: int) -> str:
    for preset_id, preset in IMAGE_PRESETS.items():
        if preset["width"] == int(width) and preset["height"] == int(height):
            return preset_id
    return "custom"
