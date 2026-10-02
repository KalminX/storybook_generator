"""Runs many stories one after another, isolating failures.

Sequential on purpose: API rate limits, image costs and reliability matter
more than throughput. ``run_story`` is any callable, so a concurrent runner
could later replace this loop without touching the pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from src.models.concept import StoryConcept
from src.pipeline.story_pipeline import StoryOutcome, StoryResult

logger = logging.getLogger(__name__)

_PREVIEW_LENGTH = 60


@dataclass
class BatchSummary:
    results: list[StoryResult] = field(default_factory=list)

    def count(self, outcome: StoryOutcome) -> int:
        return sum(1 for r in self.results if r.outcome == outcome)

    @property
    def completed(self) -> int:
        return self.count(StoryOutcome.COMPLETED)

    @property
    def failed(self) -> int:
        return self.count(StoryOutcome.FAILED)

    @property
    def skipped(self) -> int:
        return self.count(StoryOutcome.SKIPPED)


def run_batch(
    concepts: Sequence[StoryConcept],
    run_story: Callable[[StoryConcept], StoryResult],
    *,
    limit: int | None = None,
) -> BatchSummary:
    """Run each concept in order. ``limit`` caps stories actually worked on.

    Already-finished (skipped) stories don't count towards ``limit``, so
    ``limit=1`` always produces at most one new or resumed book.
    """
    summary = BatchSummary()
    worked = 0
    total = len(concepts)
    for index, concept in enumerate(concepts, start=1):
        if limit is not None and worked >= limit:
            logger.info("Stopping after %d story(ies) as requested (--limit).", limit)
            break
        logger.info("")
        logger.info("[%d/%d] %s", index, total, _preview(concept.text))
        result = run_story(concept)
        summary.results.append(result)
        if result.outcome != StoryOutcome.SKIPPED:
            worked += 1
    return summary


def _preview(text: str) -> str:
    return text if len(text) <= _PREVIEW_LENGTH else text[: _PREVIEW_LENGTH - 3] + "..."
