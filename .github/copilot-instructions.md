# AI agent guide for this repository

This repo stores Kinyarwanda Bible text aligned to audio by chapter/verse; focus your work on preserving the data model, naming conventions, and alignment between `datastorage` (canonical) and `workstorage` (in-progress).

## Big picture and layout

- Canonical text data lives under `datastorage/text/<testament>/<##_<book_canonical>/*.json`.
- Canonical audio lives under `datastorage/audio/<testament>/<##_<book_canonical>/*.mp3`.
- In‑progress artifacts (per‑book) live under `workstorage/<##_<book_canonical>/` and may mirror chapter JSON plus auxiliary files (e.g., cue marker `.txt`).
- Structure metadata is in `datastorage/text/KinyarwandaBibleStructure.json` with `OldTestament` and `NewTestament` arrays; each book has `{ id, name, chapters }`. The `id` equals the folder/file numeric prefix and the `book_number` stored in chapter JSON.

## File naming and path conventions

- Chapter text JSON path: `datastorage/text/newTestament/60_1_peter/1_peter2.json` (pattern: `<book_canonical><chapter>.json`).
- Chapter audio path: `datastorage/audio/newTestament/60_1_peter/audiobible_newTestament_60_1_peter_1_peter2.mp3`.
- Work files example: `workstorage/60_1_peter/1_peter2.txt` (tab‑separated cue markers) and `workstorage/60_1_peter/1_peter2.json` (same schema as canonical).
- Ignore Windows ADS metadata files like `*.json:Zone.Identifier` and do not treat them as content.

## Chapter JSON schema (authoritative)

```jsonc
{
  "book": "Book 60", // literal label as found in sources
  "book_canonical": "1_peter", // folder slug and filename prefix
  "book_number": 60, // numeric id from structure file
  "chapter": 2, // 1-based chapter index
  "verses": {
    "1": { "text": "…", "start": 26.01, "end": 31.38 },
    "2": { "text": "…", "start": 44.72, "end": 44.82 }
  }
}
```

- Keys under `verses` are strings of verse numbers (e.g., `"1"`, `"2"`), not integers.
- `text` is Kinyarwanda; preserve diacritics/spaces verbatim.
- `start`/`end` are floating‑point seconds relative to the chapter audio start.

## Cue marker `.txt` files (workstorage)

- Example: `workstorage/60_1_peter/1_peter2.txt` with header:
  `Name\tStart\tDuration\tTime Format\tType\tDescription`
- Times are in `m:ss.mmm`; `Duration` is often `0:00.000`; `Type` typically `Cue`.
- Marker names may repeat (e.g., `Marker 07` appears twice); treat rows as independent cues.
- Common task is mapping these cues to verse boundaries and converting time to seconds.

## Practical patterns and guardrails

- Always keep `book_number` equal to the folder/book id (see `KinyarwandaBibleStructure.json`).
- Maintain the filename pattern and directory layout; scripts should derive paths from the book id and slug to avoid hard‑coding.
- When updating verse timings:
  - Leave `text` unchanged unless the source text file in `datastorage/text` changes.
  - Ensure `start <= end` and both are within the corresponding audio duration if you can check it.
  - Do not renumber verse keys or convert them to integers.
- Prefer UTF‑8 (no BOM) and Unix newlines for all text files.

## Typical agent workflows in this repo

- Parse a cue marker `.txt` in `workstorage/<book>/` and update the matching chapter JSON’s `start`/`end` values.
- Validate a chapter JSON: required top‑level keys exist; `verses` keys are strings; each verse has `text`, `start`, `end` as defined above.
- Promote finalized JSON from `workstorage/<book>/` to `datastorage/text/<…>/` once verified.

## Examples from this repo

- Text JSON: `datastorage/text/newTestament/60_1_peter/1_peter2.json` with verse `"1": { "text": "Nuko mwiyambure…", "start": 26.01, "end": 31.38 }`.
- Audio MP3: `datastorage/audio/newTestament/60_1_peter/audiobible_newTestament_60_1_peter_1_peter2.mp3`.
- Structure reference: `datastorage/text/KinyarwandaBibleStructure.json` → New Testament entry `{ "id": 60, "name": "1 Peter", "chapters": 5 }`.

## What is not here

- There is no build system or test harness in the repo; if you add helper scripts (e.g., under `tools/`), keep them minimal, documented, and avoid large dependencies.

If any of these conventions are unclear or you spot inconsistencies (e.g., timing anomalies or naming mismatches), leave a short note in your PR and ask for confirmation before mass‑editing.
