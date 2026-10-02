"""Orchestrates one storybook from concept to PDF, resumably.

This is the only component that decides the order of operations:

    concept -> story.json -> character bible -> page images -> PDF -> complete

Progress is checkpointed after every step, and after every page image. On
each run the checkpoint is first reconciled with the files actually on disk,
so work finished just before a crash (file written, checkpoint not yet
saved) is adopted instead of paid for again.

No provider SDK and no PDF library is used here; all of that is injected.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from src.generation.character_bible import build_character_bible
from src.generation.image_generator import ImageGenerator
from src.generation.story_generator import StoryGenerator
from src.infrastructure.checkpoint import CheckpointStore
from src.infrastructure.retry import RetryPolicy, retry_call
from src.models.character_bible import CharacterBible
from src.models.concept import StoryConcept
from src.models.state import StoryState, StoryStatus
from src.models.story import Storybook
from src.utils.filesystem import StoryPaths, atomic_write_bytes, atomic_write_json
from src.utils.images import ImageDecodeError, to_png

logger = logging.getLogger(__name__)

# (storybook, {page_number: image_path}, output_pdf_path) -> None
Renderer = Callable[[Storybook, Mapping[int, Path], Path], None]


class StoryOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StoryResult:
    story_id: str
    outcome: StoryOutcome
    elapsed_seconds: float = 0.0
    title: str | None = None
    error: str | None = None


class StoryPipeline:
    def __init__(
        self,
        *,
        story_generator: StoryGenerator,
        image_generator: ImageGenerator,
        renderer: Renderer,
        retry_policy: RetryPolicy,
        output_directory: Path,
        reference_images: int = 1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._story_generator = story_generator
        self._image_generator = image_generator
        self._renderer = renderer
        self._retry_policy = retry_policy
        self._output_directory = output_directory
        self._reference_images = reference_images
        self._sleep = sleep

    def paths_for(self, story_id: str) -> StoryPaths:
        return StoryPaths.for_story(self._output_directory, story_id)

    def load_state(self, story_id: str) -> StoryState | None:
        """Read-only view of a story's checkpoint (used for status reports)."""
        return CheckpointStore(self.paths_for(story_id).state_json).load()

    def run(
        self,
        concept: StoryConcept,
        force_pages: Iterable[int] = (),
        on_progress: Callable[[str, int, str], None] | None = None,
    ) -> StoryResult:
        """Produce (or finish) one storybook. Never raises for ordinary failures."""
        start = time.monotonic()
        force_pages = sorted(set(force_pages))
        paths = self.paths_for(concept.story_id)
        store = CheckpointStore(paths.state_json)
        state = store.load_or_create(concept.story_id, concept.text)
        notify = on_progress or (lambda stage, pct, msg: None)

        def result(outcome: StoryOutcome, title=None, error=None) -> StoryResult:
            return StoryResult(concept.story_id, outcome, time.monotonic() - start, title, error)

        if state.concept != concept.text:
            error = (
                f"Folder {paths.root} belongs to a different concept ({state.concept!r}); "
                "refusing to overwrite it."
            )
            logger.error(error)
            notify("failed", 0, error)
            return result(StoryOutcome.FAILED, error=error)

        if state.is_complete and paths.pdf.is_file() and not force_pages:
            logger.info("Already finished: %s", paths.pdf)
            notify("completed", 100, "Already completed")
            return result(StoryOutcome.SKIPPED)

        paths.ensure()
        notify("started", 5, "Initializing storybook...")
        logger.info("Story %s started", concept.story_id)
        storybook: Storybook | None = None
        try:
            storybook = self._reconcile_with_disk(state, paths)
            store.save(state)

            storybook = self._ensure_story(state, store, paths, concept, storybook, notify=notify)
            bible = self._ensure_character_bible(state, store, paths, storybook, notify=notify)
            for number in force_pages:
                if number not in state.pages:
                    raise ValueError(
                        f"page {number} does not exist (story has {len(state.pages)} pages)"
                    )
                logger.info("Page %d will be regenerated as requested", number)
                state.reset_page(number)
            if force_pages:
                store.save(state)
            self._ensure_images(state, store, paths, storybook, bible, notify=notify)
            self._ensure_pdf(state, store, paths, storybook, notify=notify)

            state.mark_completed()
            store.save(state)
            notify("completed", 100, f"Storybook '{storybook.title}' complete!")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Story %s failed during %s: %s", concept.story_id, state.status.value, message
            )
            logger.debug("Traceback for %s", concept.story_id, exc_info=True)
            state.mark_failed(message)
            store.save(state)
            notify("failed", 0, message)
            title = storybook.title if storybook else None
            return result(StoryOutcome.FAILED, title=title, error=message)

        elapsed = time.monotonic() - start
        logger.info("Story %s completed in %.1fs: %s", concept.story_id, elapsed, paths.pdf)
        return result(StoryOutcome.COMPLETED, title=storybook.title)

    # --- steps ----------------------------------------------------------------

    def _reconcile_with_disk(self, state: StoryState, paths: StoryPaths) -> Storybook | None:
        """Make the checkpoint agree with the files that actually exist."""
        storybook = _load_storybook(paths.story_json)
        if storybook is None:
            if state.story_generated:
                logger.warning("story.json is missing or invalid; the story will be regenerated")
                state.invalidate_story()
            return None

        if not state.story_generated:
            logger.info("Found story.json from an interrupted run; reusing it")
        state.mark_story_generated([p.page_number for p in storybook.pages])

        for number, page in state.pages.items():
            image_path = paths.page_image(number)
            valid = _is_valid_image(image_path)
            if page.image_generated and not valid:
                logger.warning("Page %d image is missing or damaged; it will be regenerated", number)
                state.reset_page(number)
            elif not page.image_generated and valid:
                logger.info("Found finished image for page %d from an interrupted run", number)
                state.mark_page_image_generated(number, _relative(image_path, paths.root))

        if state.pdf_generated and not paths.pdf.is_file():
            state.invalidate_pdf()
        return storybook

    def _ensure_story(
        self,
        state: StoryState,
        store: CheckpointStore,
        paths: StoryPaths,
        concept: StoryConcept,
        storybook: Storybook | None,
        notify: Callable[[str, int, str], None] = lambda *_: None,
    ) -> Storybook:
        if state.story_generated and storybook is not None:
            notify("story_generated", 22, f"Story text loaded: '{storybook.title}'")
            return storybook

        _move_aside_stale_pages(paths)
        state.set_status(StoryStatus.GENERATING_STORY)
        store.save(state)
        notify("generating_story", 12, "Writing story narrative & structuring pages...")
        logger.info("Writing story text...")
        started = time.monotonic()
        storybook = retry_call(
            lambda: self._story_generator.generate(concept.text),
            policy=self._retry_policy,
            description=f"{concept.story_id} story text",
            sleep=self._sleep,
        )
        atomic_write_json(paths.story_json, storybook)
        state.mark_story_generated([p.page_number for p in storybook.pages])
        store.save(state)
        notify("story_generated", 22, f"Story text written: '{storybook.title}' ({len(storybook.pages)} pages)")
        logger.info(
            "Story written in %.1fs: %r (%d pages)",
            time.monotonic() - started,
            storybook.title,
            len(storybook.pages),
        )
        return storybook

    def _ensure_character_bible(
        self,
        state: StoryState,
        store: CheckpointStore,
        paths: StoryPaths,
        storybook: Storybook,
        notify: Callable[[str, int, str], None] = lambda *_: None,
    ) -> CharacterBible:
        # A hand-edited character_bible.json is respected; otherwise build it.
        bible = None
        if state.character_bible_generated:
            bible = _load_character_bible(paths.character_bible_json)
        if bible is None:
            notify("generating_character_bible", 26, "Designing character visual consistency bible...")
            bible = build_character_bible(storybook)
            atomic_write_json(paths.character_bible_json, bible)
            state.mark_character_bible_generated()
            store.save(state)
        notify("character_bible_generated", 28, f"Character bible ready ({len(bible.characters)} characters)")
        return bible

    def _ensure_images(
        self,
        state: StoryState,
        store: CheckpointStore,
        paths: StoryPaths,
        storybook: Storybook,
        bible: CharacterBible,
        notify: Callable[[str, int, str], None] = lambda *_: None,
    ) -> None:
        pending = state.pending_pages()
        total = len(storybook.pages)
        if not pending:
            return
        state.set_status(StoryStatus.GENERATING_IMAGES)
        store.save(state)
        done = total - len(pending)
        if done:
            logger.info("Resuming illustrations: %d of %d already done", done, total)

        for number in pending:
            pct = 28 + int(((done) / max(total, 1)) * 64)
            notify("generating_images", pct, f"Illustrating page {number} of {total}...")
            references = self._reference_bytes(state, paths, exclude=number)
            logger.info("Illustrating page %d/%d...", number, total)
            started = time.monotonic()
            png = retry_call(
                lambda: self._image_generator.generate_page_image(
                    storybook, number, bible, references
                ),
                policy=self._retry_policy,
                description=f"{state.story_id} page {number} image",
                sleep=self._sleep,
            )
            image_path = paths.page_image(number)
            atomic_write_bytes(image_path, png)
            state.mark_page_image_generated(number, _relative(image_path, paths.root))
            store.save(state)
            done += 1
            pct_after = 28 + int(((done) / max(total, 1)) * 64)
            notify("page_image_generated", pct_after, f"Page {number} of {total} illustrated")
            logger.info("Page %d/%d done in %.1fs", number, total, time.monotonic() - started)

    def _ensure_pdf(
        self,
        state: StoryState,
        store: CheckpointStore,
        paths: StoryPaths,
        storybook: Storybook,
        notify: Callable[[str, int, str], None] = lambda *_: None,
    ) -> None:
        if state.pdf_generated and paths.pdf.is_file():
            notify("pdf_generated", 98, "PDF book rendered")
            return
        state.set_status(StoryStatus.RENDERING_PDF)
        store.save(state)
        notify("rendering_pdf", 94, "Compiling print-ready PDF layout...")
        started = time.monotonic()
        images = {page.page_number: paths.page_image(page.page_number) for page in storybook.pages}
        self._renderer(storybook, images, paths.pdf)
        state.mark_pdf_generated()
        store.save(state)
        notify("pdf_generated", 98, "PDF book compiled successfully")
        logger.info("PDF created in %.1fs", time.monotonic() - started)

    def _reference_bytes(self, state: StoryState, paths: StoryPaths, exclude: int) -> list[bytes]:
        """PNG bytes of the book's first N finished pages, for visual consistency."""
        if self._reference_images <= 0:
            return []
        finished = [
            n for n, page in sorted(state.pages.items()) if page.image_generated and n != exclude
        ]
        return [paths.page_image(n).read_bytes() for n in finished[: self._reference_images]]


# --- helpers --------------------------------------------------------------------


def _load_storybook(path: Path) -> Storybook | None:
    try:
        return Storybook.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValidationError, ValueError) as exc:
        logger.warning("Ignoring invalid %s: %s", path.name, exc)
        return None


def _load_character_bible(path: Path) -> CharacterBible | None:
    try:
        return CharacterBible.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValidationError, ValueError) as exc:
        logger.warning("Ignoring invalid %s (%s); rebuilding it", path.name, exc)
        return None


def _is_valid_image(path: Path) -> bool:
    try:
        to_png(path.read_bytes())
    except (FileNotFoundError, ImageDecodeError):
        return False
    return True


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _move_aside_stale_pages(paths: StoryPaths) -> None:
    """Illustrations of a previous, discarded story must never be adopted by a new one."""
    stale = list(paths.pages_dir.glob("page-*.png")) if paths.pages_dir.is_dir() else []
    if not stale:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = paths.root / f"pages.old-{stamp}"
    paths.pages_dir.rename(target)
    paths.pages_dir.mkdir()
    logger.warning("Moved %d old illustration(s) to %s", len(stale), target.name)
