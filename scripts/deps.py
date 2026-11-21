#!/usr/bin/env python3
"""What this computer can run of the video-library skill, and what is missing. Read-only unless --install.

    python3 -I deps.py                      # report: platform, tools, engines, what works here, the fix for what is missing
    python3 -I deps.py --install            # install the missing tools for the library (Homebrew on macOS: exiftool, ffmpeg)
    python3 -I deps.py --install --with map # also the video map: reel-studio (cloned if missing) + its environments
                                            # (on Linux also its open-model engines: deps.py --install --with linux-vision)
    python3 -I deps.py --install --with map --with descriptions   # + the scene-description model (ask first: large):
                                            # macOS Apple Silicon: Qwen3-VL-8B 4-bit for MLX (≈ 5.4 GB);
                                            # Intel Mac and Linux: Qwen3-VL for transformers — 4B (≈ 9 GB) on a
                                            # CPU, 8B (≈ 17 GB) with NVIDIA
    python3 -I deps.py --install --with descriptions --vlm-model Qwen/Qwen3-VL-2B-Instruct
                                            # another model instead (any engine; here ≈ 4.5 GB, weaker): downloaded into
                                            # ~/.cache/reel-studio/models/<name lower case> and remembered in config.json
                                            # {"models": {"vlm"}} (= engines.py set-model vlm; env REEL_STUDIO_VLM_MODEL wins)

Platforms
  macOS, Apple Silicon   everything: sorting, duplicates, catalog, CapCut paths, archive, video map with descriptions
  macOS, Intel           everything; scene descriptions on the transformers engine by default (no MLX; CPU, slow;
                         the 4B model is a ≈ 9 GB download), or --engine vlm=llamacpp
  Linux (and WSL2)       sorting (python3 -I sort_inbox.py — Разложить.command is a macOS double-click launcher), duplicates,
                         catalog, archive, drive install; the video map and search with open-model engines (reel-studio's
                         engines.py: DINOv2, SigLIP 2, RapidOCR, YuNet, RT-DETR, AST; descriptions: Qwen3-VL via transformers or
                         llama.cpp); CapCut paths only for drafts reachable through VIDEO_LIBRARY_CAPCUT_DRAFTS (CapCut has no
                         Linux build). Drives are looked for in /media/$USER, /run/media/$USER, /mnt or $VIDEO_LIBRARY_VOLUMES.
  Windows                not native: WSL2 + Ubuntu, then as Linux.
Engines are chosen per capability on every platform (flag → env REEL_STUDIO_ENGINE_<CAP> → ~/.cache/reel-studio/config.json →
platform default); the table: <venv python> <reel-studio>/scripts/engines.py; reel-studio's references/engines.md explains them.
The video map borrows reel-studio's Python environments (~/.cache/reel-studio: venv, gigvenv, vlmvenv on Apple Silicon), its
common.py (LUT per clip) and engines.py. reel-studio: https://github.com/tofuurem/reel-studio-skill (path: $REEL_STUDIO_SKILL,
default ~/.claude/skills/reel-studio).
Prints DEPS_OK when everything for the chosen parts is there (the library always; --with map / descriptions when
asked), else DEPS_MISSING [...]. Root-only steps (Homebrew itself, Xcode tools, apt packages) are printed for the user to run.
"""
import argparse
import json
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
TF_QWEN = {"4b": ("Qwen/Qwen3-VL-4B-Instruct", os.path.join(CACHE, "models", "qwen3-vl-4b"), "≈ 9 GB"),
           "8b": ("Qwen/Qwen3-VL-8B-Instruct", os.path.join(CACHE, "models", "qwen3-vl-8b"), "≈ 17 GB")}
VENV = os.path.join(CACHE, "venv", "bin", "python")
CONFIG = os.path.join(CACHE, "config.json")
MAP_CAPS = ["feature_print", "labels", "ocr", "people", "faces", "aesthetics", "sound_events", "decode"]
PY_MIN = (3, 9)
LINUX_PKGS = {"apt": "sudo apt install libimage-exiftool-perl ffmpeg", "dnf": "sudo dnf install perl-Image-ExifTool ffmpeg",
              "pacman": "sudo pacman -S perl-image-exiftool ffmpeg", "zypper": "sudo zypper install exiftool ffmpeg"}


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
    p["linux"] = s == "Linux"
    p["nvidia"] = bool(shutil.which("nvidia-smi")) and run(["nvidia-smi", "-L"]).returncode == 0
    if p["nvidia"]:
        p["name"] += " + NVIDIA GPU"
    return p


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


def parts(p):
    """[(part, works here?, note)] — what the user gets on this platform."""
    mac, arm, lin = p["mac"], p["apple_silicon"], p["linux"]
    ok = mac or lin
    other = "not native: use WSL2 + Ubuntu"
    return [
        ("sort new footage into days and cameras (sort_inbox.py)", True,
         "" if mac else "python3 -I sort_inbox.py (Разложить.command is macOS only)" if lin else "with explicit --root and --inbox"),
        ("byte-by-byte duplicate check (verify_dups.py)", True, ""),
        ("migrate a drive, install tools on it (install_to_drive.py)", ok, "" if mac else "drives in %s" %
         (" / ".join(volumes()) or "/media/$USER, /run/media/$USER, /mnt or $VIDEO_LIBRARY_VOLUMES") if lin else other),
        ("all-drive catalog and «what can be freed» (catalog_all.py)", ok, "" if ok else other),
        ("archive and «верни в работу» (moves inside a drive)", ok, "" if ok else other),
        ("CapCut paths after moves (fix_capcut_paths.py)", ok, "" if mac else
         "only drafts reachable through VIDEO_LIBRARY_CAPCUT_DRAFTS (CapCut has no Linux build)" if lin else other),
        ("video map: frames, speech, sounds, search", ok, "" if mac else "open-model engines (reel-studio engines.py)" if lin else other),
        ("video map: scene descriptions with Qwen3-VL", ok, "MLX" if arm else
         "transformers engine (CPU: 4B, NVIDIA: 8B) or llama.cpp" if lin else
         "transformers engine by default (no MLX on Intel; CPU, slow; 4B ≈ 9 GB download) or llama.cpp" if mac else other),
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


def linux_pm():
    return next((m for m, b in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper")) if shutil.which(b)), None)


def engines_here(caps):
    """{cap: [chosen engine, [engines that run in reel-studio's venv]]} from its engines.py, or None (no reel-studio / venv /
    engines.py yet)."""
    scripts = os.path.join(REEL, "scripts")
    if not (os.path.isfile(os.path.join(scripts, "engines.py")) and os.path.exists(VENV)):
        return None
    code = ("import json, sys; sys.path.insert(0, %r); import engines as E; "
            "print(json.dumps({c: [E.choose(c), E.available(c)] for c in %r}))" % (scripts, caps))
    r = run([VENV, "-I", "-c", code])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"_error": (r.stderr.strip().splitlines() or ["engines.py failed"])[-1]}


def picked_model(arg=None):
    """(what the user picked, its local folder or file) — --vlm-model, else env REEL_STUDIO_VLM_MODEL, else config.json
    {"models": {"vlm"}} (as reel-studio's engines.vlm_model()); (None, None) = the engine's default model."""
    m = arg or os.environ.get("REEL_STUDIO_VLM_MODEL")
    if not m:
        try:
            m = (json.load(open(CONFIG)).get("models") or {}).get("vlm")
        except (OSError, ValueError, AttributeError):
            m = None
    m = (m or "").strip()
    if not m:
        return None, None
    if os.path.exists(os.path.expanduser(m)):
        return m, os.path.expanduser(m)
    return m, os.path.join(CACHE, "models", m.rstrip("/").split("/")[-1].lower())


def remember_model(m):
    try:
        cfg = json.load(open(CONFIG))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("models", {})["vlm"] = m
    os.makedirs(CACHE, exist_ok=True)
    tmp = CONFIG + ".tmp"
    json.dump(cfg, open(tmp, "w"), indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


def check(p, want_map, want_desc, vlm_model=None):
    R = Report()
    R.add(sys.version_info >= PY_MIN, "python3", platform.python_version())
    if p["mac"] and not has_brew():
        R.add(False, "brew", "Homebrew installs exiftool and ffmpeg",
              ("manual", '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'))
    pm = linux_pm() if p["linux"] else None
    for tool in ("exiftool", "ffmpeg", "ffprobe"):
        fix = ("brew", "exiftool" if tool == "exiftool" else "ffmpeg") if p["mac"] else \
              ("manual", LINUX_PKGS[pm]) if pm else \
              ("manual", "install %s with your package manager" % ("exiftool (libimage-exiftool-perl)" if tool == "exiftool" else "ffmpeg"))
        R.add(bool(shutil.which(tool)), tool, "camera, date and colour profile of every clip" if tool == "exiftool" else "", fix)
    if not (p["mac"] or p["linux"]):
        return R
    map_needed = want_map or want_desc
    lin = p["linux"]
    reel_ok = os.path.isfile(os.path.join(REEL, "scripts", "common.py")) and os.path.isfile(os.path.join(REEL, "scripts", "deps.py"))
    R.add(reel_ok, "reel-studio", REEL if reel_ok else "the map uses its environments, LUTs and engines — " + REEL_REPO,
          ("reel", None), required=map_needed)
    if reel_ok:
        eng_ok = os.path.isfile(os.path.join(REEL, "scripts", "engines.py"))
        R.add(eng_ok, "reel-studio engines", "engines.py" if eng_ok else "an older reel-studio: update it (git -C %s pull)" % REEL,
              ("manual", "git -C \"%s\" pull" % REEL), required=map_needed and lin)
    if p["mac"]:
        swift = run(["xcrun", "--find", "swiftc"]).returncode == 0
        R.add(swift, "swiftc", "builds the SoundAnalysis detector for the map on first use",
              ("manual", "xcode-select --install"), required=map_needed)
    for env, what in (("venv", "image and sound engines, numpy" if lin else "Apple Vision frames, numpy"),
                      ("gigvenv", "speech: GigaAM v3 + Silero VAD")):
        ok = os.path.exists(os.path.join(CACHE, env, "bin", "python"))
        R.add(ok, "env " + env, what, ("reel-deps", None), required=map_needed)
    eng = engines_here(MAP_CAPS + ["vlm"]) if reel_ok else None
    if eng and "_error" in eng:
        R.add(False, "engines", eng["_error"], ("reel-deps", None), required=map_needed)
        eng = None
    for cap in MAP_CAPS if eng else []:
        name, avail = eng[cap]
        R.add(name in avail, "engine " + cap, "%s (runs here: %s)" % (name, ", ".join(avail) or "none"),
              ("reel-deps", None), required=map_needed and cap != "decode")
    picked, local = picked_model(vlm_model)
    have_picked = bool(local) and (os.path.isfile(local) or os.path.isfile(os.path.join(local, "config.json")) or
                                   (os.path.isdir(local) and any(f.endswith(".gguf") for f in os.listdir(local))))
    if p["apple_silicon"]:
        ok = os.path.exists(os.path.join(CACHE, "vlmvenv", "bin", "python"))
        R.add(ok, "env vlmvenv", "mlx-vlm for scene descriptions", ("reel-deps", None), required=want_desc)
        if picked:
            R.add(have_picked, "vlm model (picked)", local if have_picked else "%s → %s (download)" % (picked, local),
                  ("picked", picked), required=want_desc)
        else:
            ok = os.path.isfile(os.path.join(QWEN_DIR, "config.json"))
            R.add(ok, "Qwen3-VL-8B 4-bit", QWEN_DIR + " (≈ 5.4 GB)", ("qwen", None), required=want_desc)
    elif want_desc:
        vlm = (eng or {}).get("vlm", ["transformers", []])
        if vlm[0] == "llamacpp":
            R.add(bool(shutil.which("llama-mtmd-cli")), "llama-mtmd-cli", "llama.cpp for the llamacpp vlm engine",
                  ("manual", "install llama.cpp (https://github.com/ggml-org/llama.cpp) so llama-mtmd-cli is on PATH"), required=want_desc)
            gg = os.path.join(CACHE, "models", "qwen3-vl-gguf")
            R.add(os.path.isdir(gg) and any("mmproj" in f for f in os.listdir(gg)), "Qwen3-VL GGUF", gg + " (model .gguf + mmproj .gguf)",
                  ("manual", "put a Qwen3-VL .gguf and its mmproj .gguf into " + gg), required=want_desc)
        else:
            size = "8b" if p["nvidia"] else "4b"
            repo, d, gb = TF_QWEN[size]
            have = next((TF_QWEN[s][1] for s in ("8b", "4b") if os.path.isfile(os.path.join(TF_QWEN[s][1], "config.json"))), None)
            R.add("transformers" in vlm[1], "vlm transformers", "torch + transformers in the venv", ("reel-deps", None), required=want_desc)
            if picked:
                R.add(have_picked, "vlm model (picked)", local if have_picked else "%s → %s (download — ask first)" % (picked, local),
                      ("picked", picked), required=want_desc)
            else:
                R.add(bool(have), "Qwen3-VL (transformers)", have or "%s → %s (%s download — ask first)" % (repo, d, gb),
                      ("tfqwen", size), required=want_desc)
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
        sh([sys.executable, "-I", os.path.join(REEL, "scripts", "deps.py"), "--install"] +
           (["--with", "linux-vision"] if p["linux"] else []), dry)
    if "qwen" in kinds:
        hf = os.path.join(CACHE, "vlmvenv", "bin", "hf")
        if dry or os.path.exists(hf):
            sh([hf, "download", QWEN_REPO, "--local-dir", QWEN_DIR], dry)
        else:
            manual.append("%s download %s --local-dir %s" % (hf, QWEN_REPO, QWEN_DIR))
    for kind, m in R.fix:
        if kind == "picked":
            d = picked_model(m)[1]
            py = os.path.join(CACHE, "vlmvenv", "bin", "python") if p["apple_silicon"] else VENV
            cmd = [py, "-I", "-c", "import sys; from huggingface_hub import snapshot_download; "
                   "snapshot_download(sys.argv[1], local_dir=sys.argv[2])", m, d]
            if dry or os.path.exists(py):
                sh(cmd, dry)
            else:
                manual.append(" ".join(cmd))
    for kind, size in R.fix:
        if kind == "tfqwen":
            repo, d, _ = TF_QWEN[size]
            cmd = [VENV, "-I", "-c", "import sys; from huggingface_hub import snapshot_download; "
                   "snapshot_download(sys.argv[1], local_dir=sys.argv[2])", repo, d]
            if dry or os.path.exists(VENV):
                sh(cmd, dry)
            else:
                manual.append(" ".join(cmd))
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
    ap.add_argument("--vlm-model", metavar="HF_ID",
                    help="with descriptions: another scene-description model instead of the default (e.g. "
                         "Qwen/Qwen3-VL-2B-Instruct for transformers, an mlx-community 4-bit repo for MLX); --install "
                         "downloads it and remembers it in ~/.cache/reel-studio/config.json")
    ap.add_argument("--with", dest="extras", action="append", default=[], choices=["map", "descriptions"],
                    help="map = the video map (reel-studio, its environments and engines); descriptions = also the "
                         "Qwen3-VL model: 8B 4-bit for MLX ≈ 5.4 GB (Apple Silicon), 4B ≈ 9 GB / 8B ≈ 17 GB for transformers")
    a = ap.parse_args()
    want_desc = "descriptions" in a.extras
    want_map = "map" in a.extras or want_desc
    p = plat()
    R = check(p, want_map, want_desc, a.vlm_model)
    if a.install and R.fix:
        show(p, R)
        print("installing:")
        manual = install(p, R, a.dry_run)
        if not a.dry_run:
            R = check(p, want_map, want_desc, a.vlm_model)
            print("after install:")
            show(p, R)
        if manual:
            print("run yourself:")
            for m in dict.fromkeys(manual):
                print("  " + m)
    else:
        show(p, R)
        if R.fix:
            cmd = "python3 -I %s --install%s" % (os.path.abspath(__file__),
                  "".join(" --with " + x for x in a.extras) + (" --vlm-model " + a.vlm_model if a.vlm_model else ""))
            # only optional items missing: everything asked for works — the command is an offer, not a fix
            print(("fix: " if R.missing else "optional: ") + cmd)
    if want_desc and p["mac"] and not p["apple_silicon"]:
        print("note: scene descriptions on an Intel Mac run on the transformers engine (CPU, slow; 4B ≈ 9 GB download); "
              "the map runs without them")
    if a.vlm_model and a.install and not a.dry_run and want_desc and not R.missing:
        remember_model(a.vlm_model)
        print("vlm model remembered: %s (~/.cache/reel-studio/config.json; env REEL_STUDIO_VLM_MODEL overrides)" % a.vlm_model)
    if a.vlm_model and not want_desc:
        print("note: --vlm-model is used with --with descriptions")
    if want_desc and not p["apple_silicon"] and not a.vlm_model:
        print("note: the transformers model is a large download (4B ≈ 9 GB, 8B ≈ 17 GB) — ask the user before --install")
    print("DEPS_OK" if not R.missing else "DEPS_MISSING %s" % R.missing)
    sys.exit(1 if R.missing else 0)


if __name__ == "__main__":
    main()
