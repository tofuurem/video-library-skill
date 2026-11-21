#!/usr/bin/env python3
"""Companion to rename_days.py: after day folders were renamed, rewrites the paths to them inside projects —
Video Archive/* and Video Production/* (texts and symlinks).

    python3 -I rename_days_projects.py LIST.tsv            — plan: which files and links would change
    python3 -I rename_days_projects.py LIST.tsv --apply    — do it (copies before the edit go to _logs)
    python3 -I rename_days_projects.py --undo JOURNAL.tsv  — restore the files from the copies and the links back

LIST.tsv is the same as for rename_days.py («old name<TAB>new name»). The drive is the one the list lies on when
it is in <drive>/_docs/ (for --undo: the drive whose Source Video/_logs/ holds the journal), otherwise --disk.
Only the path segment «…/<month>/<old day>/» and «_карта/<old day>/» changes, also in JSON with \\uXXXX escapes.
Logs (*.log) are not touched — they are history. node_modules and venv folders are skipped.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import unicodedata

TOPS = ("Video Archive", "Video Production")
SKIP_DIRS = {"node_modules", "venv", "dfvenv", "pkvenv", "gigvenv", "vlmvenv"}
TEXT_EXT = {".json", ".md", ".txt", ".tsx", ".ts", ".py", ".sh", ".csv", ".tsv", ".js", ".mjs", ".yaml", ".yml"}


def esc(s):
    return json.dumps(s)[1:-1]          # \uXXXX, as in JSON written with ensure_ascii


def read_list(p):
    pairs = []
    for line in open(p, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        a, b = line.split("\t")
        pairs.append((unicodedata.normalize("NFC", a), unicodedata.normalize("NFC", b)))
    return pairs


def rules(pairs):
    """[(regex, replacement)] — the old day only as a whole path segment after the month folder or _карта."""
    out = []
    for old, new in pairs:
        month = "%s %s" % (old[:7], {"01": "январь", "02": "февраль", "03": "март", "04": "апрель", "05": "май",
                                     "06": "июнь", "07": "июль", "08": "август", "09": "сентябрь", "10": "октябрь",
                                     "11": "ноябрь", "12": "декабрь"}[old[5:7]])
        for pre in (month, "_карта"):
            for p_txt, o_txt, n_txt in ((pre, old, new), (esc(pre), esc(old), esc(new))):
                rx = re.compile(re.escape(p_txt + "/" + o_txt) + r"(?=/|\"|$)", re.M)
                out.append((rx, (lambda r: lambda m: r)(p_txt + "/" + n_txt)))
    return out


def walk(disk):
    for top in TOPS:
        for r, ds, fs in os.walk(os.path.join(disk, top)):
            ds[:] = [d for d in ds if d not in SKIP_DIRS and not d.startswith("._")]
            for f in fs + [d for d in os.listdir(r) if os.path.islink(os.path.join(r, d)) and os.path.isdir(os.path.join(r, d))]:
                if not f.startswith("._"):
                    yield os.path.join(r, f)


def plan(pairs, disk):
    rs = rules(pairs)
    texts, links = [], []
    for p in walk(disk):
        if os.path.islink(p):
            t = os.readlink(p)
            tn = unicodedata.normalize("NFC", t)
            nt = tn
            for rx, rep in rs:
                nt = rx.sub(rep, nt)
            if nt != tn:
                links.append((p, t, nt))
            continue
        if os.path.splitext(p)[1].lower() not in TEXT_EXT or os.path.getsize(p) > 30e6:
            continue
        try:
            raw = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        # The file text is matched as is (the rules are NFC, the text is not normalised): fine while the month and
        # day names involved have no «й/ё» (same bytes in NFC and NFD). A path with «й/ё» written in NFD in a text
        # is not found — after --apply, search the projects for the old day names.
        n, cnt = raw, 0
        for rx, rep in rs:
            n, k = rx.subn(rep, n)
            cnt += k
        if cnt:
            texts.append((p, n, cnt))
    return texts, links


def library_drive(disk):
    if not os.path.isfile(os.path.join(disk, "Source Video", "_catalog.csv")):
        sys.exit("Not a library drive: %s (pass --disk)" % disk)
    return disk


def main():
    ap = argparse.ArgumentParser(description="Rewrite renamed day-folder paths inside Video Archive / Video Production "
                                             "projects (dry run by default).")
    ap.add_argument("list", nargs="?", help="the same TSV as for rename_days.py: old name<TAB>new name")
    ap.add_argument("--disk", help="drive root (default: derived from the location of the list or the journal)")
    ap.add_argument("--apply", action="store_true", help="do it")
    ap.add_argument("--undo", help="journal .tsv of an earlier --apply to undo")
    a = ap.parse_args()
    if a.undo:
        disk = library_drive(a.disk or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(a.undo)))))
        bdir = a.undo[:-4] + "_backup"
        for line in list(open(a.undo, encoding="utf-8"))[1:]:
            kind, path, old, new = line.rstrip("\n").split("\t")
            if kind == "text":
                shutil.copy2(os.path.join(bdir, os.path.relpath(path, disk)), path)
            elif kind == "link":
                os.remove(path)
                os.symlink(old, path)
        print("Undo done.")
        return
    if not a.list:
        ap.error("a rename list is required")
    disk = library_drive(a.disk or os.path.dirname(os.path.dirname(os.path.abspath(a.list))))
    pairs = read_list(a.list)
    texts, links = plan(pairs, disk)
    for p, _, c in texts:
        print("text   %4d  %s" % (c, os.path.relpath(p, disk)))
    for p, t, nt in links:
        print("link         %s\n             %s\n          →  %s" % (os.path.relpath(p, disk), t, nt))
    print("files %d, replacements %d, links %d" % (len(texts), sum(c for _, _, c in texts), len(links)))
    if not a.apply:
        print("Dry run: nothing changed.")
        return
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    jp = os.path.join(disk, "Source Video", "_logs", "rename_days_projects_%s.tsv" % stamp)
    bdir = jp[:-4] + "_backup"
    with open(jp, "w", encoding="utf-8") as j:
        j.write("kind\tpath\told\tnew\n")
        for p, n, c in texts:
            b = os.path.join(bdir, os.path.relpath(p, disk))
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(p, b)
            if p.endswith(".json"):
                json.loads(n)
            with open(p, "w", encoding="utf-8") as f:
                f.write(n)
            j.write("text\t%s\t%d\t\n" % (p, c))
        for p, t, nt in links:
            os.remove(p)
            os.symlink(nt, p)
            j.write("link\t%s\t%s\t%s\n" % (p, t, nt))
    print("Done. Journal: %s\nBackups: %s" % (jp, bdir))
    print("Undo: python3 -I \"%s\" --undo \"%s\"" % (os.path.abspath(__file__), jp))


if __name__ == "__main__":
    main()
