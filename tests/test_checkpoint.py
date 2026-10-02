import pytest

from src.infrastructure.checkpoint import CheckpointStore
from src.models.state import StoryState, StoryStatus


@pytest.fixture
def store(tmp_path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "story" / "state.json")


def test_missing_checkpoint_loads_as_none(store):
    assert store.load() is None


def test_round_trip(store):
    state = StoryState(story_id="s1", concept="A fox")
    state.mark_story_generated([1, 2, 3])
    state.mark_page_image_generated(1, "pages/page-001.png")
    state.set_status(StoryStatus.GENERATING_IMAGES)
    store.save(state)

    loaded = store.load()
    assert loaded == state
    assert loaded.pending_pages() == [2, 3]


def test_load_or_create(store):
    created = store.load_or_create("s1", "A fox")
    assert created.status == StoryStatus.PENDING
    assert not store.path.exists()  # creating does not save
    created.mark_story_generated([1])
    store.save(created)
    assert store.load_or_create("s1", "A fox").story_generated


@pytest.mark.parametrize("content", ["{not json", '{"story_id": "s1"}', "[]"])
def test_corrupt_checkpoint_is_quarantined_not_deleted(store, content, caplog):
    store.path.parent.mkdir(parents=True)
    store.path.write_text(content)

    assert store.load() is None

    leftovers = list(store.path.parent.glob("state.json.corrupt-*"))
    assert len(leftovers) == 1
    assert leftovers[0].read_text() == content
    assert not store.path.exists()
    assert "unreadable" in caplog.text


def test_failed_save_keeps_previous_checkpoint(store, monkeypatch):
    original = StoryState(story_id="s1", concept="A fox")
    store.save(original)

    def explode(*_):
        raise OSError("disk full")

    monkeypatch.setattr("src.utils.filesystem.os.replace", explode)
    changed = original.model_copy(deep=True)
    changed.mark_story_generated([1, 2])
    with pytest.raises(OSError):
        store.save(changed)

    monkeypatch.undo()
    assert store.load() == original
