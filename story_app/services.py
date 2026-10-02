"""Services layer bridging Django views with the Storybook Generator pipeline."""

from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from src.app import build_pipeline
from src.config import AppConfig, ConfigError, find_config_file, load_api_key, load_config
from src.models.concept import StoryConcept, make_story_id
from src.models.state import StoryState, StoryStatus
from src.models.story import Storybook
from src.pipeline.story_pipeline import StoryOutcome, StoryPipeline, StoryResult
from src.utils.filesystem import StoryPaths, atomic_write_json
from src.utils.inputs import load_style_spec

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Global in-memory broadcast queues for active SSE streams: story_id -> list of queues
_active_listeners: dict[str, list[queue.Queue]] = defaultdict(list)
_listeners_lock = threading.Lock()

# Active background jobs: story_id -> Thread
_running_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def get_project_root() -> Path:
    return PROJECT_ROOT


def get_app_config() -> AppConfig:
    config_file = find_config_file(PROJECT_ROOT)
    return load_config(config_file)


def get_api_key(config: AppConfig | None = None) -> str:
    if config is None:
        config = get_app_config()
    return load_api_key(config.provider.api_key_env, PROJECT_ROOT / ".env")


def broadcast_event(story_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Send an SSE event payload to all active listeners for a story."""
    payload = {
        "event": event_type,
        "story_id": story_id,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }
    with _listeners_lock:
        for q in _active_listeners.get(story_id, []):
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def register_listener(story_id: str) -> queue.Queue:
    q = queue.Queue(maxsize=100)
    with _listeners_lock:
        _active_listeners[story_id].append(q)
    return q


def unregister_listener(story_id: str, q: queue.Queue) -> None:
    with _listeners_lock:
        if story_id in _active_listeners and q in _active_listeners[story_id]:
            _active_listeners[story_id].remove(q)
            if not _active_listeners[story_id]:
                del _active_listeners[story_id]


def event_stream(story_id: str) -> Generator[str, None, None]:
    """Yields SSE formatted messages for story progress."""
    q = register_listener(story_id)
    try:
        # Initial ping
        state = get_story_state(story_id)
        init_payload = {
            "event": "state_update",
            "story_id": story_id,
            "data": state.model_dump(mode="json") if state else {"status": "pending"},
        }
        yield f"data: {json.dumps(init_payload)}\n\n"

        while True:
            try:
                msg = q.get(timeout=15.0)
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                # Keep-alive heartbeat
                yield f": heartbeat\n\n"
    finally:
        unregister_listener(story_id, q)


def is_job_running(story_id: str) -> bool:
    with _threads_lock:
        t = _running_threads.get(story_id)
        return t is not None and t.is_alive()


# In-memory progress tracking for active jobs
_job_progress: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def get_job_progress(story_id: str, state: StoryState | None = None) -> tuple[int, str]:
    """Returns (percentage: int, message: str) for a story."""
    with _jobs_lock:
        if story_id in _job_progress:
            info = _job_progress[story_id]
            return info.get("percentage", 10), info.get("message", "Processing...")

    if state is None:
        return 0, "Pending"

    if state.is_complete:
        return 100, "Complete"

    if state.status == StoryStatus.FAILED:
        return 0, state.last_error or "Failed"

    if not state.story_generated:
        return 15, "Writing story narrative..."

    if not state.character_bible_generated:
        return 28, "Designing character bible..."

    total_pages = len(state.pages)
    if total_pages > 0:
        done_pages = sum(1 for p in state.pages.values() if p.image_generated)
        if done_pages < total_pages:
            pct = 28 + int((done_pages / total_pages) * 64)
            return pct, f"Illustrating page {done_pages + 1} of {total_pages}..."
        elif not state.pdf_generated:
            return 95, "Compiling PDF layout..."

    if state.pdf_generated:
        return 100, "Complete"

    return 50, "Generating..."


def list_all_stories() -> list[dict[str, Any]]:
    """Return summary metadata for all storybooks in output/."""
    try:
        config = get_app_config()
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return []

    output_dir = config.paths.output_directory
    if not output_dir.exists():
        return []

    stories = []
    for item in output_dir.iterdir():
        if not item.is_dir() or item.name.startswith(("_", ".")):
            continue

        story_id = item.name
        paths = StoryPaths.for_story(output_dir, story_id)
        state_file = paths.state_json
        story_file = paths.story_json

        state_data: StoryState | None = None
        if state_file.is_file():
            try:
                state_data = StoryState.model_validate_json(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        story_title = None
        page_count = 0
        if story_file.is_file():
            try:
                storybook = Storybook.model_validate_json(story_file.read_text(encoding="utf-8"))
                story_title = storybook.title
                page_count = len(storybook.pages)
            except Exception:
                pass

        # Check pages available
        pages_dir = paths.pages_dir
        existing_images = []
        if pages_dir.is_dir():
            existing_images = sorted(pages_dir.glob("page-*.png"))

        cover_image_url = None
        if existing_images:
            first_page = existing_images[0]
            cover_image_url = f"/media/{story_id}/pages/{first_page.name}"

        pdf_url = None
        if paths.pdf.is_file():
            pdf_url = f"/media/{story_id}/storybook.pdf"

        status_str = state_data.status.value if state_data else "pending"
        running = is_job_running(story_id)
        if running:
            status_str = "in_progress"

        concept_text = state_data.concept if state_data else story_id.replace("-", " ")
        updated_at = state_data.updated_at if state_data else datetime.fromtimestamp(item.stat().st_mtime)

        pct, progress_msg = get_job_progress(story_id, state_data)

        stories.append({
            "story_id": story_id,
            "title": story_title or concept_text,
            "concept": concept_text,
            "status": status_str,
            "is_complete": state_data.is_complete if state_data else paths.pdf.is_file(),
            "page_count": page_count or len(existing_images),
            "generated_images_count": len(existing_images),
            "cover_image_url": cover_image_url,
            "pdf_url": pdf_url,
            "updated_at": updated_at,
            "last_error": state_data.last_error if state_data else None,
            "is_running": running,
            "progress_percentage": pct,
            "progress_message": progress_msg,
        })

    stories.sort(key=lambda s: s["updated_at"], reverse=True)
    return stories


def get_story_state(story_id: str) -> StoryState | None:
    config = get_app_config()
    paths = StoryPaths.for_story(config.paths.output_directory, story_id)
    if paths.state_json.is_file():
        try:
            return StoryState.model_validate_json(paths.state_json.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def get_story_details(story_id: str) -> dict[str, Any] | None:
    config = get_app_config()
    paths = StoryPaths.for_story(config.paths.output_directory, story_id)
    running = is_job_running(story_id)

    if not paths.root.is_dir() and not running:
        return None

    state = get_story_state(story_id)
    storybook: Storybook | None = None
    if paths.story_json.is_file():
        try:
            storybook = Storybook.model_validate_json(paths.story_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    character_bible_data = None
    if paths.character_bible_json.is_file():
        try:
            character_bible_data = json.loads(paths.character_bible_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    pages_list = []
    if storybook:
        for p in storybook.pages:
            img_path = paths.page_image(p.page_number)
            has_img = img_path.is_file()
            pages_list.append({
                "page_number": p.page_number,
                "text": p.text,
                "image_prompt": p.image_prompt,
                "has_image": has_img,
                "image_url": f"/media/{story_id}/pages/page-{p.page_number:03d}.png" if has_img else None,
            })
    elif paths.pages_dir.is_dir():
        for img_file in sorted(paths.pages_dir.glob("page-*.png")):
            try:
                num = int(img_file.stem.split("-")[1])
                pages_list.append({
                    "page_number": num,
                    "text": f"Page {num}",
                    "image_prompt": "",
                    "has_image": True,
                    "image_url": f"/media/{story_id}/pages/{img_file.name}",
                })
            except Exception:
                pass

    pct, progress_msg = get_job_progress(story_id, state)

    return {
        "story_id": story_id,
        "title": storybook.title if storybook else (state.concept if state else story_id.replace("-", " ")),
        "concept": state.concept if state else story_id.replace("-", " "),
        "state": state,
        "storybook": storybook,
        "character_bible": character_bible_data,
        "pages": pages_list,
        "has_pdf": paths.pdf.is_file(),
        "pdf_url": f"/media/{story_id}/storybook.pdf" if paths.pdf.is_file() else None,
        "is_running": running,
        "progress_percentage": pct,
        "progress_message": progress_msg,
    }


def start_story_job(concept_text: str, force_pages: list[int] | None = None) -> str:
    """Kick off background generation for a story concept."""
    config = get_app_config()
    api_key = get_api_key(config)
    concept_id = make_story_id(concept_text)
    concept = StoryConcept(story_id=concept_id, text=concept_text.strip(), line_number=1)

    # Ensure paths and initial checkpoint exist immediately before spawning thread
    from src.infrastructure.checkpoint import CheckpointStore
    paths = StoryPaths.for_story(config.paths.output_directory, concept_id)
    paths.ensure()
    store = CheckpointStore(paths.state_json)
    state = store.load_or_create(concept_id, concept.text)
    store.save(state)

    if is_job_running(concept_id):
        logger.warning(f"Story {concept_id} is already generating.")
        return concept_id

    def on_progress(stage: str, percentage: int, message: str):
        with _jobs_lock:
            _job_progress[concept_id] = {
                "stage": stage,
                "percentage": percentage,
                "message": message,
                "updated_at": time.time(),
            }
        broadcast_event(concept_id, "progress", {
            "stage": stage,
            "percentage": percentage,
            "message": message,
        })

    def worker():
        logger.info(f"Starting generation worker for story: {concept_id}")
        on_progress("started", 5, f"Starting book: '{concept_text}'")
        try:
            pipeline = build_pipeline(config, api_key)
            result = pipeline.run(concept, force_pages=force_pages or (), on_progress=on_progress)
            if result.outcome == StoryOutcome.COMPLETED:
                on_progress("completed", 100, f"Storybook '{result.title}' ready!")
                broadcast_event(concept_id, "completed", {
                    "outcome": result.outcome.value,
                    "title": result.title,
                    "elapsed": result.elapsed_seconds,
                })
            else:
                on_progress("failed", 0, result.error or "Generation failed")
                broadcast_event(concept_id, "failed", {
                    "outcome": result.outcome.value,
                    "error": result.error,
                })
        except Exception as exc:
            logger.exception(f"Worker exception for story {concept_id}: {exc}")
            on_progress("failed", 0, str(exc))
            broadcast_event(concept_id, "error", {"error": str(exc)})
        finally:
            with _threads_lock:
                _running_threads.pop(concept_id, None)
            with _jobs_lock:
                _job_progress.pop(concept_id, None)

    thread = threading.Thread(target=worker, daemon=True, name=f"StoryGen-{concept_id}")
    with _threads_lock:
        _running_threads[concept_id] = thread
    thread.start()

    return concept_id


def regenerate_page_image(story_id: str, page_number: int, custom_prompt: str | None = None) -> bool:
    """Regenerate a single page image with optional custom prompt."""
    config = get_app_config()
    paths = StoryPaths.for_story(config.paths.output_directory, story_id)
    if not paths.story_json.is_file():
        return False

    storybook = Storybook.model_validate_json(paths.story_json.read_text(encoding="utf-8"))
    
    # Update prompt if provided
    if custom_prompt and custom_prompt.strip():
        updated_pages = []
        for p in storybook.pages:
            if p.page_number == page_number:
                updated_pages.append(p.model_copy(update={"image_prompt": custom_prompt.strip()}))
            else:
                updated_pages.append(p)
        storybook = storybook.model_copy(update={"pages": updated_pages})
        atomic_write_json(paths.story_json, storybook)

    state = get_story_state(story_id)
    concept_text = state.concept if state else storybook.title
    start_story_job(concept_text, force_pages=[page_number])
    return True


def resume_story(story_id: str) -> str | None:
    """Resume an interrupted or failed story generation from its saved checkpoint."""
    state = get_story_state(story_id)
    if state and state.concept:
        concept_text = state.concept
    else:
        config = get_app_config()
        paths = StoryPaths.for_story(config.paths.output_directory, story_id)
        if paths.story_json.is_file():
            try:
                sb = Storybook.model_validate_json(paths.story_json.read_text(encoding="utf-8"))
                concept_text = sb.title
            except Exception:
                concept_text = story_id.replace("-", " ")
        else:
            concept_text = story_id.replace("-", " ")

    return start_story_job(concept_text)


def restart_story(story_id: str) -> str | None:
    """Restart a storybook generation completely from scratch."""
    config = get_app_config()
    paths = StoryPaths.for_story(config.paths.output_directory, story_id)
    state = get_story_state(story_id)
    concept_text = state.concept if state else story_id.replace("-", " ")

    # Reset state and remove old pages
    if paths.state_json.is_file():
        paths.state_json.unlink(missing_ok=True)
    if paths.story_json.is_file():
        paths.story_json.unlink(missing_ok=True)
    if paths.character_bible_json.is_file():
        paths.character_bible_json.unlink(missing_ok=True)
    if paths.pdf.is_file():
        paths.pdf.unlink(missing_ok=True)
    if paths.pages_dir.is_dir():
        shutil.rmtree(paths.pages_dir, ignore_errors=True)

    return start_story_job(concept_text)


def delete_story_folder(story_id: str) -> bool:
    config = get_app_config()
    paths = StoryPaths.for_story(config.paths.output_directory, story_id)
    if paths.root.is_dir():
        shutil.rmtree(paths.root)
        return True
    return False


def get_style_spec_content() -> str:
    config = get_app_config()
    if config.paths.style_file.is_file():
        return config.paths.style_file.read_text(encoding="utf-8")
    return ""


def save_style_spec_content(content: str) -> None:
    config = get_app_config()
    config.paths.style_file.write_text(content, encoding="utf-8")
