"""Produces the illustration for one storybook page.

Composes the final image prompt from the style specification, character bible
and page, calls an image provider, and returns verified PNG bytes. Where the
image is stored is the caller's decision.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.models.character_bible import CharacterBible
from src.models.story import Storybook, StoryPage
from src.providers.base import ImageData, ImageGenerationProvider, InvalidResponseError
from src.utils.images import ImageDecodeError, to_png

logger = logging.getLogger(__name__)


def build_image_prompt(
    *,
    style_spec: str,
    bible: CharacterBible,
    page: StoryPage,
    total_pages: int,
    has_reference_images: bool = False,
) -> str:
    sections = [
        "Create one illustration for a page of a children's picture book.",
        f"STYLE SPECIFICATION\n===================\n{style_spec.strip()}",
        "CHARACTER BIBLE\n===============\n"
        f"Book: {bible.title}\n"
        "Every character must look exactly as described here on every page.\n\n"
        f"{bible.to_prompt_text()}",
        "CURRENT PAGE\n============\n"
        f"Page {page.page_number} of {total_pages}.\n"
        f"Story text on this page (for context; printed separately, do not draw it):\n"
        f"{page.text}",
        f"PAGE IMAGE PROMPT\n=================\n{page.image_prompt}",
    ]
    if has_reference_images:
        sections.append(
            "The attached image(s) are earlier illustrations from this same book. "
            "Match their art style, palette and character designs exactly, "
            "but draw the new scene described above."
        )
    return "\n\n".join(sections)


class ImageGenerator:
    def __init__(
        self,
        provider: ImageGenerationProvider,
        style_spec: str,
        *,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> None:
        self._provider = provider
        self._style_spec = style_spec
        self._aspect_ratio = aspect_ratio
        self._image_size = image_size

    def generate_page_image(
        self,
        storybook: Storybook,
        page_number: int,
        bible: CharacterBible,
        reference_images: Sequence[bytes] = (),
    ) -> bytes:
        """Return PNG bytes for ``page_number``. ``reference_images`` are PNG bytes."""
        page = storybook.page(page_number)
        prompt = build_image_prompt(
            style_spec=self._style_spec,
            bible=bible,
            page=page,
            total_pages=len(storybook.pages),
            has_reference_images=bool(reference_images),
        )
        image = self._provider.generate_image(
            prompt=prompt,
            reference_images=[ImageData(data=d, mime_type="image/png") for d in reference_images],
            aspect_ratio=self._aspect_ratio,
            image_size=self._image_size,
        )
        try:
            png = to_png(image.data)
        except ImageDecodeError as exc:
            raise InvalidResponseError(f"page {page_number} image is unreadable: {exc}") from exc
        logger.debug("Page %d image: %d bytes PNG", page_number, len(png))
        return png
