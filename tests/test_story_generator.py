import pytest

from src.generation.story_generator import StoryGenerator, build_story_prompt
from src.infrastructure.retry import RetryPolicy, retry_call
from src.models.story import Storybook
from src.providers.base import InvalidResponseError, PermanentProviderError
from tests.fakes import FakeTextProvider, sample_story_data

STYLE = "# Style\nWatercolor. Ages 3-6. Exactly 3 pages."


def test_prompt_contains_style_spec_and_concept_verbatim():
    request = build_story_prompt("  A fox finds a garden. ", STYLE)
    assert STYLE.strip() in request.prompt
    assert "A fox finds a garden." in request.prompt
    assert request.prompt.index("STYLE SPECIFICATION") < request.prompt.index("STORY CONCEPT")
    assert request.system_instruction


def test_generate_returns_validated_storybook():
    provider = FakeTextProvider(sample_story_data(pages=3))
    book = StoryGenerator(provider, STYLE).generate("A fox finds a garden.")
    assert isinstance(book, Storybook)
    assert [p.page_number for p in book.pages] == [1, 2, 3]
    call = provider.calls[0]
    assert call["model"] is Storybook
    assert "A fox finds a garden." in call["prompt"]


def test_invalid_output_raises_retryable_error():
    bad = sample_story_data()
    bad["pages"][1]["page_number"] = 7
    with pytest.raises(InvalidResponseError, match="page numbers"):
        StoryGenerator(FakeTextProvider(bad), STYLE).generate("x")


def test_invalid_output_then_valid_output_succeeds_under_retry():
    bad = sample_story_data()
    del bad["title"]
    provider = FakeTextProvider(bad, sample_story_data())
    generator = StoryGenerator(provider, STYLE)
    book = retry_call(
        lambda: generator.generate("x"),
        policy=RetryPolicy(max_attempts=3, initial_delay=0, max_delay=0),
        description="story",
        sleep=lambda _: None,
    )
    assert book.title == "The Hidden Garden"
    assert len(provider.calls) == 2


def test_provider_errors_propagate_unchanged():
    error = PermanentProviderError("invalid key")
    with pytest.raises(PermanentProviderError) as info:
        StoryGenerator(FakeTextProvider(error), STYLE).generate("x")
    assert info.value is error


def test_supports_storybook_subclass_with_extra_metadata():
    class ExtendedStorybook(Storybook):
        reading_level: str

    data = {**sample_story_data(), "reading_level": "Ages 3-5"}
    provider = FakeTextProvider(data)
    book = StoryGenerator(provider, STYLE, storybook_model=ExtendedStorybook).generate("x")
    assert book.reading_level == "Ages 3-5"
    assert provider.calls[0]["model"] is ExtendedStorybook


def test_from_style_file(tmp_path):
    style_file = tmp_path / "style.md"
    style_file.write_text(STYLE)
    provider = FakeTextProvider()
    StoryGenerator.from_style_file(provider, style_file).generate("x")
    assert STYLE in provider.calls[0]["prompt"]
