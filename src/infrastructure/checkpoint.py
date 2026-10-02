"""Persistence for per-story progress (``state.json``).

Saves are atomic, so a crash mid-save leaves the previous checkpoint intact.
An unreadable checkpoint is never deleted: it is moved aside as
``state.json.corrupt-<timestamp>`` and treated as absent, letting the caller
rebuild progress from the files already on disk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.models.state import StoryState
from src.utils.filesystem import atomic_write_json

logger = logging.getLogger(__name__)


class CheckpointStore:
    def __init__(self, state_path: Path) -> None:
        self._path = state_path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> StoryState | None:
        """Return the saved state, or None if there is none (or it was corrupt)."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return StoryState.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            quarantined = self._quarantine()
            logger.warning(
                "Checkpoint %s was unreadable (%s); moved to %s and rebuilding from disk.",
                self._path,
                type(exc).__name__,
                quarantined.name,
            )
            return None

    def save(self, state: StoryState) -> None:
        atomic_write_json(self._path, state)

    def load_or_create(self, story_id: str, concept: str) -> StoryState:
        state = self.load()
        if state is None:
            state = StoryState(story_id=story_id, concept=concept)
        return state

    def _quarantine(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
        self._path.rename(target)
        return target
