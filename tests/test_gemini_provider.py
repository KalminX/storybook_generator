"""Gemini provider tests.

These run the real google-genai SDK against an in-process httpx mock transport,
so request serialisation and error handling are exercised with no network.
"""

import base64
import json

import httpx
import pytest
from google import genai
from google.genai import types

from src.models.story import Storybook
from src.providers.base import (
    ContentRejectedError,
    ImageData,
    InvalidResponseError,
    PermanentProviderError,
    TransientProviderError,
)
from src.providers.gemini import GeminiProvider
from tests.fakes import make_image_bytes, sample_story_data

FAKE_KEY = "test-key-not-real"


def text_response(text: str, finish_reason: str = "STOP") -> dict:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish_reason}
        ]
    }


def error_response(code: int, status: str, details: list | None = None) -> httpx.Response:
    body = {"error": {"code": code, "message": "something went wrong", "status": status}}
    if details:
        body["error"]["details"] = details
    return httpx.Response(code, json=body)


def make_provider(handler) -> tuple[GeminiProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result = handler(request)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    client = genai.Client(
        api_key=FAKE_KEY,
        http_options=types.HttpOptions(
            client_args={"transport": httpx.MockTransport(recording_handler)}
        ),
    )
    provider = GeminiProvider(
        api_key=FAKE_KEY,
        text_model="text-model-x",
        image_model="image-model-x",
        timeout_seconds=30,
        client=client,
    )
    return provider, requests


def generate(provider: GeminiProvider) -> dict:
    return provider.generate_structured(
        system_instruction="be an author", prompt="a fox story", response_model=Storybook
    )


def test_successful_structured_request():
    story = sample_story_data()
    provider, requests = make_provider(lambda _: text_response(json.dumps(story)))

    assert generate(provider) == story

    request = requests[0]
    assert request.url.path.endswith("/models/text-model-x:generateContent")
    assert FAKE_KEY not in str(request.url)  # key travels in a header
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "be an author"
    assert body["contents"][0]["parts"][0]["text"] == "a fox story"
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert set(config["responseSchema"]["properties"]) == {"title", "characters", "pages"}


def test_rate_limit_is_transient_with_retry_after():
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]
    provider, _ = make_provider(lambda _: error_response(429, "RESOURCE_EXHAUSTED", details))
    with pytest.raises(TransientProviderError) as info:
        generate(provider)
    assert info.value.retry_after == 37


@pytest.mark.parametrize("code, status", [(500, "INTERNAL"), (503, "UNAVAILABLE"), (504, "DEADLINE_EXCEEDED")])
def test_server_errors_are_transient(code, status):
    provider, _ = make_provider(lambda _: error_response(code, status))
    with pytest.raises(TransientProviderError):
        generate(provider)


@pytest.mark.parametrize(
    "code, status, hint",
    [
        (400, "INVALID_ARGUMENT", "400"),
        (401, "UNAUTHENTICATED", "GEMINI_API_KEY"),
        (403, "PERMISSION_DENIED", "GEMINI_API_KEY"),
        (404, "NOT_FOUND", "model names"),
    ],
)
def test_client_errors_are_permanent(code, status, hint):
    provider, _ = make_provider(lambda _: error_response(code, status))
    with pytest.raises(PermanentProviderError, match=hint) as info:
        generate(provider)
    assert not isinstance(info.value, TransientProviderError)


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_network_errors_are_transient(exc):
    def handler(request):
        raise exc

    provider, _ = make_provider(handler)
    with pytest.raises(TransientProviderError, match="network error"):
        generate(provider)


def test_blocked_prompt_is_rejected():
    provider, _ = make_provider(lambda _: {"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ContentRejectedError, match="blocked"):
        generate(provider)


def test_safety_finish_reason_is_rejected():
    provider, _ = make_provider(lambda _: text_response("", finish_reason="SAFETY"))
    with pytest.raises(ContentRejectedError, match="SAFETY"):
        generate(provider)


@pytest.mark.parametrize(
    "response, match",
    [
        (text_response("{not json"), "invalid JSON"),
        (text_response("[1, 2]"), "JSON object"),
        (text_response('{"title": "cut', finish_reason="MAX_TOKENS"), "MAX_TOKENS"),
        (text_response("   "), "empty"),
        ({"candidates": []}, "no candidates"),
    ],
)
def test_malformed_responses_are_retryable_invalid_response(response, match):
    provider, _ = make_provider(lambda _: response)
    with pytest.raises(InvalidResponseError, match=match):
        generate(provider)


# --- images -------------------------------------------------------------------


def image_response(data: bytes, mime: str = "image/png", finish_reason: str = "STOP") -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "Here is your picture"},
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}},
                    ],
                },
                "finishReason": finish_reason,
            }
        ]
    }


def test_image_request_and_response():
    png = make_image_bytes()
    provider, requests = make_provider(lambda _: image_response(png))
    reference = make_image_bytes("blue")

    image = provider.generate_image(
        prompt="draw a fox",
        reference_images=[ImageData(data=reference, mime_type="image/png")],
        aspect_ratio="3:4",
        image_size="2K",
    )

    assert image == ImageData(data=png, mime_type="image/png")
    request = requests[0]
    assert request.url.path.endswith("/models/image-model-x:generateContent")
    body = json.loads(request.content)
    parts = [part for content in body["contents"] for part in content["parts"]]
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == reference
    assert parts[-1]["text"] == "draw a fox"
    config = body["generationConfig"]
    assert config["responseModalities"] == ["IMAGE"]
    assert config["imageConfig"] == {"aspectRatio": "3:4", "imageSize": "2K"}


def test_image_request_without_optional_settings():
    provider, requests = make_provider(lambda _: image_response(make_image_bytes()))
    provider.generate_image(prompt="draw a fox")
    body = json.loads(requests[0].content)
    assert "imageConfig" not in body["generationConfig"]
    assert len(body["contents"][0]["parts"]) == 1


@pytest.mark.parametrize("reason", ["IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT"])
def test_image_safety_is_rejected(reason):
    provider, _ = make_provider(lambda _: text_response("no", finish_reason=reason))
    with pytest.raises(ContentRejectedError, match=reason):
        provider.generate_image(prompt="x")


def test_text_only_image_response_is_retryable():
    provider, _ = make_provider(lambda _: text_response("I cannot draw that", finish_reason="NO_IMAGE"))
    with pytest.raises(InvalidResponseError, match="no image"):
        provider.generate_image(prompt="x")


def test_image_rate_limit_is_transient():
    provider, _ = make_provider(lambda _: error_response(429, "RESOURCE_EXHAUSTED"))
    with pytest.raises(TransientProviderError):
        provider.generate_image(prompt="x")
