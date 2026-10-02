from src.models.concept import StoryConcept
from src.pipeline.batch import run_batch
from src.pipeline.story_pipeline import StoryOutcome, StoryResult


def concepts(n: int) -> list[StoryConcept]:
    return [StoryConcept(story_id=f"s{i}", text=f"Story {i}", line_number=i) for i in range(1, n + 1)]


class Runner:
    def __init__(self, outcomes: dict[str, StoryOutcome]):
        self.outcomes = outcomes
        self.ran: list[str] = []

    def __call__(self, concept: StoryConcept) -> StoryResult:
        self.ran.append(concept.story_id)
        outcome = self.outcomes.get(concept.story_id, StoryOutcome.COMPLETED)
        error = "boom" if outcome == StoryOutcome.FAILED else None
        return StoryResult(concept.story_id, outcome, error=error)


def test_failure_does_not_stop_the_batch():
    runner = Runner({"s3": StoryOutcome.FAILED})
    summary = run_batch(concepts(4), runner)
    assert runner.ran == ["s1", "s2", "s3", "s4"]
    assert (summary.completed, summary.failed, summary.skipped) == (3, 1, 0)


def test_limit_counts_only_stories_worked_on():
    runner = Runner({"s1": StoryOutcome.SKIPPED, "s2": StoryOutcome.SKIPPED})
    summary = run_batch(concepts(5), runner, limit=1)
    assert runner.ran == ["s1", "s2", "s3"]
    assert (summary.completed, summary.skipped) == (1, 2)


def test_failed_story_counts_towards_limit():
    runner = Runner({"s1": StoryOutcome.FAILED})
    run_batch(concepts(3), runner, limit=1)
    assert runner.ran == ["s1"]


def test_progress_lines_are_logged(caplog):
    caplog.set_level("INFO")
    run_batch(concepts(2), Runner({}))
    assert "[1/2] Story 1" in caplog.text
    assert "[2/2] Story 2" in caplog.text
