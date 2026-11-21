#!/usr/bin/env python3
"""Renames day folders on one drive together with everything that refers to them.

    python3 -I rename_days.py LIST.tsv                 — plan and checks only (touches nothing)
    python3 -I rename_days.py LIST.tsv --apply         — do it
    python3 -I rename_days.py --undo JOURNAL.tsv       — undo by the journal

LIST.tsv: «old day folder name<TAB>new name», lines starting with # are skipped. The drive is the one the
list lies on when it is in <drive>/_docs/, otherwise --disk. What changes for each day (renames and path
edits only, clip files are not touched):
  1. Source Video/<year>/<month>/<day>        → new name (rename within the drive);
  2. Source Video/_карта/<day>                → new name;
  3. _карта/<day>/клипы.json: folder and path of the clips;
  4. Source Video/_catalog.csv: path;
  5. CapCut drafts: absolute paths <drive>/Source Video/<day>/… (--no-capcut: leave them alone). Draft folders:
     CapCut's default folder on the Mac (~/Movies/CapCut/User Data/Projects/com.lveditor.draft) and every folder
     listed in the VIDEO_LIBRARY_CAPCUT_DRAFTS environment variable (separated by «:»).
Copies of every edited file before the edit — Source Video/_logs/rename_days_<time>_backup/<absolute path>.
Journal (action, src, dst, note) — Source Video/_logs/rename_days_<time>.tsv. Afterwards: video_map.py --index and
catalog_all.py (this script runs them after --apply). CapCut must be closed. When a draft folder from
VIDEO_LIBRARY_CAPCUT_DRAFTS is not reachable (its drive is not connected), --apply refuses unless
--skip-offline-drafts is given; fix_capcut_paths.py repairs those drafts later by file name.
Projects (Video Archive / Video Production) are not touched here: run rename_days_projects.py with the same list next.
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

TEXT_EXT = {".json", ".tmp", ".bak"}
DAY_RX = re.compile(r"^\d{4}-\d{2}-\d{2} \S.*$")


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


def read_list(path):
    pairs = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                sys.exit("%s:%d: expected «old<TAB>new»" % (path, n))
            old, new = (p.strip() for p in parts)
            if not DAY_RX.match(new) or new[:10] != old[:10] or "/" in new:
                sys.exit("%s:%d: the new name must start with the same date: %r → %r" % (path, n, old, new))
            if old != new:
                pairs.append((old, new))
    return pairs


def day_dirs(sv):
    """day folder name → relative path «year/month/day»."""
    out = {}
    for y in sorted(os.listdir(sv)):
        if re.fullmatch(r"\d{4}", y):
            for m in sorted(os.listdir(os.path.join(sv, y))):
                mp = os.path.join(sv, y, m)
                if os.path.isdir(mp):
                    for d in os.listdir(mp):
                        if os.path.isdir(os.path.join(mp, d)):
                            out[d] = "%s/%s/%s" % (y, m, d)
    return out


def draft_files():
    for label, top in capcut_draft_dirs():
        if not os.path.isdir(top):
            continue
        for r, ds, fs in os.walk(top):
            for f in fs:
                p = os.path.join(r, f)
                if f.startswith("._") or os.path.splitext(f)[1].lower() not in TEXT_EXT or os.path.getsize(p) > 50e6:
                    continue
                yield label, top, p


def draft_name(top, p):
    return os.path.relpath(p, top).split(os.sep)[0]


def capcut_running():
    out = subprocess.run(["pgrep", "-il", "capcut"], capture_output=True, text=True).stdout
    return bool(out.strip())


class Run:
    def __init__(self, disk, apply):
        self.disk, self.sv, self.apply = disk, os.path.join(disk, "Source Video"), apply
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.backup = os.path.join(self.sv, "_logs", "rename_days_%s_backup" % stamp)
        self.journal = os.path.join(self.sv, "_logs", "rename_days_%s.tsv" % stamp)
        self.rows = []

    def log(self, action, src, dst="", note=""):
        self.rows.append((action, src, dst, note))
        if self.apply:
            new = not os.path.exists(self.journal)
            with open(self.journal, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f, delimiter="\t", lineterminator="\n")
                if new:
                    w.writerow(["action", "src", "dst", "note"])
                w.writerow([action, src, dst, note])

    def save_backup(self, p):
        b = self.backup + p
        if not os.path.exists(b):
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(p, b)
        return b

    def write_text(self, p, text, note):
        if p.endswith(".json"):
            json.loads(text)                                  # never write a broken JSON
        if self.apply:
            b = self.save_backup(p)
            tmp = p + ".rename_tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            shutil.copymode(p, tmp)
            os.replace(tmp, p)
            self.log("rewrite", p, b, note)
        else:
            self.rows.append(("rewrite", p, "", note))

    def rename(self, src, dst):
        if self.apply:
            os.rename(src, dst)
            self.log("rename", src, dst)
        else:
            self.rows.append(("rename", src, dst, ""))


def main():
    ap = argparse.ArgumentParser(description="Rename day folders together with _карта, клипы.json, _catalog.csv "
                                             "and CapCut drafts (dry run by default).")
    ap.add_argument("list", nargs="?", help="TSV: old day folder name<TAB>new name")
    ap.add_argument("--disk", help="drive root (default: the drive whose _docs/ holds the list)")
    ap.add_argument("--apply", action="store_true", help="do it (CapCut must be closed)")
    ap.add_argument("--undo", help="journal .tsv of an earlier --apply to undo")
    ap.add_argument("--skip-offline-drafts", action="store_true",
                    help="run although a draft folder from VIDEO_LIBRARY_CAPCUT_DRAFTS is not reachable; "
                         "fix_capcut_paths.py repairs those drafts later")
    ap.add_argument("--no-capcut", action="store_true",
                    help="leave CapCut drafts alone (their paths to these days will point nowhere)")
    a = ap.parse_args()
    if a.undo:
        return undo(a.undo)
    if not a.list:
        ap.error("a rename list is required")
    disk = a.disk or os.path.dirname(os.path.dirname(os.path.abspath(a.list)))
    sv = os.path.join(disk, "Source Video")
    if not os.path.isfile(os.path.join(sv, "_catalog.csv")):
        sys.exit("Not a library drive: %s" % disk)
    pairs = read_list(a.list)
    days = day_dirs(sv)
    problems = []
    plan = []                                   # (old_rel, new_rel, old_name, new_name)
    seen_new = set()
    for old, new in pairs:
        rel = days.get(old)
        if not rel:
            problems.append("no day folder «%s»" % old)
            continue
        new_rel = rel.rsplit("/", 1)[0] + "/" + new
        if new in days or new in seen_new:
            problems.append("folder «%s» already exists (this script does not merge days)" % new)
        if os.path.exists(os.path.join(sv, "_карта", new)):
            problems.append("_карта already has «%s»" % new)
        seen_new.add(new)
        plan.append((rel, new_rel, old, new))
    run = Run(disk, a.apply)
    prefix = os.path.join(sv, "")                     # "<drive>/Source Video/"

    # what refers to the days: клипы.json, _catalog.csv, drafts
    def sub_rel(s):
        for o, n, _, _ in plan:
            if s == o or s.startswith(o + "/"):
                return n + s[len(o):]
        return s

    maps = []
    for o, n, old, new in plan:
        kj = os.path.join(sv, "_карта", old, "клипы.json")
        if os.path.isfile(kj):
            with open(kj, encoding="utf-8") as f:
                doc = json.load(f)
            doc["folder"] = sub_rel(doc.get("folder", ""))
            for c in doc.get("clips", []):
                if "path" in c:
                    c["path"] = sub_rel(c["path"])
            maps.append((kj, os.path.join(sv, "_карта", new, "клипы.json"), doc, len(doc.get("clips", []))))
        elif os.path.isdir(os.path.join(sv, "_карта", old)):
            problems.append("_карта/%s has no клипы.json" % old)

    cat = os.path.join(sv, "_catalog.csv")
    with open(cat, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        fields, cat_rows = rd.fieldnames, list(rd)
    n_cat = 0
    for r in cat_rows:
        nr = sub_rel(r["path"])
        if nr != r["path"]:
            r["path"], n_cat = nr, n_cat + 1

    abs_map = [(prefix + o + "/", prefix + n + "/") for o, n, _, _ in plan]
    drafts = {}                                       # (label, draft) → number of paths
    draft_edits = []
    for label, top, p in ([] if a.no_capcut else draft_files()):
        with open(p, encoding="utf-8", errors="surrogateescape") as f:
            s = f.read()
        if prefix not in s:
            continue
        ns, cnt = s, 0
        for o, n in abs_map:
            k = ns.count(o)
            if k:
                ns, cnt = ns.replace(o, n), cnt + k
        if cnt:
            key = (label, draft_name(top, p))
            drafts[key] = drafts.get(key, 0) + cnt
            draft_edits.append((p, ns, "%d путей" % cnt))
    # extra draft folders (VIDEO_LIBRARY_CAPCUT_DRAFTS) that are not reachable now: their drafts cannot be checked
    offline = [(label, top) for label, top in capcut_draft_dirs()[1:] if not os.path.isdir(top)]

    # report
    print("Drive: %s\nDay folders to rename: %d" % (disk, len(plan)))
    for o, n, old, new in plan:
        print("  %-40s → %s" % (old, new))
    print("\nклипы.json: %d files, %d clips" % (len(maps), sum(m[3] for m in maps)))
    print("_catalog.csv: %d rows" % n_cat)
    print("CapCut drafts: %d files" % len(draft_edits))
    for (label, d), k in sorted(drafts.items()):
        print("  %-12s %-20s %5d paths" % (label, d, k))
    if a.no_capcut:
        print("  left alone (--no-capcut)")
    elif offline:
        for label, top in offline:
            print("  %s is not reachable (%s): its drafts were not checked." % (label, top))
    if problems:
        print("\nWill not run:\n  " + "\n  ".join(problems))
    if not a.apply:
        print("\nDry run: nothing changed.")
        return 1 if problems else 0
    if problems:
        sys.exit(1)
    if offline and not (a.skip_offline_drafts or a.no_capcut):
        sys.exit("Draft folders not reachable: %s.\nConnect them (their CapCut drafts may point to this drive) or add "
                 "--skip-offline-drafts; fix_capcut_paths.py repairs those drafts later by file name."
                 % ", ".join(top for _, top in offline))
    if capcut_running():
        sys.exit("CapCut is running: close it, or it will overwrite the drafts.")

    # run: backups and text edits first, then the renames
    for kj, _, doc, _ in maps:
        run.write_text(kj, json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "клипы.json")
    run.save_backup(cat)
    tmp = cat + ".rename_tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(cat_rows)
    os.replace(tmp, cat)
    run.log("rewrite", cat, run.backup + cat, "%d строк" % n_cat)
    for p, ns, note in draft_edits:
        b = run.save_backup(p)
        with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(ns)
        run.log("rewrite", p, b, note)
    for o, n, old, new in plan:
        run.rename(os.path.join(sv, o), os.path.join(sv, n))
        mp = os.path.join(sv, "_карта", old)
        if os.path.isdir(mp):
            run.rename(mp, os.path.join(sv, "_карта", new))

    # checks
    bad = [o for o, n, _, _ in plan if os.path.exists(os.path.join(sv, o)) or not os.path.isdir(os.path.join(sv, n))]
    missing = 0
    for label, top, p in ([] if a.no_capcut else draft_files()):
        with open(p, encoding="utf-8", errors="surrogateescape") as f:
            for m in re.finditer(r'"(%s[^"\\]+)"' % re.escape(prefix), f.read()):
                if not os.path.exists(m.group(1)):
                    missing += 1
    print("\nDone. Journal: %s\nBackups: %s" % (run.journal, run.backup))
    print("Check: day folders not in place %d, paths to this drive in drafts that do not exist %d" % (len(bad), missing))
    tools = os.path.join(sv, "_tools")
    subprocess.run([sys.executable, "-I", os.path.join(tools, "video_map.py"), "--index"], cwd=tools)
    subprocess.run([sys.executable, "-I", os.path.join(tools, "catalog_all.py")], cwd=tools)
    if a.no_capcut:
        run.log("note", "CapCut", "", "черновики не правились (--no-capcut)")
    elif offline:
        for label, top in offline:
            run.log("todo", top, "", "при подключении: fix_capcut_paths.py --apply")
        print("Draft folders were not reachable: %s.\nOnce they are, run fix_capcut_paths.py (dry run first, then --apply)."
              % ", ".join(top for _, top in offline))
    print("Undo: python3 -I \"%s\" --undo \"%s\"" % (os.path.abspath(__file__), run.journal))
    print("Next, the projects (Video Archive / Video Production) — dry run, then add --apply:\n"
          "  python3 -I \"%s\" \"%s\" --disk \"%s\""
          % (os.path.join(os.path.dirname(os.path.abspath(__file__)), "rename_days_projects.py"),
             os.path.abspath(a.list), disk))


def undo(journal):
    with open(journal, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in reversed(rows):
        if r["action"] == "rename" and os.path.exists(r["dst"]) and not os.path.exists(r["src"]):
            os.rename(r["dst"], r["src"])
        elif r["action"] == "rewrite" and os.path.isfile(r["dst"]):
            shutil.copy2(r["dst"], r["src"])
    print("Undid %d actions. Rebuild the search (video_map.py --index) and the catalog (catalog_all.py)." % len(rows))
    print("If rename_days_projects.py was applied after it, undo that too, with its own journal.")


if __name__ == "__main__":
    sys.exit(main())
