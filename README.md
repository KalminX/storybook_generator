# Storybook Generator

Turns a list of one-line story ideas into finished, illustrated children's
picture books (PDF), using Google's Gemini AI to write the stories and paint
the pictures.

You write:

```
A young fox discovers a hidden garden.
A nervous penguin learns to swim.
```

You get one folder per idea, each with a finished `storybook.pdf`.

---

## What you need

- A Mac (macOS).
- **Python 3.11 or newer.** To check, open **Terminal** (press ⌘-Space, type
  *Terminal*, press Enter) and type `python3 --version`. If it says 3.11 or
  higher you're set. Otherwise download the installer from
  <https://www.python.org/downloads/> and run it.
- **A Gemini API key.** Get one free at <https://aistudio.google.com/apikey>
  (sign in with a Google account, click *Create API key*, copy it).
  Image generation may require billing to be enabled on the key's Google
  account. Each book uses one text request plus one image per page — check
  Google's current pricing before making many books.

## First-time setup

1. Put the `storybook-generator` folder wherever you like (e.g. Documents).
2. **Double-click `start.command`.**
   - If macOS says it "cannot be opened because it is from an unidentified
     developer": right-click `start.command`, choose **Open**, then **Open**
     again. You only need to do this once.
   - The first time, it spends a minute or two installing what it needs.
3. A file called `.env` opens in TextEdit. Paste your key after the `=` sign
   so the line looks like this (with your real key):

   ```
   GEMINI_API_KEY=AIzaSy...your key...
   ```

   Save it (⌘-S) and close TextEdit. Keep this file private; never share it.
4. Double-click `start.command` again. It starts making books.

> Prefer Terminal? From inside the folder:
> ```bash
> python3 -m venv .venv
> .venv/bin/pip install -r requirements.txt
> cp .env.example .env        # then put your key in .env
> .venv/bin/python run.py
> ```

## Quick Start: Web App & Storybook Studio

Launch the interactive web application in your browser:

- **Mac Double-Click**: Double-click [`start_web.command`](file:///Users/kalmin/projects/storybook_generator/start_web.command)
- **Terminal**:
  ```bash
  python run_web.py
  ```
  Visit `http://localhost:8000/` in your browser.

### Web Features
- **Story Studio**: Generate new storybooks with one click, preset chips, and live generation monitors.
- **Interactive Reader**: Flip through illustrated pages with GSAP animations, Web Speech audio narration, and keyboard navigation.
- **Character Bible & Redo**: View character designs and regenerate individual page illustrations directly from the web interface.
- **Library & PDF Download**: Manage all your storybooks, monitor progress in real time, and download PDFs.

---

## Quick Start: Command Line Batch Mode

**Double-click `start.command`** or run `python run.py`.

You'll see progress like:

```
Found 3 story concept(s); 3 selected.

[1/3] A young fox discovers a hidden garden.
Writing story text...
Story written in 12.3s: 'Fern and the Secret Garden' (12 pages)
Illustrating page 1/12...
Page 1/12 done in 18.2s
...
Completed: 3
Failed: 0
Skipped: 0
```

A book with 12 pages usually takes several minutes. You can leave it running.

### Adding stories

Open `input/stories.txt` (in TextEdit) and add **one idea per line**.
Blank lines and lines starting with `#` are ignored. Save, then run again —
books that are already finished are skipped, so only new ideas are made.

Changing the wording of an idea counts as a new story.

### Changing the style

> **See [`generation_guide.md`](generation_guide.md)** for a full guide to
> steering stories: writing the style spec, adding plot points, recipes for
> different kinds of books, and fixing individual pages.

Edit `input/style_spec.md`. Everything in it — audience, length, tone, art
style, colors — is sent to the AI for every story and every picture. The
program never changes this file.

Style changes apply to books made afterwards. To remake a finished book in the
new style, delete (or move) its folder from `output/` and run again.

### Finding finished books

Everything is in the `output` folder, one folder per story:

```
output/
└── a-young-fox-discovers-a-hidden-garden-db627fcf/
    ├── storybook.pdf          ← the finished book
    ├── pages/page-001.png     ← each illustration
    ├── story.json             ← the story text
    ├── character_bible.json   ← how each character looks
    └── state.json             ← progress bookkeeping (don't edit)
```

The folder name comes from the idea's text, so it never changes even if you
reorder `stories.txt`.

## If something goes wrong

**Just run it again.** Progress is saved after every step and every picture.
After a crash, a closed window, a lost internet connection or a restarted Mac,
double-clicking `start.command` continues exactly where it stopped. Finished
pictures are never paid for twice.

- Temporary problems (busy servers, rate limits, network hiccups) are retried
  automatically, waiting a little longer each time.
- If one story fails, the others still get made. The summary at the end lists
  what failed and why; full details are in `logs/app.log`.
- "GEMINI_API_KEY is not set": the key is missing from `.env` (see setup).
- "check that GEMINI_API_KEY is correct": the key is wrong or has no access
  to the model (e.g. billing not enabled).
- "check the model names in your config file": see *Settings* below.
- To see the hidden `.env` file in Finder, press ⌘-Shift-. (period).

**Check your setup without spending anything:**

```bash
.venv/bin/python run.py --dry-run
```

This checks the key, the input files and the folders, and lists every story
with its status (new / in progress / done / failed).

## Fixing a single picture

If you don't like one illustration, regenerate just that page (story number =
its line in `stories.txt`, counting ideas only):

```bash
.venv/bin/python run.py --story 1 --redo-page 4
```

To change how a character looks everywhere, edit `character_bible.json` in the
book's folder, then redo the pages you want redrawn.

## Other options

```bash
.venv/bin/python run.py --limit 1          # make just one book (good for testing)
.venv/bin/python run.py --story 2          # only the 2nd story
.venv/bin/python run.py --resume           # only continue unfinished books
.venv/bin/python run.py --help             # everything else
```

## Settings

Settings live in `config.example.yaml`. To change them, copy it to
`config.yaml` and edit the copy — `config.yaml` wins when it exists. There you
can change:

- **AI models** (`provider.text_model`, `provider.image_model`)
- **Retries** (how many times, how long to wait)
- **Picture shape and size** (`images.aspect_ratio`, `images.image_size`)
- **Consistency** (`images.reference_images`: earlier pictures shown to the AI
  so characters stay the same)
- **PDF layout**: page size, margins, fonts (including your own `.ttf` files),
  text size, colors, page numbers, cover picture

---

## For developers

```
run.py                   CLI entry point (thin)
src/cli.py               arguments, story selection, dry run, summary
src/app.py               composition root: wires concrete classes together
src/pipeline/            story_pipeline.py (order of steps, resume), batch.py
src/generation/          story_generator.py, character_bible.py, image_generator.py
src/providers/           base.py (interfaces + error types), gemini.py, factory.py
src/rendering/           pdf_renderer.py (ReportLab)
src/infrastructure/      checkpoint.py, retry.py, logger.py
src/models/              Pydantic models: story, state, concept, character bible
src/utils/               atomic file writes, output paths, input parsing, images
scripts/                 try_story.py / try_page.py: cheap one-story / one-page checks
```

- Only `src/providers/gemini.py` imports the Gemini SDK. To add another
  vendor, implement `TextGenerationProvider` / `ImageGenerationProvider` from
  `providers/base.py`, translating its errors into the error types there, and
  add a branch in `providers/factory.py`.
- Retrying happens only in `infrastructure/retry.py`, applied by the pipeline.
  Providers signal retryable failures by raising `TransientProviderError`.
- Tests never call a real API: `pytest` (fake providers live in `tests/fakes.py`).

```bash
.venv/bin/python -m pytest -q
```
