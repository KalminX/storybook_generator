"""Renders a Storybook and its page illustrations into a PDF with ReportLab.

Independent of any AI provider: it takes a validated Storybook, a mapping of
page number -> image file, and layout settings. The layout lives in a few
small ``_draw_*`` functions so it is easy to adjust after reviewing samples.

Layout (all sizes from PdfConfig):
  cover       - title, with the first illustration above it if enabled
  story page  - illustration fitted into the upper area, text centred in a
                block of ``text_area_ratio`` of the page below it, and an
                optional page number in the bottom margin
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from src.config import PdfConfig
from src.models.story import Storybook
from src.utils.filesystem import atomic_write_bytes

logger = logging.getLogger(__name__)

# Share of the cover's content height given to the illustration.
_COVER_IMAGE_RATIO = 0.72
_FONT_STEP = 1.0


class RenderError(Exception):
    """The PDF could not be produced (missing image, bad font...)."""


@dataclass(frozen=True)
class _Box:
    x: float
    y: float  # bottom edge, PDF coordinates
    width: float
    height: float

    @property
    def top(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class _Fonts:
    body: str
    title: str


def render_storybook(
    storybook: Storybook,
    page_images: Mapping[int, Path],
    output_path: Path,
    config: PdfConfig,
) -> None:
    """Write the finished book to ``output_path`` atomically."""
    images = _load_images(storybook, page_images, config)
    fonts = _Fonts(
        body=_register_font(config.font_file, config.font_name),
        title=_register_font(config.title_font_file, config.title_font_name),
    )
    page_size = (config.page_width_mm * mm, config.page_height_mm * mm)

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=page_size)
    canvas.setTitle(storybook.title)
    canvas.setCreator("storybook-generator")

    first_image = images[storybook.pages[0].page_number]
    cover_image = first_image if config.cover_illustration else None
    _draw_cover(canvas, storybook.title, cover_image, config, fonts)
    canvas.showPage()
    for page in storybook.pages:
        _draw_story_page(canvas, page.text, images[page.page_number], page.page_number, config, fonts)
        canvas.showPage()
    canvas.save()

    atomic_write_bytes(output_path, buffer.getvalue())


# --- page layouts ---------------------------------------------------------------


def _draw_cover(canvas, title, image, config: PdfConfig, fonts: _Fonts) -> None:
    content = _content_box(config)
    _fill_background(canvas, config)
    if image is None:
        _draw_text_block(canvas, title, content, fonts.title, config.title_font_size, config)
        return
    image_height = content.height * _COVER_IMAGE_RATIO
    image_box = _Box(content.x, content.top - image_height, content.width, image_height)
    gap = config.margin_mm * mm / 2
    title_box = _Box(content.x, content.y, content.width, content.height - image_height - gap)
    _fit_image(canvas, image, image_box)
    _draw_text_block(canvas, title, title_box, fonts.title, config.title_font_size, config)


def _draw_story_page(canvas, text, image, page_number, config: PdfConfig, fonts: _Fonts) -> None:
    content = _content_box(config)
    _fill_background(canvas, config)
    text_height = content.height * config.text_area_ratio
    gap = config.margin_mm * mm / 2
    image_box = _Box(
        content.x, content.y + text_height + gap, content.width, content.height - text_height - gap
    )
    text_box = _Box(content.x, content.y, content.width, text_height)
    _fit_image(canvas, image, image_box)
    _draw_text_block(canvas, text, text_box, fonts.body, config.font_size, config)
    if config.show_page_numbers:
        _draw_page_number(canvas, page_number, config, fonts)


# --- drawing primitives ---------------------------------------------------------


def _content_box(config: PdfConfig) -> _Box:
    margin = config.margin_mm * mm
    width, height = config.page_width_mm * mm, config.page_height_mm * mm
    return _Box(margin, margin, width - 2 * margin, height - 2 * margin)


def _fill_background(canvas, config: PdfConfig) -> None:
    if config.background_color.upper() == "#FFFFFF":
        return
    canvas.setFillColor(HexColor(config.background_color))
    canvas.rect(0, 0, config.page_width_mm * mm, config.page_height_mm * mm, stroke=0, fill=1)


def _fit_image(canvas, image: ImageReader, box: _Box) -> None:
    """Draw ``image`` as large as possible inside ``box``, centred, aspect preserved."""
    img_width, img_height = image.getSize()
    scale = min(box.width / img_width, box.height / img_height)
    width, height = img_width * scale, img_height * scale
    x = box.x + (box.width - width) / 2
    y = box.y + (box.height - height) / 2
    canvas.drawImage(image, x, y, width=width, height=height, mask="auto")


def _draw_text_block(canvas, text: str, box: _Box, font: str, size: float, config: PdfConfig) -> None:
    """Draw ``text`` centred in ``box``, shrinking the font until it fits."""
    markup = escape(text.strip()).replace("\n", "<br/>")
    paragraph, height = _layout_paragraph(markup, box.width, font, size, config)
    while height > box.height and size - _FONT_STEP >= config.min_font_size:
        size -= _FONT_STEP
        paragraph, height = _layout_paragraph(markup, box.width, font, size, config)
    if height > box.height:
        logger.warning(
            "Text does not fit its area even at %.0fpt and will overflow: %.40r...", size, text
        )
    y = box.y + max(0.0, (box.height - height) / 2)
    paragraph.drawOn(canvas, box.x, y)


def _layout_paragraph(markup: str, width: float, font: str, size: float, config: PdfConfig):
    style = ParagraphStyle(
        "storybook",
        fontName=font,
        fontSize=size,
        leading=size * config.line_spacing,
        alignment=TA_CENTER,
        textColor=HexColor(config.text_color),
    )
    paragraph = Paragraph(markup, style)
    _, height = paragraph.wrap(width, 10**6)
    return paragraph, height


def _draw_page_number(canvas, page_number: int, config: PdfConfig, fonts: _Fonts) -> None:
    size = max(8.0, config.font_size * 0.6)
    canvas.setFont(fonts.body, size)
    canvas.setFillColor(HexColor(config.text_color))
    y = max(size * 0.5, config.margin_mm * mm / 2 - size / 2)
    canvas.drawCentredString(config.page_width_mm * mm / 2, y, str(page_number))


# --- resources ------------------------------------------------------------------


def _load_images(
    storybook: Storybook, page_images: Mapping[int, Path], config: PdfConfig
) -> dict[int, ImageReader]:
    images: dict[int, ImageReader] = {}
    for page in storybook.pages:
        path = page_images.get(page.page_number)
        if path is None or not Path(path).is_file():
            raise RenderError(f"missing illustration for page {page.page_number}: {path}")
        try:
            if config.embed_images_as == "jpeg":
                reader = ImageReader(io.BytesIO(_as_jpeg(Path(path), config.jpeg_quality)))
            else:
                reader = ImageReader(str(path))
            reader.getSize()
        except Exception as exc:
            raise RenderError(f"unreadable illustration for page {page.page_number}: {exc}") from exc
        images[page.page_number] = reader
    return images


def _as_jpeg(path: Path, quality: int) -> bytes:
    """Re-encode an illustration as JPEG: ~10x smaller PDFs, visually identical in print."""
    with PILImage.open(path) as image:
        if image.mode in ("RGBA", "LA", "P"):
            rgba = image.convert("RGBA")
            image = PILImage.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


def _register_font(font_file: Path | None, fallback_name: str) -> str:
    """Register a TTF file (if given) and return the font name to use."""
    if font_file is None:
        known = set(pdfmetrics.getRegisteredFontNames()) | set(pdfmetrics.standardFonts)
        if fallback_name not in known:
            raise RenderError(
                f"unknown font {fallback_name!r}; use a standard PDF font or set a font file"
            )
        return fallback_name
    name = font_file.stem
    if name not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(TTFont(name, str(font_file)))
        except Exception as exc:
            raise RenderError(f"could not load font file {font_file}: {exc}") from exc
    return name
