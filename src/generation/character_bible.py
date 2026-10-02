"""Builds the character bible from a generated story.

The bible is derived deterministically from the Storybook (no API call), so it
is free to rebuild and identical on every run. It is kept separate from any
provider so richer strategies - e.g. a model-written reference sheet or a
generated character portrait - can replace it later without touching callers.
"""

from __future__ import annotations

from src.models.character_bible import CharacterBible, CharacterReference
from src.models.story import Storybook


def build_character_bible(storybook: Storybook) -> CharacterBible:
    return CharacterBible(
        title=storybook.title,
        characters=[
            CharacterReference(
                name=character.name,
                role=character.description,
                appearance=character.appearance,
                clothing=character.clothing,
            )
            for character in storybook.characters
        ],
    )
