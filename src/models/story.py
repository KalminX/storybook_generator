"""Domain models for a generated storybook.

These models double as the structured-output schema requested from the text
provider, so field descriptions are written for the model as well as for humans.

To add metadata required by a future style specification, subclass these models
(or add optional fields with defaults) - existing saved ``story.json`` files
stay loadable as long as new fields are optional.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _DomainModel(BaseModel):
    # Strip stray whitespace from model output; ignore unexpected extra keys
    # rather than failing a whole (expensive) story over them.
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class Character(_DomainModel):
    name: str = Field(min_length=1, description="The character's name as used in the story.")
    description: str = Field(
        min_length=1, description="Who the character is: role, personality, species."
    )
    appearance: str = Field(
        min_length=1,
        description="Precise, stable visual details: species, size, colors, "
        "distinguishing features. Used to keep illustrations consistent.",
    )
    clothing: str | None = Field(
        default=None, description="Clothing or accessories worn on every page, if any."
    )

    @field_validator("clothing")
    @classmethod
    def _blank_clothing_is_none(cls, value: str | None) -> str | None:
        return value or None


class StoryPage(_DomainModel):
    page_number: int = Field(ge=1, description="1-based page number.")
    text: str = Field(min_length=1, description="The story text printed on this page.")
    image_prompt: str = Field(
        min_length=1,
        description="A description of the illustration for this page: scene, "
        "characters present, action, setting, mood.",
    )


class Storybook(_DomainModel):
    title: str = Field(min_length=1, description="The book's title.")
    characters: list[Character] = Field(
        min_length=1, description="Every recurring character that appears in the illustrations."
    )
    pages: list[StoryPage] = Field(min_length=1, description="The pages in reading order.")

    @field_validator("pages")
    @classmethod
    def _pages_sorted_and_contiguous(cls, pages: list[StoryPage]) -> list[StoryPage]:
        pages = sorted(pages, key=lambda p: p.page_number)
        numbers = [p.page_number for p in pages]
        expected = list(range(1, len(pages) + 1))
        if numbers != expected:
            raise ValueError(
                f"page numbers must run 1..{len(pages)} without gaps or duplicates, got {numbers}"
            )
        return pages

    @model_validator(mode="after")
    def _unique_character_names(self) -> Storybook:
        seen: set[str] = set()
        for character in self.characters:
            key = character.name.casefold()
            if key in seen:
                raise ValueError(f"duplicate character name: {character.name!r}")
            seen.add(key)
        return self

    def page(self, page_number: int) -> StoryPage:
        """Return the page with the given number (raises KeyError if absent)."""
        for page in self.pages:
            if page.page_number == page_number:
                return page
        raise KeyError(page_number)
