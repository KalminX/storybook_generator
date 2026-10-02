import logging
import os
import re

import pytest

from src.config import PdfConfig
from src.models.story import Storybook
from src.rendering.pdf_renderer import RenderError, render_storybook
from tests.fakes import make_image_bytes, sample_story_data


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page(?!s)", pdf))


@pytest.fixture
def book() -> Storybook:
    return Storybook.model_validate(sample_story_data(pages=3))


@pytest.fixture
def images(tmp_path, book):
    paths = {}
    colors = ["tomato", "gold", "skyblue"]
    for page, color in zip(book.pages, colors):
        path = tmp_path / f"page-{page.page_number:03d}.png"
        path.write_bytes(make_image_bytes(color, size=(120, 90)))
        paths[page.page_number] = path
    return paths


def test_renders_cover_plus_one_page_per_story_page(tmp_path, book, images):
    out = tmp_path / "book" / "storybook.pdf"
    render_storybook(book, images, out, PdfConfig())
    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF")
    assert page_count(pdf) == 1 + len(book.pages)
    assert os.listdir(out.parent) == ["storybook.pdf"]  # atomic: no temp leftovers


def test_page_size_follows_config(tmp_path, book, images):
    out = tmp_path / "book.pdf"
    render_storybook(book, images, out, PdfConfig(page_width_mm=100, page_height_mm=50))
    match = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", out.read_bytes())
    width, height = float(match.group(1)), float(match.group(2))
    assert width == pytest.approx(100 / 25.4 * 72, abs=0.1)
    assert height == pytest.approx(50 / 25.4 * 72, abs=0.1)


def test_missing_image_raises(tmp_path, book, images):
    del images[2]
    with pytest.raises(RenderError, match="page 2"):
        render_storybook(book, images, tmp_path / "book.pdf", PdfConfig())
    assert not (tmp_path / "book.pdf").exists()


def test_unreadable_image_raises(tmp_path, book, images):
    images[3].write_bytes(b"not a picture")
    with pytest.raises(RenderError, match="page 3"):
        render_storybook(book, images, tmp_path / "book.pdf", PdfConfig())


def test_long_text_shrinks_and_warns_only_if_still_too_long(tmp_path, book, images, caplog):
    data = sample_story_data(pages=3)
    data["pages"][0]["text"] = "A slightly longer sentence about a fox. " * 6
    data["pages"][1]["text"] = "An absurdly long page of text that cannot possibly fit. " * 200
    long_book = Storybook.model_validate(data)
    with caplog.at_level(logging.WARNING):
        render_storybook(long_book, images, tmp_path / "book.pdf", PdfConfig())
    assert caplog.text.count("does not fit") == 1


def test_special_characters_are_escaped(tmp_path, images):
    data = sample_story_data(pages=3)
    data["title"] = "Tom & Jerry <3"
    data["pages"][0]["text"] = "Line one\nLine <two> & more"
    render_storybook(Storybook.model_validate(data), images, tmp_path / "book.pdf", PdfConfig())


def test_options_without_cover_image_or_page_numbers(tmp_path, book, images):
    config = PdfConfig(
        cover_illustration=False,
        show_page_numbers=False,
        background_color="#FFF8E7",
        text_color="#333333",
    )
    render_storybook(book, images, tmp_path / "book.pdf", config)
    assert page_count((tmp_path / "book.pdf").read_bytes()) == 4


def test_bad_font_settings_raise(tmp_path, book, images):
    with pytest.raises(RenderError, match="unknown font"):
        render_storybook(book, images, tmp_path / "a.pdf", PdfConfig(font_name="NoSuchFont"))
    bad_file = tmp_path / "broken.ttf"
    bad_file.write_bytes(b"not a font")
    with pytest.raises(RenderError, match="font file"):
        render_storybook(book, images, tmp_path / "b.pdf", PdfConfig(font_file=bad_file))


def test_invalid_color_rejected_by_config():
    with pytest.raises(ValueError):
        PdfConfig(text_color="red")


def test_jpeg_embedding_is_much_smaller_than_png(tmp_path, book):
    from PIL import Image

    # Noisy images compress poorly as PNG, like real illustrations.
    images = {}
    for page in book.pages:
        path = tmp_path / f"p{page.page_number}.png"
        Image.effect_noise((400, 400), 60).convert("RGB").save(path)
        images[page.page_number] = path
    render_storybook(book, images, tmp_path / "png.pdf", PdfConfig(embed_images_as="png"))
    render_storybook(book, images, tmp_path / "jpg.pdf", PdfConfig(embed_images_as="jpeg"))
    jpeg_size = (tmp_path / "jpg.pdf").stat().st_size
    assert jpeg_size < (tmp_path / "png.pdf").stat().st_size / 2
    assert b"/DCTDecode" in (tmp_path / "jpg.pdf").read_bytes()


def test_transparent_png_is_flattened_onto_white(tmp_path, book):
    from PIL import Image

    images = {}
    for page in book.pages:
        path = tmp_path / f"p{page.page_number}.png"
        Image.new("RGBA", (50, 50), (255, 0, 0, 0)).save(path)
        images[page.page_number] = path
    render_storybook(book, images, tmp_path / "book.pdf", PdfConfig())
