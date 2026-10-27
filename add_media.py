#!/usr/bin/env python3
"""
add_media.py - copy photos and videos into the SAADAXA website.

What it does:
  1. Looks through a folder (for example your unzipped Google Drive download).
  2. Photos  -> resized to max 1920 px wide, saved as JPEG in media/  (+ a small thumbnail).
  3. Videos  -> re-encoded to 720p MP4 in media/ (needs ffmpeg). Videos still bigger
                than 45 MB after that are skipped: upload those to YouTube instead.
  4. Writes media/gallery.json, which the website reads to show the gallery.

Run it again any time you have new files. Files already added are skipped, and
captions you typed into media/gallery.json are kept.

Usage (from inside the website folder):
  python3 add_media.py ~/Downloads/saadaxa-drive
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Pillow is missing. Install it with:  pip install pillow")

try:  # optional: lets the script read iPhone .HEIC photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

SITE = Path(__file__).resolve().parent
MEDIA = SITE / "media"
JSON_FILE = MEDIA / "gallery.json"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}
MAX_IMAGE_WIDTH = 1920
THUMB_WIDTH = 640
MAX_VIDEO_MB = 45


def slug(name: str) -> str:
    """Make a safe, web-friendly file name: 'IMG 2034 (1).JPG' -> 'img-2034-1'."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "file"


def caption_from(name: str) -> str:
    """Turn a file name into a starting caption you can edit later."""
    words = re.sub(r"[_\-]+", " ", name).strip()
    if re.fullmatch(r"(img|vid|dsc|pxl|mvimg|whatsapp)?[\s\d]*", words.lower()):
        return ""  # camera-style names make bad captions; leave blank
    return words[:1].upper() + words[1:]


def add_image(src: Path, out_name: str) -> dict | None:
    full = MEDIA / f"{out_name}.jpg"
    thumb = MEDIA / f"{out_name}-thumb.jpg"
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")  # fix phone rotation
            big = im.copy()
            big.thumbnail((MAX_IMAGE_WIDTH, MAX_IMAGE_WIDTH * 2))
            big.save(full, "JPEG", quality=82, optimize=True, progressive=True)
            small = im.copy()
            small.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
            small.save(thumb, "JPEG", quality=78, optimize=True)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not read {src.name}: {e}")
        return None
    return {"type": "image", "src": f"media/{full.name}", "thumb": f"media/{thumb.name}",
            "caption": caption_from(src.stem), "from": src.name}


def add_video(src: Path, out_name: str, have_ffmpeg: bool) -> dict | None:
    out = MEDIA / f"{out_name}.mp4"
    poster = MEDIA / f"{out_name}-poster.jpg"
    if have_ffmpeg:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
               "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "medium",
               "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)]
        if subprocess.run(cmd).returncode != 0:
            print(f"  ! ffmpeg failed on {src.name}")
            return None
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out),
                        "-frames:v", "1", "-vf", "scale=640:-2", str(poster)])
    elif src.suffix.lower() == ".mp4":
        shutil.copy2(src, out)
    else:
        print(f"  ! {src.name}: install ffmpeg to convert {src.suffix} videos to MP4")
        return None

    size_mb = out.stat().st_size / 1e6
    if size_mb > MAX_VIDEO_MB:
        out.unlink(missing_ok=True)
        poster.unlink(missing_ok=True)
        print(f"  ! {src.name} is {size_mb:.0f} MB even after compressing -> upload it to YouTube instead")
        return None
    item = {"type": "video", "src": f"media/{out.name}", "caption": caption_from(src.stem), "from": src.name}
    if poster.exists():
        item["poster"] = f"media/{poster.name}"
    return item


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 add_media.py /path/to/your/photos-folder")
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.is_dir():
        sys.exit(f"Folder not found: {source}")

    MEDIA.mkdir(exist_ok=True)
    have_ffmpeg = shutil.which("ffmpeg") is not None
    if not have_ffmpeg:
        print("Note: ffmpeg not found, so videos will not be compressed (only .mp4 files are copied).")

    gallery = json.loads(JSON_FILE.read_text()) if JSON_FILE.exists() else []
    done = {g.get("from") for g in gallery}
    used = {Path(g.get("src", "")).stem for g in gallery}

    files = sorted(p for p in source.rglob("*") if p.is_file() and not p.name.startswith("."))
    added = skipped = 0
    for f in files:
        ext = f.suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            continue
        if f.name in done:
            skipped += 1
            continue
        if ext in {".heic", ".heif"} and not HEIC_OK:
            print(f"  ! {f.name}: install HEIC support with  pip install pillow-heif")
            continue

        name, n = slug(f.stem), 2
        while name in used:
            name, n = f"{slug(f.stem)}-{n}", n + 1
        used.add(name)

        print(f"  + {f.name}")
        item = add_image(f, name) if ext in IMAGE_EXT else add_video(f, name, have_ffmpeg)
        if item:
            gallery.append(item)
            added += 1

    JSON_FILE.write_text(json.dumps(gallery, indent=2, ensure_ascii=False) + "\n")
    total_mb = sum(p.stat().st_size for p in MEDIA.iterdir()) / 1e6
    print(f"\nDone: {added} added, {skipped} already there. media/ folder is now {total_mb:.0f} MB.")
    print("Next: edit captions in media/gallery.json, then git add, commit and push.")


if __name__ == "__main__":
    main()
