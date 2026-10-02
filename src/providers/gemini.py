"""Gemini implementation of the provider interfaces.

This is the only module in the application that imports the Google GenAI SDK.
It builds requests, parses responses, and maps SDK/network exceptions onto
the provider-neutral errors in ``providers.base``. It never retries itself
(the SDK's own retries are left disabled) - retry policy lives in the caller.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from src.providers.base import (
    ContentRejectedError,
    ImageData,
    ImageGenerationProvider,
    InvalidResponseError,
    PermanentProviderError,
    ProviderError,
    TextGenerationProvider,
    TransientProviderError,
)

logger = logging.getLogger(__name__)

# HTTP status codes worth retrying: timeout, rate limit, server-side errors.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

_REJECTED_FINISH_REASONS = frozenset(
    {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    }
)


class GeminiProvider(TextGenerationProvider, ImageGenerationProvider):
    def __init__(
        self,
        *,
        api_key: str,
        text_model: str,
        image_model: str,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        """``client`` may be injected for testing; otherwise a real SDK client is built."""
        self._text_model = text_model
        self._image_model = image_model
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    # --- text ---------------------------------------------------------------

    def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
            # No tools are used; disabling also silences an SDK warning per call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        logger.debug("Gemini text request to %s (%d prompt chars)", self._text_model, len(prompt))
        response = self._call(
            lambda: self._client.models.generate_content(
                model=self._text_model, contents=prompt, config=config
            )
        )
        text = _response_text(response)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(f"Gemini returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise InvalidResponseError(f"expected a JSON object, got {type(data).__name__}")
        return data

    # --- images -------------------------------------------------------------

    def generate_image(
        self,
        *,
        prompt: str,
        reference_images: Sequence[ImageData] = (),
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> ImageData:
        contents: list[Any] = [
            types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
            for image in reference_images
        ]
        contents.append(prompt)
        image_config = None
        if aspect_ratio or image_size:
            image_config = types.ImageConfig(aspect_ratio=aspect_ratio, image_size=image_size)
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=image_config,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        logger.debug(
            "Gemini image request to %s (%d prompt chars, %d reference image(s))",
            self._image_model,
            len(prompt),
            len(reference_images),
        )
        response = self._call(
            lambda: self._client.models.generate_content(
                model=self._image_model, contents=contents, config=config
            )
        )
        return _response_image(response)

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _call(request):
        """Run an SDK request, translating failures into provider errors."""
        try:
            return request()
        except genai_errors.APIError as exc:
            raise _translate_api_error(exc) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientProviderError(f"network error: {type(exc).__name__}: {exc}") from exc


def _translate_api_error(exc: genai_errors.APIError) -> ProviderError:
    message = f"Gemini API error {exc.code} {exc.status or ''}: {exc.message or exc}".strip()
    if exc.code in _TRANSIENT_STATUS_CODES:
        return TransientProviderError(message, retry_after=_retry_delay_seconds(exc.details))
    if exc.code in (401, 403):
        message += " (check that GEMINI_API_KEY is correct and has access to this model)"
    elif exc.code == 404:
        message += " (check the model names in your config file)"
    return PermanentProviderError(message)


def _retry_delay_seconds(details: Any) -> float | None:
    """Extract the server's suggested wait from a google.rpc.RetryInfo detail."""
    try:
        entries = details.get("error", details).get("details", [])
    except AttributeError:
        return None
    for entry in entries if isinstance(entries, list) else []:
        delay = entry.get("retryDelay") if isinstance(entry, dict) else None
        match = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(delay or ""))
        if match:
            return float(match.group(1))
    return None


def _first_candidate(response: Any) -> tuple[Any, str | None]:
    """Return the first candidate and its finish reason, raising on blocks/refusals."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise ContentRejectedError(f"Gemini blocked the prompt: {feedback.block_reason}")

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise InvalidResponseError("Gemini returned no candidates")

    reason = _enum_name(getattr(candidates[0], "finish_reason", None))
    if reason in _REJECTED_FINISH_REASONS:
        raise ContentRejectedError(f"Gemini refused to generate content: {reason}")
    if reason == "MAX_TOKENS":
        raise InvalidResponseError("Gemini response was cut off (MAX_TOKENS)")
    return candidates[0], reason


def _response_text(response: Any) -> str:
    """Return the text of the first candidate, or raise an explanatory error."""
    _, reason = _first_candidate(response)
    text = response.text
    if not text or not text.strip():
        raise InvalidResponseError(f"Gemini returned an empty response (finish reason: {reason})")
    return text


def _response_image(response: Any) -> ImageData:
    """Return the first inline image of the first candidate."""
    candidate, reason = _first_candidate(response)
    parts = getattr(getattr(candidate, "content", None), "parts", None) or []
    for part in parts:
        blob = getattr(part, "inline_data", None)
        if blob is not None and blob.data and (blob.mime_type or "").startswith("image/"):
            return ImageData(data=blob.data, mime_type=blob.mime_type)
    raise InvalidResponseError(f"Gemini returned no image (finish reason: {reason})")


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", None) or str(value)
