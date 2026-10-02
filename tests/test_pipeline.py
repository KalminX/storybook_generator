import json
from pathlib import Path

import pytest

from src.generation.image_generator import ImageGenerator
from src.generation.story_generator import StoryGenerator
from src.infrastructure.retry import RetryPolicy
from src.models.concept import StoryConcept, make_story_id
from src.models.state import StoryState, StoryStatus
from src.pipeline.story_pipeline import StoryOutcome, StoryPipeline
from src.providers.base import PermanentProviderError, TransientProviderError
from tests.fakes import FakeImageProvider, FakeTextProvider, make_image_bytes, sample_story_data

STYLE = "Watercolor."
CONCEPT_TEXT = "A young fox discovers a hidden garden."


class FakeRenderer:
    def __init__(self, fail: Exception | None = None):
        self.calls = []
        self.fail = fail

    def __call__(self, storybook, page_images, output_path: Path):
        self.calls.append((storybook, dict(page_images)))
        if self.fail:
            raise self.fail
        assert all(Path(p).is_file() for p in page_images.values())
        output_path.write_bytes(b"%PDF-fake")


class Harness:
    """A pipeline wired to fakes, with fresh fakes available for each 'run'."""

    def __init__(self, output: Path, pages: int = 4, reference_images: int = 1):
        self.output = output
        self.pages = pages
        self.reference_images = reference_images
        self.concept = StoryConcept(
            story_id=make_story_id(CONCEPT_TEXT), text=CONCEPT_TEXT, line_number=1
        )
        self.new_run()

    def new_run(self, text_responses=(), image_failures=(), image_fail_at=None, renderer=None):
        self.text = FakeTextProvider(*(text_responses or [sample_story_data(self.pages)]))
        self.image = FakeImageProvider(*image_failures, fail_at=image_fail_at)
        self.renderer = renderer or FakeRenderer()
        self.pipeline = StoryPipeline(
            story_generator=StoryGenerator(self.text, STYLE),
            image_generator=ImageGenerator(self.image, STYLE),
            renderer=self.renderer,
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0, max_delay=0),
            output_directory=self.output,
            reference_images=self.reference_images,
            sleep=lambda _: None,
        )
        return self

    def run(self, **kwargs):
        return self.pipeline.run(self.concept, **kwargs)

    @property
    def paths(self):
        return self.pipeline.paths_for(self.concept.story_id)

    def state(self) -> StoryState:
        return StoryState.model_validate_json(self.paths.state_json.read_text())

    def pages_requested(self) -> list[int]:
        return [int(c["prompt"].split("Page ")[1].split(" of")[0]) for c in self.image.calls]


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path / "output")


def test_happy_path_produces_every_file(h):
    result = h.run()

    assert result.outcome == StoryOutcome.COMPLETED
    assert result.title == "The Hidden Garden"
    paths = h.paths
    assert json.loads(paths.story_json.read_text())["title"] == "The Hidden Garden"
    assert json.loads(paths.character_bible_json.read_text())["characters"][0]["name"] == "Fern"
    for n in range(1, 5):
        assert paths.page_image(n).read_bytes().startswith(b"\x89PNG")
    assert paths.pdf.read_bytes() == b"%PDF-fake"

    state = h.state()
    assert state.status == StoryStatus.COMPLETED
    assert state.pending_pages() == []
    assert state.pages[2].image_file == "pages/page-002.png"
    assert len(h.text.calls) == 1
    assert h.pages_requested() == [1, 2, 3, 4]


def test_transient_errors_are_retried_within_a_run(h):
    h.new_run(image_failures=[TransientProviderError("503"), TransientProviderError("429")])
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.pages_requested() == [1, 1, 1, 2, 3, 4]


def test_failure_keeps_progress_and_next_run_resumes_from_failed_page(h):
    # Pages 1 and 2 succeed, then page 3 fails permanently.
    h.new_run(image_fail_at={3: PermanentProviderError("bad request")})
    result = h.run()

    assert result.outcome == StoryOutcome.FAILED
    assert "bad request" in result.error
    state = h.state()
    assert state.status == StoryStatus.FAILED
    assert state.failed_stage == StoryStatus.GENERATING_IMAGES
    assert state.pending_pages() == [3, 4]
    assert not h.paths.pdf.exists()

    # Second run: no story regeneration; only pages 3 and 4 are requested.
    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.text.calls == []
    assert h.pages_requested() == [3, 4]
    assert h.state().status == StoryStatus.COMPLETED


def test_completed_story_is_skipped_without_any_api_calls(h):
    h.run()
    h.new_run()
    result = h.run()
    assert result.outcome == StoryOutcome.SKIPPED
    assert h.text.calls == [] and h.image.calls == [] and h.renderer.calls == []


def test_crash_after_image_write_before_checkpoint_is_adopted(h):
    # Simulate: story saved, page 1 PNG written, but the process died before
    # state.json recorded it.
    h.new_run(image_failures=[KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        h.run()
    assert h.state().pending_pages() == [1, 2, 3, 4]
    h.paths.page_image(1).write_bytes(make_image_bytes("green"))

    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.text.calls == []
    assert h.pages_requested() == [2, 3, 4]


def test_crash_after_story_write_before_checkpoint_is_adopted(h):
    h.paths.ensure()
    h.paths.story_json.write_text(json.dumps(sample_story_data(4)))
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.text.calls == []


def test_damaged_page_image_is_regenerated(h):
    h.run()
    h.paths.page_image(2).write_bytes(b"garbage")
    h.paths.pdf.unlink()
    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.pages_requested() == [2]


def test_missing_pdf_is_rerendered_without_api_calls(h):
    h.run()
    h.paths.pdf.unlink()
    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.image.calls == [] and h.text.calls == []
    assert len(h.renderer.calls) == 1


def test_force_pages_regenerates_exactly_those_pages(h):
    h.run()
    h.new_run()
    assert h.run(force_pages=[2, 4]).outcome == StoryOutcome.COMPLETED
    assert h.pages_requested() == [2, 4]
    assert len(h.renderer.calls) == 1


def test_force_unknown_page_fails_cleanly(h):
    h.run()
    h.new_run()
    result = h.run(force_pages=[99])
    assert result.outcome == StoryOutcome.FAILED
    assert "page 99" in result.error


def test_reference_images_use_first_finished_page(h):
    h.run()
    refs = [len(c["reference_images"]) for c in h.image.calls]
    assert refs == [0, 1, 1, 1]
    page_one = h.paths.page_image(1).read_bytes()
    assert all(c["reference_images"][0].data == page_one for c in h.image.calls[1:])


def test_reference_images_can_be_disabled(tmp_path):
    h = Harness(tmp_path / "output", reference_images=0)
    h.run()
    assert all(c["reference_images"] == [] for c in h.image.calls)


def test_story_generation_failure_is_recorded(h):
    h.new_run(text_responses=[PermanentProviderError("invalid key")])
    result = h.run()
    assert result.outcome == StoryOutcome.FAILED
    state = h.state()
    assert state.failed_stage == StoryStatus.GENERATING_STORY
    assert "invalid key" in state.last_error
    assert not state.story_generated


def test_render_failure_is_recorded_and_retried_next_run(h):
    h.new_run(renderer=FakeRenderer(fail=OSError("disk full")))
    assert h.run().outcome == StoryOutcome.FAILED
    assert h.state().failed_stage == StoryStatus.RENDERING_PDF
    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert h.image.calls == []


def test_folder_belonging_to_another_concept_is_not_touched(h):
    h.paths.ensure()
    other = StoryState(story_id=h.concept.story_id, concept="Something else entirely")
    h.paths.state_json.write_text(other.model_dump_json())
    before = h.paths.state_json.read_text()

    result = h.run()

    assert result.outcome == StoryOutcome.FAILED
    assert "different concept" in result.error
    assert h.paths.state_json.read_text() == before
    assert h.text.calls == []


def test_regenerated_story_never_adopts_old_illustrations(h):
    h.run()
    h.paths.story_json.unlink()  # user discards the story text
    h.paths.pdf.unlink()
    h.new_run()
    assert h.run().outcome == StoryOutcome.COMPLETED
    assert len(h.text.calls) == 1
    assert h.pages_requested() == [1, 2, 3, 4]
    assert len(list(h.paths.root.glob("pages.old-*"))) == 1


def test_hand_edited_character_bible_is_used(h):
    h.new_run(renderer=FakeRenderer(fail=OSError("stop before pdf")))
    h.run()
    bible = json.loads(h.paths.character_bible_json.read_text())
    bible["characters"][0]["appearance"] = "A silver fox with a blue collar"
    h.paths.character_bible_json.write_text(json.dumps(bible))
    h.run(force_pages=[1])
    assert "silver fox with a blue collar" in h.image.calls[-1]["prompt"]
