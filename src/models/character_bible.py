"""The character bible: a fixed visual reference shared by every page illustration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CharacterReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    appearance: str = Field(min_length=1)
    clothing: str | None = None


class CharacterBible(BaseModel):
    title: str
    characters: list[CharacterReference] = Field(min_length=1)

    def to_prompt_text(self) -> str:
        """Render as plain text for inclusion in an image prompt."""
        blocks = []
        for character in self.characters:
            lines = [
                f"{character.name}",
                f"  Who: {character.role}",
                f"  Appearance: {character.appearance}",
            ]
            if character.clothing:
                lines.append(f"  Always wears: {character.clothing}")
            else:
                # Without this, image models tend to invent accessories that
                # then appear on some pages and not others.
                lines.append("  Clothing: none - do not add clothing or accessories")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
