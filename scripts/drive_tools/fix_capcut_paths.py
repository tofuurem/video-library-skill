#!/usr/bin/env python3
"""Repairs broken clip paths in CapCut drafts after clips or drives were moved.

    python3 -I fix_capcut_paths.py                 — show what would be fixed (touches nothing)
    python3 -I fix_capcut_paths.py --apply         — fix (copies of the files before the edit go to a backup)
    python3 -I fix_capcut_paths.py --undo FOLDER   — restore the files from a backup

Draft folders: CapCut's default folder on the Mac (~/Movies/CapCut/User Data/Projects/com.lveditor.draft)
plus every folder listed in the VIDEO_LIBRARY_CAPCUT_DRAFTS environment variable (separated by «:»).
CapCut must be closed.
How a new path is found: every drive path in a draft (/Volumes/…, /media/<user>/…, /run/media/<user>/…, /mnt/…, or under
$VIDEO_LIBRARY_VOLUMES) that does not exist is looked up by its file name in Source Video/_catalog.csv of every connected
drive and in their Video Archive / Video Production. A path is changed only when exactly one file with that name is found.
All other paths are left alone and printed. The new path keeps the draft's own mount root: a Mac draft repaired on Linux
gets /Volumes/<drive>/… again (CapCut opens it on the Mac), and a path that exists here under another mount root counts as fine.
Backups go to <drive>/Source Video/_logs when this tool runs from <drive>/Source Video/_tools/,
otherwise to ~/.cache/video-library/logs.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sys

TEXT_EXT = {".json", ".tmp", ".bak"}
PRUNE = {"node_modules", "node_modules_exfat_old", ".git", "tmp", "public"}


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


PATH_RX = re.compile(r'"((?:%s)/[^"\\]+)"' % "|".join([re.escape(r) for r in volumes()] + [MOUNT_RX]))


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


def backup_root():
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "_tools" and os.path.basename(os.path.dirname(here)) == "Source Video":
        return os.path.join(os.path.dirname(here), "_logs")
    return os.path.expanduser("~/.cache/video-library/logs")


def index():
    idx = {}
    for root in sorted({r for _, r in drive_roots()}):
        cat = os.path.join(root, "Source Video", "_catalog.csv")
        if not os.path.isfile(cat):
            continue
        with open(cat, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                idx.setdefault(r["file"], set()).add(os.path.join(root, "Source Video", r["path"]))
        for top in ("Video Archive", "Video Production"):
            for r, ds, fs in os.walk(os.path.join(root, top)):
                ds[:] = [d for d in ds if d not in PRUNE]
                for f in fs:
                    if not f.startswith("._") and os.path.splitext(f)[1].lower() in (
                            ".mp4", ".mov", ".jpg", ".jpeg", ".png", ".heic", ".dng", ".mp3", ".wav", ".m4a"):
                        idx.setdefault(f, set()).add(os.path.join(r, f))
    return idx


def files():
    for label, top in capcut_draft_dirs():
        if not os.path.isdir(top):
            continue
        for r, ds, fs in os.walk(top):
            for f in fs:
                p = os.path.join(r, f)
                if f.startswith("._") or os.path.splitext(f)[1].lower() not in TEXT_EXT or os.path.getsize(p) > 50e6:
                    continue
                try:
                    s = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                if PATH_RX.search(s):
                    yield label, top, p, s


def draft_of(top, p):
    return os.path.relpath(p, top).split(os.sep)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo")
    a = ap.parse_args()
    if a.undo:
        n = 0
        for r, ds, fs in os.walk(a.undo):
            for f in fs:
                if f.startswith("._"):
                    continue
                b = os.path.join(r, f)
                orig = "/" + os.path.relpath(b, a.undo)
                shutil.copy2(b, orig)
                n += 1
        print("Restored from backup: %d files" % n)
        return
    if a.apply and any("capcut" in x.lower() for x in os.popen("pgrep -il capcut").read().split()):
        sys.exit("CapCut is running: close it, or it will overwrite the drafts.")
    idx = index()
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = os.path.join(backup_root(), "capcut_paths_%s_backup" % stamp)
    stats = {}          # (draft folder label, draft) → [fixed, not found, ambiguous]
    unresolved = {}
    n_files = 0
    for label, top, p, s in files():
        key = (label, draft_of(top, p))
        st = stats.setdefault(key, [set(), set(), set()])

        def sub(m):
            old = m.group(1)
            if os.path.exists(local_path(old)):
                return m.group(0)
            hits = idx.get(os.path.basename(old), set())
            if len(hits) == 1:
                st[0].add(old)
                new, d, h = next(iter(hits)), drive_of(old), drive_of(next(iter(hits)))
                if d and h and d[0] != h[0]:                  # keep the draft's mount root (CapCut runs on the Mac)
                    new = d[0] + new[len(h[0]):]
                return '"%s"' % new
            (st[2] if hits else st[1]).add(old)
            unresolved.setdefault(key, set()).add(old)
            return m.group(0)

        ns = PATH_RX.sub(sub, s)
        if ns != s and a.apply:
            if p.endswith(".json"):
                json.loads(ns)                       # never write a broken JSON
            b = backup + p
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(p, b)
            with open(p, "w", encoding="utf-8") as f:
                f.write(ns)
            n_files += 1
    print("%-12s %-16s %10s %10s %13s" % ("folder", "draft", "fixed", "not found", "ambiguous"))
    for k in sorted(stats):
        f, m, amb = stats[k]
        if f or m or amb:
            print("%-12s %-16s %10d %10d %13d" % (k[0], k[1], len(f), len(m), len(amb)))
    if unresolved:
        print("\nNot fixed (the file is on no connected drive, or its name is not unique):")
        for k in sorted(unresolved):
            dirs = sorted({os.path.dirname(x) for x in unresolved[k]})
            print("  %s / %s: %d — %s" % (k[0], k[1], len(unresolved[k]), "; ".join(dirs)[:300]))
    if a.apply:
        print("\nFiles fixed: %d. Backup: %s" % (n_files, backup))
        print("Undo: python3 -I \"%s\" --undo \"%s\"" % (os.path.abspath(__file__), backup))
    else:
        print("\nDry run: nothing changed.")


if __name__ == "__main__":
    main()
