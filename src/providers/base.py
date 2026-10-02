"""Provider-neutral interfaces and error types.

Everything above the provider layer depends only on this module. A provider
implementation must translate its SDK's exceptions into these error types so
the retry layer can tell transient failures from permanent ones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.infrastructure.retry import TransientError


class ProviderError(Exception):
    """Base class for all provider failures."""


class TransientProviderError(ProviderError, TransientError):
    """Rate limit, timeout, network or server error - worth retrying."""


class PermanentProviderError(ProviderError):
    """Bad request, invalid API key, unknown model... - retrying will not help."""


class ContentRejectedError(PermanentProviderError):
    """The provider refused the request or response (e.g. a safety filter)."""


class InvalidResponseError(ProviderError, TransientError):
    """The response was malformed (bad JSON, failed validation, missing data).

    Treated as transient: generative models often succeed on a second attempt.
    """


class TextGenerationProvider(ABC):
    @abstractmethod
    def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        """Generate JSON matching ``response_model``'s schema and return it as a dict.

        Implementations constrain the output to the schema where supported but
        return raw data; validating it is the caller's job.
        """


@dataclass(frozen=True)
class ImageData:
    data: bytes
    mime_type: str


class ImageGenerationProvider(ABC):
    @abstractmethod
    def generate_image(
        self,
        *,
        prompt: str,
        reference_images: Sequence[ImageData] = (),
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> ImageData:
        """Generate one image from ``prompt``.

        ``reference_images`` are earlier illustrations the model should match
        for character and style consistency. ``aspect_ratio`` (e.g. "1:1") and
        ``image_size`` (e.g. "1K") are hints; ``None`` means provider default.
        """
