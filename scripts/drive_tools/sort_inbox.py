#!/usr/bin/env python3
"""Sorts video and photos from Source Video/_inbox into days and cameras.

    Source Video/2026/2026-07 июль/2026-07-14 Lisbon — old town/Pocket4P_D-Log/DJI_….MP4

Rules:
  * the shooting day comes from the metadata; the day starts at 05:00 (anything shot
    after midnight stays with its evening);
  * inside a day, one folder per «Camera_Profile»: one folder = one LUT;
  * file names never change;
  * a file already in the library (same name, size and bytes) goes to
    Source Video/_дубликаты, it is not deleted;
  * anything that cannot be sorted goes to _inbox/_проверить with the reason;
  * every run writes a journal to Source Video/_logs; it can be undone:
        python3 sort_inbox.py --undo "Source Video/_logs/sort_….tsv"

Date hint: put files into an _inbox subfolder named «YYYY-MM-DD …»
(e.g. «2026-07-14 Lisbon — old town»). Files without a reliable date (a camera
with a wrong clock, videos from messengers) get this date, and a new day
folder gets the subfolder's name.

Needs exiftool and ffprobe (brew install exiftool ffmpeg).
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- settings
DAY_START_HOUR = 5
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
          "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".avi", ".mkv", ".3gp"}
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".dng", ".png", ".tif", ".tiff",
             ".webp", ".gif", ".arw", ".cr2", ".cr3", ".nef", ".raf"}
SIDECAR_EXT = {".aae", ".xmp", ".thm"}          # travel with their main file
DJI_JUNK_EXT = {".lrf", ".srt"}                 # DJI proxy previews / subtitles
IGNORE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_EXT = {".command", ".py", ".sh", ".md", ".txt", ".tsv", ".csv", ".json"}

# Model / Encoder → short camera name for the folder
CAMERA_NAMES = {
    "DJI OsmoPocket4P": "Pocket4P", "PP-041": "Pocket4P",
    "DJI OsmoAction5 Pro": "Action5Pro", "AC004": "Action5Pro",
    "DJI OsmoPocket4": "Pocket4", "OP-041": "Pocket4",
    "DJI OsmoPocket3": "Pocket3", "DJI OsmoAction4": "Action4", "AC003": "Action4",
    "DJI NEO": "Neo",            # DJI Neo drone: records 8-bit only → always Normal
}
# Pocket 3 (dvtm_PP-101.proto): the first djmd record has no profile field (2.4 is empty); 10-bit BT.709
# goes to Pocket3_10bit-unknown. Not yet compared against a clip with a known profile.
# Colour profile code that DJI writes into its «djmd» data track (protobuf).
# Checked on 855 clips: the code matched the camera's own label on all 496 Pocket 4P
# clips and the bit depth / HLG on all 179 Action 5 Pro clips. The field depends on the firmware:
DJI_COLOR_FIELD = {"dvtm_ac204.proto": "2.4.1",            # Action 5 Pro
                   "dvtm_ac203.proto": "2.4.1",            # Action 4 (AC003): Normal checked
                   # on 3 clips (field 2.4 present but empty = 0; two of the three 10-bit). That D-Log M sits
                   # in 2.4.1, as on Action 5 Pro, is a guess: no D-Log M clip seen yet, check the first one.
                   "dvtm_osmo_pocket_4.proto": "2.2.3.1"}  # Pocket 4 and 4P
DJI_COLOR_CODES = {0: "Normal", 2: "D-Log", 9: "HLG", 19: "D-Log-M", 22: "D-Log2"}
# Fallback when there is no djmd track (e.g. the file was re-encoded in DJI Mimo):
# what «10-bit, BT.709» means for a camera. Action 5 Pro records Normal in 8-bit only.
TEN_BIT_709_PROFILE = {"Action5Pro": "D-Log-M"}
# Folder names for the profiles DJI writes into DjiCameraColorGammaSxS
GAMMA_NAMES = {"Rec.709": "Normal", "Rec.2100 HLG": "HLG", "HLG": "HLG",
               "D-Log M": "D-Log-M", "D-LogM": "D-Log-M"}

SPECIAL_DIRS = {"_inbox", "_tools", "_logs", "_дубликаты"}
CHECK_DIR_NAME = "_проверить"

EXIF_TAGS = ["FileName", "FileSize", "Make", "Model", "Encoder", "Software",
             "CreationDate", "DateTimeOriginal", "DateCreated", "CreateDate", "Duration",
             "ImageWidth", "ImageHeight", "Rotation", "VideoFrameRate",
             "CompressorID", "TransferCharacteristics", "ColorPrimaries",
             "DjiCameraColorGammaSxS", "DjiCameraCameraModel",
             "ContentIdentifier", "Category"]

SCREEN_PATTERNS = [
    # macOS: «Запись экрана — 2026-10-09 в 00.52.26» (Russian UI), «Screen Recording 2026-10-09 at 00.52.26»
    (re.compile(r"(?:Запись экрана|Снимок экрана|Screen Recording|Screenshot)\D*?"
                r"(\d{4})-(\d{2})-(\d{2})\D+?(\d{1,2})[.:](\d{2})[.:](\d{2})"), "ymd"),
    # iOS 18: «ScreenRecording_10-09-2026 00-52-26_1.MP4»
    (re.compile(r"ScreenRecording_(\d{2})-(\d{2})-(\d{4})[ _](\d{2})-(\d{2})-(\d{2})"), "mdy"),
]
SCREEN_NAME = re.compile(r"(Запись экрана|Снимок экрана|Screen ?Recording|Screenshot|RPReplay)",
                         re.IGNORECASE)
DJI_NAME = re.compile(r"^DJI_(\d{14})_")
DATE_HINT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(.*)$")


# ---------------------------------------------------------------- helpers
def log(msg=""):
    print(msg, flush=True)


def parse_dt(value):
    """'2026:10:31 21:00:05+07:00' → local time (no time zone)."""
    if not value or not isinstance(value, str):
        return None
    m = re.match(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})", value)
    if not m:
        return None
    try:
        t = dt.datetime(*map(int, m.groups()))
    except ValueError:
        return None
    return t if t.year >= 2010 else None


def shooting_day(t):
    return (t - dt.timedelta(hours=DAY_START_HOUR)).date()


def same_bytes(a, b, chunk=8 << 20):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(chunk), fb.read(chunk)
            if x != y:
                return False
            if not x:
                return True


def run_exiftool(paths):
    if not paths:
        return {}
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        for p in paths:
            f.write(p + "\n")
        argfile = f.name
    try:
        cmd = ["exiftool", "-j", "-n", "-q", "-q", "-api", "largefilesupport=1",
               "-charset", "filename=utf8"] + ["-" + t for t in EXIF_TAGS] + ["-@", argfile]
        out = subprocess.run(cmd, capture_output=True, check=False).stdout
    finally:
        os.unlink(argfile)
    data = json.loads(out.decode("utf-8") or "[]")
    return {os.path.normpath(d["SourceFile"]): d for d in data}


def pix_fmt(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return (r.stdout.strip().splitlines() or [""])[0].strip(",")


def _varint(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return r, i


def _protobuf_fields(b, prefix="", out=None, depth=0):
    """Parses protobuf without a schema → {"2.4.1": [19], "1.1.1": ["dvtm_ac204.proto"]}."""
    out = {} if out is None else out
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("not protobuf")
        path = prefix + "." + str(field) if prefix else str(field)
        if wire == 0:
            v, i = _varint(b, i)
            out.setdefault(path, []).append(v)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        elif wire == 2:
            n, i = _varint(b, i)
            sub = b[i:i + n]
            i += n
            nested = {}
            try:
                if depth > 6 or not sub:
                    raise ValueError
                _protobuf_fields(sub, path, nested, depth + 1)
            except (ValueError, IndexError):
                nested = {}
            if nested:
                for k, v in nested.items():
                    out.setdefault(k, []).extend(v)
            else:
                try:
                    out.setdefault(path, []).append(sub.decode("utf-8"))
                except UnicodeDecodeError:
                    pass
        else:
            raise ValueError("not protobuf")
    return out


def dji_color_code(path):
    """Profile code from the first record of the djmd track; None if it cannot be read."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_tag_string",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    idx = next((ln.split(",")[0] for ln in r.stdout.splitlines() if ln.endswith(",djmd")), None)
    if idx is None:
        return None
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", "0:" + idx,
                        "-c", "copy", "-frames:0", "1", "-f", "data", "pipe:1"], capture_output=True)
    try:
        fields = _protobuf_fields(r.stdout)
    except (ValueError, IndexError):
        return None
    proto = next((v for v in fields.get("1.1.1", []) if isinstance(v, str)), None)
    if proto not in DJI_COLOR_FIELD:
        return None
    return (fields.get(DJI_COLOR_FIELD[proto]) or [0])[0]   # 0 is not written in protobuf


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def safe(s):
    return re.sub(r"[^\w.+-]+", "-", s.strip(), flags=re.UNICODE).strip("-") or "Unknown"


# ---------------------------------------------------------------- classification
def camera_name(meta):
    for key in ("Encoder", "DjiCameraCameraModel", "Model"):
        v = meta.get(key)
        if isinstance(v, str) and v in CAMERA_NAMES:
            return CAMERA_NAMES[v]
    cat = meta.get("Category")
    if isinstance(cat, str):
        m = re.search(r"model_name:([\w-]+)", cat)
        if m and m.group(1) in CAMERA_NAMES:
            return CAMERA_NAMES[m.group(1)]
    enc = meta.get("Encoder")
    if isinstance(enc, str) and enc.startswith("DJI "):
        return safe(enc[4:].replace("Osmo", ""))
    make, model = meta.get("Make"), meta.get("Model")
    if isinstance(make, str) and make.strip().upper() == "DJI" and isinstance(model, str):
        return safe(model)
    if isinstance(model, str) and "iphone" in model.lower():
        return "iPhone"
    if isinstance(model, str) and model.strip():
        return safe(model)
    return None


def video_profile(cam, meta, path):
    gamma = meta.get("DjiCameraColorGammaSxS")
    if isinstance(gamma, str) and gamma.strip():
        return GAMMA_NAMES.get(gamma.strip(), safe(gamma))
    trc, prim = meta.get("TransferCharacteristics"), meta.get("ColorPrimaries")
    if cam == "iPhone":
        if trc in (16, 18):
            return "HDR"
        if prim == 9:
            return "Apple-Log"
        return "Normal"
    code = dji_color_code(path) if str(meta.get("Encoder") or meta.get("Make") or "").upper().startswith("DJI") else None
    if code is not None:
        return DJI_COLOR_CODES.get(code, "Code%d" % code)
    if trc == 18:
        return "HLG"
    if trc == 16:
        return "HDR"
    ten_bit = "10" in pix_fmt(path)
    if cam in TEN_BIT_709_PROFILE and ten_bit:
        return TEN_BIT_709_PROFILE[cam]
    if ten_bit and str(meta.get("Encoder") or meta.get("Make") or "").upper().startswith("DJI"):
        return "10bit-unknown"   # DJI with no readable profile: could be log or Normal
    return "Normal"


def take_datetime(path, meta):
    """→ (local time or None, where it came from)."""
    name = os.path.basename(path)
    m = DJI_NAME.match(name)
    if m:
        t = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        if t.year < 2010:
            return None, "часы камеры сбиты (год %d)" % t.year
        return t, "имя DJI"
    for rx, order in SCREEN_PATTERNS:
        m = rx.search(name)
        if m:
            g = list(map(int, m.groups()))
            y, mo, d = (g[0], g[1], g[2]) if order == "ymd" else (g[2], g[0], g[1])
            try:
                return dt.datetime(y, mo, d, g[3], g[4], g[5]), "имя файла"
            except ValueError:
                pass
    for key in ("CreationDate", "DateTimeOriginal", "DateCreated"):
        t = parse_dt(meta.get(key))
        if t:
            return t, key
    return None, "нет даты съёмки в метаданных"


def classify(path, meta, live_ids, photo_stems):
    """→ dict(kind, folder, time, reason)."""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    t, src = take_datetime(path, meta)
    res = {"time": t, "time_src": src, "kind": None, "folder": None, "reason": None}
    cam = camera_name(meta)

    if ext in PHOTO_EXT:
        if SCREEN_NAME.search(name) or (ext == ".png" and not cam):
            res.update(kind="screen", folder="Screen")
        elif cam:
            res.update(kind="photo", folder=cam + "_Photo")
        else:
            res.update(kind="photo", folder="Other_Photo")
        return res

    if ext in VIDEO_EXT:
        if SCREEN_NAME.search(name):
            res.update(kind="screen", folder="Screen")
            return res
        dur = num(meta.get("Duration")) or 0
        cid = meta.get("ContentIdentifier")
        stem = os.path.splitext(path)[0]
        if cam == "iPhone" and dur <= 4.5 and (stem in photo_stems or (cid and cid in live_ids)):
            res.update(kind="live", folder="iPhone_Photo")
            return res
        if cam:
            res.update(kind="video", folder=cam + "_" + video_profile(cam, meta, path))
        else:
            res.update(kind="video", folder="Other")
            if t is None:
                res["reason"] = "неизвестная камера и нет даты (видео из мессенджера?)"
        return res

    res.update(kind="other", reason="не фото и не видео")
    return res


# ---------------------------------------------------------------- structure
class Tree:
    def __init__(self, root):
        self.root = root
        self.index = {}          # file name → [paths] (year/month/day only)
        self.days = {}           # 'YYYY-MM-DD' → day folder path
        self.months = {}         # 'YYYY-MM' → month folder path
        self.planned = {}        # name → [(source, destination)] in this run
        for year in os.listdir(root):
            yp = os.path.join(root, year)
            if not (re.fullmatch(r"\d{4}", year) and os.path.isdir(yp)):
                continue
            for month in os.listdir(yp):
                mp = os.path.join(yp, month)
                mm = re.match(r"(\d{4}-\d{2})", month)
                if not (mm and os.path.isdir(mp)):
                    continue
                self.months[mm.group(1)] = mp
                for day in os.listdir(mp):
                    dp = os.path.join(mp, day)
                    dm = re.match(r"(\d{4}-\d{2}-\d{2})", day)
                    if dm and os.path.isdir(dp):
                        self.days[dm.group(1)] = dp
            for r, ds, fs in os.walk(yp):
                for f in fs:
                    if not f.startswith("._"):
                        self.index.setdefault(f, []).append(os.path.join(r, f))

    def day_dir(self, day, label=None):
        key = day.isoformat()
        if key in self.days:
            return self.days[key]
        mkey = key[:7]
        month = self.months.get(mkey) or os.path.join(
            self.root, key[:4], "%s %s" % (mkey, MONTHS[day.month - 1]))
        self.months[mkey] = month
        name = key + ((" " + label.strip()) if label and label.strip() else "")
        self.days[key] = os.path.join(month, name)
        return self.days[key]

    def candidates(self, name):
        """Files with this name: (where it is now, where it will be)."""
        return [(p, p) for p in self.index.get(name, [])] + self.planned.get(name, [])

    def add_planned(self, src, dst):
        self.planned.setdefault(os.path.basename(dst), []).append((src, dst))


def date_hint(rel):
    """First folder of the path named «YYYY-MM-DD label» → (date, label)."""
    for part in rel.split(os.sep)[:-1]:
        m = DATE_HINT.match(part)
        if m:
            try:
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            label = m.group(4).strip(" -—_")
            return d, label
    return None, None


# ---------------------------------------------------------------- catalog
CAT_FIELDS = ["day", "time", "folder", "kind", "file", "duration_s", "resolution",
              "orientation", "fps", "size_mb", "path", "origin"]


def update_catalog(root, rows_new):
    path = os.path.join(root, "_catalog.csv")
    rows = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["file"], r["size_mb"])] = r
    for r in rows_new:
        key = (r["file"], r["size_mb"])
        old = rows.get(key)
        if old and old.get("origin") and r["origin"] not in old["origin"].split(" | "):
            r["origin"] = old["origin"] + " | " + r["origin"]
        rows[key] = r
    # current paths: everything actually in year/month/day
    present = {}
    for year in os.listdir(root):
        if re.fullmatch(r"\d{4}", year):
            for r, ds, fs in os.walk(os.path.join(root, year)):
                for f in fs:
                    if not f.startswith("._") and f not in IGNORE_NAMES:
                        p = os.path.join(r, f)
                        present[(f, "%.1f" % (os.path.getsize(p) / 1e6))] = p
    out = []
    for key, r in rows.items():
        if key in present:
            p = present[key]
            r["path"] = os.path.relpath(p, root)
            r["folder"] = os.path.basename(os.path.dirname(p))
            out.append(r)
    out.sort(key=lambda r: (r["day"], r["time"], r["file"]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    os.replace(tmp, path)
    return len(out)


def catalog_row(dst, meta, info, day, origin):
    w, h = num(meta.get("ImageWidth")), num(meta.get("ImageHeight"))
    rot = num(meta.get("Rotation")) or 0
    if w and h and rot in (90, 270):
        w, h = h, w
    orient = "" if not (w and h) else ("вертикальное" if h > w else "горизонтальное")
    dur = num(meta.get("Duration"))
    fps = num(meta.get("VideoFrameRate"))
    t = info["time"]
    return {
        "day": day.isoformat() if day else "",
        "time": t.strftime("%H:%M:%S") if t else "",
        "folder": info["folder"] or "",
        "kind": info["kind"] or "",
        "file": os.path.basename(dst),
        "duration_s": "%.1f" % dur if dur else "",
        "resolution": "%dx%d" % (w, h) if w and h else "",
        "orientation": orient,
        "fps": "%.2f" % fps if fps else "",
        "size_mb": "%.1f" % (os.path.getsize(dst) / 1e6),
        "path": "",
        "origin": origin,
    }


# ---------------------------------------------------------------- main pass
def collect(inbox, check_dir, root):
    files = []
    for r, ds, fs in os.walk(inbox):
        ds[:] = sorted(d for d in ds if not d.startswith(".")
                       and os.path.join(r, d) != check_dir
                       # never take sorted or service folders as input
                       and not (r == root and (d in SPECIAL_DIRS or re.fullmatch(r"\d{4}", d))))
        for f in sorted(fs):
            if f.startswith("._") or f.startswith(".") or f in IGNORE_NAMES:
                continue
            if os.path.splitext(f)[1].lower() in IGNORE_EXT:
                continue
            p = os.path.join(r, f)
            if not os.path.islink(p):
                files.append(p)
    return files


def read_labels(path):
    """File of «YYYY-MM-DD<TAB>label» lines → {date: label} for new day folders."""
    out = {}
    if path:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(.+)", line.strip())
                if m:
                    out[dt.date(*map(int, m.groups()[:3]))] = m.group(4).strip()
    return out


def build_plan(root, inbox, origin_base, fixed_labels=None, compare=True):
    check_dir = os.path.join(root, "_inbox", CHECK_DIR_NAME)
    dup_dir = os.path.join(root, "_дубликаты")
    files = collect(inbox, check_dir, root)
    media = [p for p in files if os.path.splitext(p)[1].lower() in VIDEO_EXT | PHOTO_EXT]
    media_set = set(media)
    log("Reading metadata: %d files…" % len(media))
    metas = run_exiftool(media)
    tree = Tree(root)

    photo_stems, live_ids = set(), set()
    for p in media:
        if os.path.splitext(p)[1].lower() in PHOTO_EXT:
            photo_stems.add(os.path.splitext(p)[0])
            cid = metas.get(os.path.normpath(p), {}).get("ContentIdentifier")
            if cid:
                live_ids.add(cid)

    plan = []            # dict(src, dst, action, reason, …)
    planned_dst = {}
    main_dst = {}        # stem → destination folder of the main file (sidecars, Live Photo)
    main_day = {}
    side_dst = {}        # stem → where the main file went (including _дубликаты)

    def to_check(p, reason):
        plan.append({"src": p, "dst": os.path.join(check_dir, os.path.relpath(p, inbox)),
                     "action": "check", "reason": reason})

    items = []
    for p in files:
        ext = os.path.splitext(p)[1].lower()
        if ext in SIDECAR_EXT:
            continue
        if ext in DJI_JUNK_EXT:
            to_check(p, "служебный файл DJI (%s) — можно удалить" % ext)
            continue
        if p not in media_set:
            to_check(p, "не фото и не видео")
            continue
        meta = metas.get(os.path.normpath(p), {})
        info = classify(p, meta, live_ids, photo_stems)
        items.append((p, meta, info))
    # Live Photo videos go last: they need their photo's folder
    items.sort(key=lambda x: (x[2]["kind"] == "live", x[2]["time"] or dt.datetime.max, x[0]))

    # labels for new days from «YYYY-MM-DD label» subfolders
    labels = dict(fixed_labels or {})
    for p, meta, info in items:
        hint_day, hint_label = date_hint(os.path.relpath(p, inbox))
        t = info["time"]
        if hint_day and hint_label and (t is None or shooting_day(t) == hint_day):
            labels.setdefault(hint_day, hint_label)

    for p, meta, info in items:
        rel = os.path.relpath(p, inbox)
        hint_day, hint_label = date_hint(rel)
        t = info["time"]
        day = shooting_day(t) if t else hint_day
        stem = os.path.splitext(p)[0]
        if info["kind"] == "live" and stem in main_dst:
            dst_dir = main_dst[stem]
            day = main_day.get(stem, day)
        elif day is None:
            to_check(p, info["reason"] or info["time_src"])
            continue
        elif info["reason"] and not hint_day:
            to_check(p, info["reason"])
            continue
        else:
            dst_dir = os.path.join(tree.day_dir(day, labels.get(day)), info["folder"])
        dst = os.path.join(dst_dir, os.path.basename(p))
        origin = os.path.join(origin_base, rel) if origin_base else rel
        entry = {"src": p, "dst": dst, "action": "move", "meta": meta, "info": info,
                 "day": day, "origin": origin, "reason": ""}

        size = os.path.getsize(p)
        dup_of = None
        for now, final in tree.candidates(os.path.basename(p)):
            if now != p and os.path.getsize(now) == size and (not compare or same_bytes(p, now)):
                dup_of = final
                break
        if dup_of:
            entry.update(action="dup", dst=os.path.join(dup_dir, origin),
                         reason="уже есть: " + os.path.relpath(dup_of, root), keep=dup_of)
        elif os.path.exists(dst) or dst in planned_dst:
            to_check(p, "в папке назначения уже есть другой файл с таким именем")
            continue
        else:
            planned_dst[dst] = p
            tree.add_planned(p, dst)
        plan.append(entry)
        side_dst[stem] = os.path.dirname(entry["dst"])
        if entry["action"] == "move":
            main_dst[stem] = os.path.dirname(entry["dst"])
            main_day[stem] = day

    for p in files:
        if os.path.splitext(p)[1].lower() in SIDECAR_EXT:
            d = side_dst.get(os.path.splitext(p)[0])
            if d:
                plan.append({"src": p, "dst": os.path.join(d, os.path.basename(p)),
                             "action": "sidecar", "reason": ""})
            else:
                to_check(p, "сайдкар без основного файла")
    return plan


def summarize(plan, root):
    moves = [e for e in plan if e["action"] == "move"]
    dups = [e for e in plan if e["action"] == "dup"]
    checks = [e for e in plan if e["action"] == "check"]
    by_dir = {}
    for e in moves:
        k = os.path.relpath(os.path.dirname(e["dst"]), root)
        by_dir.setdefault(k, [0, 0])
        by_dir[k][0] += 1
        by_dir[k][1] += os.path.getsize(e["src"])
    log("")
    log("Will sort %d files%s" % (len(moves), ":" if moves else "."))
    for k in sorted(by_dir):
        n, s = by_dir[k]
        log("  %4d  %6.1f GB  %s" % (n, s / 1e9, k))
    if dups:
        log("")
        log("Already in the library (byte-identical): %d → _дубликаты/" % len(dups))
        for e in dups[:10]:
            log("        %s  (%s)" % (os.path.basename(e["src"]), e["reason"]))
        if len(dups) > 10:
            log("        … and %d more" % (len(dups) - 10))
    if checks:
        log("")
        log("Could not sort: %d → _inbox/%s/" % (len(checks), CHECK_DIR_NAME))
        reasons = {}
        for e in checks:
            reasons.setdefault(e["reason"], []).append(os.path.basename(e["src"]))
        for r, names in reasons.items():
            log("  %4d  %s: %s%s" % (len(names), r, ", ".join(names[:3]),
                                    " …" if len(names) > 3 else ""))
    return len(moves), len(dups), len(checks)


def execute(plan, root, inbox):
    os.makedirs(os.path.join(root, "_logs"), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = os.path.join(root, "_logs", "sort_%s.tsv" % stamp)
    n = 2
    while os.path.exists(log_path):      # two runs in the same second do not overwrite each other's journal
        log_path = os.path.join(root, "_logs", "sort_%s_%d.tsv" % (stamp, n))
        n += 1
    cat_rows = []
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write("action\tsrc\tdst\treason\n")
        for e in plan:
            src, dst = e["src"], e["dst"]
            if os.path.exists(dst):
                log("  ! skipping, already exists: %s" % dst)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)          # same drive → instant; macOS moves the ._ files itself
            lf.write("%s\t%s\t%s\t%s\n" % (e["action"], src, dst, e.get("reason", "")))
            lf.flush()
            if e["action"] == "move":
                cat_rows.append(catalog_row(dst, e["meta"], e["info"], e["day"], e["origin"]))
            elif e["action"] == "dup":
                cat_rows.append(catalog_row(e["keep"], e["meta"], e["info"], e["day"], e["origin"]))
    if any(e["action"] == "check" for e in plan):
        rp = os.path.join(root, "_inbox", CHECK_DIR_NAME, "ПРИЧИНЫ.txt")
        os.makedirs(os.path.dirname(rp), exist_ok=True)
        with open(rp, "a", encoding="utf-8") as f:
            f.write("# %s\n" % stamp)
            for e in plan:
                if e["action"] == "check":
                    f.write("%s\t%s\n" % (os.path.relpath(e["dst"], os.path.dirname(rp)), e["reason"]))
    n = update_catalog(root, cat_rows)
    remove_empty_dirs(inbox, keep={inbox, os.path.join(root, "_inbox", CHECK_DIR_NAME)})
    log("")
    log("Done. Catalog: %d files in _catalog.csv" % n)
    log("Journal: %s" % os.path.relpath(log_path, root))
    log("Undo: python3 \"%s\" --undo \"%s\"" % (os.path.abspath(__file__), log_path))


def remove_empty_dirs(top, keep):
    for r, ds, fs in os.walk(top, topdown=False):
        if r in keep:
            continue
        left = [f for f in os.listdir(r) if not (f.startswith("._") or f in IGNORE_NAMES)]
        if not left:
            shutil.rmtree(r, ignore_errors=True)


def undo(log_path):
    with open(log_path, encoding="utf-8") as f:
        rows = [l.rstrip("\n").split("\t") for l in f][1:]
    back = 0
    for row in reversed(rows):
        if len(row) < 3:
            continue
        _, src, dst = row[:3]
        if os.path.exists(dst) and not os.path.exists(src):
            os.makedirs(os.path.dirname(src), exist_ok=True)
            os.rename(dst, src)
            back += 1
    log("Moved back: %d files" % back)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Sort _inbox into days and cameras")
    ap.add_argument("--root", default=os.path.dirname(here), help="the Source Video folder")
    ap.add_argument("--inbox", help="what to sort (default <root>/_inbox)")
    ap.add_argument("--dry-run", action="store_true", help="only show the plan")
    ap.add_argument("--plan-out", help="write the plan to a TSV")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--undo", help="undo a run using its journal from _logs")
    ap.add_argument("--labels", help="file of «YYYY-MM-DD<TAB>label» lines naming new days")
    ap.add_argument("--no-compare", action="store_true",
                    help="with --dry-run: treat same name and size as a duplicate, without reading the bytes")
    a = ap.parse_args()

    if a.undo:
        undo(a.undo)
        return
    for tool in ("exiftool", "ffprobe"):
        if not shutil.which(tool):
            log("%s not found. Install: brew install exiftool ffmpeg" % tool)
            sys.exit(1)

    root = os.path.abspath(a.root)
    inbox = os.path.abspath(a.inbox or os.path.join(root, "_inbox"))
    os.makedirs(inbox, exist_ok=True)
    if os.stat(inbox).st_dev != os.stat(root).st_dev:
        log("The inbox must be on the same drive as %s" % root)
        sys.exit(1)
    origin_base = "" if inbox in (root, os.path.join(root, "_inbox")) else os.path.basename(inbox)

    if a.no_compare and not a.dry_run:
        log("--no-compare works only with --dry-run")
        sys.exit(1)
    plan = build_plan(root, inbox, origin_base, read_labels(a.labels), compare=not a.no_compare)
    if not plan:
        log("The inbox is empty, nothing to sort.")
        return
    moves, dups, checks = summarize(plan, root)
    if a.plan_out:
        with open(a.plan_out, "w", encoding="utf-8") as f:
            f.write("action\tsrc\tdst\treason\n")
            for e in plan:
                f.write("%s\t%s\t%s\t%s\n" % (e["action"], e["src"], e["dst"], e.get("reason", "")))
    if a.dry_run:
        return
    if not a.yes:
        if not sys.stdin.isatty():
            log("Confirmation needed: run with --yes")
            return
        ans = input("\nSort? [Enter = yes, n = no] ").strip().lower()
        if ans in ("n", "н", "no", "нет"):
            log("Nothing was changed.")
            return
    execute(plan, root, inbox)


if __name__ == "__main__":
    main()
