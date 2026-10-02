"""Developer tool: generate the text of ONE story and print it. No images, no PDF.

Useful for checking the prompt, style specification and model choice cheaply.
Output goes to output/_trials/ and never touches real story folders.

    python scripts/try_story.py              # first concept in stories.txt
    python scripts/try_story.py 3            # third concept
    python scripts/try_story.py "A shy owl"  # any concept text
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import ConfigError, find_config_file, load_api_key, load_config  # noqa: E402
from src.generation.story_generator import StoryGenerator  # noqa: E402
from src.infrastructure.logger import log_duration, setup_logging  # noqa: E402
from src.app import retry_policy  # noqa: E402
from src.infrastructure.retry import retry_call  # noqa: E402
from src.models.concept import make_story_id  # noqa: E402
from src.providers.factory import create_providers  # noqa: E402
from src.utils.filesystem import atomic_write_json  # noqa: E402
from src.utils.inputs import load_concepts  # noqa: E402

logger = logging.getLogger("try_story")


def main(argv: list[str]) -> int:
    config = load_config(find_config_file(PROJECT_DIR))
    api_key = load_api_key(config.provider.api_key_env, PROJECT_DIR / ".env")
    setup_logging(config.paths.log_directory, config.logging.level, secrets=[api_key])

    arg = argv[0] if argv else "1"
    if arg.isdigit():
        concept = load_concepts(config.paths.input_file)[int(arg) - 1].text
    else:
        concept = arg

    providers = create_providers(config.provider, api_key)
    generator = StoryGenerator.from_style_file(providers.text, config.paths.style_file)
    policy = retry_policy(config.retry)

    logger.info("Generating story with %s: %s", config.provider.text_model, concept)
    with log_duration(logger, "Story generation"):
        book = retry_call(lambda: generator.generate(concept), policy=policy, description="story")

    out = config.paths.output_directory / "_trials" / f"{make_story_id(concept)}-story.json"
    atomic_write_json(out, book)

    print(f"\n{book.title}\n{'=' * len(book.title)}")
    for character in book.characters:
        print(f"* {character.name}: {character.appearance}")
    for page in book.pages:
        print(f"\n[{page.page_number}] {page.text}\n    picture: {page.image_prompt}")
    print(f"\nSaved to {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ConfigError as exc:
        sys.exit(f"Error: {exc}")
