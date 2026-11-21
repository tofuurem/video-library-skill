#!/usr/bin/env python3
"""Video map: what was shot in every clip of a day — speech, sounds, scenes, best frames, descriptions. Never touches the sources.

    python3 -I video_map.py YYYY-MM-DD [YYYY-MM-DD …]          — all stages, day by day
    python3 -I video_map.py YYYY-MM-DD --only extract,frames    — selected stages
    python3 -I video_map.py --index                             — rebuild the search over the whole map

Stages (each can be re-run — finished work is skipped):
  extract  one pass over the file: keyframes (as the camera writes them: 1–2 per second) at 384 px with the profile LUT
           + 16 kHz audio;
  frames   scenes by Apple Vision feature prints, in each the sharpest normally exposed frame, Vision labels,
           text in frame, people/faces, aesthetics; a sheet of up to 16 best frames with timecodes (vm_frames.py);
  speech   Silero VAD + GigaAM v3 on speech only (vm_speech.py, under the memory guard);
  sounds   Apple SoundAnalysis, 3 s windows (~/.cache/video-map/bin/sound_events);
  vlm      descriptions of ≤ 150 s segments by Qwen3-VL-8B from the 3–5 best frames + transcript (vlm_describe.py,
           under the memory guard: ceiling 11 GB, always ≥ 4 GB left to the Mac);
  assemble Source Video/_карта/<day folder>/клипы.json + листы/; then the search index _карта/поиск.sqlite.
Needs macOS (Apple Vision, SoundAnalysis) and reel-studio with its envs (LUTs, Vision venv, GigaAM, Qwen3-VL);
the vlm stage needs Apple Silicon and is skipped on Intel Macs.
Work files (frames, audio) live on the Mac's disk in ~/.cache/video-map/work (on exFAT every small file eats 1 MB).
The day description (день.md: timeline, quotes, best moments, ratings) is written by Claude from клипы.json.
"""
import argparse
import csv
import json
import os
import platform
import re
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
VLM_MODEL = os.path.expanduser("~/.cache/reel-studio/models/qwen3-vl-8b-4bit")   # vlm_describe.py's default
SOUND_BIN = os.path.expanduser("~/.cache/video-map/bin/sound_events")
SOUND_SRC = os.path.join(HERE, "sound_events.swift")
VIDEO_EXT = (".mp4", ".mov", ".m4v")
CHUNK = 150.0
STAGES = ["extract", "frames", "speech", "sounds", "vlm", "assemble"]


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
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "info", "-hwaccel", "videotoolbox", "-skip_frame", "nokey", "-i", clip,
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
    if not os.path.exists(SOUND_BIN):
        os.makedirs(os.path.dirname(SOUND_BIN), exist_ok=True)
        subprocess.run(["xcrun", "swiftc", "-O", SOUND_SRC, "-o", SOUND_BIN], check=True, capture_output=True)
    r = subprocess.run([SOUND_BIN, os.path.join(w, "audio.wav")], capture_output=True)
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
    json.dump({"windows": rows, "runs": runs}, open(out, "w"), ensure_ascii=False)


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
    log("  vlm: %d segments" % n)
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "mem_guard.py"), "--max-gb", "11", "--min-free-gb", "4", "--",
                        VLM, "-I", os.path.join(HERE, "vlm_describe.py"), jp, op, "--mem-gb", "9"])
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
    vlm = {}
    op = os.path.join(WORK, day, "vlm_out.jsonl")
    jobs = {j["id"]: j for j in json.load(open(os.path.join(WORK, day, "vlm_jobs.json")))} if os.path.exists(os.path.join(WORK, day, "vlm_jobs.json")) else {}
    if os.path.exists(op):
        for line in open(op, encoding="utf-8"):
            r = json.loads(line)
            j = jobs.get(r["id"], {})
            vlm.setdefault(r["id"].split("@")[0], []).append({"s": j.get("s"), "e": j.get("e"), **parse_vlm(r["text"])})
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


def preflight(stages):
    """Platform and dependency check before any stage runs. Returns the stages that can run on this Mac."""
    if sys.platform != "darwin":
        sys.exit("The video map needs macOS (Apple Vision, SoundAnalysis; Apple Silicon for scene descriptions). On this OS "
                 "the other library tools still work: sort_inbox.py, catalog_all.py, verify_dups.py, fix_capcut_paths.py, "
                 "and vm_search.py / vm_brief.py / vm_annotate.py on a map built on a Mac.")
    arm = platform.machine() == "arm64" or subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True,
                                                           text=True).stdout.strip() == "1"      # Rosetta python reports x86_64
    if "vlm" in stages and not arm:
        log("! vlm skipped: scene descriptions (Qwen3-VL via MLX) need Apple Silicon; the other stages run")
        stages = [s for s in stages if s != "vlm"]
    need = {"extract": [("reel-studio scripts (LUTs)", os.path.join(SKILL, "common.py"))],
            "frames": [("reel-studio env venv (Apple Vision)", VENV)],
            "speech": [("reel-studio env gigvenv (GigaAM)", GIG)],
            "vlm": [("reel-studio env vlmvenv (Qwen3-VL)", VLM), ("Qwen3-VL model", VLM_MODEL)]}
    missing = [(what, path) for st in stages for what, path in need.get(st, []) if not os.path.exists(path)]
    if "sounds" in stages and not os.path.exists(SOUND_BIN) and \
            subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True).returncode:
        missing.append(("swiftc for the sounds stage (Xcode Command Line Tools)", "fix: xcode-select --install"))
    if missing:
        msg = ["Missing for the video map:"] + ["  %s: %s" % m for m in missing]
        if any(what.startswith("reel-studio") for what, _ in missing):
            msg.append("Fix: install reel-studio (https://github.com/tofuurem/reel-studio-skill) into ~/.claude/skills/reel-studio "
                       "(or set REEL_STUDIO_SKILL to its folder) and run its scripts/deps.py --install.")
        if any(path == VLM_MODEL for _, path in missing):
            msg.append("The Qwen3-VL model (≈ 5.4 GB) is a separate download — reel-studio's setup_env.sh prints the command; "
                       "or leave vlm out: --only extract,frames,speech,sounds,assemble.")
        sys.exit("\n".join(msg))
    return stages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="*")
    ap.add_argument("--only", help="comma-separated stages: " + ",".join(STAGES))
    ap.add_argument("--index", action="store_true")
    a = ap.parse_args()
    stages = a.only.split(",") if a.only else STAGES
    if a.days:
        stages = preflight(stages)
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
