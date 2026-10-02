"""Reading the user's input files: story concepts and the style specification."""

from __future__ import annotations

import logging
from pathlib import Path

from src.models.concept import StoryConcept, make_story_id, normalize_concept

logger = logging.getLogger(__name__)

COMMENT_PREFIX = "#"


class InputError(Exception):
    """Raised when an input file is missing or unusable."""


def parse_concepts(text: str) -> list[StoryConcept]:
    """Parse one concept per line; skip blanks, ``#`` comments and duplicates."""
    concepts: list[StoryConcept] = []
    seen: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = normalize_concept(raw_line)
        if not line or line.startswith(COMMENT_PREFIX):
            continue
        story_id = make_story_id(line)
        if story_id in seen:
            logger.warning(
                "Line %d repeats the concept on line %d; skipping duplicate.",
                line_number,
                seen[story_id],
            )
            continue
        seen[story_id] = line_number
        concepts.append(StoryConcept(story_id=story_id, text=line, line_number=line_number))
    return concepts


def load_concepts(path: Path) -> list[StoryConcept]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise InputError(f"Story file not found: {path}") from exc
    concepts = parse_concepts(text)
    if not concepts:
        raise InputError(f"No story concepts found in {path}. Add one concept per line.")
    return concepts


def load_style_spec(path: Path) -> str:
    """Return the style specification exactly as written (never modified)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise InputError(f"Style specification not found: {path}") from exc
    if not text.strip():
        raise InputError(f"Style specification {path} is empty.")
    return text
