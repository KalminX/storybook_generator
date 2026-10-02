"""Filesystem helpers: atomic writes and the per-story output layout."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


# mkstemp creates files as 0600; atomic writes restore normal permissions.
_FILE_MODE = 0o666 & ~_current_umask()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers see either the old or the new file.

    Writes to a temporary file in the same directory, fsyncs it, then renames
    it over the target. A crash mid-write leaves the previous file intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp:
            os.fchmod(tmp.fileno(), _FILE_MODE)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write JSON. Pydantic models are serialised with ``model_dump``."""
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fsync_directory(directory: Path) -> None:
    # Persist the rename itself. Not supported on every platform; best effort.
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@dataclass(frozen=True)
class StoryPaths:
    """Deterministic locations of every file belonging to one story."""

    root: Path

    @classmethod
    def for_story(cls, output_directory: Path, story_id: str) -> StoryPaths:
        if not story_id or "/" in story_id or "\\" in story_id or story_id.startswith("."):
            raise ValueError(f"unsafe story id: {story_id!r}")
        return cls(output_directory / story_id)

    @property
    def story_json(self) -> Path:
        return self.root / "story.json"

    @property
    def state_json(self) -> Path:
        return self.root / "state.json"

    @property
    def character_bible_json(self) -> Path:
        return self.root / "character_bible.json"

    @property
    def pages_dir(self) -> Path:
        return self.root / "pages"

    def page_image(self, page_number: int) -> Path:
        if page_number < 1:
            raise ValueError(f"page numbers start at 1, got {page_number}")
        return self.pages_dir / f"page-{page_number:03d}.png"

    @property
    def pdf(self) -> Path:
        return self.root / "storybook.pdf"

    def ensure(self) -> None:
        """Create the story's folders (never touches existing files)."""
        self.pages_dir.mkdir(parents=True, exist_ok=True)


def ensure_writable_directory(directory: Path) -> None:
    """Create ``directory`` if needed and confirm files can be written to it."""
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".write-test"
    try:
        probe.write_bytes(b"")
    finally:
        probe.unlink(missing_ok=True)
