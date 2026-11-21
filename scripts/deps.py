#!/usr/bin/env python3
"""What this computer can run of the video-library skill, and what is missing. Read-only unless --install.

    python3 -I deps.py                      # report: platform, tools, what works here, the fix for what is missing
    python3 -I deps.py --install            # install the missing tools for the library (Homebrew: exiftool, ffmpeg)
    python3 -I deps.py --install --with map # also the video map: reel-studio (cloned if missing) + its environments
    python3 -I deps.py --install --with map --with descriptions   # + Qwen3-VL-8B 4-bit for scene descriptions (≈ 5.4 GB)

Platforms
  macOS, Apple Silicon   everything: sorting, duplicates, catalog, CapCut paths, archive, video map with descriptions
  macOS, Intel           everything except scene descriptions (Qwen3-VL runs on MLX, Apple Silicon only)
  Linux / Windows        not supported: the library lives on drives mounted in /Volumes, CapCut drafts are read from
                         ~/Movies, the map uses Apple Vision and SoundAnalysis. Only sort_inbox.py (with explicit
                         --root and --inbox) and verify_dups.py run there, with exiftool and ffmpeg.
The video map borrows reel-studio's Python environments (~/.cache/reel-studio: venv, gigvenv, vlmvenv) and its
common.py (LUT per clip). reel-studio: https://github.com/tofuurem/reel-studio-skill (path: $REEL_STUDIO_SKILL,
default ~/.claude/skills/reel-studio).
Prints DEPS_OK when everything for the chosen parts is there (the library always; --with map / descriptions when
asked), else DEPS_MISSING [...]. Root-only steps (Homebrew itself, Xcode tools) are printed for the user to run.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

REEL_REPO = "https://github.com/tofuurem/reel-studio-skill"
REEL = os.path.expanduser(os.environ.get("REEL_STUDIO_SKILL") or "~/.claude/skills/reel-studio")
CACHE = os.path.expanduser("~/.cache/reel-studio")
QWEN_REPO = "mlx-community/Qwen3-VL-8B-Instruct-4bit"
QWEN_DIR = os.path.join(CACHE, "models", "qwen3-vl-8b-4bit")
PY_MIN = (3, 9)


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 1, "", "")


def plat():
    s, m = platform.system(), platform.machine().lower()
    p = {"system": s, "mac": s == "Darwin", "apple_silicon": False, "name": s}
    if p["mac"]:
        p["apple_silicon"] = m == "arm64" or run(["sysctl", "-n", "sysctl.proc_translated"]).stdout.strip() == "1"
        p["name"] = "macOS %s %s" % (platform.mac_ver()[0], "Apple Silicon" if p["apple_silicon"] else "Intel")
    elif s == "Linux":
        p["name"] = "Linux" + (" (WSL)" if "microsoft" in platform.release().lower() else "")
    return p


def parts(p):
    """[(part, works here?, note)] — what the user gets on this platform."""
    mac, arm = p["mac"], p["apple_silicon"]
    why = "macOS only (drives in /Volumes)"
    return [
        ("sort new footage into days and cameras (sort_inbox.py)", True, "" if mac else "with explicit --root and --inbox"),
        ("byte-by-byte duplicate check (verify_dups.py)", True, ""),
        ("migrate a drive, install tools on it (install_to_drive.py)", mac, "" if mac else why),
        ("all-drive catalog and «what can be freed» (catalog_all.py)", mac, "" if mac else why),
        ("CapCut paths after moves (fix_capcut_paths.py)", mac, "" if mac else "macOS only (CapCut drafts in ~/Movies)"),
        ("video map: frames, speech, sounds, search", mac, "" if mac else "macOS only (Apple Vision, SoundAnalysis)"),
        ("video map: scene descriptions with Qwen3-VL", mac and arm, "" if arm else "Apple Silicon only (MLX)"),
    ]


class Report:
    def __init__(self):
        self.rows, self.missing, self.fix = [], [], []

    def add(self, ok, name, info="", fix=None, required=True):
        self.rows.append(("ok" if ok else ("MISSING" if required else "optional"), name, info))
        if not ok:
            if required:
                self.missing.append(name)
            if fix:
                self.fix.append(fix)


def has_brew():
    return shutil.which("brew") or next((b for b in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(b)), None)


def check(p, want_map, want_desc):
    R = Report()
    R.add(sys.version_info >= PY_MIN, "python3", platform.python_version())
    if p["mac"] and not has_brew():
        R.add(False, "brew", "Homebrew installs exiftool and ffmpeg",
              ("manual", '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'))
    for tool in ("exiftool", "ffmpeg", "ffprobe"):
        fix = ("brew", "exiftool" if tool == "exiftool" else "ffmpeg") if p["mac"] else \
              ("manual", "install %s with your package manager" % ("exiftool (libimage-exiftool-perl)" if tool == "exiftool" else "ffmpeg"))
        R.add(bool(shutil.which(tool)), tool, "camera, date and colour profile of every clip" if tool == "exiftool" else "", fix)
    if not p["mac"]:
        return R
    map_needed = want_map or want_desc
    swift = run(["xcrun", "--find", "swiftc"]).returncode == 0
    R.add(swift, "swiftc", "builds the sound detector for the map on first use",
          ("manual", "xcode-select --install"), required=map_needed)
    reel_ok = os.path.isfile(os.path.join(REEL, "scripts", "common.py")) and os.path.isfile(os.path.join(REEL, "scripts", "deps.py"))
    R.add(reel_ok, "reel-studio", REEL if reel_ok else "the map uses its environments and LUTs — " + REEL_REPO,
          ("reel", None), required=map_needed)
    for env, what in (("venv", "Apple Vision frames, numpy"), ("gigvenv", "speech: GigaAM v3 + Silero VAD")):
        ok = os.path.exists(os.path.join(CACHE, env, "bin", "python"))
        R.add(ok, "env " + env, what, ("reel-deps", None), required=map_needed)
    if p["apple_silicon"]:
        ok = os.path.exists(os.path.join(CACHE, "vlmvenv", "bin", "python"))
        R.add(ok, "env vlmvenv", "mlx-vlm for scene descriptions", ("reel-deps", None), required=want_desc)
        ok = os.path.isfile(os.path.join(QWEN_DIR, "config.json"))
        R.add(ok, "Qwen3-VL-8B 4-bit", QWEN_DIR + " (≈ 5.4 GB)", ("qwen", None), required=want_desc)
    return R


def sh(cmd, dry):
    print("  $ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    if dry:
        return True
    return subprocess.run(cmd).returncode == 0


def install(p, R, dry):
    manual = []
    brew = has_brew()
    pkgs = sorted({arg for kind, arg in R.fix if kind == "brew"})
    if pkgs:
        if brew:
            sh([brew, "install"] + pkgs, dry)
        else:
            manual.append("brew install " + " ".join(pkgs))
    kinds = {kind for kind, _ in R.fix}
    if "reel" in kinds:
        if os.path.exists(REEL):
            manual.append("%s exists but is not reel-studio — move it away or set REEL_STUDIO_SKILL" % REEL)
        else:
            sh(["git", "clone", REEL_REPO, REEL], dry)
    if kinds & {"reel", "reel-deps"} and (dry or os.path.isfile(os.path.join(REEL, "scripts", "deps.py"))):
        sh([sys.executable, "-I", os.path.join(REEL, "scripts", "deps.py"), "--install"], dry)
    if "qwen" in kinds:
        hf = os.path.join(CACHE, "vlmvenv", "bin", "hf")
        if dry or os.path.exists(hf):
            sh([hf, "download", QWEN_REPO, "--local-dir", QWEN_DIR], dry)
        else:
            manual.append("%s download %s --local-dir %s" % (hf, QWEN_REPO, QWEN_DIR))
    manual += [arg for kind, arg in R.fix if kind == "manual"]
    return manual


def show(p, R):
    print("platform: " + p["name"])
    for state, name, info in R.rows:
        print("  %-8s %-20s %s" % (state, name, info))
    print("what works here:")
    for name, ok, note in parts(p):
        print("  %-3s %s%s" % ("yes" if ok else "no", name, ("  — " + note) if note else ""))


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="Check / install what the video-library skill needs on this computer.")
    ap.add_argument("--install", action="store_true", help="install what is missing (asks nothing; root-only steps are printed)")
    ap.add_argument("--dry-run", action="store_true", help="with --install: print the commands, run nothing")
    ap.add_argument("--with", dest="extras", action="append", default=[], choices=["map", "descriptions"],
                    help="map = the video map (reel-studio and its environments); "
                         "descriptions = also Qwen3-VL-8B 4-bit, ≈ 5.4 GB, Apple Silicon only")
    a = ap.parse_args()
    want_desc = "descriptions" in a.extras
    want_map = "map" in a.extras or want_desc
    p = plat()
    R = check(p, want_map, want_desc)
    if a.install and R.fix:
        show(p, R)
        print("installing:")
        manual = install(p, R, a.dry_run)
        if not a.dry_run:
            R = check(p, want_map, want_desc)
            print("after install:")
            show(p, R)
        if manual:
            print("run yourself:")
            for m in dict.fromkeys(manual):
                print("  " + m)
    else:
        show(p, R)
        if R.fix:
            print("fix: python3 -I %s --install%s" % (os.path.abspath(__file__),
                  "".join(" --with " + x for x in a.extras)))
    if want_desc and p["mac"] and not p["apple_silicon"]:
        print("note: scene descriptions need Apple Silicon; the map runs without them here")
    print("DEPS_OK" if not R.missing else "DEPS_MISSING %s" % R.missing)
    sys.exit(1 if R.missing else 0)


if __name__ == "__main__":
    main()
