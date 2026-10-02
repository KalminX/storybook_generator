# Generation Guide: Steering Your Storybooks

This guide explains **where you can steer** the stories and pictures, **what to
write** in each place, and **how to test changes cheaply** before making whole books.

---

## 1. The five places you can steer

| # | Where | Affects | Use it for |
|---|-------|---------|-----------|
| 1 | `input/style_spec.md` | **Every** story and **every** picture | Audience, length, tone, genre, art style (the rules for the whole series) |
| 2 | `input/stories.txt` | One story per line | The idea, plot points, characters, setting, lesson for *that* book |
| 3 | `output/<book>/character_bible.json` | One finished book's pictures | Fixing or changing how a character looks |
| 4 | `output/<book>/story.json` | One finished book | Rewording page text, or changing what one picture shows |
| 5 | `config.yaml` | Everything | Picture shape, consistency, AI models, PDF layout |

A simple rule: **things that apply to all books go in the style spec; things
that apply to one book go on its line in `stories.txt`.**

---

## 2. How your words reach the AI

Knowing this helps you write better instructions.

**Writing the story.** The AI receives your whole style spec, then your one
line from `stories.txt`, under these headings:

```
STYLE SPECIFICATION
<everything in style_spec.md>

STORY CONCEPT
<your line from stories.txt>
```

It's told that the style spec is **the authority** on audience, length, tone,
page count, vocabulary and illustration style. It returns a title, a cast of
characters (with exact appearance details) and pages, each with text and a
picture description.

**Drawing each picture.** The picture AI receives:

```
STYLE SPECIFICATION   ← your whole style_spec.md again
CHARACTER BIBLE       ← how every character looks (from the story)
CURRENT PAGE          ← "Page 3 of 10" + that page's text, for context
PAGE IMAGE PROMPT     ← what this particular picture shows
```

It also gets the book's first finished picture as a visual reference, so
characters and style stay the same from page to page (see section 7).

Two consequences:
- **The style spec is read by both the writer and the illustrator.** Label
  your sections clearly ("Story" vs "Illustration style") so each part is
  applied to the right job.
- **The picture AI is told not to draw the page's words.** The text is printed
  under the picture in the PDF.

---

## 3. The style specification (`input/style_spec.md`)

This is your series "bible". Be specific: vague words like "nice" or "fun"
give generic results, and concrete rules give consistent ones.

### Recommended sections

```markdown
# Storybook Style Specification

## Audience
Children aged 4–6, read aloud by a parent at bedtime.

## Story length and shape
- Exactly 12 pages.
- 2–3 short sentences per page (no more than 35 words).
- Structure: pages 1–2 introduce the hero and their wish or problem;
  pages 3–9 are three attempts or discoveries, each a little bigger;
  page 10 is the turning point; pages 11–12 are a calm, happy ending.

## Tone and language
- Warm, gentle and a little funny. Never scary or sad for long.
- Simple words a 5-year-old knows; one "delicious" new word per book is fine.
- Include a repeated phrase that children can join in with.
- Dialogue in quotation marks is welcome.

## Characters
- One main character (an animal) plus one or two friends.
- The main character solves the problem themselves; adults don't rescue them.
- Give the main character one signature item of clothing or accessory.

## Values
- Show kindness, curiosity and trying again. Never preach: show, don't tell.

## Illustration style
- Soft watercolor with fine ink outlines, like classic picture books.
- Warm pastel palette; golden-hour light.
- Simple backgrounds; the characters are always the clear focus.
- Characters are round, friendly and expressive.
- No text, letters, signs or numbers inside the pictures.
```

### Tips
- **Page count:** state an exact number ("Exactly 12 pages") if you want every
  book the same length. A range ("10–12 pages") gives the AI freedom.
- **Words per page:** give a hard limit. Long text shrinks the font in the PDF.
- **Clothing:** if a character has no clothing listed, the pictures are
  told to add *none*. If you *want* outfits, say so in the style spec
  (e.g. "the main character always wears one signature item").
- **Illustration rules apply to every picture**, so put lasting visual
  decisions here: medium, palette, lighting, level of detail, and what never
  appears.
- The program never changes this file. Changes apply to books made **after**
  the change; finished books are not redone (see section 8).

---

## 4. Story ideas (`input/stories.txt`)

**One story per line.** Lines starting with `#` are notes to yourself and are
ignored, and so are blank lines. A line can be long, and more detail gives more
control.

### Level 1: just the idea
```
A nervous penguin learns to swim.
```
The AI decides everything else. Good for exploring.

### Level 2: idea + direction
```
A nervous penguin learns to swim. Funny and gentle. The lesson: being brave means trying even when you're scared.
```

### Level 3: idea + plot points
Spell out the beats you want, in order:
```
A nervous penguin named Pebble learns to swim. Plot: (1) all the other chicks dive in but Pebble stays on the ice; (2) Pebble practises in a tiny puddle; (3) a friendly walrus shows her to float first; (4) a fish she wants to befriend swims away, so she follows it in without thinking; (5) she realises she is swimming. Ending: Pebble teaches a younger chick.
```

### Level 4: fully specified
```
Title: "Pebble Takes the Plunge". Characters: Pebble, a small grey penguin chick with a pink knitted hat; Mo, an old walrus with one bent tusk. Setting: a snowy Antarctic bay at sunrise. Plot: (1) ... (2) ... (3) ... Ending: ... Lesson: courage grows a little at a time. Mood: cosy and funny.
```

### Useful things to include in a line
| To control... | Write something like... |
|---|---|
| Names | "The fox is called Fern." |
| Look of a character | "Fern is a small silver fox with a green satchel." |
| Setting | "Set in a seaside village in autumn." |
| Plot points | "Plot: (1) … (2) … (3) …" |
| Ending | "Ending: they become best friends." |
| Lesson or theme | "Lesson: sharing makes things more fun." |
| Mood for this book | "Extra silly." / "Quiet bedtime mood." |
| Recurring series character | Repeat the *same* description word for word in each line. |

### Important
- **Each line is one book.** Don't split an idea over several lines.
- **Changing a line's wording makes it a new book** (a new folder). The old
  book stays in `output/`. Extra spaces or capital letters don't count as changes.
- **Duplicate lines are ignored**: only the first copy is made.
- If a line contradicts the style spec (e.g. asks for 20 pages when the spec says
  12), results are unpredictable. Keep book-specific wishes within the series rules.

---

## 5. Recipes for different kinds of story

Put the series rules in `style_spec.md` and the book details on each line.

**Bedtime story**
- *Style spec:* "Slow, soothing rhythm. Energy winds down across the book. The
  final two pages are night-time, with the characters falling asleep.
  Illustrations get darker and bluer towards the end."

**Adventure**
- *Style spec:* "A clear goal on page 1, three obstacles of increasing size,
  a brave choice at the climax, a triumphant return home. Mild suspense only."
- *Line:* "A mouse sails a teacup across the pond to rescue her kite. Obstacles: a sleepy frog, a waterfall, a storm."

**Lesson / feelings book**
- *Style spec:* "The character feels one strong emotion, tries unhelpful ways
  to cope, then finds a helpful one. Name the feeling explicitly. Never scold."
- *Line:* "A bear cub feels jealous of his new baby sister. Helpful way: helping sing her a lullaby."

**Rhyming book**
- *Style spec:* "Every page is a rhyming couplet or quatrain with a steady,
  bouncy rhythm (like Dr. Seuss or Julia Donaldson). Rhymes must be natural;
  never twist sentences just to rhyme."

**Counting / ABC book**
- *Style spec:* "Exactly 10 pages; page N features exactly N objects,
  named in the text. The objects must be clearly countable in the illustration."
- Keep the "no numbers in the pictures" rule. The count is in the text,
  and the picture shows the objects.

**A series with the same hero**
- Describe the hero word for word in the style spec's *Characters*
  section (name, species, colours, outfit). Every book then starts from the
  same description. Each line just gives that book's adventure.

---

## 6. Fixing things after a book is made

You don't have to remake a whole book to fix one part.

### A picture is wrong
Redraw just that page (the number after `--story` is the line's position in
`stories.txt`, counting ideas only, not comments or blank lines):

```bash
.venv/bin/python run.py --story 1 --redo-page 4
```

Repeat `--redo-page` to redo several: `--redo-page 4 --redo-page 7`.
Each redo is a new attempt and gives a different picture.

### A picture shows the wrong thing
1. Open `output/<book>/story.json` in TextEdit.
2. Find the page's `"image_prompt"` and rewrite the description.
3. Save, then redo that page (as above).

### A character looks wrong on several pages
1. Open `output/<book>/character_bible.json` in TextEdit.
2. Edit their `"appearance"` or `"clothing"` (e.g. `"clothing": "A red scarf"`).
3. Save, then redo the affected pages.

Your edited bible is used from then on for that book.

### The words on a page need changing
1. Edit the page's `"text"` in `output/<book>/story.json` and save.
2. Delete (or move) `storybook.pdf` from that book's folder.
3. Run again (e.g. `--story 1`). The PDF is rebuilt with your new text. This
   makes **no** AI calls and costs nothing.

### When editing JSON files
- **Make a copy first** (e.g. `story copy.json`) so you can undo mistakes.
- Only change the text **inside** the quotation marks.
- Keep the quotes, commas and brackets exactly as they are. Don't add, remove
  or renumber pages.
- If `character_bible.json` gets damaged, it is simply rebuilt from the story
  (free).
- ⚠️ If `story.json` gets damaged, the program can't trust it and **remakes the
  whole book**: new story, new pictures, full cost. The old pictures are moved
  to a `pages.old-…` folder, not deleted.

  **Check your edit before running again** (replace `<book>` with the folder name):

  ```bash
  .venv/bin/python -c "import sys; from src.models.story import Storybook; b = Storybook.model_validate_json(open(sys.argv[1]).read()); print('OK:', b.title, '-', len(b.pages), 'pages')" output/<book>/story.json
  ```

  `OK: …` means it's safe. An error message (e.g. `expected ',' at line 30`)
  points to the mistake. Fix it, or put your copy back.

---

## 7. Settings that affect results (`config.yaml`)

Copy `config.example.yaml` to `config.yaml` and edit the copy.

| Setting | What it does | Suggestion |
|---|---|---|
| `images.reference_images` | How many of the book's first finished pictures are shown to the AI with every new page | `1` (default) keeps characters consistent. Try `2` if settings (rooms, fountains, houses) drift between pages. Max `4`. |
| `images.aspect_ratio` | Picture shape: `"1:1"`, `"3:4"`, `"4:3"`, `"16:9"`… | Match your page shape. |
| `images.image_size` | `"1K"`, `"2K"`, `"4K"` | Bigger is sharper for printing but costs more. |
| `provider.text_model` | The model that writes stories | Change only if Google renames or retires models. |
| `provider.image_model` | The model that draws pictures | Same. |
| `pdf.*` | Page size, margins, fonts, text size, colours | See the comments in the file. |

---

## 8. Testing changes cheaply

Don't make ten full books to test a new style spec. Use the trial scripts,
which never touch your real books (output goes to `output/_trials/`):

```bash
# Write one story (one cheap text request) and print it
.venv/bin/python scripts/try_story.py 1                 # the 1st line of stories.txt
.venv/bin/python scripts/try_story.py "A shy owl joins the choir."   # any idea

# Draw one page of that trial story (one picture)
.venv/bin/python scripts/try_page.py 3                  # page 3
```

A good workflow:
1. Edit `style_spec.md`.
2. Run `try_story.py` 2–3 times with different ideas. Read the text: length, tone, structure.
3. Run `try_page.py` for a page with several characters. Check the art style.
4. Adjust and repeat until you're happy.
5. Make one real book: `.venv/bin/python run.py --limit 1`.
6. Then run the rest: `.venv/bin/python run.py` (or double-click `start.command`).

**To remake finished books with a new style**, move their folders out of
`output/` (e.g. into a folder called `old-books`) and run again. The program
never overwrites finished books by itself.

---

## 9. Advanced: the built-in instructions

The fixed instructions that wrap your text live in two places in the code.
Most people never need to touch them; the style spec is the right place for
nearly everything.

- **Story writer instructions:** `SYSTEM_INSTRUCTION` in
  `src/generation/story_generator.py` (e.g. "number pages from 1", "give
  precise appearance details", "no words in illustrations unless the style
  specification asks for them").
- **Picture layout of the prompt:** `build_image_prompt` in
  `src/generation/image_generator.py` (the four headed sections shown in section 2).

If you change them, run the tests afterwards:
`.venv/bin/python -m pytest -q`.

---

## Quick checklist

- [ ] Style spec states: audience, **exact** page count, words per page, tone, structure, illustration style, and what never appears.
- [ ] Style spec separates *Story* rules from *Illustration* rules.
- [ ] Each line in `stories.txt` is one complete idea, with plot points if you care about the plot.
- [ ] Recurring characters are described word for word the same everywhere.
- [ ] Tested with `try_story.py` / `try_page.py` before running the whole batch.
