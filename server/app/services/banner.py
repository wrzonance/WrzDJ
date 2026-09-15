"""Banner image processing service.

Handles upload validation, resizing, WebP conversion, desaturation for kiosk,
and dominant color extraction.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import UploadFile
from PIL import Image, ImageEnhance, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.models.event import Event

settings = get_settings()

# Guard against decompression bombs (default is 178M pixels)
Image.MAX_IMAGE_PIXELS = 25_000_000

ALLOWED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def _get_banners_dir() -> Path:
    """Return banners directory, creating it if needed."""
    banners_dir = Path(settings.resolved_uploads_dir) / "banners"
    banners_dir.mkdir(parents=True, exist_ok=True)
    return banners_dir


def _extract_dominant_colors(img: Image.Image, num_colors: int = 3) -> list[str]:
    """Extract dominant colors from an image using quantization.

    Returns a list of hex color strings like ['#1a2b3c', '#4d5e6f', '#789abc'].
    """
    # Resize small for fast color analysis
    small = img.copy().resize((64, 64), Image.LANCZOS)
    if small.mode != "RGB":
        small = small.convert("RGB")

    # Quantize to find dominant colors
    quantized = small.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    if not palette:
        return ["#1a1a2e", "#16213e", "#0f3460"]

    # Count pixels per color to sort by dominance
    color_counts: dict[int, int] = {}
    for pixel in quantized.getdata():
        color_counts[pixel] = color_counts.get(pixel, 0) + 1

    # Sort by frequency (most common first)
    sorted_indices = sorted(color_counts.keys(), key=lambda i: color_counts[i], reverse=True)

    colors = []
    for idx in sorted_indices[:num_colors]:
        r = palette[idx * 3]
        g = palette[idx * 3 + 1]
        b = palette[idx * 3 + 2]
        # Darken colors for use as background (multiply by 0.4 to keep dark theme)
        r = int(r * 0.4)
        g = int(g * 0.4)
        b = int(b * 0.4)
        colors.append(f"#{r:02x}{g:02x}{b:02x}")

    # Pad with defaults if fewer colors extracted
    defaults = ["#1a1a2e", "#16213e", "#0f3460"]
    while len(colors) < num_colors:
        colors.append(defaults[len(colors) % len(defaults)])

    return colors


def _create_kiosk_variant(
    img: Image.Image, fade_color: tuple[int, int, int] | None = None
) -> Image.Image:
    """Create a desaturated kiosk variant with a baked-in bottom fade.

    Reduces saturation to ~40%, darkens slightly, and composites a gradient fade
    into the bottom 60% of the image so it blends into the kiosk background color.
    The fade is baked into the pixels — no browser alpha compositing needed (which
    fails on Raspberry Pi Chromium under Wayland/Cage).

    Args:
        img: Source image (RGB).
        fade_color: RGB tuple for the fade target (typically the first dominant color).
            If None, defaults to the dark theme background.
    """
    kiosk = img.copy()
    if kiosk.mode != "RGB":
        kiosk = kiosk.convert("RGB")

    # Reduce saturation to 40%
    enhancer = ImageEnhance.Color(kiosk)
    kiosk = enhancer.enhance(0.4)

    # Slightly reduce brightness
    enhancer = ImageEnhance.Brightness(kiosk)
    kiosk = enhancer.enhance(0.8)

    # Bake gradient fade into the image pixels
    bg_color = fade_color or (26, 26, 46)
    w, h = kiosk.size
    fade_start = int(h * 0.4)  # Top 40% fully visible, bottom 60% fades out

    # Create alpha mask: 255 (opaque image) at top → 0 (show background) at bottom
    mask = Image.new("L", (w, h), 255)
    for y in range(fade_start, h):
        alpha = int(255 * (1.0 - (y - fade_start) / (h - fade_start)))
        mask.paste(alpha, (0, y, w, y + 1))

    # Composite: kiosk image over solid background using the mask
    bg = Image.new("RGB", (w, h), bg_color)
    result = Image.composite(kiosk, bg, mask)

    return result


def process_banner_upload(file: UploadFile, event_code: str) -> tuple[str, str, list[str]]:
    """Process an uploaded banner image.

    Validates, resizes to 1920x480, converts to WebP, creates a desaturated kiosk
    variant, and extracts dominant colors.

    Args:
        file: The uploaded file.
        event_code: Event code for filename generation.

    Returns:
        Tuple of (banner_filename, kiosk_filename, dominant_colors).

    Raises:
        ValueError: If the file is invalid (wrong format, too large, corrupt).
    """
    max_size = settings.max_banner_size_mb * 1024 * 1024

    # Validate file size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > max_size:
        raise ValueError(f"File size exceeds {settings.max_banner_size_mb}MB limit.")
    if size == 0:
        raise ValueError("File is empty.")

    # Restrict Image.open() to the allowlisted plugins so no other decoder's
    # _open() ever sees the uploaded bytes (#583). Pillow raises
    # UnidentifiedImageError both for non-images and for formats outside the
    # allowlist, so the two cases share one message.
    try:
        img = Image.open(file.file, formats=sorted(ALLOWED_FORMATS))
    except UnidentifiedImageError:
        raise ValueError("Unsupported or corrupt image file. Use JPEG, PNG, GIF, or WebP.")
    except Exception:
        raise ValueError("Invalid or corrupt image file.")

    try:
        img.load()  # Force full read to catch truncated files
    except Exception:
        raise ValueError("Invalid or corrupt image file.")

    # Convert to RGB (WebP output, drop alpha)
    if img.mode in ("RGBA", "LA", "P", "PA"):
        background = Image.new("RGB", img.size, (26, 26, 46))  # Dark bg matching theme
        if img.mode == "P":
            img = img.convert("RGBA")
        if "A" in img.mode:
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Extract dominant colors before resizing (more accurate from full image)
    colors = _extract_dominant_colors(img)

    # Resize to target dimensions
    target_w = settings.banner_width
    target_h = settings.banner_height
    img = img.resize((target_w, target_h), Image.LANCZOS)

    # Generate filenames
    timestamp = int(time.time())
    base_name = f"{event_code.lower()}_{timestamp}"
    banner_filename = f"banners/{base_name}.webp"
    kiosk_filename = f"banners/{base_name}_kiosk.webp"

    banners_dir = _get_banners_dir()

    # Save main banner
    img.save(banners_dir / f"{base_name}.webp", "WEBP", quality=92)

    # Create and save kiosk variant (desaturated + baked gradient fade)
    # Parse first dominant color as RGB for the fade target
    fade_rgb = _hex_to_rgb(colors[0]) if colors else None
    kiosk_img = _create_kiosk_variant(img, fade_color=fade_rgb)
    kiosk_img.save(banners_dir / f"{base_name}_kiosk.webp", "WEBP", quality=92)

    return banner_filename, kiosk_filename, colors


def delete_banner_files(banner_filename: str | None) -> None:
    """Delete banner and kiosk variant files if they exist.

    Args:
        banner_filename: The main banner filename (e.g., 'banners/abc123_1234.webp').
            The kiosk variant is derived by adding '_kiosk' suffix.
    """
    if not banner_filename:
        return

    uploads_dir = Path(settings.resolved_uploads_dir).resolve()

    for filename in [banner_filename, _kiosk_filename(banner_filename)]:
        filepath = (uploads_dir / filename).resolve()
        # Ensure resolved path stays within uploads directory
        if not filepath.is_relative_to(uploads_dir):
            continue
        try:
            filepath.unlink(missing_ok=True)
        except OSError:
            pass  # nosec B110


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string like '#1a2b3c' to an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _kiosk_filename(banner_filename: str) -> str:
    """Derive the kiosk variant filename from the main banner filename."""
    stem = banner_filename.rsplit(".", 1)[0]
    return f"{stem}_kiosk.webp"


def save_banner_to_event(db: Session, event: Event, filename: str, colors: list[str]) -> None:
    """Persist banner metadata on an event and commit.

    Args:
        db: Database session.
        event: The event to update.
        filename: The banner filename (relative to uploads dir).
        colors: Dominant color hex strings extracted from the banner.
    """
    event.banner_filename = filename
    event.banner_colors = json.dumps(colors)
    db.commit()
    db.refresh(event)


def delete_banner_from_event(db: Session, event: Event) -> None:
    """Remove banner files from disk, clear DB fields, and commit.

    Args:
        db: Database session.
        event: The event whose banner should be removed.
    """
    delete_banner_files(event.banner_filename)
    event.banner_filename = None
    event.banner_colors = None
    db.commit()
    db.refresh(event)
