#!/usr/bin/env python3
"""Repairs broken clip paths in CapCut drafts after clips or drives were moved.

    python3 -I fix_capcut_paths.py                 — show what would be fixed (touches nothing)
    python3 -I fix_capcut_paths.py --apply         — fix (copies of the files before the edit go to a backup)
    python3 -I fix_capcut_paths.py --undo FOLDER   — restore the files from a backup

Draft folders: CapCut's default folder on the Mac (~/Movies/CapCut/User Data/Projects/com.lveditor.draft)
plus every folder listed in the VIDEO_LIBRARY_CAPCUT_DRAFTS environment variable (separated by «:»).
CapCut must be closed.
How a new path is found: every /Volumes/… path in a draft that does not exist is looked up by its file name
in Source Video/_catalog.csv of every connected drive and in their Video Archive / Video Production.
A path is changed only when exactly one file with that name is found. All other paths are left alone and printed.
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
PATH_RX = re.compile(r'"(/Volumes/[^"\\]+)"')
PRUNE = {"node_modules", "node_modules_exfat_old", ".git", "tmp", "public"}


def capcut_draft_dirs():
    """[(label, folder)]: CapCut's default draft folder on the Mac ("Mac") and every folder listed in
    VIDEO_LIBRARY_CAPCUT_DRAFTS (os.pathsep-separated); label = the volume name for /Volumes/<name>/…, else the path."""
    out = [("Mac", os.path.expanduser("~/Movies/CapCut/User Data/Projects/com.lveditor.draft"))]
    for p in os.environ.get("VIDEO_LIBRARY_CAPCUT_DRAFTS", "").split(os.pathsep):
        if not p:
            continue
        p = os.path.normpath(os.path.expanduser(p))
        if p in (t for _, t in out):
            continue
        parts = p.split(os.sep)
        out.append((parts[2].strip() if len(parts) > 3 and parts[1] == "Volumes" else p, p))
    return out


def backup_root():
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "_tools" and os.path.basename(os.path.dirname(here)) == "Source Video":
        return os.path.join(os.path.dirname(here), "_logs")
    return os.path.expanduser("~/.cache/video-library/logs")


def index():
    idx = {}
    for name in os.listdir("/Volumes"):
        root = os.path.join("/Volumes", name)
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
                if "/Volumes/" in s:
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
            if os.path.exists(old):
                return m.group(0)
            hits = idx.get(os.path.basename(old), set())
            if len(hits) == 1:
                st[0].add(old)
                return '"%s"' % next(iter(hits))
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
