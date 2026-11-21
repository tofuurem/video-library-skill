#!/usr/bin/env python3
"""All-drive video catalog: one table over every connected drive.

    python3 -I catalog_all.py                — build it and write it into the root of every connected drive
    python3 -I catalog_all.py --out FOLDER   — write it only there

A drive is included when its root has «Source Video/_catalog.csv» (written by sort_inbox.py).
Writes two files:
  ВСЕ ДИСКИ — каталог.csv   one row per clip and photo from every drive;
  ВСЕ ДИСКИ.md              summary: drives, trips by month, projects, what can be freed.
When a drive is not connected, its rows come from the previous «ВСЕ ДИСКИ — каталог.csv» (marked «нет в сети»).

Where a clip is used comes from:
  * sources.txt in Video Archive / Video Production on every drive;
  * CapCut drafts (*/draft_info.json): CapCut's default folder on the Mac
    (~/Movies/CapCut/User Data/Projects/com.lveditor.draft) and every folder listed in the
    VIDEO_LIBRARY_CAPCUT_DRAFTS environment variable (separated by «:»);
  * projects in Video Production / Video Archive: assets/camera symlinks and DJI_… names in texts;
  * when a drive is not connected — its projects' marks on clips of connected drives, from the previous build.
Before writing, the previous build is copied to Source Video/_logs/catalog_<time>_backup/.
Deletes and moves nothing.
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

CSV_NAME = "ВСЕ ДИСКИ — каталог.csv"
MD_NAME = "ВСЕ ДИСКИ.md"
DJI_RX = re.compile(r"DJI_\d{14}_\d{4}_D\.(?:MP4|JPG|DNG)", re.I)
CLIP_EXT = {".mp4", ".mov", ".jpg", ".dng", ".insv"}
TEXT_EXT = {".json", ".md", ".txt", ".ts", ".tsx", ".py", ".csv", ".tsv"}
PRUNE = {"node_modules", ".git", "node_modules_exfat_old", "public", "tmp", "Cache", "CEF"}
REGEN = ["node_modules", "node_modules_exfat_old", "work/tmp", "reel/public/shots", "reel/public/footage",
         "out/prev", "out/demo"]
# target bitrate for an «archive» re-encode (HEVC 10-bit, profile and LOG kept), Mbit/s
TARGET = [(3000, 40), (2000, 30), (0, 15)]
SMALL_MBPS = 12          # «keepsake» copy: 1080p HEVC 10-bit


def volumes():
    """Folders the drives are mounted in: $VIDEO_LIBRARY_VOLUMES (os.pathsep list), else the existing ones of /Volumes
    (macOS), /media/$USER and /run/media/$USER (Linux desktops), /media (drives mounted without a user folder), /mnt.
    A drive is a folder right inside one of them, or the folder itself when it directly holds Source Video; its name may
    end in a space (copy it exactly). The same function is inlined in every tool that looks for drives."""
    env = os.environ.get("VIDEO_LIBRARY_VOLUMES")
    if env:
        roots = env.split(os.pathsep)
    else:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if not user:
            try:
                import pwd
                user = pwd.getpwuid(os.getuid()).pw_name
            except (ImportError, KeyError):
                pass
        roots = ["/Volumes"] + (["/media/" + user, "/run/media/" + user] if user else []) + ["/media", "/mnt"]
    out = []
    for r in roots:
        r = r.rstrip("/")
        if r and r not in out and os.path.isdir(r):
            out.append(r)
    return out


def drive_roots():
    """[(drive name without a trailing space, its root)] of what is connected: every folder right inside a mount root of
    volumes(), or the mount root itself when it directly holds Source Video (e.g. $VIDEO_LIBRARY_VOLUMES=/mnt/<Drive>).
    Folders that are not drives (a user folder in /media, the system disk) are listed too: callers look inside."""
    out = []
    for v in volumes():
        if os.path.isdir(os.path.join(v, "Source Video")):
            out.append((os.path.basename(v).strip(), v))
            continue
        try:
            names = sorted(os.listdir(v))
        except OSError:
            continue
        out += [(n.strip(), os.path.join(v, n)) for n in names if not n.startswith(".") and os.path.isdir(os.path.join(v, n))]
    return out


MOUNT_RX = r'/Volumes|/run/media/[^/"\\]+|/media/[^/"\\]+|/media|/mnt'   # where drives sit on macOS / Linux, any user
DRIVE_TOP = ("Source Video", "Video Production", "Video Archive", "_docs")   # folders right in a drive's root


def drive_of(path):
    """(mount root, drive folder name as on disk) of a path on a drive — under volumes() or any usual mount root
    (a path written on another computer, e.g. /Volumes/… in a Mac's CapCut draft) — else None. A folder that directly
    holds Source Video is the drive itself: /media/<Drive>/… mounted without a user folder, /mnt/<Drive>/…"""
    best = None
    for rx in [re.escape(r) for r in volumes()] + MOUNT_RX.split("|"):     # the longest mount root wins:
        m = re.match(r"(%s)/([^/]+)(?:/|$)" % rx, path)                     # /media/<user>/X over /media/<user>
        if m and (not best or len(m.group(1)) > len(best[0])):
            best = m.group(1), m.group(2)
    if not best:
        return None
    root, name = best
    if root.count("/") > 1 and (name in DRIVE_TOP or os.path.isdir(os.path.join(root, "Source Video"))):
        root, name = os.path.dirname(root), os.path.basename(root)
    return root, name


_CONNECTED = {}


def local_path(p):
    """The same file on this computer: a drive path written elsewhere (/Volumes/X/… on a Mac, /media/<user>/X/… on
    Linux) moved under the mount root where drive X is connected here (names compared without a trailing space)."""
    d = drive_of(p)
    if not d or os.path.exists(p):
        return p
    if not _CONNECTED:
        for name, root in drive_roots():
            _CONNECTED.setdefault(name, root)
    here = _CONNECTED.get(d[1].strip())
    return here + p[len(os.path.join(*d)):] if here else p


PATH_RX = re.compile(r'"path":"((?:%s)/[^"]+)"' % "|".join([re.escape(r) for r in volumes()] + [MOUNT_RX]))


def capcut_draft_dirs():
    """[(label, folder)]: CapCut's default draft folder on the Mac ("Mac") and every folder listed in
    VIDEO_LIBRARY_CAPCUT_DRAFTS (os.pathsep-separated); label = the drive name for a folder on a drive, else the path."""
    out = [("Mac", os.path.expanduser("~/Movies/CapCut/User Data/Projects/com.lveditor.draft"))]
    for p in os.environ.get("VIDEO_LIBRARY_CAPCUT_DRAFTS", "").split(os.pathsep):
        if not p:
            continue
        p = os.path.normpath(os.path.expanduser(p))
        if p in (t for _, t in out):
            continue
        d = drive_of(p)
        out.append((d[1].strip() if d else p, p))
    return out


def small_gb(r):
    return min(r["гб"], SMALL_MBPS * r["мин"] * 60 / 8000)


def hevc_gb(r):
    return min(r["гб"], (target_mbps(r["разрешение"]) or 40) * r["мин"] * 60 / 8000)


def drives():
    out, seen = [], set()
    for name, root in drive_roots():
        if name not in seen and os.path.isfile(os.path.join(root, "Source Video", "_catalog.csv")):
            seen.add(name)
            out.append((name, root))
    return out


def du(path):
    r = subprocess.run(["du", "-sk", path], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0]) * 1024
    except (IndexError, ValueError):
        return 0


def free_bytes(root):
    st = os.statvfs(root)
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def place_of(path):
    parts = path.split("/")
    for p in parts:
        m = re.match(r"\d{4}-\d{2}-\d{2} (.+)", p)
        if m:
            return m.group(1)
        if p.startswith("_без даты"):
            return p
    return ""


def read_catalog(drive, root):
    rows = []
    with open(os.path.join(root, "Source Video", "_catalog.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rel = "Source Video/" + r["path"]
            rows.append({"диск": drive, "день": r["day"], "место": place_of(r["path"]), "папка": r["folder"],
                         "тип": r["kind"], "файл": r["file"], "мин": num(r["duration_s"]) / 60,
                         "разрешение": r["resolution"], "ориентация": r["orientation"], "fps": r["fps"],
                         "гб": num(r["size_mb"]) / 1000, "путь": rel, "абс": os.path.join(root, rel),
                         "проекты": set(), "в сети": True})
    return rows


def to_abs(p):
    """A draft path written on another computer (/Volumes/… in a Mac draft read on Linux) points to where that drive is
    mounted here; a path to an old drive name is returned as is."""
    return os.path.normpath(local_path(p))


def project_name(root, path):
    rel = os.path.relpath(path, root).split(os.sep)
    if rel[0] in ("Video Archive", "Video Production") and len(rel) > 1:
        return rel[1]
    return "/".join(rel[:2])


class NFCDict(dict):
    """Paths with «й/ё» come in NFD (as Finder/macOS writes folder names) and in NFC (sources.txt, scripts) — compare in NFC.
    Without it a folder name that is NFD on the drive never matches the NFC path in a project's sources.txt."""

    def __init__(self, items=()):
        super().__init__((unicodedata.normalize("NFC", k), v) for k, v in items)

    def get(self, k, d=None):
        return super().get(unicodedata.normalize("NFC", k), d) if isinstance(k, str) else d

    def __getitem__(self, k):
        return super().__getitem__(unicodedata.normalize("NFC", k))

    def __contains__(self, k):
        return isinstance(k, str) and super().__contains__(unicodedata.normalize("NFC", k))


def collect_usage(drv, by_abs, by_name):
    """→ ({project: clips}, {project folder: {clip names found on no drive}}); fills row['проекты']."""
    projects = {}
    missing = {}

    def use(row, proj):
        row["проекты"].add(proj)
        projects.setdefault(proj, set()).add(row["абс"])

    def lost(projdir, name):
        missing.setdefault(projdir, set()).add(name)

    for drive, root in drv:
        # sources.txt is the exact list: for such projects clip names mentioned in notes do not count as usage
        with_sources = set()
        for st in glob.glob(os.path.join(root, "Video Archive", "*", "sources.txt")) + glob.glob(os.path.join(root, "Video Production", "*", "sources.txt")):
            with_sources.add(os.path.basename(os.path.dirname(st)))
            proj = os.path.basename(os.path.dirname(st))
            for line in open(st, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                row = by_abs.get(os.path.join(root, line))
                if row:
                    use(row, proj)
                elif (os.path.splitext(line)[1].lower() in CLIP_EXT
                      and os.path.basename(line).upper() not in by_name):
                    lost(os.path.dirname(st), os.path.basename(line))
        # projects: symlinks and clip names in texts
        for top in ("Video Archive", "Video Production"):
            for r, ds, fs in os.walk(os.path.join(root, top)):
                ds[:] = [d for d in ds if d not in PRUNE]
                for name in fs + ds:
                    p = os.path.join(r, name)
                    proj = project_name(root, p)
                    if proj in with_sources:
                        continue
                    if os.path.islink(p):
                        row = by_abs.get(os.path.realpath(p)) or by_abs.get(os.readlink(p))
                        if row:
                            use(row, proj)
                        else:
                            tname = os.path.basename(os.readlink(p))
                            if os.path.splitext(tname)[1].lower() in CLIP_EXT and tname.upper() not in by_name:
                                lost(os.path.join(root, top, proj), tname)
                        continue
                    if name.startswith("._") or os.path.splitext(name)[1].lower() not in TEXT_EXT:
                        continue
                    if name == "sources.txt" or not os.path.isfile(p) or os.path.getsize(p) > 20e6:
                        continue
                    try:
                        s = open(p, encoding="utf-8").read()
                    except (UnicodeDecodeError, OSError):
                        continue
                    for m in set(DJI_RX.findall(s)):
                        if m.upper() not in by_name:
                            lost(os.path.join(root, top, proj), m)
                        for row in by_name.get(m.upper(), []):
                            use(row, proj)
    # CapCut drafts: the Mac's default folder and the folders from VIDEO_LIBRARY_CAPCUT_DRAFTS
    for _, draft_dir in capcut_draft_dirs():
        scan_capcut(draft_dir, by_abs, by_name, use)
    return projects, missing


def scan_capcut(draft_root, by_abs, by_name, use):
    for d in glob.glob(os.path.join(draft_root, "*")):
        files = [os.path.join(d, "draft_info.json")] + glob.glob(os.path.join(d, "Timelines", "*", "draft_info.json"))
        proj = "CapCut: " + os.path.basename(d)
        for fp in files:
            if not os.path.isfile(fp):
                continue
            try:
                s = open(fp, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for p in set(PATH_RX.findall(s)):
                row = by_abs.get(to_abs(p))
                if not row:
                    cands = by_name.get(os.path.basename(p).upper(), [])
                    row = cands[0] if len(cands) == 1 else None
                if row:
                    use(row, proj)


def regen_size(proj_dir):
    total = 0
    for r, ds, fs in os.walk(proj_dir):
        for d in list(ds):
            rel = os.path.relpath(os.path.join(r, d), proj_dir)
            if d in ("node_modules", "node_modules_exfat_old") or any(rel.endswith(x) for x in REGEN[2:]):
                total += du(os.path.join(r, d))
                ds.remove(d)
    return total


def gb(b):
    return b / 1e9


def target_mbps(res):
    m = re.match(r"(\d+)x(\d+)", res or "")
    if not m:
        return None
    long_side = max(int(m.group(1)), int(m.group(2)))
    for lim, t in TARGET:
        if long_side >= lim:
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="folder for the result (default: the root of every connected drive)")
    a = ap.parse_args()
    drv = drives()
    if not drv:
        sys.exit("No connected drives with Source Video/_catalog.csv")
    print("Drives:", ", ".join(d for d, _ in drv))
    rows = []
    for d, root in drv:
        rows += read_catalog(d, root)
    online = {d for d, _ in drv}
    # rows of offline drives come from the newest previous all-drive catalog
    old_use = {}      # (drive, path) → projects from the previous build, for clips of connected drives
    olds = [os.path.join(root, CSV_NAME) for _, root in drv if os.path.exists(os.path.join(root, CSV_NAME))]
    if olds:
        with open(max(olds, key=os.path.getmtime), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                used = set(x for x in r["использован в"].split(" | ") if x)
                if r["диск"] in online:
                    old_use[(r["диск"], r["путь"])] = used
                    continue
                rows.append({"диск": r["диск"], "день": r["день"], "место": r["место"], "папка": r["папка"],
                             "тип": r["тип"], "файл": r["файл"], "мин": num(r["длительность, мин"]),
                             "разрешение": r["разрешение"], "ориентация": r.get("ориентация", ""),
                             "fps": r["fps"], "гб": num(r["размер, ГБ"]), "путь": r["путь"], "абс": "",
                             "проекты": used, "в сети": False})
    offline = {r["диск"] for r in rows if not r["в сети"]}
    by_abs = NFCDict((r["абс"], r) for r in rows if r["абс"])
    by_name = {}
    for r in rows:
        by_name.setdefault(r["файл"].upper(), []).append(r)
    projects, missing = collect_usage(drv, by_abs, by_name)
    # projects on an offline drive (CapCut drafts kept on it, say) cannot be read now: carry their marks on clips
    # of connected drives over from the previous build, or such a clip would look unused
    if offline:
        found = set(projects)
        for r in rows:
            if r["в сети"]:
                for p in old_use.get((r["диск"], r["путь"]), ()):
                    if p not in found:
                        r["проекты"].add(p)
                        projects.setdefault(p, set()).add(r["абс"])

    # copies of one clip on different drives
    by_key = {}
    for r in rows:
        by_key.setdefault((r["файл"], round(r["гб"], 3)), []).append(r)
    for r in rows:
        others = [x["диск"] for x in by_key[(r["файл"], round(r["гб"], 3))] if x is not r]
        r["копии"] = ", ".join(sorted(set(others)))

    # ------------------------------------------------------------ CSV
    rows.sort(key=lambda r: (r["день"] or "9999", r["диск"], r["путь"]))
    fields = ["диск", "день", "место", "папка", "тип", "файл", "длительность, мин", "разрешение", "ориентация", "fps",
              "размер, ГБ", "битрейт, Мбит/с", "использован в", "копия на дисках", "путь"]
    csv_rows = []
    for r in rows:
        mbps = (r["гб"] * 8000 / (r["мин"] * 60)) if r["мин"] else 0
        csv_rows.append({"диск": r["диск"], "день": r["день"], "место": r["место"], "папка": r["папка"],
                         "тип": r["тип"], "файл": r["файл"], "длительность, мин": "%.1f" % r["мин"] if r["мин"] else "",
                         "разрешение": r["разрешение"], "ориентация": r["ориентация"], "fps": r["fps"],
                         "размер, ГБ": "%.3f" % r["гб"], "битрейт, Мбит/с": "%.0f" % mbps if mbps else "",
                         "использован в": " | ".join(sorted(r["проекты"])), "копия на дисках": r["копии"],
                         "путь": r["путь"]})

    # ------------------------------------------------------------ summary
    L = []
    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    vids = [r for r in rows if r["тип"] == "video"]
    L += ["# Все диски: видео", "",
          "Собрано %s скриптом `Source Video/_tools/catalog_all.py` (лежит на каждом диске). "
          "Запускай заново, когда что-то добавил: `python3 -I \"%s/<диск>/Source Video/_tools/catalog_all.py\"`."
          % (now, "/Volumes" if "/Volumes" in volumes() else "<папка дисков>"),   # never this computer's /media/<user>
          "Полный список — `%s`: по строке на клип, с местом, длительностью, битрейтом и проектами, где он использован." % CSV_NAME,
          "Этот файл и каталог лежат в корне каждого подключённого диска; диски, которых не было в сети, взяты из прошлой сборки.", ""]

    MAIN_AT = len(L)
    L += ["## Диски", "", "| Диск | Объём | Свободно | Source Video | Video Archive | Video Production | Остальное (не исходники) |",
          "|---|---|---|---|---|---|---|"]
    extra_notes = []
    for d, root in drv:
        free, total = free_bytes(root)
        sizes = {}
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if name.startswith(".") or name in ("System Volume Information",) or not os.path.isdir(p):
                continue
            sizes[name] = du(p)
        other = ", ".join("%s %.0f ГБ" % (k, gb(v)) for k, v in sorted(sizes.items(), key=lambda x: -x[1])
                          if k not in ("Source Video", "Video Archive", "Video Production") and v > 1e9)
        L.append("| %s | %.2f ТБ | %.0f ГБ | %.0f ГБ | %.0f ГБ | %.0f ГБ | %s |" % (
            d, total / 1e12, gb(free), gb(sizes.get("Source Video", 0)), gb(sizes.get("Video Archive", 0)),
            gb(sizes.get("Video Production", 0)), other or "—"))
    for d in sorted({r["диск"] for r in rows} - online):
        L.append("| %s | нет в сети | — | %.0f ГБ клипов (по прошлому каталогу) | — | — | — |" % (
            d, sum(r["гб"] for r in rows if r["диск"] == d)))
    L.append("")

    # trips
    L += ["## Что где снято", "", "Подряд идущие дни с одним местом склеены. Часы — суммарная длительность видео.", "",
          "| Даты | Место | Диск | Дней | Клипов | Часов | ГБ | Использовано в проектах |", "|---|---|---|---|---|---|---|---|"]
    groups = []
    for r in sorted((r for r in rows if r["день"]), key=lambda r: (r["день"], r["диск"])):
        base = r["место"].split(" — ")[0] if r["место"] else "—"
        if groups and groups[-1]["base"] == base and groups[-1]["диск"] == r["диск"]:
            g = groups[-1]
        else:
            g = {"base": base, "диск": r["диск"], "days": set(), "n": 0, "min": 0, "gb": 0, "used": 0, "from": r["день"]}
            groups.append(g)
        g["days"].add(r["день"])
        g["to"] = r["день"]
        g["n"] += 1
        g["min"] += r["мин"]
        g["gb"] += r["гб"]
        g["used"] += 1 if r["проекты"] else 0
    for g in groups:
        f, t = g["from"], g["to"]
        dates = "%s.%s.%s" % (f[8:], f[5:7], f[:4]) if f == t else "%s.%s–%s.%s.%s" % (f[8:], f[5:7], t[8:], t[5:7], t[:4])
        L.append("| %s | %s | %s | %d | %d | %.1f | %.0f | %d из %d |" % (
            dates, g["base"], g["диск"], len(g["days"]), g["n"], g["min"] / 60, g["gb"], g["used"], g["n"]))
    undated = [r for r in rows if not r["день"]]
    if undated:
        L.append("| без даты | %s | %s | — | %d | %.1f | %.0f | |" % (
            ", ".join(sorted({r["место"] for r in undated})), ", ".join(sorted({r["диск"] for r in undated})),
            len(undated), sum(r["мин"] for r in undated) / 60, sum(r["гб"] for r in undated)))
    tot_h = sum(r["мин"] for r in vids) / 60
    L += ["", "Всего: %d клипов и фото, видео %.0f часов, %.2f ТБ." % (len(rows), tot_h, sum(r["гб"] for r in rows) / 1000), ""]

    # projects
    L += ["## Проекты и сколько клипов в них вошло", "",
          "| Проект | Клипов | Где лежат клипы |", "|---|---|---|"]
    for proj, clips in sorted(projects.items()):
        where = sorted({by_abs[c]["диск"] for c in clips if c in by_abs})
        L.append("| %s | %d | %s |" % (proj, len(clips), ", ".join(where)))
    L.append("")

    # what can be freed
    L += ["## Что можно освободить", "", "Ничего не удалено. Каждый пункт — только по твоему «да».", "",
          "### 1. Без потери отснятого (пересоздаётся само)", "", "| Что | Где | ГБ |", "|---|---|---|"]
    regen_total = 0
    keep = []
    for _, draft_dir in capcut_draft_dirs():
        # the cache sits next to Projects: <User Data>/Cache; shown under the drive it is on, or «Mac»
        cache = os.path.join(os.path.dirname(os.path.dirname(draft_dir)), "Cache")
        if os.path.isdir(cache):
            s = du(cache)
            regen_total += s
            d = drive_of(cache)
            where = ("%s: `%s`" % (d[1].strip(), os.path.relpath(cache, os.path.join(*d))) if d
                     else "Mac: `%s`" % cache.replace(os.path.expanduser("~"), "~", 1))
            L.append("| Кэш CapCut (чистится в CapCut: Настройки → Кэш → Очистить) | %s | %.0f |" % (where, gb(s)))
    for d, root in drv:
        for top in ("Video Archive", "Video Production"):
            for proj in sorted(glob.glob(os.path.join(root, top, "*"))):
                if os.path.basename(proj).startswith("._") or not os.path.isdir(proj):
                    continue
                s = regen_size(proj)
                lost_names = missing.get(proj)
                if s > 0.5e9 and lost_names:
                    keep.append((d, top, os.path.basename(proj), s, sorted(lost_names)))
                elif s > 0.5e9:
                    regen_total += s
                    note = " (в работе: перед сборкой снова `npm install`)" if top == "Video Production" else ""
                    L.append("| node_modules и временное (work/tmp, out/prev, reel/public)%s | %s: `%s/%s` | %.0f |" % (
                        note, d, top, os.path.basename(proj), gb(s)))
    L += ["| **Итого** | | **%.0f** |" % gb(regen_total), ""]
    if keep:
        L += ["Не трогать: исходники удалены, временное проекта — единственная копия.", "",
              "| Проект | Нет исходников | Временное, ГБ | Какие клипы |", "|---|---|---|---|"]
        for d, top, name, s, names in keep:
            L.append("| %s: `%s/%s` | %d | %.0f | %s%s |" % (
                d, top, name, len(names), gb(s), ", ".join(names[:3]), ", …" if len(names) > 3 else ""))
        L.append("")

    # copies on different drives
    cross = {}
    for k, lst in by_key.items():
        ds = sorted({x["диск"] for x in lst})
        if len(ds) > 1:
            cross[k] = ds
    L += ["### 2. Одинаковые клипы на разных дисках", ""]
    if cross:
        s = sum(k[1] for k in cross)
        L += ["%d клипов (%.0f ГБ) лежат больше чем на одном диске. Это резервные копии: удалять, только если решишь, что резерв не нужен." % (len(cross), s), ""]
    else:
        L += ["Нет: каждый клип лежит только на одном диске. Резервных копий исходников тоже нет — если диск умрёт, его клипы пропадут.", ""]

    # long unused clips
    unused = [r for r in vids if not r["проекты"]]
    long_unused = sorted((r for r in unused if r["мин"] >= 10), key=lambda r: -r["гб"])
    L += ["### 3. Длинные клипы, которые не вошли ни в один проект", "",
          "Клип от 10 минут — обычно дорога или «камера просто писала». Ни в одном проекте не использован.", "",
          "Варианты: **А** — пережать в тот же 4K, HEVC 10 бит ~40 Мбит/с: LOG/HLG сохраняется, на глаз почти без потерь, "
          "освобождает ~40%%. **Б** — уменьшить до 1080p ~%d Мбит/с «на память»: освобождает ~80%%, для монтажа в 4K уже не годится. "
          "**В** — удалить." % SMALL_MBPS, "",
          "| Диск | Клипов | Часов | ГБ сейчас | А: освободится | Б: освободится |", "|---|---|---|---|---|---|"]
    tot = [0, 0, 0, 0, 0]
    for d in sorted({r["диск"] for r in long_unused}):
        lst = [r for r in long_unused if r["диск"] == d]
        size = sum(r["гб"] for r in lst)
        a_ = size - sum(hevc_gb(r) for r in lst)
        b_ = size - sum(small_gb(r) for r in lst)
        h = sum(r["мин"] for r in lst) / 60
        L.append("| %s | %d | %.1f | %.0f | %.0f ГБ | %.0f ГБ |" % (d, len(lst), h, size, a_, b_))
        tot = [tot[0] + len(lst), tot[1] + h, tot[2] + size, tot[3] + a_, tot[4] + b_]
    L += ["| **Итого** | **%d** | **%.1f** | **%.0f** | **%.0f ГБ** | **%.0f ГБ** |" % tuple(tot), "",
          "Самые тяжёлые (полный список — в CSV, фильтр «использован в» пусто и «длительность» ≥ 10):", "",
          "| Диск | День | Место | Файл | Мин | ГБ | Мбит/с |", "|---|---|---|---|---|---|---|"]
    for r in long_unused[:25]:
        L.append("| %s | %s | %s | %s | %.0f | %.1f | %.0f |" % (r["диск"], r["день"], r["место"], r["файл"], r["мин"], r["гб"],
                                                          r["гб"] * 8000 / (r["мин"] * 60) if r["мин"] else 0))
    L.append("")

    all_unused = sum(r["гб"] for r in unused)
    all_a = all_unused - sum(hevc_gb(r) for r in unused if r["мин"])
    all_b = all_unused - sum(small_gb(r) for r in unused if r["мин"])
    L += ["### 4. Все неиспользованные видео", "",
          "Всего не вошли ни в один проект: %d клипов, %.0f часов, %.0f ГБ. Вариант А для всех освободит ~%.0f ГБ, вариант Б — ~%.0f ГБ." % (
              len(unused), sum(r["мин"] for r in unused) / 60, all_unused, all_a, all_b),
          "Использованные в проектах клипы не трогаются: их оригиналы нужны, если ролик придётся пересобрать.", ""]

    free_all = sum(free_bytes(root)[0] for _, root in drv)
    main_ = ["## Главное", "",
             "- %d клипов и фото, %.0f часов видео, %.2f ТБ исходников на %d дисках; свободно на подключённых %.0f ГБ." % (
                 len(rows), tot_h, sum(r["гб"] for r in rows) / 1000, len({r["диск"] for r in rows}), gb(free_all)),
             "- **Резервных копий исходников нет**: каждый клип лежит ровно на одном диске." if not cross else
             "- %d клипов лежат больше чем на одном диске (резерв)." % len(cross),
             "- Без потери отснятого можно освободить ~%.0f ГБ (кэш CapCut, node_modules, временное) — раздел 1." % gb(regen_total),
             "- %d длинных клипов (от 10 минут, %.0f часов, %.0f ГБ) не вошли ни в один проект — раздел 3." % (tot[0], tot[1], tot[2]),
             ""]
    L[MAIN_AT:MAIN_AT] = main_
    md = "\n".join(L) + "\n"
    outs = [a.out] if a.out else [root for _, root in drv]
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    for o in outs:
        os.makedirs(o, exist_ok=True)                 # --out may name a new folder
        logs = os.path.join(o, "Source Video", "_logs")
        if os.path.isdir(logs):          # back up the previous build: rows of offline drives are taken from it
            bk = os.path.join(logs, "catalog_%s_backup" % stamp)
            for name in (CSV_NAME, MD_NAME):
                if os.path.isfile(os.path.join(o, name)):
                    os.makedirs(bk, exist_ok=True)
                    shutil.copy2(os.path.join(o, name), os.path.join(bk, name))
        with open(os.path.join(o, CSV_NAME), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(csv_rows)
        with open(os.path.join(o, MD_NAME), "w", encoding="utf-8") as f:
            f.write(md)
        print("Written:", os.path.join(o, MD_NAME))
    print("Clips: %d, projects: %d, unused videos: %d (%.0f GB)" % (len(rows), len(projects), len(unused), all_unused))


if __name__ == "__main__":
    main()
