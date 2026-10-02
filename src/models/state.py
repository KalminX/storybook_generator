"""Persistent per-story progress, saved as ``state.json``.

The state records which expensive steps are already done so an interrupted
run can resume without repeating paid API work. All transitions go through
methods here so the rules live in one place; persistence is handled by
``infrastructure.checkpoint``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

STATE_SCHEMA_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StoryStatus(str, Enum):
    PENDING = "pending"
    GENERATING_STORY = "generating_story"
    GENERATING_IMAGES = "generating_images"
    RENDERING_PDF = "rendering_pdf"
    COMPLETED = "completed"
    FAILED = "failed"


class PageState(BaseModel):
    image_generated: bool = False
    image_file: str | None = None
    completed_at: datetime | None = None


class StoryState(BaseModel):
    schema_version: int = STATE_SCHEMA_VERSION
    story_id: str
    concept: str
    status: StoryStatus = StoryStatus.PENDING
    story_generated: bool = False
    character_bible_generated: bool = False
    pages: dict[int, PageState] = Field(default_factory=dict)
    pdf_generated: bool = False
    last_error: str | None = None
    failed_stage: StoryStatus | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None

    # --- queries -----------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.status == StoryStatus.COMPLETED

    def pending_pages(self) -> list[int]:
        """Page numbers whose image still needs generating, in order."""
        return sorted(n for n, page in self.pages.items() if not page.image_generated)

    @property
    def all_images_generated(self) -> bool:
        return bool(self.pages) and not self.pending_pages()

    # --- transitions -------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = _utcnow()

    def set_status(self, status: StoryStatus) -> None:
        self.status = status
        self._touch()

    def mark_story_generated(self, page_numbers: list[int]) -> None:
        """Record that story text exists and register exactly these pages.

        Pages that already exist keep their progress; pages not listed are dropped.
        """
        self.story_generated = True
        self.pages = {n: self.pages.get(n, PageState()) for n in sorted(page_numbers)}
        self._touch()

    def invalidate_story(self) -> None:
        """Forget the story and everything derived from it (it must be regenerated)."""
        self.story_generated = False
        self.character_bible_generated = False
        self.pages = {}
        self.pdf_generated = False
        self.completed_at = None
        self._touch()

    def invalidate_pdf(self) -> None:
        self.pdf_generated = False
        self.completed_at = None
        self._touch()

    def mark_character_bible_generated(self) -> None:
        self.character_bible_generated = True
        self._touch()

    def mark_page_image_generated(self, page_number: int, image_file: str) -> None:
        if page_number not in self.pages:
            raise KeyError(f"unknown page {page_number} for story {self.story_id}")
        self.pages[page_number] = PageState(
            image_generated=True, image_file=image_file, completed_at=_utcnow()
        )
        self._touch()

    def reset_page(self, page_number: int) -> None:
        """Force a page image to be regenerated on the next run."""
        if page_number not in self.pages:
            raise KeyError(f"unknown page {page_number} for story {self.story_id}")
        self.pages[page_number] = PageState()
        self.pdf_generated = False
        self.completed_at = None
        self._touch()

    def mark_pdf_generated(self) -> None:
        self.pdf_generated = True
        self._touch()

    def mark_completed(self) -> None:
        if not (self.story_generated and self.all_images_generated and self.pdf_generated):
            raise ValueError(f"story {self.story_id} cannot be completed: steps remain")
        self.status = StoryStatus.COMPLETED
        self.last_error = None
        self.failed_stage = None
        self.completed_at = _utcnow()
        self._touch()

    def mark_failed(self, error: str) -> None:
        """Record a failure. Completed steps are kept so the next run resumes."""
        self.failed_stage = self.status if self.status != StoryStatus.FAILED else self.failed_stage
        self.status = StoryStatus.FAILED
        self.last_error = error
        self._touch()
