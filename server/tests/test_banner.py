"""Tests for banner image processing service."""

import io
import json
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from PIL import Image

from app.services.banner import (
    _create_kiosk_variant,
    _extract_dominant_colors,
    _kiosk_filename,
    delete_banner_files,
    process_banner_upload,
    save_banner_to_event,
)


def _make_upload_file(img: Image.Image, fmt: str = "PNG", filename: str = "test.png") -> UploadFile:
    """Create an UploadFile from a Pillow Image."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return UploadFile(file=buf, filename=filename)


def _make_rgb_image(width: int = 100, height: int = 50, color: tuple = (255, 0, 0)) -> Image.Image:
    """Create a simple solid-color RGB image."""
    return Image.new("RGB", (width, height), color)


class TestExtractDominantColors:
    def test_returns_three_hex_strings(self):
        img = _make_rgb_image(color=(200, 100, 50))
        colors = _extract_dominant_colors(img, num_colors=3)
        assert len(colors) == 3
        for c in colors:
            assert c.startswith("#")
            assert len(c) == 7  # #rrggbb

    def test_colors_are_darkened(self):
        # A bright red image should yield a darkened red in the output
        img = _make_rgb_image(color=(255, 0, 0))
        colors = _extract_dominant_colors(img, num_colors=1)
        # 255 * 0.4 = 102 -> #660000
        r = int(colors[0][1:3], 16)
        assert r <= 110  # Roughly 255*0.4 with quantization variance

    def test_pads_with_defaults_for_single_color_image(self):
        # A solid-color image may only produce 1 quantized color
        img = _make_rgb_image(color=(128, 128, 128))
        colors = _extract_dominant_colors(img, num_colors=3)
        assert len(colors) == 3


class TestCreateKioskVariant:
    def test_returns_rgb_image(self):
        img = _make_rgb_image()
        kiosk = _create_kiosk_variant(img)
        assert kiosk.mode == "RGB"
        assert kiosk.size == img.size

    def test_kiosk_is_darker_than_original(self):
        img = _make_rgb_image(color=(200, 200, 200))
        kiosk = _create_kiosk_variant(img)
        # Sample center pixel
        orig_pixel = img.getpixel((50, 25))
        kiosk_pixel = kiosk.getpixel((50, 25))
        # Brightness reduced to 0.8, so kiosk pixel values should be lower
        assert kiosk_pixel[0] < orig_pixel[0]


class TestKioskFilename:
    def test_derives_kiosk_filename(self):
        assert _kiosk_filename("banners/abc_123.webp") == "banners/abc_123_kiosk.webp"

    def test_handles_nested_path(self):
        assert _kiosk_filename("a/b/c.webp") == "a/b/c_kiosk.webp"


class TestProcessBannerUpload:
    @patch("app.services.banner._get_banners_dir")
    def test_valid_png_upload(self, mock_dir, tmp_path):
        mock_dir.return_value = tmp_path
        img = _make_rgb_image(200, 100)
        upload = _make_upload_file(img, "PNG")

        banner_fn, kiosk_fn, colors = process_banner_upload(upload, "TEST01")

        assert banner_fn.startswith("banners/test01_")
        assert banner_fn.endswith(".webp")
        assert kiosk_fn.endswith("_kiosk.webp")
        assert len(colors) == 3
        # Files should exist on disk
        base = banner_fn.split("/")[-1]
        assert (tmp_path / base).exists()

    @patch("app.services.banner._get_banners_dir")
    def test_valid_jpeg_upload(self, mock_dir, tmp_path):
        mock_dir.return_value = tmp_path
        img = _make_rgb_image(200, 100)
        upload = _make_upload_file(img, "JPEG", "test.jpg")

        banner_fn, _, _ = process_banner_upload(upload, "EVT")
        assert banner_fn.startswith("banners/evt_")

    def test_rejects_empty_file(self):
        buf = io.BytesIO(b"")
        upload = UploadFile(file=buf, filename="empty.png")
        with pytest.raises(ValueError, match="empty"):
            process_banner_upload(upload, "TEST01")

    def test_rejects_oversized_file(self):
        # Create a file that exceeds 5MB
        buf = io.BytesIO(b"x" * (6 * 1024 * 1024))
        upload = UploadFile(file=buf, filename="big.png")
        with pytest.raises(ValueError, match="exceeds"):
            process_banner_upload(upload, "TEST01")

    def test_rejects_corrupt_file(self):
        buf = io.BytesIO(b"not an image at all")
        upload = UploadFile(file=buf, filename="corrupt.png")
        with pytest.raises(ValueError, match="Invalid or corrupt"):
            process_banner_upload(upload, "TEST01")

    def test_rejects_unsupported_format(self):
        # BMP is not in ALLOWED_FORMATS
        img = _make_rgb_image()
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        buf.seek(0)
        upload = UploadFile(file=buf, filename="test.bmp")
        with pytest.raises(ValueError, match="Unsupported"):
            process_banner_upload(upload, "TEST01")

    @patch("app.services.banner._get_banners_dir")
    def test_handles_rgba_image(self, mock_dir, tmp_path):
        mock_dir.return_value = tmp_path
        img = Image.new("RGBA", (100, 50), (255, 0, 0, 128))
        upload = _make_upload_file(img, "PNG")

        banner_fn, _, _ = process_banner_upload(upload, "TEST01")
        assert banner_fn.endswith(".webp")


class TestDeleteBannerFiles:
    def test_deletes_both_variants(self, tmp_path):
        # Create main and kiosk files
        (tmp_path / "banners").mkdir()
        main_file = tmp_path / "banners" / "test_123.webp"
        kiosk_file = tmp_path / "banners" / "test_123_kiosk.webp"
        main_file.write_bytes(b"fake")
        kiosk_file.write_bytes(b"fake")

        with patch("app.services.banner.settings") as mock_settings:
            mock_settings.resolved_uploads_dir = str(tmp_path)
            delete_banner_files("banners/test_123.webp")

        assert not main_file.exists()
        assert not kiosk_file.exists()

    def test_noop_on_none(self):
        # Should not raise
        delete_banner_files(None)

    def test_path_traversal_blocked(self, tmp_path):
        # Attempting to delete outside uploads dir should be silently skipped
        outside_file = tmp_path / "secret.txt"
        outside_file.write_bytes(b"secret")

        with patch("app.services.banner.settings") as mock_settings:
            mock_settings.resolved_uploads_dir = str(tmp_path / "uploads")
            delete_banner_files("../../secret.txt")

        assert outside_file.exists()  # File must NOT be deleted


class TestSaveBannerToEvent:
    def test_persists_banner_metadata(self, db):
        from app.models.event import Event
        from app.models.user import User
        from app.services.auth import get_password_hash

        user = User(username="banneruser", password_hash=get_password_hash("pw"), role="dj")
        db.add(user)
        db.commit()
        db.refresh(user)

        from datetime import timedelta

        from app.core.time import utcnow

        event = Event(
            code="BNR01",
            join_code="SJZEX2",
            name="Banner Test",
            created_by_user_id=user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        save_banner_to_event(db, event, "banners/bnr01_123.webp", ["#aa0000", "#00bb00", "#0000cc"])

        assert event.banner_filename == "banners/bnr01_123.webp"
        assert json.loads(event.banner_colors) == ["#aa0000", "#00bb00", "#0000cc"]
