#!/usr/bin/env python3
"""Put the video-library skeleton and tools on a drive. Dry run by default.

    python3 -I install_to_drive.py "/Volumes/<disk>"            # show the plan, touch nothing
    python3 -I install_to_drive.py "/Volumes/<disk>" --apply    # do it
    (Linux: "/media/$USER/<disk>", "/run/media/$USER/<disk>", "/mnt/<disk>" or a folder in $VIDEO_LIBRARY_VOLUMES.)

Creates what is missing: Source Video/{_inbox, _tools/reference, _logs}, Video Production, Video Archive, _docs.
Tools: scripts/drive_tools/* -> Source Video/_tools/, assets/inbox/Разложить.command -> Source Video/_inbox/.
  missing on the drive              -> copied;
  same bytes                        -> left alone;
  different, drive copy is older    -> replaced; the old file goes to Source Video/_logs/tools_<stamp>_backup/;
  different, drive copy not older   -> skipped and reported: it was changed on the drive. Bring that version
                                       into the skill first (cp -p), run selfcheck.py, then install again.
Written only if missing (an existing file is never touched): Source Video/_inbox/КАК ПОЛЬЗОВАТЬСЯ.txt,
CLAUDE.md, _docs/КАК ВЕСТИ ПРОЕКТЫ.md and _docs/КАРТА ВИДЕО.md (templates from assets/templates, drive name filled in).
Not written here: _docs/ИНВЕНТАРИЗАЦИЯ.md and _docs/ИДЕИ РОЛИКОВ.md — Claude fills those templates by hand.
Never moves, renames or deletes anything. With --apply writes the journal Source Video/_logs/install_<stamp>.tsv.
--any-folder: allow a folder that is not a mounted volume (for a test in a scratch folder).
Разложить.command is the macOS double-click launcher; on Linux it is copied too (the drive may meet a Mac) and sorting is
run as python3 -I "Source Video/_tools/sort_inbox.py".
"""
import argparse
import datetime as dt
import filecmp
import os
import shutil
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(SKILL, "scripts", "drive_tools")
ASSETS = os.path.join(SKILL, "assets")
SKIP = {"__pycache__", ".DS_Store"}
DIRS = ["Source Video", "Source Video/_inbox", "Source Video/_tools", "Source Video/_tools/reference",
        "Source Video/_logs", "Video Production", "Video Archive", "_docs"]
# (template in assets, path on the drive) — written only when the drive has no such file
TEMPLATES = [(os.path.join(ASSETS, "inbox", "КАК ПОЛЬЗОВАТЬСЯ.txt"), "Source Video/_inbox/КАК ПОЛЬЗОВАТЬСЯ.txt"),
             (os.path.join(ASSETS, "templates", "CLAUDE.md"), "CLAUDE.md"),
             (os.path.join(ASSETS, "templates", "КАК ВЕСТИ ПРОЕКТЫ.md"), "_docs/КАК ВЕСТИ ПРОЕКТЫ.md"),
             (os.path.join(ASSETS, "templates", "КАРТА ВИДЕО.md"), "_docs/КАРТА ВИДЕО.md")]


def master_files():
    """[(file in the skill, path relative to the drive root)] — tools and the inbox launcher."""
    out = []
    for r, ds, fs in os.walk(TOOLS):
        ds[:] = sorted(d for d in ds if d not in SKIP and not d.startswith("."))
        for f in sorted(fs):
            if f.startswith(".") or f in SKIP or f.endswith(".pyc"):
                continue
            src = os.path.join(r, f)
            out.append((src, os.path.join("Source Video", "_tools", os.path.relpath(src, TOOLS))))
    out.append((os.path.join(ASSETS, "inbox", "Разложить.command"), "Source Video/_inbox/Разложить.command"))
    return out


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


def check_root(path, any_folder):
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        vols = ", ".join(repr(r) for _, r in drive_roots())
        sys.exit("No such folder: %r. Mounted volumes: %s (a name may end in a space — copy it exactly)." % (root, vols or "none"))
    if os.path.realpath(root) == "/":
        sys.exit("This is the system disk — not a place for the library.")
    if not any_folder and ((os.path.dirname(root) not in volumes() and root not in volumes()) or not os.path.ismount(root)):
        sys.exit("%r is not a mounted drive in %s. For a test in an empty folder: --any-folder."
                 % (root, " / ".join(volumes()) or "/Volumes, /media/$USER, /run/media/$USER, /mnt"))
    return root


def plan_for(root):
    plan = []                                   # (action, rel, src, note)
    for d in DIRS:
        if not os.path.isdir(os.path.join(root, d)):
            plan.append(("mkdir", d, None, ""))
    for src, rel in master_files():
        dst = os.path.join(root, rel)
        if not os.path.exists(dst):
            plan.append(("copy", rel, src, "new"))
        elif filecmp.cmp(src, dst, shallow=False):
            plan.append(("same", rel, src, ""))
        elif os.path.getmtime(dst) < os.path.getmtime(src):
            plan.append(("update", rel, src, "the drive has an older version from %s" %
                         dt.datetime.fromtimestamp(os.path.getmtime(dst)).strftime("%d.%m.%Y %H:%M")))
        else:
            plan.append(("conflict", rel, src, "changed on the drive %s, later than the skill's copy — left alone" %
                         dt.datetime.fromtimestamp(os.path.getmtime(dst)).strftime("%d.%m.%Y %H:%M")))
    for src, rel in TEMPLATES:
        dst = os.path.join(root, rel)
        plan.append(("keep" if os.path.exists(dst) else "write", rel, src, ""))
    return plan


def shown_root(root):
    """The drive root as written into files on the drive: /Volumes/<drive> on a Mac, else «<папка дисков>/<drive>» —
    never this computer's mount folder (/media/<user>/… carries the user name, and the drive moves between computers)."""
    return root if os.path.dirname(root) == "/Volumes" else "<папка дисков>/" + os.path.basename(root)


def fill(text, root):
    return (text.replace("{{DISK}}", os.path.basename(root).strip())
                .replace("{{ROOT}}", shown_root(root))
                .replace("{{DATE}}", dt.date.today().strftime("%d.%m.%Y")))


def show(plan, root):
    titles = {"mkdir": "Create folders", "copy": "Copy tools (missing on the drive)",
              "update": "Update (the old version is backed up to _logs)", "conflict": "Skip: newer on the drive",
              "write": "Write from a template (no such file yet)", "keep": "Already there — left alone",
              "same": "Already identical"}
    print("Drive: %r" % root)
    for act in ("mkdir", "copy", "update", "conflict", "write", "keep", "same"):
        items = [p for p in plan if p[0] == act]
        if not items:
            continue
        print("\n%s: %d" % (titles[act], len(items)))
        if act == "same":
            continue
        for _, rel, _, note in items:
            print("  %s%s" % (rel, ("  — " + note) if note else ""))
    if any(p[0] == "conflict" for p in plan):
        print("\nDifferences: diff \"<skill>/scripts/drive_tools/<file>\" \"%s/Source Video/_tools/<file>\"" % root)


def apply(plan, root):
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    logs = os.path.join(root, "Source Video", "_logs")
    backup = os.path.join(logs, "tools_%s_backup" % stamp)
    for act, rel, _, _ in plan:
        if act == "mkdir":
            os.makedirs(os.path.join(root, rel), exist_ok=True)
    journal = []
    for act, rel, src, note in plan:
        dst = os.path.join(root, rel)
        if act in ("copy", "update"):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if act == "update":
                b = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(dst, b)
                note = "old version: " + os.path.relpath(b, root)
            shutil.copy2(src, dst)             # keeps mtime, so the next run sees "same"
        elif act == "write":
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding="utf-8") as f:
                text = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(fill(text, root))
        elif act not in ("mkdir", "conflict"):
            continue
        journal.append((act, rel, note))                 # relative to the drive root: no local mount path on the drive
    log = os.path.join(logs, "install_%s.tsv" % stamp)
    with open(log, "w", encoding="utf-8") as f:
        f.write("action\tpath\tnote\n")
        for row in journal:
            f.write("%s\t%s\t%s\n" % row)
    print("\nDone. Journal: %s" % os.path.relpath(log, root))
    print("On exFAT, macOS adds ._* files next to new files — that is normal.")


def main():
    ap = argparse.ArgumentParser(description="Put the video-library structure and tools on a drive")
    ap.add_argument("volume", help="drive root, e.g. \"/Volumes/MyDrive\"")
    ap.add_argument("--apply", action="store_true", help="do it (without it: plan only)")
    ap.add_argument("--any-folder", action="store_true", help="allow a folder that is not a drive (for a test)")
    a = ap.parse_args()
    root = check_root(a.volume, a.any_folder)
    plan = plan_for(root)
    show(plan, root)
    if not a.apply:
        print("\nDry run: nothing touched. To do it: the same call with --apply.")
        return
    apply(plan, root)


if __name__ == "__main__":
    main()
