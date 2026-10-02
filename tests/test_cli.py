"""End-to-end CLI tests on a temporary project, with fake providers and the real PDF renderer."""

from functools import partial
from pathlib import Path

import pytest

from src.cli import EXIT_FAILURES, EXIT_INTERRUPTED, EXIT_OK, EXIT_SETUP_ERROR, main, parse_args
from src.generation.image_generator import ImageGenerator
from src.generation.story_generator import StoryGenerator
from src.infrastructure.retry import RetryPolicy
from src.models.concept import make_story_id
from src.pipeline.story_pipeline import StoryPipeline
from src.providers.base import PermanentProviderError
from src.rendering.pdf_renderer import render_storybook
from tests.fakes import FakeImageProvider, FakeTextProvider, sample_story_data

STORIES = ["A young fox discovers a hidden garden.", "A nervous penguin learns to swim."]

CONFIG = """
provider:
  text_model: fake-text
  image_model: fake-image
retry:
  max_attempts: 2
  initial_delay: 0
  max_delay: 0
"""


@pytest.fixture
def project(tmp_path, monkeypatch, restore_root_logger) -> Path:
    (tmp_path / "config.yaml").write_text(CONFIG)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "stories.txt").write_text("\n".join(STORIES) + "\n")
    (tmp_path / "input" / "style_spec.md").write_text("Watercolor, ages 3-6.")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    return tmp_path


class FakeFactory:
    """Stands in for app.build_pipeline; records the image provider of each build."""

    def __init__(self, image_fail_at=None):
        self.image_fail_at = image_fail_at or {}
        self.builds = 0
        self.image_providers: list[FakeImageProvider] = []

    def __call__(self, config, api_key):
        self.builds += 1
        image = FakeImageProvider(fail_at=self.image_fail_at)
        self.image_providers.append(image)
        style = config.paths.style_file.read_text()
        return StoryPipeline(
            story_generator=StoryGenerator(FakeTextProvider(sample_story_data(3)), style),
            image_generator=ImageGenerator(image, style),
            renderer=partial(render_storybook, config=config.pdf),
            retry_policy=RetryPolicy(max_attempts=2, initial_delay=0, max_delay=0),
            output_directory=config.paths.output_directory,
            sleep=lambda _: None,
        )


def run(project: Path, *argv: str, factory=None) -> int:
    return main(list(argv), project_dir=project, pipeline_factory=factory or FakeFactory())


def pdf(project: Path, concept: str) -> Path:
    return project / "output" / make_story_id(concept) / "storybook.pdf"


def log_text(project: Path) -> str:
    return (project / "logs" / "app.log").read_text()


def test_full_run_generates_all_books(project):
    assert run(project) == EXIT_OK
    for concept in STORIES:
        assert pdf(project, concept).read_bytes().startswith(b"%PDF")
    log = log_text(project)
    assert "Completed: 2" in log and "Failed: 0" in log and "Skipped: 0" in log
    assert "fake-key-for-tests" not in log


def test_limit_one_generates_exactly_one_book(project):
    assert run(project, "--limit", "1") == EXIT_OK
    assert pdf(project, STORIES[0]).exists()
    assert not (project / "output" / make_story_id(STORIES[1])).exists()
    # The next --limit 1 run skips the finished book and makes the second.
    assert run(project, "--limit", "1") == EXIT_OK
    assert pdf(project, STORIES[1]).exists()


def test_failure_is_isolated_and_resumed_on_next_run(project):
    # Image call 5 = story 2, page 2 (story 1 uses calls 1-3).
    factory = FakeFactory(image_fail_at={5: PermanentProviderError("bad request")})
    assert run(project, factory=factory) == EXIT_FAILURES
    assert pdf(project, STORIES[0]).exists()
    assert not pdf(project, STORIES[1]).exists()
    assert "Completed: 1" in log_text(project) and "Failed: 1" in log_text(project)

    factory = FakeFactory()
    assert run(project, factory=factory) == EXIT_OK
    assert pdf(project, STORIES[1]).exists()
    assert len(factory.image_providers[0].calls) == 2  # only pages 2 and 3 of story 2
    assert "Skipped: 1" in log_text(project)


@pytest.mark.parametrize("selector", ["2", make_story_id(STORIES[1])])
def test_story_selection(project, selector):
    assert run(project, "--story", selector) == EXIT_OK
    assert pdf(project, STORIES[1]).exists()
    assert not pdf(project, STORIES[0]).exists()


@pytest.mark.parametrize("selector", ["9", "no-such-story"])
def test_unknown_story_is_a_setup_error(project, selector, capsys):
    assert run(project, "--story", selector) == EXIT_SETUP_ERROR
    assert "Setup problem" in capsys.readouterr().out


def test_resume_only_continues_started_stories(project):
    factory = FakeFactory(image_fail_at={2: PermanentProviderError("x")})
    run(project, "--story", "1", factory=factory)  # story 1 started, fails mid-way
    factory = FakeFactory()
    assert run(project, "--resume", factory=factory) == EXIT_OK
    assert pdf(project, STORIES[0]).exists()
    assert not (project / "output" / make_story_id(STORIES[1])).exists()


def test_redo_page(project):
    run(project, "--story", "1")
    factory = FakeFactory()
    assert run(project, "--story", "1", "--redo-page", "2", factory=factory) == EXIT_OK
    assert len(factory.image_providers[0].calls) == 1
    assert "Page 2 of 3" in factory.image_providers[0].calls[0]["prompt"]


def test_interrupt_exits_cleanly_with_progress_saved(project):
    factory = FakeFactory(image_fail_at={2: KeyboardInterrupt()})
    assert run(project, factory=factory) == EXIT_INTERRUPTED
    state = project / "output" / make_story_id(STORIES[0]) / "state.json"
    assert '"image_generated": true' in state.read_text()


def test_dry_run_reports_setup_and_status_without_building_pipeline(project, capsys):
    run(project, "--story", "1")
    factory = FakeFactory()
    assert run(project, "--dry-run", factory=factory) == EXIT_OK
    out = capsys.readouterr().out
    assert factory.builds == 0
    assert "API key: GEMINI_API_KEY is set" in out
    assert "[done]" in out and "[new]" in out
    assert make_story_id(STORIES[1]) in out


def test_dry_run_reports_missing_key_and_inputs(project, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY")
    (project / "input" / "style_spec.md").unlink()
    assert run(project, "--dry-run") == EXIT_SETUP_ERROR
    out = capsys.readouterr().out
    assert "GEMINI_API_KEY is not set" in out
    assert "Style specification not found" in out
    assert "2 problem(s) found" in out


def test_missing_key_on_real_run_is_a_setup_error(project, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY")
    assert run(project) == EXIT_SETUP_ERROR
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().out


def test_invalid_config_is_a_setup_error(project, capsys):
    (project / "config.yaml").write_text("provider: {}\n")
    assert run(project) == EXIT_SETUP_ERROR
    assert "Invalid configuration" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv", [["--redo-page", "2"], ["--limit", "0"], ["--story", "1", "--redo-page", "0"]]
)
def test_invalid_arguments(argv):
    with pytest.raises(SystemExit) as info:
        parse_args(argv)
    assert info.value.code == 2
