#!/usr/bin/env python3
"""
heic2jpg — Recursively convert HEIC/HEIF images to high-quality JPG in place.

What’s new vs the previous version:
- Better quality defaults (quality=96, subsampling=0, optimize+progressive)
- tqdm progress bar
- Robust color management to avoid subtle color shifts:
    * Default: convert to sRGB and embed an sRGB ICC profile
    * --icc keep: keep & embed source ICC (no conversion)
    * --icc none: embed nothing (not recommended)
- Explicit support for .heic, .heif, .heics, .heifs

Dependencies:
    pip install pillow pillow-heif tqdm
    (Recommended: Pillow with ImageCms for color conversion.)

Usage:
    python heic2jpg.py [PATH ...]
    ./heic2jpg [PATH ...]
Options:
    -w, --workers N     Number of parallel workers (default: CPU count)
    -q, --quality N     JPEG quality 1..100 (default: 96)
    --overwrite         Overwrite existing .jpg if present (default: skip)
    --icc {srgb,keep,none}  How to handle color profiles (default: srgb)
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        from PIL import ImageCms  # type: ignore
        _HAVE_CMS = True
    except Exception:
        _HAVE_CMS = False
except ImportError:
    sys.stderr.write(
        "Error: Pillow not installed.\n"
        "Install with: pip install pillow pillow-heif tqdm\n"
    )
    raise

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception as e:
    sys.stderr.write(
        "Error: pillow-heif is not available or failed to load.\n"
        "Install with: pip install pillow-heif\n"
        f"Details: {e}\n"
    )
    raise

try:
    from tqdm import tqdm  # type: ignore
except Exception:
    tqdm = None  # fall back to simple counters if tqdm not present

HEIF_EXTS = {".heic", ".heif", ".heics", ".heifs"}  # case-insensitive
DEFAULT_QUALITY = 92
DEFAULT_SUBSAMPLING = 2  # 4:2:0 (good chroma tradeoffs)
DEFAULT_OPTIMIZE = True
DEFAULT_PROGRESSIVE = True
ALPHA_BG = (255, 255, 255)  # background when flattening transparency


def find_heif_files(paths: Iterable[Path]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        if p.is_dir():
            for ext in HEIF_EXTS:
                files.extend(p.rglob(f"*{ext}"))
                files.extend(p.rglob(f"*{ext.upper()}"))
        elif p.is_file() and p.suffix.lower() in HEIF_EXTS:
            files.append(p)
    # Deduplicate by resolved path, stable order
    unique = {str(f.resolve()): f for f in files}
    return sorted(unique.values(), key=lambda x: str(x).lower())


def prompt_yes_no(question: str, default: bool | None = None) -> bool:
    suffix = " [y/n]" if default is None else (" [Y/n]" if default else " [y/N]")
    while True:
        resp = input(f"{question}{suffix}: ").strip().lower()
        if not resp and default is not None:
            return default
        if resp in {"y", "yes"}:
            return True
        if resp in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def _exif_orient_and_flatten(im: Image.Image, bg=ALPHA_BG) -> Image.Image:
    # Correct orientation first
    im = ImageOps.exif_transpose(im)
    # Flatten any transparency
    if "A" in im.getbands():
        im_rgba = im.convert("RGBA")
        bg_img = Image.new("RGB", im_rgba.size, bg)
        bg_img.paste(im_rgba, mask=im_rgba.split()[-1])
        return bg_img
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def _convert_to_srgb(im: Image.Image, src_icc: bytes | None) -> tuple[Image.Image, bytes | None]:
    """
    Convert to sRGB if we can detect a source profile and ImageCms is available.
    Return (converted_image, icc_bytes_to_embed).
    """
    if not _HAVE_CMS:
        # Fallback: keep as-is; if we had a source profile, keep it.
        return im, src_icc

    try:
        srgb_prof = ImageCms.createProfile("sRGB")
        srgb_bytes = ImageCms.ImageCmsProfile(srgb_prof).tobytes()
    except Exception:
        # Should be rare; if we cannot create sRGB profile, keep existing ICC
        return im, src_icc

    if src_icc:
        try:
            src_prof = ImageCms.ImageCmsProfile(io.BytesIO(src_icc))
            # Ensure we're working with 8-bit RGB
            if im.mode != "RGB":
                im = im.convert("RGB")
            im = ImageCms.profileToProfile(im, src_prof, srgb_prof, outputMode="RGB", renderingIntent=0)
            return im, srgb_bytes
        except Exception:
            # If conversion fails, at least embed original ICC to reduce shifts
            return im, src_icc
    else:
        # No source ICC; treat pixels as sRGB and tag as sRGB for consistent viewing
        return im, srgb_bytes


def _save_jpeg(
    im: Image.Image,
    dst_path: Path,
    *,
    quality: int,
    subsampling: int,
    optimize: bool,
    progressive: bool,
    exif: bytes | None,
    icc_profile: bytes | None,
) -> None:
    save_kwargs = dict(
        format="JPEG",
        quality=quality,
        subsampling=subsampling,
        optimize=optimize,
        progressive=progressive,
    )
    if exif:
        save_kwargs["exif"] = exif
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    im.save(dst_path, **save_kwargs)


def _convert_one(
    src: str,
    overwrite: bool,
    quality: int,
    subsampling: int,
    optimize: bool,
    progressive: bool,
    icc_mode: str,  # "srgb" | "keep" | "none"
) -> Tuple[str, str, str]:
    """
    Worker function (top-level for Windows):
    Returns (status, src_path, message_or_dest).
      status: 'converted' | 'skipped' | 'failed'
    """
    src_path = Path(src)
    dst_path = src_path.with_suffix(".jpg")

    if dst_path.exists() and not overwrite:
        return ("skipped", str(src_path), "destination exists")

    try:
        with Image.open(src_path) as im:
            # Preserve EXIF (after orientation fix below)
            # Some HEICs don't carry standard EXIF; .getexif() returns an editable container anyway.
            # We obtain bytes after orientation so it's consistent.
            im = ImageOps.exif_transpose(im)
            exif_bytes = im.getexif().tobytes()

            # Grab source ICC if present
            src_icc = im.info.get("icc_profile")

            # Flatten & ensure RGB
            im = _exif_orient_and_flatten(im)

            # Color management
            if icc_mode == "srgb":
                im, icc_to_embed = _convert_to_srgb(im, src_icc)
            elif icc_mode == "keep":
                icc_to_embed = src_icc
            else:  # "none"
                icc_to_embed = None

            # Save high-quality JPEG
            _save_jpeg(
                im,
                dst_path,
                quality=quality,
                subsampling=subsampling,
                optimize=optimize,
                progressive=progressive,
                exif=exif_bytes if exif_bytes else None,
                icc_profile=icc_to_embed,
            )

        # Verify output then delete original
        if dst_path.exists() and dst_path.stat().st_size > 0:
            try:
                src_path.unlink()
            except Exception as del_err:
                return ("converted", str(src_path), f"{dst_path} (warning: could not delete source: {del_err})")
            return ("converted", str(src_path), str(dst_path))

        # Cleanup on failure
        try:
            if dst_path.exists():
                dst_path.unlink()
        except Exception:
            pass
        return ("failed", str(src_path), "empty or missing output")

    except (UnidentifiedImageError, OSError, ValueError) as e:
        try:
            if dst_path.exists():
                dst_path.unlink()
        except Exception:
            pass
        return ("failed", str(src_path), repr(e))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="heic2jpg",
        description="Recursively convert HEIC/HEIF to high-quality JPG in place.",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan (default: .)")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count() or 1,
                        help="Parallel workers (default: CPU count)")
    parser.add_argument("-q", "--quality", type=int, default=DEFAULT_QUALITY,
                        help=f"JPEG quality 1..100 (default: {DEFAULT_QUALITY})")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .jpg if present")
    parser.add_argument("--icc", choices=("srgb", "keep", "none"), default="srgb",
                        help="Color profile handling (default: srgb)")
    args = parser.parse_args(argv)

    roots = [Path(p).resolve() for p in args.paths]
    heif_files = find_heif_files(roots)
    total = len(heif_files)

    if total == 0:
        print("No HEIC/HEIF files found.")
        return 0

    print(f"Found {total} HEIC/HEIF file(s).")
    if not prompt_yes_no("Proceed with conversion?", default=False):
        print("Aborted.")
        return 0

    print(f"Starting conversion with {args.workers} worker(s)...")

    stop = False

    def _sigint_handler(signum, frame):
        nonlocal stop
        stop = True
        print("\nCancellation requested; finishing running tasks...")

    signal.signal(signal.SIGINT, _sigint_handler)

    ok = skipped = failed = 0

    pbar = None
    if tqdm is not None:
        pbar = tqdm(total=total, unit="img")

    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {
            ex.submit(
                _convert_one,
                str(p),
                args.overwrite,
                max(1, min(100, args.quality)),
                DEFAULT_SUBSAMPLING,
                DEFAULT_OPTIMIZE,
                DEFAULT_PROGRESSIVE,
                args.icc,
            ): p
            for p in heif_files
        }

        try:
            for fut in as_completed(futures):
                status, src, info = fut.result()
                if status == "converted":
                    ok += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    if pbar is not None:
                        pbar.write(f"✗ Failed: {src} -> {info}")
                    else:
                        print(f"\n✗ Failed: {src} -> {info}")

                if pbar is not None:
                    pbar.update(1)
                    pbar.set_postfix(converted=ok, skipped=skipped, failed=failed)
                else:
                    # Simple text progress if tqdm is unavailable
                    done = ok + skipped + failed
                    print(f"[{done}/{total}] ✓ {ok}  ~ {skipped}  ✗ {failed}", end="\r", flush=True)

                if stop:
                    for f in futures:
                        f.cancel()
                    break
        except KeyboardInterrupt:
            print("\nInterrupted. Cancelling pending tasks…")
        finally:
            if pbar is not None:
                pbar.close()
            else:
                print()  # newline for clean output

    print("Done.")
    print(f"Converted: {ok}  Skipped: {skipped}  Failed: {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
