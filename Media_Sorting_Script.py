import os
import re
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image
import piexif

import csv
import subprocess

# ============================================================
# CONFIG
# ============================================================

SOURCE_DIR = r"D:\Sorting_script\output_v3\to_sort"
OUTPUT_DIR = r"D:\Sorting_script\output_v3\sorted"
LOG_FILE = r"D:\Sorting_script\sort_log.csv"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tiff", ".heic", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".mpg"}

# Enable/disable timestamp repair
ENABLE_TIMESTAMP_FIX = True


# ============================================================
# TIMESTAMP REPAIR (EXIF, XMP, QuickTime, filesystem)
# ============================================================

def check_exiftool():
    try:
        result = subprocess.run(
            ["exiftool", "-ver"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

EXIFTOOL_EXISTS = check_exiftool()

if not EXIFTOOL_EXISTS:
    print("WARNING: exiftool is not installed. Timestamp repair will be skipped.")

def ensure_exiftool_available():
    """Check if exiftool is installed. If missing, disable timestamp fixing."""
    try:
        subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
        return True
    except Exception:
        print("\nWARNING: exiftool is not installed. Timestamp repair skipped.\n")
        return False


def apply_correct_dates(filepath, date):
    if not EXIFTOOL_EXISTS:
        return False

    try:
        result = subprocess.run(
            [
                "exiftool",
                f"-AllDates={date.strftime('%Y:%m:%d %H:%M:%S')}",
                f"-FileModifyDate={date.strftime('%Y:%m:%d %H:%M:%S')}",
                "-overwrite_original",
                str(filepath)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


# ============================================================
# CSV LOGFILE
# ============================================================

def init_log():
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Source",
                    "Destination",
                    "Device",
                    "Category",
                    "Date",
                    "Hash",
                    "Duplicate",
                    "TimestampFixed"
                ])

def log_move(src, dest, device, category, date, filehash, duplicate, timestamp_fixed):
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            src,
            dest,
            device,
            category,
            date,
            filehash,
            duplicate,
            "YES" if timestamp_fixed else "NO"
        ])

# ============================================================
# FILENAME DATE EXTRACTION
# ============================================================

FILENAME_DATE_PATTERNS = [
    r"(?P<y>20\d{2})[-_.](?P<m>\d{2})[-_.](?P<d>\d{2})",
    r"(?P<d>\d{2})[-_.](?P<m>\d{2})[-_.](?P<y>20\d{2})",
    r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})",
    r"(?P<d>\d{2})(?P<m>\d{2})(?P<y>20\d{2})",
    r"(IMG|VID)[-_]?(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})",
]

def parse_date_from_filename(filename):
    name = os.path.splitext(filename)[0]

    for pattern in FILENAME_DATE_PATTERNS:
        match = re.search(pattern, name)
        if match:
            try:
                return datetime(
                    int(match.group("y")),
                    int(match.group("m")),
                    int(match.group("d"))
                )
            except:
                pass
    return None

# ============================================================
# DEVICE CLEANING
# ============================================================

def clean_device_string(s: str) -> str:
    if not s:
        return "default"

    s = "".join(ch for ch in str(s) if 32 <= ord(ch) <= 126)
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")

    if s.lower() in {"", "default", "default_", "_default", "default_default"}:
        return "default"

    return s

# ============================================================
# EXIF READING
# ============================================================

def get_exif_data(path):
    try:
        img = Image.open(path)
        exif = img.getexif()

        date = None
        date_str = exif.get(36867) or exif.get(306)
        if date_str:
            try:
                date = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            except:
                pass

        make = clean_device_string(exif.get(271, ""))
        model = clean_device_string(exif.get(272, ""))

        if make == "default" or model == "default":
            device = "default"
        else:
            device = f"{make}_{model}".strip("_")

        return date, clean_device_string(device)
    except:
        return None, "default"

# ============================================================
# BEST DATE (EXIF → filename → filesystem)
# ============================================================

def get_best_date(path):
    ext = path.suffix.lower()

    if ext in IMAGE_EXT:
        exif_date, device = get_exif_data(path)
        if exif_date:
            return exif_date, device
    else:
        device = "default"

    filename_date = parse_date_from_filename(path.name)
    if filename_date:
        return filename_date, device

    return datetime.fromtimestamp(path.stat().st_mtime), device

# ============================================================
# METADATA FILENAME
# ============================================================

def clean_filename_text(text: str) -> str:
    if not text:
        return ""
    text = "".join(ch for ch in text if ch.isprintable())
    text = re.sub(r'[<>:\"/\\|?*]', "", text)
    return text.strip(" .")

def get_metadata_filename(path: Path) -> str:
    try:
        img = Image.open(path)
        exif = img.getexif()

        # ImageDescription
        desc = exif.get(270)
        if desc:
            name = clean_filename_text(str(desc))
            if name:
                return name + path.suffix

        # DocumentName
        doc = exif.get(514)
        if doc:
            name = clean_filename_text(str(doc))
            if name:
                return name + path.suffix

        # XPFilename
        xpfn = exif.get(0x5012)
        if xpfn:
            try:
                if isinstance(xpfn, bytes):
                    decoded = xpfn.decode("utf-16le").rstrip("\x00")
                else:
                    decoded = str(xpfn)
                name = clean_filename_text(decoded)
                if name:
                    if not name.lower().endswith(path.suffix.lower()):
                        name += path.suffix
                    return name
            except:
                pass
    except:
        pass

    return path.name

# ============================================================
# HASH
# ============================================================

def get_file_hash(path, blocksize=65536):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(blocksize), b""):
            h.update(block)
    return h.hexdigest()

# ============================================================
# CATEGORY DETECTION
# ============================================================

SPECIAL_KEYWORDS = [
    "whatsapp", "screenshot", "scan",
    "instagram", "facebook", "messenger",
    "snapchat", "tiktok", "wechat", "telegram"
]

def detect_special_category(path: Path, root: str) -> str:
    name = path.name.lower()
    root = root.lower()
    for word in SPECIAL_KEYWORDS:
        if word in name or word in root:
            return word
    return ""

# ============================================================
# FOLDER CREATION
# ============================================================

def make_date_path(base_dir, device, date, category=""):
    year = f"{date.year:04d}"
    month = f"{date.month:02d}"
    day = f"{date.day:02d}"

    if category:
        target = Path(base_dir) / device / category / year / month / day
    else:
        target = Path(base_dir) / device / year / month / day

    target.mkdir(parents=True, exist_ok=True)
    return target

# ============================================================
# JUNK CLEANUP
# ============================================================

def delete_junk_files(base_path):
    junk_exact = {
        ".ds_store", "desktop.ini", "thumbs.db",
        "._thumbs", ".nomedia", ".picasa", ".picasaoriginals"
    }

    for root, dirs, files in os.walk(base_path):
        for f in files:
            lower = f.lower()
            fp = Path(root) / f

            if lower in junk_exact:
                try:
                    fp.unlink()
                    print("Deleted:", fp)
                except:
                    pass
                continue

            if lower.startswith("thumbs.db"):
                try:
                    fp.unlink()
                    print("Deleted:", fp)
                except:
                    pass

##            if f.startswith("._"):
##                try:
##                    fp.unlink()
##                    print("Deleted:", fp)
##                except:
##                    pass
##                continue

            if lower.endswith(".thm"):
                try:
                    fp.unlink()
                    print("Deleted THM:", fp)
                except:
                    pass
                continue

def delete_empty_folders(base_path):
    removed = True
    while removed:
        removed = False
        for root, dirs, _ in os.walk(base_path, topdown=False):
            for d in dirs:
                p = Path(root) / d
                try:
                    if not any(p.iterdir()):
                        p.rmdir()
                        removed = True
                        print("Deleted empty folder:", p)
                except:
                    pass

def move_remaining_non_media_files():
    root_dest = Path(OUTPUT_DIR)

    for current_root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            src = Path(current_root) / file
            ext = src.suffix.lower()

            # Skip media files — we only want leftovers
##            if ext in IMAGE_EXT or ext in VIDEO_EXT:
##                continue

            # Skip junk files (already handled)
##            if file.lower() in {"desktop.ini", ".ds_store", "thumbs.db"}:
##                continue
##            if file.lower().startswith("thumbs.db"):
##                continue

            # Prepare destination path
            dest = root_dest / src.name

            # Duplicate handling
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                count = 1
                new_dest = root_dest / f"{stem}_DUP{suffix}"

                while new_dest.exists():
                    new_dest = root_dest / f"{stem}_DUP_{count}{suffix}"
                    count += 1

                dest = new_dest

            print(f"Moving leftover file: {src} → {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(src), str(dest))
            except Exception as e:
                print("Failed to move leftover file:", src, e)

# ============================================================
# MAIN SORTING LOGIC
# ============================================================

def sort_media():
    seen_hashes = {}

    for root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            path = Path(root) / file
            ext = path.suffix.lower()

            if ext not in IMAGE_EXT | VIDEO_EXT:
                continue

            date, device = get_best_date(path)
            category = detect_special_category(path, root)

            new_name = get_metadata_filename(path)
            base_name = new_name if new_name.lower().endswith(ext) else new_name + ext

            filehash = get_file_hash(path)
            duplicate = filehash in seen_hashes

            target_dir = make_date_path(OUTPUT_DIR, device, date, category)
            target_file = target_dir / base_name

            if target_file.exists():
                stem = target_file.stem
                suffix = target_file.suffix

                if not duplicate:
                    target_file = target_dir / f"{stem}_DUP{suffix}"

                count = 1
                while target_file.exists():
                    target_file = target_dir / f"{stem}_DUP_{count}{suffix}"
                    count += 1

            print(f"Moving {path} → {target_file}")
            shutil.move(str(path), str(target_file))

            # Apply timestamp repair
            print(f"Correcting date in {target_file} to {date}")
            timestamp_fixed = apply_correct_dates(target_file, date)

            log_move(
                path,
                target_file,
                device,
                category,
                date,
                filehash,
                duplicate,
                'false'
            )
            seen_hashes[filehash] = target_file

    print("\nSorting completed!")

# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    init_log()
    sort_media()

    print("\nMoving leftover non-media files...")
    move_remaining_non_media_files()

    print("\nCleaning junk files...")
    delete_junk_files(SOURCE_DIR)

    print("Removing empty folders...")
    delete_empty_folders(SOURCE_DIR)

    print("Done.")
