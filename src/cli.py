"""Command-line interface: parses arguments, selects stories, prints the summary."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from src.app import build_pipeline
from src.config import AppConfig, ConfigError, find_config_file, load_api_key, load_config
from src.infrastructure.checkpoint import CheckpointStore
from src.infrastructure.logger import setup_logging
from src.models.concept import StoryConcept
from src.models.state import StoryState, StoryStatus
from src.pipeline.batch import BatchSummary, run_batch
from src.pipeline.story_pipeline import StoryOutcome, StoryPipeline
from src.providers.factory import UnknownProviderError
from src.utils.filesystem import StoryPaths, ensure_writable_directory
from src.utils.inputs import InputError, load_concepts, load_style_spec

logger = logging.getLogger("storybook")

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_SETUP_ERROR = 2
EXIT_INTERRUPTED = 130

PipelineFactory = Callable[[AppConfig, str], StoryPipeline]


class UsageError(Exception):
    """A problem with the command-line arguments or the story selection."""


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Generate illustrated children's storybooks. "
        "Run it again at any time to continue where it left off.",
    )
    parser.add_argument(
        "--story",
        metavar="ID_OR_NUMBER",
        help="only this story: its folder name in output/, or its number in stories.txt (1 = first)",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N", help="work on at most N stories (finished ones don't count)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="only continue stories that were already started (skip brand-new ones)",
    )
    parser.add_argument(
        "--redo-page",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help="regenerate page N's picture (needs --story; may be repeated)",
    )
    parser.add_argument("--config", type=Path, metavar="FILE", help="use this settings file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check setup and list stories without calling the API",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.redo_page and not args.story:
        parser.error("--redo-page needs --story to say which book")
    if any(n < 1 for n in args.redo_page):
        parser.error("--redo-page numbers start at 1")
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path,
    pipeline_factory: PipelineFactory = build_pipeline,
) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config or find_config_file(project_dir))
    except ConfigError as exc:
        print(f"Setup problem: {exc}")
        return EXIT_SETUP_ERROR

    if args.dry_run:
        return dry_run(config, project_dir, args)

    try:
        api_key = load_api_key(config.provider.api_key_env, project_dir / ".env")
        setup_logging(config.paths.log_directory, config.logging.level, secrets=[api_key])
        concepts = load_concepts(config.paths.input_file)
        load_style_spec(config.paths.style_file)
        selected = select_concepts(concepts, config, args)
        pipeline = pipeline_factory(config, api_key)
    except (ConfigError, InputError, UsageError, UnknownProviderError) as exc:
        print(f"Setup problem: {exc}")
        return EXIT_SETUP_ERROR

    logger.info("Found %d story concept(s); %d selected.", len(concepts), len(selected))
    if not selected:
        logger.info("Nothing to do.")
        return EXIT_OK

    try:
        summary = run_batch(
            selected,
            lambda concept: pipeline.run(concept, force_pages=args.redo_page),
            limit=args.limit,
        )
    except KeyboardInterrupt:
        logger.warning("\nStopped. Progress is saved - run the same command again to continue.")
        return EXIT_INTERRUPTED

    print_summary(summary, config)
    return EXIT_FAILURES if summary.failed else EXIT_OK


def select_concepts(
    concepts: list[StoryConcept], config: AppConfig, args: argparse.Namespace
) -> list[StoryConcept]:
    selected = concepts
    if args.story:
        selected = [_find_story(concepts, args.story)]
    if args.resume:
        output = config.paths.output_directory
        selected = [c for c in selected if _is_started_and_unfinished(output, c)]
    return selected


def _find_story(concepts: list[StoryConcept], wanted: str) -> StoryConcept:
    wanted = wanted.strip().rstrip("/").split("/")[-1]
    if wanted.isdigit():
        index = int(wanted)
        if 1 <= index <= len(concepts):
            return concepts[index - 1]
        raise UsageError(f"there is no story number {index}; stories.txt has {len(concepts)}")
    for concept in concepts:
        if concept.story_id == wanted:
            return concept
    raise UsageError(f"no story with ID {wanted!r}. Use --dry-run to list story IDs.")


def _load_state(output: Path, concept: StoryConcept) -> tuple[StoryState | None, StoryPaths]:
    paths = StoryPaths.for_story(output, concept.story_id)
    return CheckpointStore(paths.state_json).load(), paths


def _is_started_and_unfinished(output: Path, concept: StoryConcept) -> bool:
    state, paths = _load_state(output, concept)
    return state is not None and not (state.is_complete and paths.pdf.is_file())


def describe_status(state: StoryState | None, pdf_exists: bool) -> str:
    if state is None:
        return "new"
    if state.is_complete and pdf_exists:
        return "done"
    progress = ""
    if state.pages:
        done = len(state.pages) - len(state.pending_pages())
        progress = f", {done}/{len(state.pages)} pictures"
    if state.status == StoryStatus.FAILED:
        stage = state.failed_stage.value if state.failed_stage else "unknown step"
        return f"failed at {stage.replace('_', ' ')}{progress} - will retry"
    return f"in progress{progress}"


def print_summary(summary: BatchSummary, config: AppConfig) -> None:
    logger.info("")
    logger.info("Completed: %d", summary.completed)
    logger.info("Failed: %d", summary.failed)
    logger.info("Skipped: %d", summary.skipped)
    for result in summary.results:
        if result.outcome == StoryOutcome.FAILED:
            logger.info("  x %s: %s", result.story_id, result.error)
    if summary.failed:
        logger.info(
            "Details are in %s. Run the same command again to retry failed stories;"
            " finished pages are kept.",
            config.paths.log_directory / "app.log",
        )
    if summary.completed:
        logger.info("Finished books are in %s", config.paths.output_directory)


# --- dry run ----------------------------------------------------------------------


def dry_run(config: AppConfig, project_dir: Path, args: argparse.Namespace) -> int:
    """Validate everything that doesn't cost money, and list the stories."""
    problems = 0

    def check(ok: bool, label: str, detail: str) -> None:
        nonlocal problems
        problems += not ok
        print(f"  {'OK ' if ok else 'XX '} {label}: {detail}")

    print("Checking setup (no API calls are made)...")
    check(
        True,
        "Settings",
        f"{config.source.name} (text: {config.provider.text_model}, "
        f"images: {config.provider.image_model})",
    )

    secrets: list[str] = []
    try:
        secrets.append(load_api_key(config.provider.api_key_env, project_dir / ".env"))
        check(True, "API key", f"{config.provider.api_key_env} is set")
    except ConfigError as exc:
        check(False, "API key", str(exc))

    for label, directory in (
        ("Output folder", config.paths.output_directory),
        ("Log folder", config.paths.log_directory),
    ):
        try:
            ensure_writable_directory(directory)
            check(True, label, f"{directory} (writable)")
        except OSError as exc:
            check(False, label, f"{directory} is not writable: {exc}")

    try:
        style = load_style_spec(config.paths.style_file)
        check(True, "Style specification", f"{config.paths.style_file} ({len(style)} characters)")
    except InputError as exc:
        check(False, "Style specification", str(exc))

    concepts: list[StoryConcept] = []
    try:
        concepts = load_concepts(config.paths.input_file)
        check(True, "Stories", f"{len(concepts)} concept(s) in {config.paths.input_file}")
    except InputError as exc:
        check(False, "Stories", str(exc))

    if concepts:
        try:
            selected = select_concepts(concepts, config, args)
        except UsageError as exc:
            check(False, "Story selection", str(exc))
            selected = []
        print("\nStories:")
        for number, concept in enumerate(concepts, start=1):
            if concept not in selected:
                continue
            state, paths = _load_state(config.paths.output_directory, concept)
            status = describe_status(state, paths.pdf.is_file())
            print(f"  {number:>3}. [{status}] {concept.story_id}\n       {concept.text}")

    print()
    if problems:
        print(f"{problems} problem(s) found. Fix them and run the check again.")
        return EXIT_SETUP_ERROR
    print("Everything looks good. Run without --dry-run to start.")
    return EXIT_OK
