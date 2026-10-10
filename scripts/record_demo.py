#!/usr/bin/env python3
"""Script to record a 720p walkthrough of Storybook Studio with custom cursor & click indicators."""

import os
import sys
import time
import math
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

CURSOR_SCRIPT = """
(() => {
    if (window.__cursor_initialized) return;
    window.__cursor_initialized = true;

    const style = document.createElement('style');
    style.innerHTML = `
        #custom-mouse-cursor {
            position: fixed;
            top: 0;
            left: 0;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: rgba(14, 165, 233, 0.85);
            border: 2.5px solid #ffffff;
            box-shadow: 0 0 12px rgba(14, 165, 233, 0.9), 0 0 24px rgba(14, 165, 233, 0.4);
            pointer-events: none;
            z-index: 99999999;
            transform: translate(-50%, -50%);
            transition: transform 0.08s ease-out, background-color 0.15s ease;
        }
        #custom-mouse-cursor::after {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 5px;
            height: 5px;
            background: #ffffff;
            border-radius: 50%;
            transform: translate(-50%, -50%);
        }
        #custom-mouse-cursor.clicking {
            transform: translate(-50%, -50%) scale(0.75);
            background: rgba(245, 158, 11, 0.95);
            border-color: #ffffff;
            box-shadow: 0 0 16px rgba(245, 158, 11, 0.9);
        }
        .click-ripple {
            position: fixed;
            border-radius: 50%;
            border: 2.5px solid #38bdf8;
            background: radial-gradient(circle, rgba(56, 189, 248, 0.4) 0%, rgba(56, 189, 248, 0) 70%);
            pointer-events: none;
            z-index: 99999998;
            transform: translate(-50%, -50%) scale(0);
            animation: ripple-animation 0.5s cubic-bezier(0.1, 0.8, 0.3, 1) forwards;
        }
        @keyframes ripple-animation {
            0% {
                width: 10px;
                height: 10px;
                opacity: 1;
                transform: translate(-50%, -50%) scale(0.3);
            }
            40% {
                opacity: 0.9;
            }
            100% {
                width: 65px;
                height: 65px;
                opacity: 0;
                transform: translate(-50%, -50%) scale(1.6);
            }
        }
    `;
    document.head.appendChild(style);

    const cursor = document.createElement('div');
    cursor.id = 'custom-mouse-cursor';
    document.body.appendChild(cursor);

    window.__currentX = window.innerWidth / 2;
    window.__currentY = window.innerHeight / 2;
    cursor.style.left = `${window.__currentX}px`;
    cursor.style.top = `${window.__currentY}px`;

    window.addEventListener('mousemove', (e) => {
        window.__currentX = e.clientX;
        window.__currentY = e.clientY;
        cursor.style.left = `${e.clientX}px`;
        cursor.style.top = `${e.clientY}px`;
    }, { passive: true });

    window.addEventListener('mousedown', (e) => {
        cursor.classList.add('clicking');
        const ripple = document.createElement('div');
        ripple.className = 'click-ripple';
        ripple.style.left = `${e.clientX}px`;
        ripple.style.top = `${e.clientY}px`;
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 550);
    }, { passive: true });

    window.addEventListener('mouseup', () => {
        cursor.classList.remove('clicking');
    }, { passive: true });
})();
"""

def smooth_move(page, start_x, start_y, target_x, target_y, duration=0.35, steps=25):
    """Move the mouse smoothly from start to target with natural ease-in-out curve."""
    for i in range(1, steps + 1):
        t = i / steps
        ease = 0.5 * (1 - math.cos(math.pi * t))
        cur_x = start_x + (target_x - start_x) * ease
        cur_y = start_y + (target_y - start_y) * ease
        page.mouse.move(cur_x, cur_y)
        time.sleep(duration / steps)
    return target_x, target_y

def smooth_click(page, cur_pos, target_x, target_y, wait_after=0.3, duration=0.35):
    """Smoothly move to position and click."""
    cur_x, cur_y = cur_pos
    cur_x, cur_y = smooth_move(page, cur_x, cur_y, target_x, target_y, duration=duration, steps=20)
    time.sleep(0.08)
    page.mouse.down()
    time.sleep(0.12)
    page.mouse.up()
    time.sleep(wait_after)
    return cur_x, cur_y

def smooth_click_element(page, cur_pos, selector_or_locator, wait_after=0.3, offset_x=0, offset_y=0, duration=0.35):
    """Find element box, smoothly move to center and click."""
    if isinstance(selector_or_locator, str):
        loc = page.locator(selector_or_locator).first
    else:
        loc = selector_or_locator
    try:
        loc.wait_for(state="visible", timeout=4000)
    except Exception:
        pass
    box = loc.bounding_box()
    if box:
        tx = box['x'] + box['width'] / 2 + offset_x
        ty = box['y'] + box['height'] / 2 + offset_y
        return smooth_click(page, cur_pos, tx, ty, wait_after=wait_after, duration=duration)
    return cur_pos

def smooth_hover_element(page, cur_pos, selector_or_locator, hover_time=0.4, duration=0.35):
    """Find element box and smoothly hover over it."""
    if isinstance(selector_or_locator, str):
        loc = page.locator(selector_or_locator).first
    else:
        loc = selector_or_locator
    try:
        loc.wait_for(state="visible", timeout=4000)
    except Exception:
        pass
    box = loc.bounding_box()
    if box:
        tx = box['x'] + box['width'] / 2
        ty = box['y'] + box['height'] / 2
        cur_x, cur_y = smooth_move(page, cur_pos[0], cur_pos[1], tx, ty, duration=duration, steps=20)
        time.sleep(hover_time)
        return cur_x, cur_y
    return cur_pos

def smooth_type(page, text, delay=0.04):
    """Type text with realistic keystroke delay."""
    for char in text:
        page.keyboard.type(char)
        time.sleep(delay)

def record_walkthrough():
    video_temp_dir = Path("/tmp/storybook_playwright_video")
    video_temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Remove older video files
    for f in video_temp_dir.glob("*.webm"):
        f.unlink(missing_ok=True)

    target_video_path = Path("/Users/kalmin/projects/storybook_generator/storybook_demo_720p.mp4")

    print("🚀 Launching Chromium recorder at 1280x720...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--hide-scrollbars"
            ]
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(video_temp_dir),
            record_video_size={"width": 1280, "height": 720},
        )

        # Inject cursor script on every frame navigation
        context.add_init_script(CURSOR_SCRIPT)

        page = context.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})

        # Start position of cursor
        cur_pos = (640, 360)

        # ----------------------------------------------------
        # SCENE 1: Library Dashboard
        # ----------------------------------------------------
        print("🎬 Scene 1: Library Dashboard Tour...")
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        time.sleep(1.0)
        cur_pos = (640, 360)

        # Hover over Header & Stats badge
        cur_pos = smooth_hover_element(page, cur_pos, "header a", hover_time=0.5)
        cur_pos = smooth_hover_element(page, cur_pos, "div.flex.items-center.space-x-4", hover_time=0.8)

        # Search bar interaction
        print("  -> Interacting with Search Bar...")
        cur_pos = smooth_click_element(page, cur_pos, "#search-input", wait_after=0.3)
        smooth_type(page, "Secret Garden", delay=0.06)
        time.sleep(0.8)

        # Hover over filtered result
        cur_pos = smooth_hover_element(page, cur_pos, ".story-card", hover_time=0.8)

        # Clear search
        cur_pos = smooth_click_element(page, cur_pos, "#search-input", wait_after=0.2)
        page.keyboard.press("Meta+A")
        time.sleep(0.1)
        page.keyboard.press("Backspace")
        time.sleep(0.8)

        # Filter buttons
        print("  -> Testing Category Filters...")
        cur_pos = smooth_click_element(page, cur_pos, 'button[data-filter="completed"]', wait_after=0.5)
        cur_pos = smooth_click_element(page, cur_pos, 'button[data-filter="all"]', wait_after=0.5)

        # Hover over multiple story cards
        cards = page.locator(".story-card")
        card_count = cards.count()
        for idx in range(min(card_count, 3)):
            cur_pos = smooth_hover_element(page, cur_pos, cards.nth(idx), hover_time=0.6)

        # ----------------------------------------------------
        # SCENE 2: Create Story Studio Flow
        # ----------------------------------------------------
        print("🎬 Scene 2: Create Story Studio...")
        cur_pos = smooth_click_element(page, cur_pos, 'a[href="/create/"]', wait_after=1.2)

        # Hover over suggestion chips
        chips = page.locator("#suggestion-chips button")
        chip_count = chips.count()
        if chip_count > 0:
            cur_pos = smooth_hover_element(page, cur_pos, chips.nth(0), hover_time=0.4)
            cur_pos = smooth_hover_element(page, cur_pos, chips.nth(1), hover_time=0.4)
            print("  -> Clicking Concept Suggestion Chip...")
            cur_pos = smooth_click_element(page, cur_pos, chips.nth(1), wait_after=0.8)

        # Focus into textarea and customize prompt
        print("  -> Editing Story Concept...")
        cur_pos = smooth_click_element(page, cur_pos, "#concept", wait_after=0.3)
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        time.sleep(0.2)
        smooth_type(page, "A curious little robot who discovers an enchanted garden in deep space.", delay=0.04)
        time.sleep(0.6)

        # Hover over style spec info link
        cur_pos = smooth_hover_element(page, cur_pos, 'a[href="/settings/"]', hover_time=0.5)

        # Hover over Generate button
        cur_pos = smooth_hover_element(page, cur_pos, "#submit-btn", hover_time=0.8)
        time.sleep(0.5)

        # ----------------------------------------------------
        # SCENE 3: Interactive Reader & Deep Feature Tour
        # ----------------------------------------------------
        print("🎬 Scene 3: Interactive Book Reader...")
        # Navigate back to library to open a book
        cur_pos = smooth_click_element(page, cur_pos, 'a[href="/"]', wait_after=1.0)
        
        # Click on "The Secret Garden Door" (a-young-fox-discovers-a-hidden-garden-db627fcf)
        cur_pos = smooth_click_element(page, cur_pos, 'div[data-title*="secret garden"]', wait_after=1.5)

        # Let the reader spread settle
        time.sleep(1.2)

        # Hover over book title and concept
        cur_pos = smooth_hover_element(page, cur_pos, "#workspace-title", hover_time=0.5)

        # Page turning demonstration
        print("  -> Turning Pages in Interactive Reader...")
        for turn in range(3):
            cur_pos = smooth_click_element(page, cur_pos, "#btn-next", wait_after=1.3, duration=0.25)

        print("  -> Flipping back a page...")
        cur_pos = smooth_click_element(page, cur_pos, "#btn-prev", wait_after=1.0, duration=0.25)

        # Click on artwork to test Zoom Modal
        print("  -> Expanding Artwork zoom modal...")
        cur_pos = smooth_click_element(page, cur_pos, "#reader-art-page", wait_after=1.0)
        cur_pos = smooth_click_element(page, cur_pos, "#btn-close-zoom", wait_after=0.6)

        # Click thumbnail in scrubber strip
        print("  -> Clicking scrubber thumbnail...")
        thumbnails = page.locator("#thumbnails-track button")
        if thumbnails.count() > 4:
            cur_pos = smooth_click_element(page, cur_pos, thumbnails.nth(4), wait_after=1.0)

        # Trigger narration / Read aloud
        print("  -> Testing Read Aloud narration feature...")
        cur_pos = smooth_click_element(page, cur_pos, "#btn-narrate", wait_after=1.0)

        # Switch to All Pages Grid
        print("  -> Switching to 'All Pages' Grid view...")
        cur_pos = smooth_click_element(page, cur_pos, "#tab-grid", wait_after=1.0)
        
        # Hover across thumbnails in the grid
        grid_items = page.locator("#all-pages-grid > div")
        grid_count = grid_items.count()
        for idx in range(min(grid_count, 4)):
            cur_pos = smooth_hover_element(page, cur_pos, grid_items.nth(idx), hover_time=0.4)

        # Switch to Character Bible
        print("  -> Switching to 'Characters' Bible view...")
        bible_tab = page.locator("#tab-bible")
        if bible_tab.is_visible():
            cur_pos = smooth_click_element(page, cur_pos, "#tab-bible", wait_after=1.2)
            # Hover over character cards
            char_cards = page.locator("#view-bible-container .rounded-xl")
            if char_cards.count() > 0:
                cur_pos = smooth_hover_element(page, cur_pos, char_cards.first, hover_time=1.0)

        # Switch back to Reader
        print("  -> Returning to Reader mode...")
        cur_pos = smooth_click_element(page, cur_pos, "#tab-reader", wait_after=0.8)

        # Test Redo Page Modal
        print("  -> Testing Redo Page illustration modal...")
        redo_btn = page.locator("#btn-open-redo")
        if redo_btn.is_visible():
            cur_pos = smooth_click_element(page, cur_pos, "#btn-open-redo", wait_after=1.0)
            modal = page.locator("#redo-modal")
            if modal.is_visible():
                # Hover over prompt input inside modal
                cur_pos = smooth_hover_element(page, cur_pos, "#textarea-redo-prompt", hover_time=0.6)
                # Close modal
                cur_pos = smooth_click_element(page, cur_pos, "#btn-cancel-redo", wait_after=0.6)

        # Hover over Download PDF button
        pdf_btn = page.locator('a[href*="download-pdf"]')
        if pdf_btn.is_visible():
            print("  -> Hovering over Download PDF action...")
            cur_pos = smooth_hover_element(page, cur_pos, pdf_btn, hover_time=0.7)

        # ----------------------------------------------------
        # SCENE 4: Settings & Style Specification
        # ----------------------------------------------------
        print("🎬 Scene 4: Settings & Style Specification...")
        cur_pos = smooth_click_element(page, cur_pos, 'a[href="/settings/"]', wait_after=1.2)

        # Scroll inside Style Spec textarea
        print("  -> Touring Style Specification & Active Config...")
        cur_pos = smooth_click_element(page, cur_pos, "#style_spec", wait_after=0.4)
        for _ in range(4):
            page.keyboard.press("PageDown")
            time.sleep(0.25)
        for _ in range(4):
            page.keyboard.press("PageUp")
            time.sleep(0.2)

        # Hover over Active Configuration details
        config_boxes = page.locator(".rounded-xl.bg-slate-900")
        if config_boxes.count() > 1:
            cur_pos = smooth_hover_element(page, cur_pos, config_boxes.nth(1), hover_time=1.2)

        # ----------------------------------------------------
        # SCENE 5: Finale back to Library
        # ----------------------------------------------------
        print("🎬 Scene 5: Finishing at Library...")
        cur_pos = smooth_click_element(page, cur_pos, 'a[href="/"]', wait_after=1.2)
        cur_pos = smooth_hover_element(page, cur_pos, ".story-card", hover_time=1.0)
        time.sleep(1.2)

        # Close page and context to finalize raw video
        print("💾 Finalizing browser recording...")
        page.close()
        context.close()
        browser.close()

    # Find the recorded raw webm file
    recorded_files = list(video_temp_dir.glob("*.webm"))
    if not recorded_files:
        raise RuntimeError("No recorded video file found in temporary directory.")
    
    raw_video = recorded_files[0]
    print(f"📹 Raw video captured: {raw_video} ({raw_video.stat().st_size} bytes)")

    # ----------------------------------------------------
    # Optimization with FFmpeg to 720p MP4
    # ----------------------------------------------------
    print("✨ Optimizing video to 720p H.264 MP4 with FFmpeg...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_video),
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-preset", "slow",
        "-crf", "20",
        "-movflags", "+faststart",
        str(target_video_path)
    ]

    subprocess.run(ffmpeg_cmd, check=True)
    
    file_size_mb = target_video_path.stat().st_size / (1024 * 1024)
    print(f"🎉 SUCCESS! Optimized 720p video saved to: {target_video_path}")
    print(f"📊 Final file size: {file_size_mb:.2f} MB")

if __name__ == "__main__":
    record_walkthrough()
