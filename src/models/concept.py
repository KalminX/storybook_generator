"""A single story concept read from the input file."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

_SLUG_MAX_LENGTH = 40
_HASH_LENGTH = 8


class StoryConcept(BaseModel):
    model_config = ConfigDict(frozen=True)

    story_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    # 1-based line in the input file; for messages only, never for identity.
    line_number: int = Field(ge=1)


def normalize_concept(text: str) -> str:
    """Collapse whitespace so cosmetic edits don't change a story's identity."""
    return " ".join(text.split())


def make_story_id(text: str) -> str:
    """Build a stable, filesystem-safe ID from the concept text itself.

    The ID is derived from content (not line position) so reordering or
    inserting lines in the input file never points a concept at another
    concept's output folder. Format: ``<readable-slug>-<8 hex chars>``.
    """
    normalized = normalize_concept(text)
    digest = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()[:_HASH_LENGTH]

    ascii_text = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > _SLUG_MAX_LENGTH:
        slug = slug[:_SLUG_MAX_LENGTH].rsplit("-", 1)[0] or slug[:_SLUG_MAX_LENGTH]
    return f"{slug}-{digest}" if slug else f"story-{digest}"
