"""Views for the Storybook Generator Django web app."""

from __future__ import annotations

import json
from pathlib import Path
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services


def index(request: HttpRequest) -> HttpResponse:
    """Dashboard / Library of all stories."""
    stories = services.list_all_stories()
    completed_count = sum(1 for s in stories if s["is_complete"])
    running_count = sum(1 for s in stories if s["is_running"])
    
    style_spec = services.get_style_spec_content()

    context = {
        "stories": stories,
        "total_stories": len(stories),
        "completed_count": completed_count,
        "running_count": running_count,
        "style_spec_preview": style_spec[:300] + "..." if len(style_spec) > 300 else style_spec,
    }
    return render(request, "story_app/index.html", context)


def create_story(request: HttpRequest) -> HttpResponse:
    """Form to configure and generate a new story."""
    if request.method == "POST":
        concept = request.POST.get("concept", "").strip()
        if not concept:
            messages.error(request, "Please enter a story concept or idea.")
            return redirect("story_create")

        try:
            story_id = services.start_story_job(concept)
            messages.success(request, f"Story generation started for: '{concept}'")
            return redirect("story_progress", story_id=story_id)
        except Exception as exc:
            messages.error(request, f"Failed to start story generation: {exc}")
            return redirect("story_create")

    context = {
        "style_spec": services.get_style_spec_content(),
    }
    return render(request, "story_app/create.html", context)


def story_progress(request: HttpRequest, story_id: str) -> HttpResponse:
    """Real-time progress monitoring view for a story."""
    story = services.get_story_details(story_id)
    if not story:
        story = {
            "story_id": story_id,
            "title": story_id.replace("-", " "),
            "concept": story_id.replace("-", " "),
            "state": None,
            "storybook": None,
            "character_bible": None,
            "pages": [],
            "has_pdf": False,
            "pdf_url": None,
            "is_running": services.is_job_running(story_id),
        }

    context = {
        "story": story,
        "story_id": story_id,
    }
    return render(request, "story_app/progress.html", context)


def story_reader(request: HttpRequest, story_id: str) -> HttpResponse:
    """Interactive digital storybook reader with GSAP page flips."""
    story = services.get_story_details(story_id)
    if not story:
        raise Http404("Story not found")

    context = {
        "story": story,
        "story_id": story_id,
        "storybook_json": json.dumps(story["storybook"].model_dump() if story["storybook"] else {}),
    }
    return render(request, "story_app/reader.html", context)


def story_events(request: HttpRequest, story_id: str) -> StreamingHttpResponse:
    """SSE endpoint streaming live progress updates."""
    response = StreamingHttpResponse(
        services.event_stream(story_id),
        content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def story_status_api(request: HttpRequest, story_id: str) -> JsonResponse:
    """JSON status API for dynamic client-side queries."""
    story = services.get_story_details(story_id)
    if not story:
        return JsonResponse({"error": "Not found"}, status=404)

    state = story["state"]
    return JsonResponse({
        "story_id": story_id,
        "title": story["title"],
        "status": state.status.value if state else "pending",
        "is_complete": state.is_complete if state else False,
        "story_generated": state.story_generated if state else False,
        "character_bible_generated": state.character_bible_generated if state else False,
        "pdf_generated": state.pdf_generated if state else False,
        "total_pages": len(story["pages"]),
        "pages": story["pages"],
        "has_pdf": story["has_pdf"],
        "pdf_url": story["pdf_url"],
        "is_running": story["is_running"],
        "percentage": story["progress_percentage"],
        "progress_message": story["progress_message"],
        "last_error": state.last_error if state else None,
    })


@require_POST
def regenerate_page(request: HttpRequest, story_id: str) -> HttpResponse:
    """Regenerate a specific page illustration."""
    page_number = int(request.POST.get("page_number", 1))
    custom_prompt = request.POST.get("custom_prompt", "").strip() or None

    success = services.regenerate_page_image(story_id, page_number, custom_prompt)
    if success:
        messages.success(request, f"Regenerating illustration for Page {page_number}...")
        return redirect("story_progress", story_id=story_id)
    else:
        messages.error(request, f"Could not regenerate page {page_number}.")
        return redirect("story_reader", story_id=story_id)


@require_POST
def resume_story(request: HttpRequest, story_id: str) -> HttpResponse:
    """Resume generation for an incomplete or interrupted story."""
    try:
        new_id = services.resume_story(story_id)
        messages.success(request, "Resuming storybook generation...")
        return redirect("story_reader", story_id=new_id or story_id)
    except Exception as exc:
        messages.error(request, f"Could not resume generation: {exc}")
        return redirect("story_reader", story_id=story_id)


@require_POST
def restart_story(request: HttpRequest, story_id: str) -> HttpResponse:
    """Restart generation for a story from scratch."""
    try:
        new_id = services.restart_story(story_id)
        messages.success(request, "Restarting storybook generation from scratch...")
        return redirect("story_reader", story_id=new_id or story_id)
    except Exception as exc:
        messages.error(request, f"Could not restart generation: {exc}")
        return redirect("story_reader", story_id=story_id)


@require_POST
def delete_story(request: HttpRequest, story_id: str) -> HttpResponse:
    """Delete a storybook directory."""
    if services.delete_story_folder(story_id):
        messages.success(request, "Story deleted successfully.")
    else:
        messages.error(request, "Could not delete story.")
    return redirect("story_index")


def settings_view(request: HttpRequest) -> HttpResponse:
    """View and update style specification and app settings."""
    if request.method == "POST":
        style_content = request.POST.get("style_spec", "")
        services.save_style_spec_content(style_content)
        messages.success(request, "Style specification saved successfully.")
        return redirect("settings")

    config = services.get_app_config()
    style_content = services.get_style_spec_content()

    context = {
        "config": config,
        "style_spec": style_content,
    }
    return render(request, "story_app/settings.html", context)


def download_pdf(request: HttpRequest, story_id: str) -> HttpResponse:
    """Download the storybook PDF."""
    config = services.get_app_config()
    pdf_path = config.paths.output_directory / story_id / "storybook.pdf"
    if not pdf_path.is_file():
        raise Http404("PDF not found")

    with open(pdf_path, "rb") as f:
        response = HttpResponse(f.read(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{story_id}.pdf"'
        return response
