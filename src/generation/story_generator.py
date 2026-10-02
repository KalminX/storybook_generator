"""Turns a story concept plus the style specification into a validated Storybook.

Pure domain logic: builds the request, asks a text provider for structured
output, validates it. Saving, retrying and checkpointing belong to the caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from src.models.story import Storybook
from src.providers.base import InvalidResponseError, TextGenerationProvider
from src.utils.inputs import load_style_spec

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
You are an award-winning author of illustrated children's picture books.
You write a complete storybook from a short concept, following the STYLE
SPECIFICATION exactly: it is the authority on audience, length, tone, page
count, vocabulary and illustration style. Where it is silent, make sensible
choices for a children's picture book.

Output rules:
- Number pages from 1 in reading order.
- "characters" lists every recurring character who appears in illustrations.
  Give each an "appearance" precise enough for an illustrator to draw them
  identically on every page (species, size, colors, distinctive features),
  and "clothing" if they wear the same outfit or accessories throughout.
- Each page's "image_prompt" describes that page's illustration: the scene,
  setting, which characters are present (by name), what they are doing, and
  the mood. Describe only what is visible. Do not restate character
  appearance or the overall art style - those are supplied separately.
- Illustrations must not contain written words unless the style
  specification explicitly asks for them.
"""


@dataclass(frozen=True)
class StoryPrompt:
    system_instruction: str
    prompt: str


def build_story_prompt(concept: str, style_spec: str) -> StoryPrompt:
    prompt = (
        "STYLE SPECIFICATION\n"
        "===================\n"
        f"{style_spec.strip()}\n\n"
        "STORY CONCEPT\n"
        "=============\n"
        f"{concept.strip()}\n\n"
        "Write the complete storybook for this concept."
    )
    return StoryPrompt(system_instruction=SYSTEM_INSTRUCTION, prompt=prompt)


class StoryGenerator:
    def __init__(
        self,
        provider: TextGenerationProvider,
        style_spec: str,
        storybook_model: type[Storybook] = Storybook,
    ) -> None:
        """``storybook_model`` may be a Storybook subclass carrying extra metadata."""
        self._provider = provider
        self._style_spec = style_spec
        self._storybook_model = storybook_model

    @classmethod
    def from_style_file(
        cls, provider: TextGenerationProvider, style_file: Path, **kwargs
    ) -> StoryGenerator:
        return cls(provider, load_style_spec(style_file), **kwargs)

    def generate(self, concept: str) -> Storybook:
        request = build_story_prompt(concept, self._style_spec)
        data = self._provider.generate_structured(
            system_instruction=request.system_instruction,
            prompt=request.prompt,
            response_model=self._storybook_model,
        )
        try:
            storybook = self._storybook_model.model_validate(data)
        except ValidationError as exc:
            raise InvalidResponseError(
                f"generated story failed validation: {_short_errors(exc)}"
            ) from exc
        logger.debug(
            "Story validated: %r, %d pages, %d characters",
            storybook.title,
            len(storybook.pages),
            len(storybook.characters),
        )
        return storybook


def _short_errors(exc: ValidationError, limit: int = 5) -> str:
    parts = [
        f"{'.'.join(str(loc) for loc in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()[:limit]
    ]
    if exc.error_count() > limit:
        parts.append(f"... and {exc.error_count() - limit} more")
    return "; ".join(parts)
