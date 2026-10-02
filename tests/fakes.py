"""In-memory fake providers so tests never call a real API."""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

from PIL import Image
from pydantic import BaseModel

from src.providers.base import ImageData, ImageGenerationProvider, TextGenerationProvider


def make_image_bytes(color: str = "red", size: tuple[int, int] = (8, 8), fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt)
    return out.getvalue()


def sample_story_data(pages: int = 3) -> dict[str, Any]:
    return {
        "title": "The Hidden Garden",
        "characters": [
            {
                "name": "Fern",
                "description": "A curious young fox",
                "appearance": "Small red fox with a white-tipped tail and green eyes",
                "clothing": "A yellow scarf",
            }
        ],
        "pages": [
            {
                "page_number": n,
                "text": f"Page {n} text.",
                "image_prompt": f"Fern exploring, scene {n}.",
            }
            for n in range(1, pages + 1)
        ],
    }


class FakeTextProvider(TextGenerationProvider):
    """Returns queued responses in order; an Exception in the queue is raised instead."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses) or [sample_story_data()]
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self, *, system_instruction: str, prompt: str, response_model: type[BaseModel]
    ) -> dict[str, Any]:
        self.calls.append(
            {"system_instruction": system_instruction, "prompt": prompt, "model": response_model}
        )
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


class FakeImageProvider(ImageGenerationProvider):
    """Returns a small real PNG per call.

    Queued ``failures`` are raised by the first calls; ``fail_at`` maps a
    1-based call number to an exception raised by that particular call.
    """

    def __init__(
        self,
        *failures: BaseException,
        image: ImageData | None = None,
        fail_at: dict[int, BaseException] | None = None,
    ) -> None:
        self.failures = list(failures)
        self.fail_at = dict(fail_at or {})
        self.image = image or ImageData(data=make_image_bytes(), mime_type="image/png")
        self.calls: list[dict[str, Any]] = []

    def generate_image(
        self,
        *,
        prompt: str,
        reference_images: Sequence[ImageData] = (),
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> ImageData:
        self.calls.append(
            {
                "prompt": prompt,
                "reference_images": list(reference_images),
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            }
        )
        if len(self.calls) in self.fail_at:
            raise self.fail_at[len(self.calls)]
        if self.failures:
            raise self.failures.pop(0)
        return self.image
