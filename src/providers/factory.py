"""Builds the configured providers. The only place that maps a provider name to a class."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import ProviderConfig
from src.providers.base import ImageGenerationProvider, TextGenerationProvider


class UnknownProviderError(ValueError):
    pass


@dataclass(frozen=True)
class Providers:
    """Text and image providers are separate so they could come from different vendors."""

    text: TextGenerationProvider
    image: ImageGenerationProvider


def create_providers(config: ProviderConfig, api_key: str) -> Providers:
    if config.name == "gemini":
        # Imported lazily so other providers never need the Gemini SDK installed.
        from src.providers.gemini import GeminiProvider

        gemini = GeminiProvider(
            api_key=api_key,
            text_model=config.text_model,
            image_model=config.image_model,
            timeout_seconds=config.request_timeout_seconds,
        )
        return Providers(text=gemini, image=gemini)
    raise UnknownProviderError(f"Unknown provider {config.name!r} in configuration")
