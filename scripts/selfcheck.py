#!/usr/bin/env python3
"""Self-check of the video-library skill. Read-only: writes nothing anywhere.

    python3 -I -B selfcheck.py

1. The master tool set in scripts/drive_tools is complete and every .py compiles.
2. mem_guard.py vs reel-studio's copy ($REEL_STUDIO_SKILL, default ~/.claude/skills/reel-studio): reported when they
   differ (both skills ship it; keep the newer one in both). vlm_describe.py is not compared: reel-studio's version
   imports its own common.py, the drive copy here stays standalone (video_map.py runs it under the guard).
3. Every mounted drive with "Source Video/_tools" (macOS): each master tool — same / older on the drive
   (install_to_drive.py will update it) / newer on the drive (changed there: bring it into the skill first) / missing.
4. The platform and what the tools need on this computer: deps.py's report.
Exit code 1 if the skill itself is broken; drift on drives and a different mem_guard.py are only reported.
"""
import filecmp
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(SKILL, "scripts", "drive_tools")
INBOX_CMD = os.path.join(SKILL, "assets", "inbox", "Разложить.command")
REEL = os.path.join(os.path.expanduser(os.environ.get("REEL_STUDIO_SKILL") or "~/.claude/skills/reel-studio"), "scripts")
EXPECTED = ["sort_inbox.py", "verify_dups.py", "catalog_all.py", "fix_capcut_paths.py", "rename_days.py",
            "rename_days_projects.py", "video_map.py", "vm_frames.py", "vm_speech.py", "vm_brief.py", "vm_search.py",
            "vm_annotate.py", "vlm_describe.py", "mem_guard.py", "sound_events.swift"]
SHARED = [("mem_guard.py", False)]    # (file, must be identical to reel-studio)


def master_files():
    out = []
    for r, ds, fs in os.walk(TOOLS):
        ds[:] = sorted(d for d in ds if d != "__pycache__" and not d.startswith("."))
        for f in sorted(fs):
            if not (f.startswith(".") or f.endswith(".pyc")):
                out.append(os.path.relpath(os.path.join(r, f), TOOLS))
    return out


def main():
    bad = 0
    print("Skill: %s" % SKILL)
    have = master_files()
    missing = [f for f in EXPECTED if f not in have]
    extra = [f for f in have if f not in EXPECTED]
    if missing:
        bad += 1
        print("!! missing in scripts/drive_tools: %s" % ", ".join(missing))
    if extra:
        print("-- also in scripts/drive_tools (not in EXPECTED): %s" % ", ".join(extra))
    for f in have:
        if f.endswith(".py"):
            p = os.path.join(TOOLS, f)
            try:
                with open(p, encoding="utf-8") as fh:
                    compile(fh.read(), p, "exec")
            except SyntaxError as e:
                bad += 1
                print("!! does not compile %s: %s" % (f, e))
    if not os.path.isfile(INBOX_CMD):
        bad += 1
        print("!! missing assets/inbox/Разложить.command")
    if not bad:
        print("OK  tools in the skill: %d, every .py compiles" % len(have))

    for f, strict in SHARED:
        other = os.path.join(REEL, f)
        if not os.path.isfile(other):
            print("-- reel-studio not found (%s): the video map needs it, see deps.py" % REEL)
        elif filecmp.cmp(os.path.join(TOOLS, f), other, shallow=False):
            print("OK  %s is the same as reel-studio's" % f)
        else:
            if strict:
                bad += 1
            print("%s %s differs from reel-studio's (%s): keep the newer one in both, then install it on the drives"
                  % ("!!" if strict else "--", f, other))

    if os.path.isdir("/Volumes"):
        print("\nDrives:")
        for name in sorted(os.listdir("/Volumes")):
            root = os.path.join("/Volumes", name)
            tdir = os.path.join(root, "Source Video", "_tools")
            if not os.path.isdir(tdir):
                continue
            rows = {"same": [], "older": [], "newer": [], "missing": []}
            for f in have:
                src, dst = os.path.join(TOOLS, f), os.path.join(tdir, f)
                if not os.path.exists(dst):
                    rows["missing"].append(f)
                elif filecmp.cmp(src, dst, shallow=False):
                    rows["same"].append(f)
                elif os.path.getmtime(dst) < os.path.getmtime(src):
                    rows["older"].append(f)
                else:
                    rows["newer"].append(f)
            cmd = os.path.join(root, "Source Video", "_inbox", "Разложить.command")
            cmd_state = "missing" if not os.path.exists(cmd) else ("same" if filecmp.cmp(INBOX_CMD, cmd, shallow=False) else "different")
            print("  %r: %d of %d tools the same; Разложить.command — %s" % (root, len(rows["same"]), len(have), cmd_state))
            if rows["older"]:
                print("     older (install_to_drive.py updates them): %s" % ", ".join(rows["older"]))
            if rows["newer"]:
                print("     newer on the drive than in the skill (bring them into the skill first): %s" % ", ".join(rows["newer"]))
            if rows["missing"]:
                print("     not on the drive: %s" % ", ".join(rows["missing"]))
            if not os.path.isfile(os.path.join(root, "CLAUDE.md")):
                print("     no CLAUDE.md in the root")

    print("\nThis computer (deps.py):")
    sys.stdout.flush()
    subprocess.run([sys.executable, "-I", "-B", os.path.join(SKILL, "scripts", "deps.py")])
    print("\nResult: %s" % ("the skill is fine" if not bad else "the skill itself has problems (!!)"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
