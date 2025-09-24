# Kinyarwanda Bible Audio Alignment Repository

This repository stores Kinyarwanda Bible text aligned to audio on a per-book, per-chapter, per-verse basis. Canonical, finalized chapter JSON lives under `datastorage/`, while in‑progress work and timing refinement happens under `workstorage/`.

## Repository Structure

```
datastorage/
  text/
    KinyarwandaBibleStructure.json       # Canonical list of books + chapter counts
    newTestament/<##_book_slug>/*.json   # Finalized NT chapter JSON
    oldTestament/<##_book_slug>/*.json   # Finalized OT chapter JSON
  audio/
    newTestament/<##_book_slug>/*.mp3    # Chapter audio (NT currently)

workstorage/
  newTestament/
    <##_book_slug>/                      # In‑progress NT book (e.g. 60_1_peter)
      <chapter>.json                     # Working chapter JSON
      timestamp/<chapter>.txt            # Preferred cue markers
      <chapter>.txt                      # (Legacy) marker fallback
  oldTestament/
    <##_book_slug>/                      # In‑progress OT book (same layout)
  verse_timing_wizard.py                 # Timing + promotion tool
```

## Chapter JSON Schema

```jsonc
{
  "book": "Book 60", // Literal label
  "book_canonical": "1_peter", // Slug used in folder and filename prefix
  "book_number": 60, // Numeric id (matches structure file and folder prefix)
  "chapter": 2, // 1-based index
  "verses": {
    "1": { "text": "…", "start": 0.0, "end": 5.96 },
    "2": { "text": "…", "start": 5.96, "end": 13.306 }
  }
}
```

Key rules:

- Verse keys are string numbers ("1", "2", …). Do not convert to integers.
- `text` is Kinyarwanda; preserve spacing/diacritics exactly.
- `start` / `end` are floating point seconds relative to chapter audio start.
- Maintain `book_number` consistency with folder prefix and structure file.

## Cue Marker `.txt` Format

Example header + rows (tab-separated):

```
Name	Start	Duration	Time Format	Type	Description
Marker 01	0:00.040	0:00.000	decimal	Cue
Marker 02	0:05.960	0:00.000	decimal	Cue
...
```

Notes:

- Start times use `m:ss.mmm`.
- Marker names may repeat; each line is an independent boundary.
- Markers are interpreted as sequential verse END boundaries.
- Preferred path: `workstorage/(new|old)Testament/<book>/timestamp/<chapter>.txt` (legacy root-level `<chapter>.txt` still accepted if `timestamp/` missing).

## Timing Mapping Logic

Given ordered marker times T0, T1, T2, …:

- Verse 1: start = 0.000, end = T0
- Verse 2: start = T0, end = T1
- Verse N: start = T(N-2), end = T(N-1)
  If fewer markers than verses, later verses remain unchanged. Extra markers are ignored.

## Wizard Script (`workstorage/verse_timing_wizard.py`)

This tool updates verse `start`/`end` in a chapter JSON using its accompanying marker file and (by default) promotes the result into `datastorage/text/<testament>/<book>/`.

Book directory resolution order (first match wins):

1. `workstorage/<book>` (legacy flat layout)
2. `workstorage/newTestament/<book>`
3. `workstorage/oldTestament/<book>`

Marker file resolution order:

1. `<book>/timestamp/<chapter>.txt`
2. `<book>/<chapter>.txt`

### Interactive Usage

```bash
python3 workstorage/verse_timing_wizard.py
```

Prompts:

1. Book (e.g. `60_1_peter`)
2. Chapter (e.g. `1_peter2`)

### Non-Interactive Usage

```bash
python3 workstorage/verse_timing_wizard.py --book 60_1_peter --chapter 1_peter2
```

Flags:

- `--book, -b` Book folder name (e.g. `60_1_peter`).
- `--chapter, -c` Chapter base filename (e.g. `1_peter2`).
- `--testament` Force testament context (`newTestament` or `oldTestament`) for lookup & promotion.
- `--dry-run` Show changes but do not write JSON or promote.
- `--verbose, -v` Print a per-verse table of old/new timings.
- `--no-promote` Skip copying updated JSON into canonical `datastorage/text/<testament>/<book>/`.

### Examples

Dry run with details:

```bash
python3 workstorage/verse_timing_wizard.py -b 60_1_peter -c 1_peter2 --dry-run --verbose
```

Verbose actual write:

```bash
python3 workstorage/verse_timing_wizard.py -b 60_1_peter -c 1_peter2 -v
```

### Output Sample

```
Verse Timing Wizard
--------------------
Verse updates:
verse	old_start	old_end	new_start	new_end
1	26.01	31.38	0.0	0.04
2	44.72	44.82	0.04	5.96
...
Updated 25 verse(s) in workstorage/60_1_peter/1_peter2.json using 27 marker(s) from workstorage/60_1_peter/1_peter2.txt.
```

Skip promotion (update only in workstorage):

```bash
python3 workstorage/verse_timing_wizard.py -b 60_1_peter -c 1_peter2 --no-promote
```

## Workflow Summary

1. Place or edit timing markers in `workstorage/(new|old)Testament/<book>/timestamp/<chapter>.txt` (or legacy flat file location).
2. Run the wizard; it auto-promotes the updated chapter JSON to `datastorage/text/<testament>/<book>/` unless `--no-promote` is supplied.
3. Review diffs in both workstorage and canonical locations (they should match exactly).
4. Commit both copies; avoid manual edits inside `datastorage/text/` unless intentionally correcting canonical text.

## Conventions & Guardrails

- Do not alter verse ordering or keys.
- Never modify `text` unless upstream canonical text changes.
- Exclude Windows ADS files `*:Zone.Identifier` from processing / commits.
- Use UTF‑8 without BOM; keep Unix line endings.

## Potential Future Enhancements

- Add a validator script (timing monotonicity, field presence).
- Optional export of timing deltas for QC.
- Support final chapter boundary (last marker vs audio duration).

## Troubleshooting

Common issues & fixes:

- Missing markers error: Ensure file exists at `workstorage/(new|old)Testament/<book>/timestamp/<chapter>.txt` or legacy path.
- Promotion failed (shutil not defined or permission denied): Verify script updated (imports `shutil`) and you have write access to `datastorage/text/...`.
- Wrong testament promoted: Re-run with explicit `--testament newTestament` or `--testament oldTestament`.
- No verses updated: Make sure the marker file has at least one data row (not just header) and times parse (`m:ss.mmm`).
- Non-monotonic timings after update: Fix ordering or duplicate markers in the `.txt` file—script sorts times ascending; verify intended boundaries.

## License / Attribution

(Add licensing or attribution info here if required.)

If you add tools or scripts, keep them dependency-light and document usage inline or in this README.
