import os
from pathlib import Path

import pytest

from src.models.state import StoryState
from src.utils.filesystem import (
    StoryPaths,
    atomic_write_bytes,
    atomic_write_json,
    ensure_writable_directory,
    read_json,
)
from src.utils.inputs import InputError, load_concepts, load_style_spec, parse_concepts


class TestStoryPaths:
    def test_layout(self, tmp_path):
        paths = StoryPaths.for_story(tmp_path, "fox-1234abcd")
        assert paths.root == tmp_path / "fox-1234abcd"
        assert paths.story_json.name == "story.json"
        assert paths.state_json.name == "state.json"
        assert paths.character_bible_json.name == "character_bible.json"
        assert paths.page_image(3) == paths.root / "pages" / "page-003.png"
        assert paths.pdf.name == "storybook.pdf"

    @pytest.mark.parametrize("bad_id", ["", "../escape", "a/b", ".hidden"])
    def test_rejects_unsafe_ids(self, tmp_path, bad_id):
        with pytest.raises(ValueError):
            StoryPaths.for_story(tmp_path, bad_id)

    def test_rejects_page_zero(self, tmp_path):
        with pytest.raises(ValueError):
            StoryPaths.for_story(tmp_path, "s").page_image(0)

    def test_ensure_does_not_touch_existing_files(self, tmp_path):
        paths = StoryPaths.for_story(tmp_path, "s")
        paths.ensure()
        paths.story_json.write_text("keep me")
        paths.ensure()
        assert paths.pages_dir.is_dir()
        assert paths.story_json.read_text() == "keep me"


class TestAtomicWrites:
    def test_writes_and_overwrites(self, tmp_path):
        target = tmp_path / "nested" / "file.bin"
        atomic_write_bytes(target, b"one")
        atomic_write_bytes(target, b"two")
        assert target.read_bytes() == b"two"
        assert os.listdir(target.parent) == ["file.bin"]  # no temp files left

    def test_written_files_get_normal_permissions(self, tmp_path):
        target = tmp_path / "file.bin"
        atomic_write_bytes(target, b"data")
        umask = os.umask(0)
        os.umask(umask)
        assert target.stat().st_mode & 0o777 == 0o666 & ~umask

    def test_failed_write_keeps_previous_content(self, tmp_path, monkeypatch):
        target = tmp_path / "state.json"
        atomic_write_bytes(target, b"original")

        def explode(*_):
            raise OSError("disk full")

        monkeypatch.setattr("src.utils.filesystem.os.replace", explode)
        with pytest.raises(OSError):
            atomic_write_bytes(target, b"corrupt")
        assert target.read_bytes() == b"original"
        assert os.listdir(tmp_path) == ["state.json"]

    def test_json_accepts_pydantic_models(self, tmp_path):
        state = StoryState(story_id="s", concept="A fox")
        state.mark_story_generated([1])
        atomic_write_json(tmp_path / "state.json", state)
        assert StoryState.model_validate(read_json(tmp_path / "state.json")) == state

    def test_ensure_writable_directory(self, tmp_path):
        target = tmp_path / "out"
        ensure_writable_directory(target)
        assert target.is_dir()
        assert list(target.iterdir()) == []


class TestInputs:
    def test_parses_concepts_skipping_blanks_comments_and_duplicates(self):
        text = "# header\nA fox.\n\n  A   penguin.  \nA fox.\n"
        concepts = parse_concepts(text)
        assert [c.text for c in concepts] == ["A fox.", "A penguin."]
        assert [c.line_number for c in concepts] == [2, 4]

    def test_ids_do_not_depend_on_line_order(self):
        first = parse_concepts("A fox.\nA penguin.")
        second = parse_concepts("A new story.\nA penguin.\nA fox.")
        ids = {c.text: c.story_id for c in second}
        for concept in first:
            assert ids[concept.text] == concept.story_id

    def test_load_concepts_errors(self, tmp_path):
        with pytest.raises(InputError, match="not found"):
            load_concepts(tmp_path / "missing.txt")
        empty = tmp_path / "stories.txt"
        empty.write_text("# only a comment\n\n")
        with pytest.raises(InputError, match="No story concepts"):
            load_concepts(empty)

    def test_load_concepts_handles_utf8_bom(self, tmp_path):
        path = tmp_path / "stories.txt"
        path.write_bytes("﻿A fox.\n".encode("utf-8"))
        assert load_concepts(path)[0].text == "A fox."

    def test_style_spec_returned_verbatim(self, tmp_path):
        path = tmp_path / "style.md"
        path.write_text("# Style\n\n  Watercolor.  \n")
        assert load_style_spec(path) == "# Style\n\n  Watercolor.  \n"

    def test_style_spec_errors(self, tmp_path):
        with pytest.raises(InputError, match="not found"):
            load_style_spec(tmp_path / "missing.md")
        blank = tmp_path / "blank.md"
        blank.write_text("  \n")
        with pytest.raises(InputError, match="empty"):
            load_style_spec(blank)

    def test_shipped_example_inputs_parse(self):
        root = Path(__file__).resolve().parent.parent
        assert len(load_concepts(root / "input" / "stories.txt")) == 3
        assert load_style_spec(root / "input" / "style_spec.md")
