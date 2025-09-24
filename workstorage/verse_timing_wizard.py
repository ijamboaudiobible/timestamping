#!/usr/bin/env python3
"""
Verse Timing Wizard

Functions:
1. Interactive mode (default if flags not provided):
    - Prompts for a book folder (e.g., 60_1_peter)
    - Prompts for a chapter base name (e.g., 1_peter2)
2. Non‑interactive (flags):
    - Provide --book and --chapter to skip prompts.

Book directory resolution order (first existing is used):
    workstorage/<book>
    workstorage/newTestament/<book>
    workstorage/oldTestament/<book>
You can force a testament with --testament newTestament|oldTestament.

It loads cue markers from `workstorage/<book>/timestamp/<chapter>.txt` (new layout) or falls back to `workstorage/<book>/<chapter>.txt` (legacy) alongside `workstorage/<book>/<chapter>.json`, then updates JSON `verses[*].start/end` using marker times:
   - Use cue markers as verse END boundaries in ascending time order.
   - Verse 1: start = 0.000, end = marker[0]
   - Verse N>1: start = marker[N-2], end = marker[N-1]
Writes the updated JSON (unless `--dry-run`).

Auto-promotion:
After a successful (non-dry-run) update, the script copies the chapter JSON into the canonical tree:
    datastorage/text/<testament>/<book>/<chapter>.json
where <testament> is resolved by looking up the numeric book id in `KinyarwandaBibleStructure.json` (OldTestament vs NewTestament arrays). Use `--no-promote` to disable.

Notes & assumptions
- Cue file is TSV with header: Name, Start, Duration, Time Format, Type, Description
- Start times are in m:ss.mmm (e.g., 1:02.853)
- Marker names may repeat; order of rows defines order. Times are sorted before mapping to be safe.
- If marker count < verse count, only the first len(markers) verses are updated; others remain unchanged.
- If marker count > verse count, extra markers are ignored with a warning.

Examples:
    # Interactive
    python3 workstorage/verse_timing_wizard.py

    # Non-interactive specify book & chapter
    python3 workstorage/verse_timing_wizard.py --book 60_1_peter --chapter 1_peter2

    # Dry run (no file write) with verbose per-verse table
    python3 workstorage/verse_timing_wizard.py -b 60_1_peter -c 1_peter2 --dry-run --verbose

    # Update without promoting to canonical datastorage
    python3 workstorage/verse_timing_wizard.py -b 60_1_peter -c 1_peter2 --no-promote
"""

from __future__ import annotations
import json
import argparse
import os
import sys
import shutil  # used for promotion copy
from typing import List, Tuple, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "workstorage")
DATA_TEXT = os.path.join(ROOT, "datastorage", "text")
STRUCTURE_JSON = os.path.join(DATA_TEXT, "KinyarwandaBibleStructure.json")


def parse_time_to_seconds(val: str) -> float:
    """Parse time in format m:ss.mmm to seconds (float).
    Accepts minutes >= 0, seconds 0..59, milliseconds 0..999. Missing milliseconds allowed.
    """
    s = val.strip()
    if not s:
        raise ValueError("Empty time string")
    if ":" not in s:
        # treat as seconds (possibly with .mmm)
        sec = float(s)
        return round(sec, 3)
    try:
        minutes_str, sec_ms = s.split(":", 1)
        minutes = int(minutes_str)
        if "." in sec_ms:
            sec_str, ms_str = sec_ms.split(".", 1)
            seconds = int(sec_str)
            # normalize milliseconds to 3 digits
            ms_norm = (ms_str + "000")[:3]
            milliseconds = int(ms_norm)
        else:
            seconds = int(sec_ms)
            milliseconds = 0
        total = minutes * 60 + seconds + milliseconds / 1000.0
        return round(total, 3)
    except Exception as e:
        raise ValueError(f"Invalid time format '{val}': {e}")


def read_markers(tsv_path: str) -> List[float]:
    """Read marker times (Start column) from the TSV file.
    Returns a list of seconds (float), sorted ascending.
    """
    if not os.path.exists(tsv_path):
        raise FileNotFoundError(f"Cue file not found: {tsv_path}")

    times: List[float] = []
    with open(tsv_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    if not lines:
        return times

    # Skip header if present (starts with 'Name\tStart')
    start_idx = 0
    if lines[0].lower().startswith("name\tstart"):
        start_idx = 1

    for line in lines[start_idx:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        start_str = cols[1].strip()
        try:
            sec = parse_time_to_seconds(start_str)
            times.append(sec)
        except ValueError:
            # Skip malformed entries but continue
            continue

    # Ensure ascending order; keep unique ordering semantics via sort
    times.sort()
    return times


def load_chapter_json(json_path: str) -> dict:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Chapter JSON not found: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chapter_json(json_path: str, data: dict) -> None:
    # Pretty-print with stable key order
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def update_timings(chapter: dict, marker_times: List[float]):
    """Update chapter['verses'][*]['start'|'end'] in place using marker_times as end boundaries.
    Returns (updated_count, total_verses, details_list) where details_list contains dicts:
        { 'verse': '1', 'old_start': <float|None>, 'old_end': <float|None>, 'new_start': float, 'new_end': float }
    """
    verses = chapter.get("verses")
    if not isinstance(verses, dict):
        raise ValueError("Invalid chapter format: missing 'verses' object")

    # Verse keys must be strings of integers; sort numerically
    try:
        verse_keys = sorted(verses.keys(), key=lambda k: int(k))
    except Exception as e:
        raise ValueError(f"Verse keys must be numeric strings: {e}")

    n_markers = len(marker_times)
    n_verses = len(verse_keys)

    n_update = min(n_markers, n_verses)
    details = []
    for i in range(n_update):
        key = verse_keys[i]
        start_val = 0.0 if i == 0 else marker_times[i - 1]
        end_val = marker_times[i]
        v = verses.get(key, {})
        old_start = v.get("start") if isinstance(v.get("start"), (int, float)) else None
        old_end = v.get("end") if isinstance(v.get("end"), (int, float)) else None
        v["start"] = round(float(start_val), 3)
        v["end"] = round(float(end_val), 3)
        verses[key] = v
        details.append({
            "verse": key,
            "old_start": old_start,
            "old_end": old_end,
            "new_start": v["start"],
            "new_end": v["end"],
        })

    # Note: If fewer markers than verses, we leave the remaining verses unchanged
    return n_update, n_verses, details


def prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update verse timing in a chapter JSON using cue markers TSV (and promote to canonical).")
    p.add_argument("--book", "-b", help="Book folder name under workstorage (e.g. 60_1_peter)")
    p.add_argument("--chapter", "-c", help="Chapter base filename (e.g. 1_peter2)")
    p.add_argument("--dry-run", action="store_true", help="Show changes without writing the JSON")
    p.add_argument("--verbose", "-v", action="store_true", help="Print per-verse timing table")
    p.add_argument("--no-promote", action="store_true", help="Skip copying updated JSON into canonical datastorage/text tree")
    p.add_argument("--testament", choices=["newTestament", "oldTestament"], help="Explicit testament for workstorage lookup & promotion")
    return p


def load_structure() -> Optional[dict]:
    try:
        with open(STRUCTURE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def determine_testament(book_number: int, structure: Optional[dict]) -> Optional[str]:
    """Determine testament from structure file; fallback heuristic: id <=39 -> old, else new."""
    if not structure:
        if book_number <= 39:
            return "oldTestament"
        if book_number >= 40:
            return "newTestament"
        return None
    for b in structure.get("OldTestament", []):
        if b.get("id") == book_number:
            return "oldTestament"
    for b in structure.get("NewTestament", []):
        if b.get("id") == book_number:
            return "newTestament"
    # Fallback heuristic
    if book_number <= 39:
        return "oldTestament"
    if book_number >= 40:
        return "newTestament"
    return None
def resolve_book_dir(book: str, testament_hint: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (path, testament_used) where path is the existing directory for the book.
    Search order: explicit testament if provided, then direct, then newTestament, then oldTestament.
    """
    # 1. Explicit testament override
    candidates = []
    if testament_hint:
        candidates.append(os.path.join(WORK, testament_hint, book))
    # 2. Direct old layout
    candidates.append(os.path.join(WORK, book))
    # 3. New / old testaments
    candidates.append(os.path.join(WORK, "newTestament", book))
    candidates.append(os.path.join(WORK, "oldTestament", book))

    for c in candidates:
        if os.path.isdir(c):
            # Infer testament from path segments
            if "/newTestament/" in c or c.endswith("/newTestament") or c.split(os.sep)[-2] == "newTestament":
                return c, "newTestament"
            if "/oldTestament/" in c or c.endswith("/oldTestament") or c.split(os.sep)[-2] == "oldTestament":
                return c, "oldTestament"
            # Undetermined (legacy direct path)
            return c, None
    return None, None



def parse_book_number(book_folder: str) -> Optional[int]:
    try:
        prefix = book_folder.split("_", 1)[0]
        return int(prefix)
    except Exception:
        return None


def main(argv: List[str]) -> int:
    print("Verse Timing Wizard")
    print("--------------------")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Fallback to interactive if flags missing
    book = args.book or prompt("Which book? (e.g., 60_1_peter): ")
    if not book:
        print("No book provided. Exiting.")
        return 1
    chapter_base = args.chapter or prompt("Which chapter? (e.g., 1_peter2): ")
    if not chapter_base:
        print("No chapter provided. Exiting.")
        return 1

    # Resolve book directory across possible layouts
    book_dir, located_testament = resolve_book_dir(book, args.testament)
    if not book_dir:
        print(f"Could not locate book directory for '{book}'. Checked: direct, newTestament, oldTestament paths.")
        return 1

    json_path = os.path.join(book_dir, f"{chapter_base}.json")
    # Preferred new location: workstorage/<book>/timestamp/<chapter>.txt
    timestamp_dir = os.path.join(book_dir, "timestamp")
    tsv_path = os.path.join(timestamp_dir, f"{chapter_base}.txt")
    if not os.path.exists(tsv_path):
        legacy_path = os.path.join(book_dir, f"{chapter_base}.txt")
        if os.path.exists(legacy_path):
            print("Info: Using legacy marker path (no timestamp/ folder found).")
            tsv_path = legacy_path
        else:
            print(f"Could not find marker file in '{timestamp_dir}' or legacy path '{legacy_path}'.")
            return 1

    try:
        markers = read_markers(tsv_path)
    except Exception as e:
        print(f"Error reading markers: {e}")
        return 1

    if not markers:
        print("No markers found. Nothing to update.")
        return 1

    try:
        chapter = load_chapter_json(json_path)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return 1

    updated, total, details = update_timings(chapter, markers)

    extra = len(markers) - total
    if extra > 0:
        print(f"Warning: {extra} extra marker(s) ignored (markers={len(markers)}, verses={total}).")
    elif updated < total:
        print(f"Warning: Only updated {updated}/{total} verses due to insufficient markers.")

    if args.verbose:
        print("\nVerse updates:")
        print("verse\told_start\told_end\tnew_start\tnew_end")
        for d in details:
            print(f"{d['verse']}\t{d['old_start']}\t{d['old_end']}\t{d['new_start']}\t{d['new_end']}")

    promoted_path = None
    if args.dry_run:
        print("\nDry run requested; NOT writing changes.")
    else:
        try:
            save_chapter_json(json_path, chapter)
        except Exception as e:
            print(f"Error saving JSON: {e}")
            return 1
        # Auto-promote unless disabled
        if args.no_promote:
            print("Promotion skipped (--no-promote).")
        else:
            book_num = parse_book_number(book)
            structure = load_structure()
            # Use located_testament preference unless explicit override is given
            testament = args.testament or located_testament
            if not testament and book_num is not None:
                testament = determine_testament(book_num, structure)
            if not testament:
                print("Warning: Could not determine testament; skipping promotion.")
            else:
                canonical_dir = os.path.join(DATA_TEXT, testament, book)
                os.makedirs(canonical_dir, exist_ok=True)
                promoted_path = os.path.join(canonical_dir, f"{chapter_base}.json")
                try:
                    shutil.copy2(json_path, promoted_path)
                except Exception as e:
                    print(f"Warning: Failed to promote chapter: {e}")
                    promoted_path = None
                else:
                    print(f"Promotion complete: {os.path.relpath(promoted_path, ROOT)}")

    action = "(dry-run)" if args.dry_run else ""
    base_msg = f"Updated {updated} verse(s) {action} in {os.path.relpath(json_path, ROOT)} using {len(markers)} marker(s) from {os.path.relpath(tsv_path, ROOT)}."
    if promoted_path and not args.dry_run:
        base_msg += f" Canonical copy: {os.path.relpath(promoted_path, ROOT)}"
    print(base_msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
