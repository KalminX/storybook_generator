import json

import pytest
from pydantic import ValidationError

from src.models.concept import make_story_id
from src.models.state import StoryState, StoryStatus
from src.models.story import Character, Storybook, StoryPage


def make_storybook(**overrides) -> dict:
    data = {
        "title": "The Hidden Garden",
        "characters": [
            {"name": "Fern", "description": "A curious fox", "appearance": "Small red fox"}
        ],
        "pages": [
            {"page_number": 1, "text": "Fern woke up.", "image_prompt": "Fox in den"},
            {"page_number": 2, "text": "She found a gate.", "image_prompt": "Fox at gate"},
        ],
    }
    data.update(overrides)
    return data


class TestStorybook:
    def test_valid_storybook_roundtrips_through_json(self):
        book = Storybook.model_validate(make_storybook())
        restored = Storybook.model_validate_json(book.model_dump_json())
        assert restored == book

    def test_strips_whitespace_and_blank_clothing_becomes_none(self):
        character = Character(name="  Fern ", description="fox", appearance="red", clothing="  ")
        assert character.name == "Fern"
        assert character.clothing is None

    def test_pages_are_sorted(self):
        data = make_storybook()
        data["pages"].reverse()
        book = Storybook.model_validate(data)
        assert [p.page_number for p in book.pages] == [1, 2]

    @pytest.mark.parametrize("numbers", [[1, 3], [2, 3], [1, 1]])
    def test_rejects_non_contiguous_page_numbers(self, numbers):
        pages = [{"page_number": n, "text": "t", "image_prompt": "p"} for n in numbers]
        with pytest.raises(ValidationError, match="page numbers"):
            Storybook.model_validate(make_storybook(pages=pages))

    def test_rejects_empty_pages_and_characters(self):
        with pytest.raises(ValidationError):
            Storybook.model_validate(make_storybook(pages=[]))
        with pytest.raises(ValidationError):
            Storybook.model_validate(make_storybook(characters=[]))

    def test_rejects_duplicate_character_names(self):
        fern = {"name": "Fern", "description": "d", "appearance": "a"}
        with pytest.raises(ValidationError, match="duplicate"):
            Storybook.model_validate(make_storybook(characters=[fern, {**fern, "name": "fern"}]))

    def test_rejects_empty_text(self):
        with pytest.raises(ValidationError):
            StoryPage(page_number=1, text="   ", image_prompt="p")

    def test_ignores_unexpected_fields(self):
        book = Storybook.model_validate(make_storybook(moral="Be brave"))
        assert "moral" not in book.model_dump()

    def test_page_lookup(self):
        book = Storybook.model_validate(make_storybook())
        assert book.page(2).text == "She found a gate."
        with pytest.raises(KeyError):
            book.page(9)


class TestStoryId:
    def test_is_stable_and_readable(self):
        story_id = make_story_id("A young fox discovers a hidden garden.")
        assert story_id == make_story_id("A young fox discovers a hidden garden.")
        assert story_id.startswith("a-young-fox-discovers-a-hidden-garden-")

    def test_ignores_whitespace_and_case_differences(self):
        assert make_story_id("A  young fox ") == make_story_id("a young FOX")

    def test_differs_for_different_concepts(self):
        assert make_story_id("A fox") != make_story_id("A penguin")

    def test_non_ascii_concept_still_gets_safe_id(self):
        story_id = make_story_id("小さな狐")
        assert story_id.startswith("story-")
        assert "/" not in story_id

    def test_long_concepts_are_truncated_on_word_boundary(self):
        story_id = make_story_id("word " * 50)
        slug = story_id.rsplit("-", 1)[0]
        assert len(slug) <= 40
        assert not slug.endswith("-")


class TestStoryState:
    def make_state(self) -> StoryState:
        state = StoryState(story_id="s1", concept="A fox")
        state.mark_story_generated([1, 2, 3])
        return state

    def test_new_state_is_pending(self):
        state = StoryState(story_id="s1", concept="A fox")
        assert state.status == StoryStatus.PENDING
        assert not state.story_generated
        assert state.pending_pages() == []
        assert not state.all_images_generated

    def test_pending_pages_in_order(self):
        state = self.make_state()
        state.mark_page_image_generated(2, "pages/page-002.png")
        assert state.pending_pages() == [1, 3]

    def test_registering_pages_again_keeps_progress(self):
        state = self.make_state()
        state.mark_page_image_generated(1, "pages/page-001.png")
        state.mark_story_generated([1, 2, 3])
        assert state.pages[1].image_generated

    def test_unknown_page_raises(self):
        with pytest.raises(KeyError):
            self.make_state().mark_page_image_generated(9, "x.png")

    def test_cannot_complete_with_steps_remaining(self):
        state = self.make_state()
        with pytest.raises(ValueError):
            state.mark_completed()

    def test_full_lifecycle(self):
        state = self.make_state()
        for n in (1, 2, 3):
            state.mark_page_image_generated(n, f"pages/page-{n:03d}.png")
        state.mark_pdf_generated()
        state.mark_completed()
        assert state.is_complete
        assert state.completed_at is not None

    def test_failure_keeps_progress_and_records_stage(self):
        state = self.make_state()
        state.mark_page_image_generated(1, "pages/page-001.png")
        state.set_status(StoryStatus.GENERATING_IMAGES)
        state.mark_failed("boom")
        assert state.status == StoryStatus.FAILED
        assert state.failed_stage == StoryStatus.GENERATING_IMAGES
        assert state.pages[1].image_generated
        state.mark_failed("boom again")
        assert state.failed_stage == StoryStatus.GENERATING_IMAGES

    def test_reset_page_invalidates_pdf(self):
        state = self.make_state()
        state.mark_page_image_generated(1, "pages/page-001.png")
        state.mark_pdf_generated()
        state.reset_page(1)
        assert state.pending_pages() == [1, 2, 3]
        assert not state.pdf_generated

    def test_json_roundtrip_with_integer_page_keys(self):
        state = self.make_state()
        state.mark_page_image_generated(1, "pages/page-001.png")
        raw = json.loads(state.model_dump_json())
        assert set(raw["pages"]) == {"1", "2", "3"}
        restored = StoryState.model_validate(raw)
        assert restored.pages[1].image_generated
        assert restored == state


def test_registering_fewer_pages_drops_the_rest():
    state = StoryState(story_id="s1", concept="A fox")
    state.mark_story_generated([1, 2, 3])
    state.mark_page_image_generated(1, "pages/page-001.png")
    state.mark_story_generated([1, 2])
    assert sorted(state.pages) == [1, 2]
    assert state.pages[1].image_generated


def test_invalidate_story_clears_derived_progress():
    state = StoryState(story_id="s1", concept="A fox")
    state.mark_story_generated([1])
    state.mark_character_bible_generated()
    state.mark_page_image_generated(1, "pages/page-001.png")
    state.mark_pdf_generated()
    state.invalidate_story()
    assert not (state.story_generated or state.character_bible_generated or state.pdf_generated)
    assert state.pages == {}
