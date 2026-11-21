#!/usr/bin/env python3
"""Search the video map on all drives at once: speech, frame descriptions, text in frame, labels, moments.

    python3 -I vm_search.py "трамвай цена"         — all words (endings: «трамва*» finds «трамвая», «трамваем»)
    python3 -I vm_search.py "трамва* OR автобус*" --kind речь --day YYYY-MM-DD --limit 30
    python3 -I vm_search.py "водопад*" --disk MyDrive         — one drive only
    python3 -I vm_search.py "водопад*" --path                 — with the clip's full path

The map's text is Russian, so queries are Russian words; FTS5 syntax: words are AND-ed, OR between alternatives, * for endings.
Searches `Source Video/_карта/поиск.sqlite` of every connected drive (/Volumes/* on macOS; /media/$USER/*, /run/media/$USER/*,
/media/*, /mnt/* on Linux; or $VIDEO_LIBRARY_VOLUMES). Every index found is copied to this computer as
~/.cache/video-map/поиск/<drive>.sqlite: when a drive is not connected, its copy is searched
and the row is marked "offline" — the moment can be found, the clip opened only with the drive.
Prints: drive, day, clip, time, record kind, text snippet (with --path also the clip's path).
"""
import argparse
import glob
import os
import shutil
import sqlite3

HERE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_карта", "поиск.sqlite")
CACHE = os.path.expanduser("~/.cache/video-map/поиск")


def mmss(t):
    try:
        t = float(t)
    except (TypeError, ValueError):
        return "—"
    return "%d:%02d" % (t // 60, t % 60)


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


def disk_name(vol):
    return os.path.basename(vol.rstrip("/")).strip()          # "/Volumes/My Drive " → "My Drive" (a trailing space in the volume name is dropped)


def sources():
    """[(drive, path to поиск.sqlite, drive root or None when offline)]"""
    res, seen = [], set()
    vols = sorted({r.rstrip("/") + "/" for _, r in drive_roots()})
    here_vol = os.path.dirname(os.path.dirname(os.path.dirname(HERE_DB))) + "/"
    if os.path.exists(HERE_DB) and here_vol not in vols:     # the tool runs from a drive mounted elsewhere
        vols.append(here_vol)
    for vol in vols:
        db = os.path.join(vol, "Source Video", "_карта", "поиск.sqlite")
        if not os.path.isfile(db):
            continue
        name = disk_name(vol)
        seen.add(name)
        res.append((name, db, vol.rstrip("/")))
        try:                                                  # fresh copy for searching without the drive
            os.makedirs(CACHE, exist_ok=True)
            cp = os.path.join(CACHE, name + ".sqlite")
            if not os.path.exists(cp) or os.path.getmtime(cp) < os.path.getmtime(db) or os.path.getsize(cp) != os.path.getsize(db):
                shutil.copy2(db, cp + ".tmp")
                os.replace(cp + ".tmp", cp)
        except OSError:
            pass
    for cp in sorted(glob.glob(os.path.join(CACHE, "*.sqlite"))):
        name = os.path.splitext(os.path.basename(cp))[0]
        if name not in seen:
            res.append((name, cp, None))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--kind", help="record kind: речь / кадры / в кадре / описание / момент")
    ap.add_argument("--day")
    ap.add_argument("--disk", help="only this drive (its volume name)")
    ap.add_argument("--path", action="store_true", help="show the clip's path")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    sql = "SELECT day, file, s, e, kind, snippet(t, 5, '«', '»', '…', 14), path, rank FROM t WHERE t MATCH ?"
    args = [a.query]
    if a.kind:
        sql += " AND kind = ?"; args.append(a.kind)
    if a.day:
        sql += " AND day = ?"; args.append(a.day)
    sql += " ORDER BY rank LIMIT ?"; args.append(a.limit)
    hits, srcs = [], sources()
    if a.disk:
        srcs = [x for x in srcs if x[0].lower() == a.disk.strip().lower()]
        if not srcs:
            raise SystemExit("no search index for drive %r (neither connected nor a copy in %s)" % (a.disk, CACHE))
    for name, db, vol in srcs:
        try:
            con = sqlite3.connect("file:%s?immutable=1" % db, uri=True)   # read-only: works on exFAT too
            for row in con.execute(sql, args):
                hits.append((row[7], name, vol, row))
            con.close()
        except sqlite3.Error as e:
            print("! %s: %s" % (name, e))
    hits.sort(key=lambda h: h[0])                             # bm25: lower is better
    for _, name, vol, (day, f, s, e, kind, snip, path, _r) in hits[:a.limit]:
        mark = "" if vol else " (offline)"
        print("%-12s %s  %-30s %6s  %-8s %s%s" % (name, day, f, mmss(s), kind, snip, mark))
        if a.path and path:
            print("             %s" % os.path.join(vol or "%s/%s" % ((volumes() or ["/Volumes"])[0], name), "Source Video", path))
    if not hits:
        print("nothing found on: %s" % ", ".join(n + ("" if v else " (copy)") for n, _, v in srcs))


if __name__ == "__main__":
    main()
