#!/usr/bin/env python3
import argparse
import os
import re
from collections import defaultdict
from pathlib import Path

# Regex to recognize duplicate suffixes
DUPLICATE_SUFFIXES = [
    r"\(\s*\d+\s*\)",          # (1), (2), (10)
    r"copy(?:\s*\d+)?",        # copy, copy2, copy 2
    r"-\s*copy(?:\s*\d+)?",    # - copy, - copy 3
    r"_copy(?:\s*\d+)?",       # _copy, _copy 2
]
DUPLICATE_TRAIL_RE = re.compile(
    r"(?:[\s._-]*(?:" + "|".join(DUPLICATE_SUFFIXES) + r"))+$",
    flags=re.IGNORECASE,
)
TRAILING_SEPARATORS_RE = re.compile(r"[\s._-]+$")

def normalize_stem(stem: str) -> str:
    """Strip duplicate markers from the END of a filename stem."""
    s = stem
    while True:
        new = DUPLICATE_TRAIL_RE.sub("", s)
        new = TRAILING_SEPARATORS_RE.sub("", new)
        if new == s:
            break
        s = new
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

def scan_folder(dirpath: Path, include_hidden: bool, prefix: str):
    """
    Return mapping: (normalized_stem, ext_lower) -> list[Path] for files in dirpath only.
    """
    groups = defaultdict(list)
    try:
        entries = list(os.scandir(dirpath))
    except PermissionError:
        return groups
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        if not include_hidden and entry.name.startswith("."):
            continue
        p = Path(entry.path)
        # If prefix filter is set, skip if stem doesn't contain it
        if prefix and prefix.lower() not in p.stem.lower():
            continue
        key = (normalize_stem(p.stem), p.suffix.lower())
        groups[key].append(p)
    return groups

def pick_winner(files):
    """Return (winner_path, losers_list, sizes) by size (largest wins)."""
    sized = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = -1
        sized.append((size, f.name.lower(), f))
    sized.sort(key=lambda t: (t[0], t[1]), reverse=True)
    winner = sized[0][2]
    losers = [t[2] for t in sized[1:]]
    return winner, losers, [t[0] for t in sized]

def human_bytes(n: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024

def collect_groups(root: Path, recursive: bool, include_hidden: bool, prefix: str):
    """Collect duplicate groups within each directory."""
    all_groups = defaultdict(list)

    def collect_dir(d: Path):
        groups = scan_folder(d, include_hidden=include_hidden, prefix=prefix)
        for k, v in groups.items():
            all_groups[(d, k)] = v

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            collect_dir(Path(dirpath))
    else:
        collect_dir(root)

    total_groups = 0
    total_files = 0
    total_to_delete = 0
    total_bytes_to_delete = 0
    actions = []

    for (dirpath, (norm_stem, ext)), files in sorted(all_groups.items()):
        if len(files) <= 1:
            continue
        stems = {p.stem for p in files}
        if not (any(DUPLICATE_TRAIL_RE.search(s) for s in stems) or len(stems) > 1):
            continue

        winner, losers, sizes = pick_winner(files)

        total_groups += 1
        total_files += len(files)
        total_to_delete += len(losers)

        group_bytes = sum(
            (f.stat().st_size if f.exists() else 0) for f in losers
        )
        total_bytes_to_delete += group_bytes

        actions.append((winner, losers, dirpath, norm_stem, ext, sizes))

    stats = {
        "duplicate_groups": total_groups,
        "files_in_groups": total_files,
        "files_to_delete": total_to_delete,
        "bytes_to_delete": total_bytes_to_delete,
    }
    return actions, stats

def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate photos/videos by duplicate suffixes; keep largest file in each group."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Folder to scan (default: current directory)")
    parser.add_argument("--no-recursive", action="store_true", help="Only scan the top-level folder")
    parser.add_argument("--include-hidden", action="store_true", help="Include dotfiles")
    parser.add_argument("--prefix", type=str, default="", help="Only consider files whose names contain this prefix")
    args = parser.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.")
        return

    recursive = not args.no_recursive

    actions, stats = collect_groups(root, recursive=recursive, include_hidden=args.include_hidden, prefix=args.prefix)

    print("=== Duplicate Detection Summary ===")
    print(f"Directory scanned : {root}")
    print(f"Recursive         : {recursive}")
    print(f"Include hidden    : {args.include_hidden}")
    print(f"Prefix filter     : {args.prefix or '(none)'}")
    print(f"Duplicate groups  : {stats['duplicate_groups']}")
    print(f"Files in groups   : {stats['files_in_groups']}")
    print(f"Files to delete   : {stats['files_to_delete']}")
    print(f"Space to recover  : {human_bytes(stats['bytes_to_delete'])}")
    print()

    if not actions:
        print("No duplicates detected based on naming patterns and prefix filter.")
        return

    preview = actions[:min(15, len(actions))]
    print("Sample of planned actions:")
    for winner, losers, dirpath, norm_stem, ext, sizes in preview:
        try:
            wsize = winner.stat().st_size
        except OSError:
            wsize = -1
        print(f"- Keep:   {winner.name} ({human_bytes(max(wsize,0))})")
        for f in losers:
            try:
                sz = f.stat().st_size
            except OSError:
                sz = -1
            print(f"  Delete: {f.name} ({human_bytes(max(sz,0))})")
        print(f"  Group: stem='{norm_stem}' ext='{ext}' in {dirpath}")
    if len(actions) > len(preview):
        print(f"...and {len(actions) - len(preview)} more groups.")
    print()

    while True:
        choice = input("Proceed to delete the duplicates listed above? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            break
        elif choice in ("n", "no", ""):
            print("No files were deleted.")
            return
        else:
            print("Please answer 'y' or 'n'.")

    print("\n=== Deleting duplicates ===")
    failures = 0
    for winner, losers, dirpath, norm_stem, ext, sizes in actions:
        for f in losers:
            try:
                os.remove(f)
                print(f"Deleted: {f}")
            except Exception as e:
                failures += 1
                print(f"Failed to delete {f}: {e}")

    print("\n=== Done ===")
    print(f"Attempted deletions: {stats['files_to_delete']}, failures: {failures}")
    print(f"Estimated space freed: {human_bytes(stats['bytes_to_delete'])}")

if __name__ == "__main__":
    main()
