#!/usr/bin/env python3
"""Video map: what was shot in every clip of a day — speech, sounds, scenes, best frames, descriptions. Never touches the sources.

    python3 -I video_map.py YYYY-MM-DD [YYYY-MM-DD …]          — all stages, day by day
    python3 -I video_map.py YYYY-MM-DD --only extract,frames    — selected stages
    python3 -I video_map.py --index                             — rebuild the search over the whole map
    python3 -I video_map.py YYYY-MM-DD --engine vlm=transformers --engine sound_events=ast   — pick engines for this run

Stages (each can be re-run — finished work is skipped):
  extract  one pass over the file: keyframes (as the camera writes them: 1–2 per second) at 384 px with the profile LUT
           + 16 kHz audio;
  frames   scenes by image feature prints, in each the sharpest normally exposed frame, labels, text in frame,
           people/faces, aesthetics; a sheet of up to 16 best frames with timecodes (vm_frames.py);
  speech   Silero VAD + GigaAM v3 on speech only (vm_speech.py, under the memory guard);
  sounds   sound events in 3 s windows: Apple SoundAnalysis (~/.cache/video-map/bin/sound_events) or AudioSet AST;
  vlm      descriptions of ≤ 150 s segments by Qwen3-VL from the 3–5 best frames + transcript (vlm_describe.py,
           under the memory guard, always ≥ 4 GB left to the computer). On a full run it is skipped with a note when
           the description model (or its env) is not installed, on any platform and engine; asked for explicitly
           (--only …vlm…, --engine vlm=…) it stops before any stage and lists what is missing;
  assemble Source Video/_карта/<day folder>/клипы.json + листы/; then the search index _карта/поиск.sqlite.
Engines: every capability (feature_print, labels, ocr, people, faces, aesthetics, sound_events, vlm, decode) runs on the
engine reel-studio's engines.py chooses — --engine CAP=NAME here, else env REEL_STUDIO_ENGINE_<CAP>, else
~/.cache/reel-studio/config.json, else the platform default: Apple frameworks + MLX on macOS; DINOv2, SigLIP 2, RapidOCR,
YuNet, RT-DETR, AST and Qwen3-VL via transformers on Linux (CUDA when an NVIDIA GPU is there). Table: <venv python>
<reel-studio>/scripts/engines.py. Keep one engine per library for feature prints and labels (scenes and labels differ).
Needs reel-studio with its envs (LUTs, venv, GigaAM; vlmvenv + MLX model, or a transformers / llama.cpp model).
Work files (frames, audio) live on this computer's disk in ~/.cache/video-map/work (on exFAT every small file eats 1 MB).
The day description (день.md: timeline, quotes, best moments, ratings) is written by Claude from клипы.json.
"""
import argparse
import csv
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SV = os.path.dirname(HERE)
MAP = os.path.join(SV, "_карта")
WORK = os.path.expanduser("~/.cache/video-map/work")
SKILL_DIR = os.environ.get("REEL_STUDIO_SKILL") or os.path.expanduser("~/.claude/skills/reel-studio")
SKILL = os.path.join(SKILL_DIR, "scripts")
VENV = os.path.expanduser("~/.cache/reel-studio/venv/bin/python")
GIG = os.path.expanduser("~/.cache/reel-studio/gigvenv/bin/python")
VLM = os.path.expanduser("~/.cache/reel-studio/vlmvenv/bin/python")
VLM_MODEL = os.path.expanduser("~/.cache/reel-studio/models/qwen3-vl-8b-4bit")   # vlm_describe.py's default (mlx)
MODELS = os.path.expanduser("~/.cache/reel-studio/models")
VLM_TF_MODELS = [os.path.join(MODELS, "qwen3-vl-4b"), os.path.join(MODELS, "qwen3-vl-8b")]   # transformers (local copies)
VLM_GGUF_DIR = os.path.join(MODELS, "qwen3-vl-gguf")                                           # llamacpp: model + mmproj
VLM_GUARD_GB = {"mlx": 11, "transformers": 14, "llamacpp": 11}     # --max-gb of the vlm stage per engine
SOUND_BIN = os.path.expanduser("~/.cache/video-map/bin/sound_events")
SOUND_SRC = os.path.join(HERE, "sound_events.swift")
VIDEO_EXT = (".mp4", ".mov", ".m4v")
CHUNK = 150.0
STAGES = ["extract", "frames", "speech", "sounds", "vlm", "assemble"]
STAGE_CAPS = {"frames": ["feature_print", "labels", "ocr", "people", "faces", "aesthetics"], "sounds": ["sound_events"],
              "vlm": ["vlm"]}
ENGINES = {}          # capability → engine chosen for this run (preflight fills it)


def hwaccel():
    """ffmpeg -hwaccel args, as reel-studio's common.HWACCEL: engines.hwaccel() when its engines.py is there (stdlib-only at
    import, so this python can load it); else the same probe inline — videotoolbox on macOS, cuda on Linux with an NVIDIA
    GPU, only when `ffmpeg -hwaccels` lists it; REEL_STUDIO_ENGINE_DECODE=none switches it off."""
    try:
        sys.path.insert(0, SKILL)
        import engines
        return list(engines.hwaccel())
    except ImportError:                           # no engines.py (an older reel-studio): decide here
        pass
    except (Exception, SystemExit) as e:          # engines.choose() exits on a bad env / config value: decide here
        log("! decode engine: %s — probing ffmpeg here" % (str(e).strip() or type(e).__name__))
    want = (os.environ.get("REEL_STUDIO_ENGINE_DECODE") or "").strip()
    if want not in ("videotoolbox", "cuda", "none"):
        want = "videotoolbox" if sys.platform == "darwin" else "cuda" if shutil.which("nvidia-smi") else "none"
    if want == "none":
        return []
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return ["-hwaccel", want] if want in out.split() else []


HWACCEL = None


def log(*a):
    print(*a, flush=True)


def day_dir(day):
    y, m = day[:4], day[:7]
    ydir = os.path.join(SV, y)
    for mon in sorted(os.listdir(ydir)):
        if mon.startswith(m):
            for d in sorted(os.listdir(os.path.join(ydir, mon))):
                if d.startswith(day):
                    return os.path.join(ydir, mon, d)
    sys.exit("no day folder " + day)


def clips_of(ddir):
    out = []
    for cam in sorted(os.listdir(ddir)):
        cdir = os.path.join(ddir, cam)
        if cam.startswith(".") or cam.startswith("_") or not os.path.isdir(cdir) or cam.endswith("_Photo"):
            continue
        for f in sorted(os.listdir(cdir)):
            if not f.startswith("._") and f.lower().endswith(VIDEO_EXT):
                out.append((cam, os.path.join(cdir, f)))
    return out


def catalog():
    rows = {}
    p = os.path.join(SV, "_catalog.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows[r["file"]] = r
    return rows


def wdir(day, clip):
    return os.path.join(WORK, day, os.path.splitext(os.path.basename(clip))[0])


# ---------------------------------------------------------------- extract
def lut_for(clip):
    sys.path.insert(0, SKILL)
    try:
        import common
        cube, why = common.lut_for(clip)
        if cube and why.startswith("default"):
            # no profile in the file and reel-studio does not know the camera: the default is a guess
            # (a log profile), while such clips are usually Normal / BT.709 — that LUT over-crushes the frames. No LUT is more honest.
            return None, "без LUT: " + why
        return cube, why
    except Exception as e:                          # LUT lookup failed — no LUT: the picture stays flat, the analysis still runs
        return None, "LUT не определён: %s" % e


def extract(day, clip):
    w = wdir(day, clip)
    done = os.path.join(w, "frames", "times.json")
    if os.path.exists(done) and os.path.exists(os.path.join(w, "audio.wav")):
        return
    os.makedirs(os.path.join(w, "frames"), exist_ok=True)
    cube, why = lut_for(clip)
    vf = "scale=384:-2"
    if cube:
        vf += ",lut3d=file='%s'" % cube.replace("'", "\\'")
    vf += ",showinfo"
    has_audio = "audio" in subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", clip],
                                          capture_output=True, text=True).stdout
    global HWACCEL
    if HWACCEL is None:
        HWACCEL = hwaccel()
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "info", *HWACCEL, "-skip_frame", "nokey", "-i", clip,
           "-map", "0:v:0", "-vf", vf, "-fps_mode", "passthrough", "-q:v", "4", os.path.join(w, "frames", "%05d.jpg")]
    if has_audio:
        cmd += ["-map", "0:a:0", "-ac", "1", "-ar", "16000", os.path.join(w, "audio.wav")]
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    times = [float(x) for x in re.findall(r"pts_time:\s*([\d.]+)", r.stderr)]
    if r.returncode or not times:
        log("  ! extract failed:", os.path.basename(clip), r.stderr[-300:])
        return
    json.dump(times, open(done, "w"))
    json.dump({"lut": cube, "lut_why": why, "audio": has_audio}, open(os.path.join(w, "extract.json"), "w"), ensure_ascii=False)
    log("  extract %s: %d frames, %.0f s" % (os.path.basename(clip), len(times), time.time() - t))


# ---------------------------------------------------------------- sounds
def sounds(day, clip):
    w = wdir(day, clip)
    out = os.path.join(w, "sounds.json")
    if os.path.exists(out) or not os.path.exists(os.path.join(w, "audio.wav")):
        return
    eng = ENGINES.get("sound_events", "soundanalysis")
    if eng == "soundanalysis":
        if not os.path.exists(SOUND_BIN):
            os.makedirs(os.path.dirname(SOUND_BIN), exist_ok=True)
            subprocess.run(["xcrun", "swiftc", "-O", SOUND_SRC, "-o", SOUND_BIN], check=True, capture_output=True)
        r = subprocess.run([SOUND_BIN, os.path.join(w, "audio.wav")], capture_output=True)
    else:                         # same JSON as the swift binary: [{"s", "e", "top": [[label, conf], …]}]
        r = subprocess.run([VENV, "-I", os.path.join(SKILL, "engines.py"), "sound_events", os.path.join(w, "audio.wav"),
                            "--engine", eng], capture_output=True)
        if r.returncode:
            log("  ! sounds (%s) failed: %s" % (eng, r.stderr.decode(errors="replace")[-300:]))
            return
    rows = json.loads(r.stdout or b"[]")
    # compress: consecutive windows with the same top sound → one run
    runs = []
    for x in rows:
        top = x.get("top") or []
        lab = top[0][0] if top else "silence"
        if runs and runs[-1]["label"] == lab and abs(runs[-1]["e"] - x["s"]) < 0.5:
            runs[-1]["e"] = x["e"]
        else:
            runs.append({"s": x["s"], "e": x["e"], "label": lab})
    doc = {"windows": rows, "runs": runs}
    if eng != "soundanalysis":
        doc["engine"] = eng                          # labels differ between engines (Apple's 303 classes vs AudioSet)
    json.dump(doc, open(out, "w"), ensure_ascii=False)


# ---------------------------------------------------------------- vlm
def vlm_jobs(day, clips, cat):
    jobs = []
    for cam, clip in clips:
        w = wdir(day, clip)
        fr = os.path.join(w, "frames.json")
        if not os.path.exists(fr):
            continue
        F = json.load(open(fr))
        if not F.get("scenes"):
            continue
        sp = json.load(open(os.path.join(w, "speech.json"))) if os.path.exists(os.path.join(w, "speech.json")) else {"segments": []}
        dur = F["scenes"][-1]["e"]
        n = max(1, int(-(-dur // CHUNK)))
        meta = cat.get(os.path.basename(clip), {})
        for k in range(n):
            a, b = dur * k / n, dur * (k + 1) / n
            sc = [s for s in F["scenes"] if a <= s["key_t"] < b] or [min(F["scenes"], key=lambda s: abs(s["key_t"] - a))]
            pick = sc if len(sc) <= 5 else [sc[round(i * (len(sc) - 1) / 4)] for i in range(5)]
            imgs, stamps = [], []
            for s in pick:
                imgs.append(os.path.join(w, "frames", s["key"]))
                stamps.append("%d:%02d" % (s["key_t"] // 60, s["key_t"] % 60))
            if len(pick) < 3:          # few scenes — add the spare frames of the same scene
                for s in pick:
                    for e in s.get("extra", [])[: 3 - len(imgs)]:
                        imgs.append(os.path.join(w, "frames", e))
            words = " ".join(x["text"] for x in sp["segments"] if x["e"] > a and x["s"] < b)
            ocr = sorted({t for s in sc for t in s["vision"].get("text", [])})[:6]
            ctx = ("Камера %s, %s %s, отрезок %d:%02d–%d:%02d клипа длиной %d:%02d. Кадры на %s." %
                   (cam, day, meta.get("time", ""), a // 60, a % 60, b // 60, b % 60, dur // 60, dur % 60, ", ".join(stamps)))
            ctx += (" Что говорят (распознано автоматически, могут быть ошибки): «%s»." % words[:600]) if words else " Речи нет."
            if ocr:
                ctx += " Текст в кадре: %s." % "; ".join(ocr)
            jobs.append({"id": "%s@%d" % (os.path.basename(clip), k), "images": imgs[:6], "context": ctx,
                         "clip": os.path.basename(clip), "s": round(a, 1), "e": round(b, 1)})
    return jobs


def run_vlm(day, clips, cat):
    jobs = vlm_jobs(day, clips, cat)
    if not jobs:
        return
    d = os.path.join(WORK, day)
    jp, op = os.path.join(d, "vlm_jobs.json"), os.path.join(d, "vlm_out.jsonl")
    n = len(jobs)
    # One date can exist on two drives while the day's work folder is shared — jobs are merged into the
    # previous ones, not overwritten (otherwise the other drive would lose its segment timecodes).
    if os.path.exists(jp):
        new = {j["id"] for j in jobs}
        jobs = [j for j in json.load(open(jp)) if j["id"] not in new] + jobs
    json.dump(jobs, open(jp, "w"), ensure_ascii=False)
    eng = ENGINES.get("vlm", "mlx")
    log("  vlm: %d segments (%s)" % (n, eng))
    py = VLM if eng == "mlx" else VENV
    max_gb = os.environ.get("VIDEO_MAP_VLM_MAX_GB") or str(VLM_GUARD_GB.get(eng, 11))
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "mem_guard.py"), "--max-gb", max_gb, "--min-free-gb", "4", "--",
                        py, "-I", os.path.join(HERE, "vlm_describe.py"), jp, op, "--engine", eng, "--mem-gb", "9"])
    if r.returncode == 137:
        log("  ! vlm stopped by the memory guard — run the vlm stage again later, finished segments are kept")


# ---------------------------------------------------------------- assemble
def parse_vlm(text):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    return {"что": text.strip()[:400]}


def assemble(day, ddir, clips, cat):
    out_dir = os.path.join(MAP, os.path.basename(ddir))
    os.makedirs(os.path.join(out_dir, "листы"), exist_ok=True)
    vlm, vlm_by = {}, {}
    op = os.path.join(WORK, day, "vlm_out.jsonl")
    jobs = {j["id"]: j for j in json.load(open(os.path.join(WORK, day, "vlm_jobs.json")))} if os.path.exists(os.path.join(WORK, day, "vlm_jobs.json")) else {}
    if os.path.exists(op):
        for line in open(op, encoding="utf-8"):
            r = json.loads(line)
            j = jobs.get(r["id"], {})
            vlm.setdefault(r["id"].split("@")[0], []).append({"s": j.get("s"), "e": j.get("e"), **parse_vlm(r["text"])})
            if r.get("engine"):                     # which model wrote it (older answers have no such field)
                vlm_by.setdefault(r["id"].split("@")[0], set()).add("%s %s" % (r["engine"], r.get("model", "")))
    old = {}
    cj = os.path.join(out_dir, "клипы.json")
    if os.path.exists(cj):                          # manual fields (summary, rating, moments) are kept
        for c in json.load(open(cj, encoding="utf-8")).get("clips", []):
            old[c["file"]] = c
    res = []
    for cam, clip in clips:
        w = wdir(day, clip)
        f = os.path.basename(clip)
        meta = cat.get(f, {})
        F = json.load(open(os.path.join(w, "frames.json"))) if os.path.exists(os.path.join(w, "frames.json")) else {}
        sp = json.load(open(os.path.join(w, "speech.json"))) if os.path.exists(os.path.join(w, "speech.json")) else {}
        so = json.load(open(os.path.join(w, "sounds.json"))) if os.path.exists(os.path.join(w, "sounds.json")) else {}
        ex = json.load(open(os.path.join(w, "extract.json"))) if os.path.exists(os.path.join(w, "extract.json")) else {}
        sheet = os.path.join(out_dir, "листы", os.path.splitext(f)[0] + ".jpg")
        dur = float(meta.get("duration_s") or 0) or (F["scenes"][-1]["e"] if F.get("scenes") else 0)
        wind = sum(x["e"] - x["s"] for x in so.get("runs", []) if x["label"].startswith("wind"))
        c = {
            "file": f, "path": os.path.relpath(clip, SV), "camera": cam, "time": meta.get("time", ""),
            "duration": round(dur, 1), "size_gb": round(float(meta.get("size_mb") or 0) / 1000, 2),
            "resolution": meta.get("resolution", ""), "fps": meta.get("fps", ""), "lut": os.path.basename(ex.get("lut") or "") or None,
            "speech_sec": sp.get("speech_sec", 0), "speech": sp.get("segments", []),
            "sounds": so.get("runs", []), "wind_sec": round(wind, 1),
            "dark_share": F.get("dark_share"), "motion": F.get("motion_mean"),
            "scenes": [{k: v for k, v in s.items() if k not in ("extra",)} for s in F.get("scenes", [])],
            "described": vlm.get(f, []),

            "sheet": os.path.relpath(sheet, out_dir) if os.path.exists(sheet) else None,
        }
        used = {k: v for k, v in F.get("engines", {}).items() if v != "vision"}
        if so.get("engine"):
            used["sound_events"] = so["engine"]
        by = sorted(vlm_by.get(f, ()))
        if by and by != ["mlx " + os.path.basename(VLM_MODEL)]:   # descriptions by another engine / model than the default
            used["vlm"] = ", ".join(by).strip()
        if used:                                    # not Apple's engines: say which (scenes, labels, sounds differ)
            c["engines"] = used
        for k in ("summary", "tags", "rating", "moments", "note"):          # filled in by Claude
            if k in old.get(f, {}):
                c[k] = old[f][k]
        res.append(c)
    doc = {"day": day, "folder": os.path.relpath(ddir, SV), "built": time.strftime("%Y-%m-%d %H:%M"),
           "clips": res}
    tmp = cj + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, cj)
    log("  assemble: %s (%d clips)" % (os.path.relpath(cj, SV), len(res)))


def build_index():
    db = os.path.join(MAP, "поиск.sqlite")
    # SQLite cannot write on exFAT (no proper locking) — build on the Mac's disk and copy the finished file over
    tmp = os.path.join(WORK, "поиск.sqlite.tmp")
    os.makedirs(WORK, exist_ok=True)
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.execute("CREATE VIRTUAL TABLE t USING fts5(day, file, s UNINDEXED, e UNINDEXED, kind, text, path UNINDEXED, tokenize='unicode61')")
    n = 0
    for d in sorted(os.listdir(MAP)):
        cj = os.path.join(MAP, d, "клипы.json")
        if not os.path.isfile(cj):
            continue
        doc = json.load(open(cj, encoding="utf-8"))
        for c in doc["clips"]:
            rows = [(x["s"], x["e"], "речь", x["text"]) for x in c.get("speech", [])]
            rows += [(x.get("s"), x.get("e"), "кадры", " ".join(str(v) if not isinstance(v, list) else " ".join(map(str, v)) for v in x.values() if not isinstance(v, (int, float)) or isinstance(v, bool))) for x in c.get("described", [])]
            rows += [(s["s"], s["e"], "в кадре", " ".join([l for l, _ in s["vision"].get("labels", [])] + s["vision"].get("text", []))) for s in c.get("scenes", [])]
            if c.get("summary"):
                rows.append((0, c["duration"], "описание", c["summary"] + " " + " ".join(c.get("tags", []))))
            for m in c.get("moments", []):
                rows.append((m.get("t"), m.get("t"), "момент", m.get("what", "")))
            for s, e, k, text in rows:
                con.execute("INSERT INTO t VALUES (?,?,?,?,?,?,?)", (doc["day"], c["file"], s, e, k, text, c["path"]))
                n += 1
    con.commit()
    con.close()
    import shutil
    shutil.copyfile(tmp, db + ".part")
    os.replace(db + ".part", db)
    os.remove(tmp)
    log("search: %d records → %s" % (n, os.path.relpath(db, SV)))


def is_apple_silicon():
    if sys.platform != "darwin":
        return False
    return platform.machine() == "arm64" or subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True,
                                                           text=True).stdout.strip() == "1"      # Rosetta python reports x86_64


def engine_table(caps, overrides):
    """{cap: (chosen, [available], error)} from reel-studio's engines.py, run in its venv (the backends live there);
    error = why engines.py could not choose (a bad --engine / env / config value, a capability an older engines.py
    lacks). None when engines.py is not there (an older reel-studio)."""
    if not os.path.isfile(os.path.join(SKILL, "engines.py")) or not os.path.exists(VENV):
        return None
    code = ("import json, sys; sys.path.insert(0, %r); import engines; o = json.loads(sys.argv[1]); r = {}\n"
            "for c in o['_caps']:\n"
            "    try: r[c] = [engines.choose(c, o.get(c)), engines.available(c), '']\n"
            "    except (Exception, SystemExit) as e: r[c] = [o.get(c), [], str(e) or type(e).__name__]\n"
            "print(json.dumps(r))" % SKILL)
    r = subprocess.run([VENV, "-I", "-c", code, json.dumps({**overrides, "_caps": caps})], capture_output=True, text=True)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        sys.exit("engines.py failed: %s" % (r.stderr.strip().splitlines() or ["?"])[-1])
    return {c: tuple(v) for c, v in res.items()}


def tf_model():
    return next((d for d in VLM_TF_MODELS if os.path.isfile(os.path.join(d, "config.json"))), None)


def picked_vlm_model():
    """The model the user picked instead of the default (reel-studio's engines.vlm_model(): env REEL_STUDIO_VLM_MODEL →
    config.json {"models": {"vlm"}}; a Hugging Face id resolves to its copy in ~/.cache/reel-studio/models), else None."""
    try:
        sys.path.insert(0, SKILL)
        import engines
        return engines.vlm_model()
    except (Exception, SystemExit):               # no engines.py, an older one, or a bad config
        return (os.environ.get("REEL_STUDIO_VLM_MODEL") or "").strip() or None


def preflight(stages, overrides, asked=True):
    """Platform, engines and dependency check before any stage runs. Fills ENGINES; returns the stages that can run here."""
    mac = sys.platform == "darwin"
    caps = [c for st in stages for c in STAGE_CAPS.get(st, [])]
    table = engine_table(caps, overrides) if caps else {}
    has_engines = table is not None
    missing = []
    if table is None:
        if not mac:
            missing += [m for m in (("reel-studio engines.py (the engines for Linux; update reel-studio)", os.path.join(SKILL, "engines.py")),
                                    ("reel-studio env venv (the engines run there)", VENV)) if not os.path.exists(m[1])]
            table = {}
        else:          # an older reel-studio without engines.py: Apple's engines, as before
            apple = {"sound_events": "soundanalysis", "vlm": "mlx" if is_apple_silicon() else "transformers"}
            table = {c: (apple.get(c, "vision"), [apple.get(c, "vision")], "") for c in caps}
            for c, n in overrides.items():
                if c not in table:
                    continue
                if c == "vlm" or n == table[c][0]:       # vlm_describe.py runs every vlm engine itself
                    table[c] = (n, [n], "")
                else:                                    # any other engine lives in engines.py
                    table[c] = (n, [], "needs reel-studio's engines.py (update reel-studio)")
    for c, (name, avail, err) in table.items():
        ENGINES[c] = name
        if err:
            missing.append(("engine for %s%s" % (c, " (%s)" % name if name else ""), err))
    if "sounds" in stages and ENGINES.get("sound_events") == "soundanalysis" and not os.path.exists(SOUND_BIN) and \
            (not mac or subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True).returncode):
        if not has_engines:
            sys.exit("Missing for the video map: swiftc for the sounds stage (Xcode Command Line Tools): xcode-select --install")
        alt = "ast"
        log("! sounds: SoundAnalysis needs swiftc (Xcode Command Line Tools: xcode-select --install) — using %s" % alt)
        ENGINES["sound_events"] = alt
        prev = table.get("sound_events", (None, [alt], ""))
        table["sound_events"] = (alt, prev[1] or [alt], prev[2])
    for c, (name, avail, err) in table.items():
        if err or c == "vlm" or (c == "sound_events" and name == "soundanalysis"):
            continue                                  # reported above / checked below / by swiftc
        if name not in avail:
            missing.append(("engine %s for %s (available here: %s)" % (name, c, ", ".join(avail) or "none"),
                            "fix: python3 -I %s --install%s" % (os.path.join(SKILL, "deps.py"), "" if mac else " --with linux-vision")))
    need = {"extract": [("reel-studio scripts (LUTs)", os.path.join(SKILL, "common.py"))],
            "frames": [("reel-studio env venv (image engines)", VENV)],
            "speech": [("reel-studio env gigvenv (GigaAM)", GIG)],
            "sounds": [("reel-studio env venv (sound engine)", VENV)] if ENGINES.get("sound_events", "soundanalysis") != "soundanalysis" else []}
    if "vlm" in stages:
        eng = ENGINES.get("vlm", "mlx")
        picked = picked_vlm_model()
        if picked:
            log("vlm model: %s (REEL_STUDIO_VLM_MODEL / engines.py set-model vlm)" % picked)
        if eng == "mlx" and not is_apple_silicon():
            need["vlm"] = [("the mlx vlm engine needs Apple Silicon (--engine vlm=transformers or llamacpp runs here)",
                            "Apple Silicon")]
        elif eng == "mlx":
            need["vlm"] = [("reel-studio env vlmvenv (Qwen3-VL on MLX)", VLM), ("Qwen3-VL model", picked or VLM_MODEL)]
        elif eng == "transformers":
            need["vlm"] = [("reel-studio env venv (transformers)", VENV),
                           ("Qwen3-VL model for transformers", picked or tf_model() or VLM_TF_MODELS[0])]
        elif eng == "llamacpp":
            gg = sorted(os.listdir(VLM_GGUF_DIR)) if os.path.isdir(VLM_GGUF_DIR) else []
            need["vlm"] = [("reel-studio env venv (PIL)", VENV),
                           ("llama-mtmd-cli on PATH (llama.cpp)", shutil.which("llama-mtmd-cli") or "llama-mtmd-cli"),
                           ("Qwen3-VL GGUF model + mmproj", VLM_GGUF_DIR if any("mmproj" in f for f in gg) and
                            any(f.endswith(".gguf") and "mmproj" not in f for f in gg) else VLM_GGUF_DIR + "/<model>.gguf")]
            if picked:
                need["vlm"][-1] = ("Qwen3-VL GGUF model (REEL_STUDIO_VLM_MODEL)", picked)
        else:
            need["vlm"] = [("vlm engine %r (mlx | transformers | llamacpp)" % eng, "")]
    vlm_miss = [(what, path) for what, path in need.get("vlm", []) if not os.path.exists(path)]
    if vlm_miss and not asked:
        # a full run (no --only vlm / --engine vlm=…) and descriptions cannot run here, on any platform and engine:
        # the map is built without them; asking for vlm explicitly exits below with the list of what is missing
        log("! vlm skipped: %s — install it (deps.py --install --with descriptions) or run --only vlm later; "
            "the other stages run" % "; ".join("%s: %s" % m if m[1] else m[0] for m in vlm_miss))
        stages = [s for s in stages if s != "vlm"]
        need.pop("vlm")
    missing += [(what, path) for st in stages for what, path in need.get(st, []) if not os.path.exists(path)]
    if missing:
        msg = ["Missing for the video map:"] + ["  %s: %s" % m for m in missing]
        if any(what.startswith("reel-studio") for what, _ in missing):
            msg.append("Fix: install reel-studio (https://github.com/tofuurem/reel-studio-skill) into ~/.claude/skills/reel-studio "
                       "(or set REEL_STUDIO_SKILL to its folder) and run its scripts/deps.py --install%s."
                       % ("" if mac else " --with linux-vision"))
        if any("model" in what for what, _ in missing):
            msg.append("The scene-description model is a separate download (mlx 8B 4-bit ≈ 5.4 GB; transformers 4B ≈ 9 GB, "
                       "8B ≈ 17 GB; a smaller one: --vlm-model Qwen/Qwen3-VL-2B-Instruct ≈ 4.5 GB): "
                       "video-library's deps.py --install --with descriptions; "
                       "or leave vlm out: --only extract,frames,speech,sounds,assemble.")
        sys.exit("\n".join(msg))
    run_caps = [c for st in stages for c in STAGE_CAPS.get(st, []) if c in ENGINES]   # without the stages skipped above
    if table and run_caps:
        log("engines: " + ", ".join("%s=%s" % (c, ENGINES[c]) for c in dict.fromkeys(run_caps)))
    return stages


def frames_engine_check(day, clips):
    """A day's scenes are cut with one feature-print engine: warn when clips already built use another one."""
    want = ENGINES.get("feature_print", "vision")
    other = {}
    for _, clip in clips:
        fj = os.path.join(wdir(day, clip), "frames.json")
        if os.path.exists(fj):
            got = json.load(open(fj)).get("engine", "vision")
            if got != want:
                other.setdefault(got, []).append(os.path.basename(clip))
    for got, names in other.items():
        log("! %d clips of %s were built with feature prints by %s, now %s: their scenes stay as they are. For one engine "
            "in the day delete their frames.json in %s and run the frames stage again: %s"
            % (len(names), day, got, want, os.path.join(WORK, day), ", ".join(names[:5])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="*")
    ap.add_argument("--only", help="comma-separated stages: " + ",".join(STAGES))
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--engine", action="append", default=[], metavar="CAP=NAME",
                    help="engine for one capability in this run, e.g. vlm=transformers, sound_events=ast, feature_print=dinov2")
    a = ap.parse_args()
    stages = a.only.split(",") if a.only else STAGES
    overrides = {}
    for x in a.engine:
        cap, _, name = x.partition("=")
        if not name:
            ap.error("--engine expects CAP=NAME, got %r" % x)
        overrides[cap.strip()] = name.strip()
        os.environ["REEL_STUDIO_ENGINE_" + cap.strip().upper()] = name.strip()     # child scripts resolve it the same way
    if a.days:
        stages = preflight(stages, overrides, asked=bool(a.only) or "vlm" in overrides)
    cat = catalog()
    for day in a.days:
        ddir = day_dir(day)
        clips = clips_of(ddir)
        log("== %s: %s, %d clips" % (day, os.path.relpath(ddir, SV), len(clips)))
        t = time.time()
        if "extract" in stages:
            for cam, clip in clips:
                extract(day, clip)
        if "frames" in stages:
            out_dir = os.path.join(MAP, os.path.basename(ddir), "листы")
            frames_engine_check(day, clips)
            for cam, clip in clips:
                w = wdir(day, clip)
                if os.path.exists(os.path.join(w, "frames", "times.json")) and not os.path.exists(os.path.join(w, "frames.json")):
                    subprocess.run([VENV, "-I", os.path.join(HERE, "vm_frames.py"), w, "--sheet",
                                    os.path.join(out_dir, os.path.splitext(os.path.basename(clip))[0] + ".jpg")])
        if "speech" in stages:
            dirs = [wdir(day, c) for _, c in clips]
            subprocess.run([sys.executable, "-I", os.path.join(HERE, "mem_guard.py"), "--max-gb", "4", "--min-free-gb", "3", "--",
                            GIG, "-I", os.path.join(HERE, "vm_speech.py"), *dirs])
        if "sounds" in stages:
            for cam, clip in clips:
                sounds(day, clip)
        if "vlm" in stages:
            run_vlm(day, clips, cat)
        if "assemble" in stages:
            assemble(day, ddir, clips, cat)
        log("== %s done in %.0f s" % (day, time.time() - t))
    if a.index or (a.days and "assemble" in stages):
        build_index()


if __name__ == "__main__":
    main()
