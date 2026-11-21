#!/usr/bin/env python3
"""Check before deleting a folder of duplicates.

For every file in the duplicates folder, searches the WHOLE drive (except that folder and
node_modules/.git/macOS service folders) for a regular file of the same size and compares
them byte by byte, start to end. Candidates with the same name first, then any file
of the same size (files in projects are sometimes renamed).

    python3 -I verify_dups.py "/Volumes/<drive>/Source Video/_дубликаты" report.tsv

Exit code 0 only if EVERY copy has a byte-identical original.
Report: status, size_bytes, copy, original (paths from the drive root).
Delete the folder only after exit code 0, and only by its full path.
"""
import os
import stat
import sys
import time

PRUNE = {"node_modules", ".git", ".Trashes", ".Spotlight-V100", ".fseventsd",
         ".TemporaryItems", ".DocumentRevisions-V100"}
CHUNK = 16 << 20


def volume_root(path):
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def same_bytes(a, b):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(CHUNK), fb.read(CHUNK)
            if x != y:
                return False
            if not x:
                return True


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    dup_dir = os.path.realpath(sys.argv[1])
    report = sys.argv[2]
    vol = volume_root(dup_dir)

    dups = sorted(os.path.join(d, f) for d, _, fs in os.walk(dup_dir)
                  for f in fs if not f.startswith("._"))
    sizes = {os.path.getsize(p) for p in dups}
    print(f"copies: {len(dups)}, drive: {vol}", flush=True)

    by_size = {}
    for d, dirs, files in os.walk(vol):
        dirs[:] = [x for x in dirs if x not in PRUNE and os.path.join(d, x) != dup_dir]
        for f in files:
            if f.startswith("._"):
                continue
            p = os.path.join(d, f)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and st.st_size in sizes:
                by_size.setdefault(st.st_size, []).append(p)

    ok = bad = 0
    total = sum(os.path.getsize(p) for p in dups)
    done = 0
    t0 = time.time()
    with open(report, "w", encoding="utf-8") as out:
        out.write("status\tsize_bytes\tcopy\toriginal\n")
        for i, p in enumerate(dups, 1):
            size, name = os.path.getsize(p), os.path.basename(p)
            match = None
            for c in sorted(by_size.get(size, []), key=lambda c: os.path.basename(c) != name):
                if os.path.realpath(c).startswith(dup_dir + os.sep) or os.path.samefile(c, p):
                    continue
                if same_bytes(p, c):
                    match = c
                    break
            if match:
                ok += 1
                out.write(f"OK\t{size}\t{os.path.relpath(p, vol)}\t{os.path.relpath(match, vol)}\n")
            else:
                bad += 1
                out.write(f"NO_ORIGINAL\t{size}\t{os.path.relpath(p, vol)}\t\n")
            out.flush()
            done += size
            print(f"{i}/{len(dups)} matched={ok} no_original={bad} "
                  f"{done / 1e9:.1f}/{total / 1e9:.1f} GB {time.time() - t0:.0f} s", flush=True)

    print(f"TOTAL: matched {ok} of {len(dups)}, no original {bad}")
    sys.exit(0 if bad == 0 and ok == len(dups) else 1)


if __name__ == "__main__":
    main()
