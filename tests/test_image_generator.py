import pytest

from src.generation.character_bible import build_character_bible
from src.generation.image_generator import ImageGenerator, build_image_prompt
from src.models.story import Storybook
from src.providers.base import ContentRejectedError, ImageData, InvalidResponseError
from src.utils.images import ImageDecodeError, to_png
from tests.fakes import FakeImageProvider, make_image_bytes, sample_story_data

STYLE = "# Style\nSoft watercolor."
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def book() -> Storybook:
    return Storybook.model_validate(sample_story_data(pages=3))


@pytest.fixture
def bible(book):
    return build_character_bible(book)


class TestCharacterBible:
    def test_built_from_story_characters(self, book, bible):
        assert bible.title == book.title
        assert [c.name for c in bible.characters] == ["Fern"]
        assert bible.characters[0].appearance == book.characters[0].appearance

    def test_prompt_text_includes_all_visual_details(self, bible):
        text = bible.to_prompt_text()
        assert "Fern" in text
        assert "white-tipped tail" in text
        assert "Always wears: A yellow scarf" in text

    def test_forbids_invented_clothing_when_none(self):
        data = sample_story_data()
        data["characters"][0]["clothing"] = None
        text = build_character_bible(Storybook.model_validate(data)).to_prompt_text()
        assert "Always wears" not in text
        assert "do not add clothing or accessories" in text

    def test_is_deterministic_and_serialisable(self, book, bible):
        assert build_character_bible(book) == bible
        assert type(bible).model_validate_json(bible.model_dump_json()) == bible


class TestImagePrompt:
    def test_sections_appear_in_required_order(self, book, bible):
        prompt = build_image_prompt(
            style_spec=STYLE, bible=bible, page=book.page(2), total_pages=3
        )
        order = ["STYLE SPECIFICATION", "CHARACTER BIBLE", "CURRENT PAGE", "PAGE IMAGE PROMPT"]
        positions = [prompt.index(heading) for heading in order]
        assert positions == sorted(positions)
        assert "Soft watercolor." in prompt
        assert "white-tipped tail" in prompt
        assert "Page 2 of 3" in prompt
        assert "Page 2 text." in prompt
        assert "Fern exploring, scene 2." in prompt
        assert "attached image" not in prompt

    def test_mentions_references_only_when_present(self, book, bible):
        prompt = build_image_prompt(
            style_spec=STYLE,
            bible=bible,
            page=book.page(1),
            total_pages=3,
            has_reference_images=True,
        )
        assert "attached image" in prompt


class TestImageGenerator:
    def test_returns_png_and_passes_settings(self, book, bible):
        provider = FakeImageProvider()
        generator = ImageGenerator(provider, STYLE, aspect_ratio="3:4", image_size="2K")
        png = generator.generate_page_image(book, 2, bible)
        assert png.startswith(PNG_SIGNATURE)
        call = provider.calls[0]
        assert call["aspect_ratio"] == "3:4"
        assert call["image_size"] == "2K"
        assert call["reference_images"] == []
        assert "Page 2 of 3" in call["prompt"]

    def test_passes_reference_images(self, book, bible):
        provider = FakeImageProvider()
        reference = make_image_bytes("blue")
        ImageGenerator(provider, STYLE).generate_page_image(book, 3, bible, [reference])
        refs = provider.calls[0]["reference_images"]
        assert refs == [ImageData(data=reference, mime_type="image/png")]
        assert "attached image" in provider.calls[0]["prompt"]

    def test_converts_jpeg_to_png(self, book, bible):
        jpeg = ImageData(data=make_image_bytes(fmt="JPEG"), mime_type="image/jpeg")
        png = ImageGenerator(FakeImageProvider(image=jpeg), STYLE).generate_page_image(
            book, 1, bible
        )
        assert png.startswith(PNG_SIGNATURE)

    def test_unreadable_image_is_retryable_error(self, book, bible):
        garbage = ImageData(data=b"not an image", mime_type="image/png")
        with pytest.raises(InvalidResponseError, match="page 1"):
            ImageGenerator(FakeImageProvider(image=garbage), STYLE).generate_page_image(
                book, 1, bible
            )

    def test_unknown_page_raises_key_error(self, book, bible):
        with pytest.raises(KeyError):
            ImageGenerator(FakeImageProvider(), STYLE).generate_page_image(book, 9, bible)

    def test_provider_errors_propagate(self, book, bible):
        error = ContentRejectedError("IMAGE_SAFETY")
        with pytest.raises(ContentRejectedError):
            ImageGenerator(FakeImageProvider(error), STYLE).generate_page_image(book, 1, bible)


class TestToPng:
    def test_png_passes_through_unchanged(self):
        png = make_image_bytes()
        assert to_png(png) is png

    def test_truncated_png_rejected(self):
        with pytest.raises(ImageDecodeError):
            to_png(make_image_bytes(size=(64, 64))[:40])
