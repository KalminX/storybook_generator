"""Developer tool: illustrate ONE page of a trial story (one image request).

Run scripts/try_story.py first to produce a trial story, then:

    python scripts/try_page.py                  # page 1 of the newest trial story
    python scripts/try_page.py 4                # page 4 of the newest trial story
    python scripts/try_page.py 4 path/to/story.json

The PNG is written next to the story file in output/_trials/.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import ConfigError, find_config_file, load_api_key, load_config  # noqa: E402
from src.generation.character_bible import build_character_bible  # noqa: E402
from src.generation.image_generator import ImageGenerator  # noqa: E402
from src.infrastructure.logger import log_duration, setup_logging  # noqa: E402
from src.app import retry_policy  # noqa: E402
from src.infrastructure.retry import retry_call  # noqa: E402
from src.models.story import Storybook  # noqa: E402
from src.providers.factory import create_providers  # noqa: E402
from src.utils.filesystem import atomic_write_bytes  # noqa: E402
from src.utils.inputs import load_style_spec  # noqa: E402

logger = logging.getLogger("try_page")


def main(argv: list[str]) -> int:
    config = load_config(find_config_file(PROJECT_DIR))
    api_key = load_api_key(config.provider.api_key_env, PROJECT_DIR / ".env")
    setup_logging(config.paths.log_directory, config.logging.level, secrets=[api_key])

    page_number = int(argv[0]) if argv else 1
    if len(argv) > 1:
        story_file = Path(argv[1])
    else:
        trials = sorted(
            (config.paths.output_directory / "_trials").glob("*-story.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if not trials:
            raise ConfigError("No trial story found. Run scripts/try_story.py first.")
        story_file = trials[-1]

    book = Storybook.model_validate_json(story_file.read_text(encoding="utf-8"))
    bible = build_character_bible(book)
    providers = create_providers(config.provider, api_key)
    generator = ImageGenerator(
        providers.image,
        load_style_spec(config.paths.style_file),
        aspect_ratio=config.images.aspect_ratio,
        image_size=config.images.image_size,
    )
    policy = retry_policy(config.retry)

    logger.info("Illustrating page %d of %r with %s", page_number, book.title, config.provider.image_model)
    with log_duration(logger, f"Page {page_number} image"):
        png = retry_call(
            lambda: generator.generate_page_image(book, page_number, bible),
            policy=policy,
            description=f"page {page_number} image",
        )

    out = story_file.with_name(story_file.name.replace("-story.json", f"-page-{page_number:03d}.png"))
    atomic_write_bytes(out, png)
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ConfigError as exc:
        sys.exit(f"Error: {exc}")
