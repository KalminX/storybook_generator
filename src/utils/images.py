"""Image format helpers (Pillow). Provider-independent."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

PNG_MIME = "image/png"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageDecodeError(ValueError):
    """The bytes are not a readable image."""


def to_png(data: bytes) -> bytes:
    """Return ``data`` as PNG bytes, verifying it decodes. PNG input is returned as-is."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if data.startswith(_PNG_SIGNATURE):
                return data
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageDecodeError(f"not a readable image: {exc}") from exc
