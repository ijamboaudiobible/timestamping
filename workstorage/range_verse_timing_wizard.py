#!/usr/bin/env python3
"""
Range Verse Timing Wizard

Similar to verse_timing_wizard.py but processes range-based timestamps from Adobe Audition.
These timestamps represent 1-second silence ranges between verses.

Key differences from verse_timing_wizard.py:
- Reads from `timestamprange/` folder instead of `timestamp/`
- Each marker represents a 1-second silence range (not a single point)
- Uses the MIDDLE of each range (start + 0.5 sec) as the verse boundary
- First marker is silence BEFORE verse 1 starts

Timing logic:
- Marker[0] = silence before verse 1
- Verse 1: start = middle of marker[0], end = middle of marker[1]
- Verse 2: start = middle of marker[1], end = middle of marker[2]
- Verse N: start = middle of marker[N-1], end = middle of marker[N]

Functions:
1. Interactive mode (default if flags not provided):
    - Prompts for a book folder (e.g., 43_john)
    - Prompts for a chapter base name (e.g., john21)
2. Non‑interactive (flags):
    - Provide --book and --chapter to skip prompts.
3. Bulk processing mode:
    - Use --book and --bulk to process all timestamprange files for a book

Book directory resolution order (first existing is used):
    workstorage/<book>
    workstorage/newTestament/<book>
    workstorage/oldTestament/<book>
You can force a testament with --testament newTestament|oldTestament.

Auto-promotion:
After a successful (non-dry-run) update, the script copies the chapter JSON into the canonical tree:
    datastorage/text/<testament>/<book>/<chapter>.json

Examples:
    # Interactive
    python3 workstorage/range_verse_timing_wizard.py

    # Non-interactive specify book & chapter
    python3 workstorage/range_verse_timing_wizard.py --book 43_john --chapter john21

    # Bulk processing - process all timestamprange files for a book
    python3 workstorage/range_verse_timing_wizard.py --book 43_john --bulk

    # Dry run (no file write) with verbose per-verse table
    python3 workstorage/range_verse_timing_wizard.py -b 43_john -c john21 --dry-run --verbose

    # Update without promoting to canonical datastorage
    python3 workstorage/range_verse_timing_wizard.py -b 43_john -c john21 --no-promote
"""

from __future__ import annotations
import json
import argparse
import os
import sys
import shutil
from typing import List, Tuple, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "workstorage")
DATA_TEXT = os.path.join(ROOT, "datastorage", "text")
STRUCTURE_JSON = os.path.join(DATA_TEXT, "KinyarwandaBibleStructure.json")

# Duration of silence range in seconds (Adobe Audition exports 1-second ranges)
SILENCE_DURATION = 1.0
# We use the middle of the silence range as the verse boundary
MIDPOINT_OFFSET = SILENCE_DURATION / 2.0  # 0.5 seconds


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


def read_range_markers(tsv_path: str) -> List[float]:
    """Read range marker times from the TSV file and compute midpoints.
    
    Each marker represents a silence range. We return the MIDPOINT of each range
    (start + 0.5 seconds for a 1-second range).
    
    Returns a list of midpoint times (float), sorted ascending.
    """
    if not os.path.exists(tsv_path):
        raise FileNotFoundError(f"Cue file not found: {tsv_path}")

    midpoints: List[float] = []
    with open(tsv_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    if not lines:
        return midpoints

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
            start_sec = parse_time_to_seconds(start_str)
            # Calculate midpoint of the silence range
            midpoint = start_sec + MIDPOINT_OFFSET
            midpoints.append(round(midpoint, 3))
        except ValueError:
            # Skip malformed entries but continue
            continue

    # Ensure ascending order
    midpoints.sort()
    return midpoints


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


def update_timings(chapter: dict, midpoint_times: List[float]):
    """Update chapter['verses'][*]['start'|'end'] in place using midpoint times.
    
    For range-based markers where first marker is silence BEFORE verse 1:
    - We need N+1 markers for N verses (one before verse 1, one after each verse)
    - Verse 1: start = midpoint[0], end = midpoint[1]
    - Verse 2: start = midpoint[1], end = midpoint[2]
    - Verse N: start = midpoint[N-1], end = midpoint[N]
    
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

    n_markers = len(midpoint_times)
    n_verses = len(verse_keys)

    # We need N+1 markers for N verses
    # With M markers, we can update min(M-1, N) verses
    n_update = min(n_markers - 1, n_verses) if n_markers > 0 else 0
    details = []
    
    for i in range(n_update):
        key = verse_keys[i]
        # Start time: midpoint of marker[i] (silence before this verse)
        start_val = midpoint_times[i]
        # End time: midpoint of marker[i+1] (silence after this verse)
        end_val = midpoint_times[i + 1]
        
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

    return n_update, n_verses, details


def prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update verse timing using range-based cue markers (Adobe Audition silence ranges).")
    p.add_argument("--book", "-b", help="Book folder name under workstorage (e.g. 43_john)")
    p.add_argument("--chapter", "-c", help="Chapter base filename (e.g. john21)")
    p.add_argument("--bulk", action="store_true", help="Process all timestamprange files for the specified book")
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
    candidates = []
    if testament_hint:
        candidates.append(os.path.join(WORK, testament_hint, book))
    # Direct old layout
    candidates.append(os.path.join(WORK, book))
    # New / old testaments
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


def process_single_chapter(book_dir: str, chapter_base: str, args, book: str) -> Tuple[bool, str]:
    """
    Process a single chapter and return (success, message).
    """
    json_path = os.path.join(book_dir, f"{chapter_base}.json")
    # Range-based timestamps location: workstorage/<book>/timestamprange/<chapter>.txt
    timestamprange_dir = os.path.join(book_dir, "timestamprange")
    tsv_path = os.path.join(timestamprange_dir, f"{chapter_base}.txt")
    
    if not os.path.exists(tsv_path):
        return False, f"Could not find range marker file: {tsv_path}"
    
    if not os.path.exists(json_path):
        return False, f"JSON file not found: {json_path}"

    try:
        midpoints = read_range_markers(tsv_path)
    except Exception as e:
        return False, f"Error reading markers for {chapter_base}: {e}"

    if not midpoints:
        return False, f"No markers found for {chapter_base}. Nothing to update."

    try:
        chapter = load_chapter_json(json_path)
    except Exception as e:
        return False, f"Error loading JSON for {chapter_base}: {e}"

    n_verses = len(chapter.get("verses", {}))
    n_markers = len(midpoints)
    required_markers = n_verses + 1  # Need N+1 markers for N verses

    updated, total, details = update_timings(chapter, midpoints)

    warning_msg = ""
    if n_markers > required_markers:
        extra = n_markers - required_markers
        warning_msg += f" [Warning: {extra} extra marker(s) ignored]"
    elif n_markers < required_markers:
        missing = required_markers - n_markers
        RED = "\033[91m"
        RESET = "\033[0m"
        warning_msg += f"\n{RED}  ⚠ ERROR: Missing {missing} marker(s)! Need {required_markers} markers for {n_verses} verses but only found {n_markers}.{RESET}"
        warning_msg += f"\n{RED}  ⚠ Verses {updated+1}-{n_verses} were NOT updated and may have incorrect timing!{RESET}"

    if args.verbose:
        print(f"\nVerse updates for {chapter_base}:")
        print("verse\told_start\told_end\tnew_start\tnew_end")
        for d in details:
            print(f"{d['verse']}\t{d['old_start']}\t{d['old_end']}\t{d['new_start']}\t{d['new_end']}")

    promoted_path = None
    if not args.dry_run:
        try:
            save_chapter_json(json_path, chapter)
        except Exception as e:
            return False, f"Error saving JSON for {chapter_base}: {e}"
        
        # Auto-promote unless disabled
        if not args.no_promote:
            book_num = parse_book_number(book)
            structure = load_structure()
            testament = args.testament
            if not testament and book_num is not None:
                testament = determine_testament(book_num, structure)
            if testament:
                canonical_dir = os.path.join(DATA_TEXT, testament, book)
                os.makedirs(canonical_dir, exist_ok=True)
                promoted_path = os.path.join(canonical_dir, f"{chapter_base}.json")
                try:
                    shutil.copy2(json_path, promoted_path)
                except Exception as e:
                    warning_msg += f" [Warning: Failed to promote chapter: {e}]"
                    promoted_path = None

    action = "(dry-run)" if args.dry_run else ""
    result_msg = f"Updated {updated}/{total} verse(s) {action} for {chapter_base} using {n_markers} range marker(s){warning_msg}."
    if promoted_path and not args.dry_run:
        result_msg += f" Promoted to: {os.path.relpath(promoted_path, ROOT)}"
    
    return True, result_msg


def process_bulk(book_dir: str, book: str, args) -> int:
    """
    Process all timestamprange files in the book directory.
    Returns exit code (0 for success, 1 for failure).
    """
    timestamprange_dir = os.path.join(book_dir, "timestamprange")
    
    if not os.path.exists(timestamprange_dir):
        print(f"No timestamprange directory found in {book_dir}")
        return 1
    
    # Find all .txt files in timestamprange directory
    txt_files = []
    try:
        for filename in os.listdir(timestamprange_dir):
            if filename.endswith('.txt'):
                chapter_base = filename[:-4]  # Remove .txt extension
                txt_files.append(chapter_base)
    except Exception as e:
        print(f"Error listing timestamprange directory: {e}")
        return 1
    
    if not txt_files:
        print(f"No .txt files found in {timestamprange_dir}")
        return 1
    
    # Sort files for consistent processing order
    txt_files.sort()
    
    print(f"Found {len(txt_files)} timestamprange file(s) to process:")
    for f in txt_files:
        print(f"  - {f}.txt")
    print()
    
    success_count = 0
    failed_files = []
    
    for chapter_base in txt_files:
        print(f"Processing {chapter_base}...")
        success, message = process_single_chapter(book_dir, chapter_base, args, book)
        print(f"  {message}")
        
        if success:
            success_count += 1
        else:
            failed_files.append(chapter_base)
    
    print(f"\nBulk processing complete:")
    print(f"  Successfully processed: {success_count}/{len(txt_files)} files")
    
    if failed_files:
        print(f"  Failed files: {', '.join(failed_files)}")
        return 1
    
    return 0


def main(argv: List[str]) -> int:
    print("Range Verse Timing Wizard")
    print("--------------------------")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Get book - required for both single and bulk modes
    book = args.book or prompt("Which book? (e.g., 43_john): ")
    if not book:
        print("No book provided. Exiting.")
        return 1

    # Resolve book directory across possible layouts
    book_dir, located_testament = resolve_book_dir(book, args.testament)
    if not book_dir:
        print(f"Could not locate book directory for '{book}'. Checked: direct, newTestament, oldTestament paths.")
        return 1

    # If testament not explicitly provided, use the located one
    if not args.testament:
        args.testament = located_testament

    # Check if bulk mode is requested
    if args.bulk:
        print(f"Bulk processing mode for book: {book}")
        print(f"Book directory: {os.path.relpath(book_dir, ROOT)}")
        return process_bulk(book_dir, book, args)

    # Single chapter mode
    chapter_base = args.chapter or prompt("Which chapter? (e.g., john21): ")
    if not chapter_base:
        print("No chapter provided. Exiting.")
        return 1

    success, message = process_single_chapter(book_dir, chapter_base, args, book)
    print(message)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
