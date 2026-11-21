#!/usr/bin/env python3
"""Video map, stage "frames": the clip's scenes and the best frame of each scene (image engines + numpy).

    ~/.cache/reel-studio/venv/bin/python -I vm_frames.py <clip folder in work> [--sheet sheet.jpg] [--calib] [--threshold X]

Input: work/<clip>/frames/*.jpg (keyframes with the LUT, 384 px) and frames/times.json (time of every frame, s).
1. Every frame: sharpness (variance of the Laplacian), brightness, difference to the previous one (motion), feature print.
2. Scenes: a new scene starts when the print drifts from the scene's start beyond the threshold and the scene lasts
   ≥ MIN_SCENE s; a scene longer than MAX_SCENE s is split evenly (the description model needs different parts of a long take).
3. In every scene the best frame: sharp and normally exposed (not dark, not blown out) + 2 spares from the start
   and the end of the scene — the description model gets them.
4. On the best frames: labels (≥ 0.3), text (ru/en), people, faces, aesthetics.
→ work/<clip>/frames.json; --sheet: a sheet of up to 16 best frames with timecodes (on the drive, next to the map).
Engines: per capability (feature_print, labels, ocr, people, faces, aesthetics) as reel-studio's engines.py chooses
(env REEL_STUDIO_ENGINE_<CAP>, ~/.cache/reel-studio/config.json, platform default). Apple Vision («vision») runs here in
one request handler per frame, as before; every other engine through engines.py. frames.json records the engines and the
scene threshold: prints of different engines are never compared (a re-run with another engine rebuilds the whole clip).
Scene threshold: --threshold, else env VIDEO_MAP_SCENE_THRESHOLD, else engines.scene_threshold(engine) (vision 0.95
Euclidean; dinov2 cosine — calibrate with --calib on a few clips with known cuts).
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MIN_SCENE = 3.0
MAX_SCENE = 40.0
FP_THRESHOLD = 0.95      # vision, calibrated with --calib: neighbouring frames within a scene ~0.45, a change of place ~1.1–1.2
CAPS = ["feature_print", "labels", "ocr", "people", "faces", "aesthetics"]
SKILL = os.path.join(os.environ.get("REEL_STUDIO_SKILL") or os.path.expanduser("~/.claude/skills/reel-studio"), "scripts")
PEOPLE_MIN_CONF = 0.5    # boxes from non-Apple detectors counted as people / faces from this confidence


def load_engines():
    """reel-studio's engines.py (sys.path like common.py), or None when it is not there: then Apple Vision only (macOS)."""
    sys.path.insert(0, SKILL)
    try:
        import engines
        return engines
    except ImportError:
        if sys.platform != "darwin":
            sys.exit("vm_frames.py: reel-studio's engines.py was not found in %s — on Linux the image engines come from it. "
                     "Update reel-studio and run its deps.py --install --with linux-vision." % SKILL)
        return None


def font(size):
    """Arial (macOS) → reel-studio's template font → DejaVuSans → Pillow's own font."""
    cands = ["/System/Library/Fonts/Supplemental/Arial.ttf"]
    cands += sorted(glob.glob(os.path.expanduser("~/.cache/reel-studio/fonts/*.ttf")))
    cands += ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                 # Pillow < 10.1: no size
        return ImageFont.load_default()


def gray(path):
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def sharpness(g):
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def vision_print(path):
    import Vision
    from Foundation import NSURL
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
    r = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
    h.performRequests_error_([r], None)
    if not r.results():
        return None
    o = r.results()[0]
    # pyobjc 13 does not return the distance from computeDistance (the out-parameter is None) — compute it here: it is
    # the Euclidean distance between the print vectors (elementType 1 = float32, 2 = float64)
    dt = np.float32 if o.elementType() == 1 else np.float64
    return np.frombuffer(bytes(o.data()), dtype=dt).astype(np.float32)


def fp_dist(a, b, engine="vision", E=None):
    if a is None or b is None:
        return 0.0
    if engine == "vision" or E is None:
        return float(np.linalg.norm(a - b))
    return float(E.distance(a, b, engine))


def feature_print(path, engine, E):
    if engine == "vision":
        return vision_print(path)
    got, vec = E.feature_print(path, engine=engine)
    if got != engine:
        sys.exit("vm_frames.py: asked for feature prints by %s, engines.py gave %s" % (engine, got))
    return np.asarray(vec, dtype=np.float32) if vec is not None else None


def details(path, eng, E):
    """Labels, text, people, faces, aesthetics of one frame. Everything on «vision» goes through one Vision request handler
    (as before engines existed); the rest through engines.py. Same keys whatever the engine."""
    vis = [c for c in CAPS[1:] if eng[c] == "vision"]
    out = vision_details(path, vis) if vis else {}
    if eng["labels"] != "vision":
        out["labels"] = [[l, round(float(c), 2)] for l, c in E.labels(path, min_conf=0.3, top=10, engine=eng["labels"])][:10]
    if eng["ocr"] != "vision":
        out["text"] = [t["text"] for t in E.ocr(path, langs=("ru", "en"), engine=eng["ocr"]) if len(t["text"].strip()) >= 3][:8]
    if eng["people"] != "vision":
        out["people"] = sum(1 for b in E.people(path, engine=eng["people"]) if b.get("c", 1) >= PEOPLE_MIN_CONF)
    if eng["faces"] != "vision":
        fs = [b for b in E.faces(path, engine=eng["faces"]) if b.get("c", 1) >= PEOPLE_MIN_CONF]
        out["faces"] = len(fs)
        out["face_size"] = round(float(max((b["h"] for b in fs), default=0.0)), 2)
    if eng["aesthetics"] != "vision":
        r = E.aesthetics(path, engine=eng["aesthetics"]) or {}
        if r.get("aesthetic") is not None:
            out["aesthetic"] = round(float(r["aesthetic"]), 2)
            out["utility"] = bool(r.get("utility"))
    order = ["labels", "text", "people", "faces", "face_size", "aesthetic", "utility"]
    return {k: out[k] for k in order if k in out}


def vision_details(path, caps=CAPS[1:]):
    import Vision
    from Foundation import NSURL
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
    cls = Vision.VNClassifyImageRequest.alloc().init()
    ocr = Vision.VNRecognizeTextRequest.alloc().init()
    ocr.setRecognitionLanguages_(["ru-RU", "en-US"])
    ocr.setRecognitionLevel_(0)
    hum = Vision.VNDetectHumanRectanglesRequest.alloc().init()
    face = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    reqs = [r for c, r in (("labels", cls), ("ocr", ocr), ("people", hum), ("faces", face)) if c in caps]
    aes = Vision.VNCalculateImageAestheticsScoresRequest.alloc().init() \
        if "aesthetics" in caps and hasattr(Vision, "VNCalculateImageAestheticsScoresRequest") else None
    if aes:
        reqs.append(aes)
    h.performRequests_error_(reqs, None)
    faces = face.results() or []
    big_face = max((f.boundingBox().size.height for f in faces), default=0.0)
    out = {
        "labels": [[o.identifier(), round(float(o.confidence()), 2)] for o in (cls.results() or []) if o.confidence() >= 0.3][:10],
        "text": [t for t in (o.topCandidates_(1)[0].string() for o in (ocr.results() or [])) if len(t.strip()) >= 3][:8],
        "people": len(hum.results() or []),
        "faces": len(faces),
        "face_size": round(float(big_face), 2),          # share of the frame height: > 0.3 — talking head / selfie
    }
    out = {k: v for k, v in out.items() if {"labels": "labels", "text": "ocr", "people": "people", "faces": "faces",
                                            "face_size": "faces"}[k] in caps}
    if aes and aes.results():
        r = aes.results()[0]
        out["aesthetic"] = round(float(r.overallScore()), 2)
        out["utility"] = bool(r.isUtility())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clipdir")
    ap.add_argument("--sheet")
    ap.add_argument("--calib", action="store_true", help="only print the distribution of distances")
    ap.add_argument("--threshold", type=float, help="scene threshold for this engine's distance (default: engines.scene_threshold)")
    a = ap.parse_args()
    E = load_engines()
    eng = {c: (E.require(c, "vm_frames.py") if E else "vision") for c in CAPS}   # exits with the fix when one cannot run
    asked = [c for c in CAPS if os.environ.get("REEL_STUDIO_ENGINE_" + c.upper(), "vision") != "vision"]
    if not E and asked:
        sys.exit("vm_frames.py: engines other than Apple Vision (%s) need reel-studio's engines.py — update reel-studio" % ", ".join(asked))
    fpe = eng["feature_print"]
    thr = a.threshold or float(os.environ.get("VIDEO_MAP_SCENE_THRESHOLD") or 0) or \
        (FP_THRESHOLD if fpe == "vision" else float(E.scene_threshold(fpe)))
    old = os.path.join(a.clipdir, "frames.json")
    if os.path.exists(old) and not a.calib:
        got = json.load(open(old)).get("engine", "vision")
        if got != fpe:
            print("vm_frames.py: %s was built with %s feature prints, now %s — rebuilding the whole clip with %s"
                  % (old, got, fpe, fpe), flush=True)
    fdir = os.path.join(a.clipdir, "frames")
    times = json.load(open(os.path.join(fdir, "times.json")))
    files = sorted(f for f in os.listdir(fdir) if f.endswith(".jpg"))
    n = min(len(files), len(times))
    files, times = files[:n], times[:n]
    if n == 0:
        json.dump({"frames": 0, "scenes": [], "engine": fpe}, open(os.path.join(a.clipdir, "frames.json"), "w"))
        return
    sharp, bright, motion, prints = [], [], [], []
    prev = None
    for f in files:
        g = gray(os.path.join(fdir, f))
        sharp.append(sharpness(g))
        bright.append(float(g.mean()))
        motion.append(float(np.abs(g - prev).mean()) if prev is not None and prev.shape == g.shape else 0.0)
        prev = g
        prints.append(feature_print(os.path.join(fdir, f), fpe, E))
    step = [fp_dist(prints[i - 1], prints[i], fpe, E) for i in range(1, n)]
    if a.calib:
        q = np.percentile(step, [50, 75, 90, 95, 99]) if step else []
        print("%s, threshold now %.3f — neighbouring-frame step: median/75/90/95/99 %%:" % (fpe, thr),
              [round(float(x), 3) for x in q])
        return
    # scenes
    bounds = [0]
    ref = 0
    for i in range(1, n):
        if times[i] - times[bounds[-1]] >= MIN_SCENE and fp_dist(prints[ref], prints[i], fpe, E) > thr:
            bounds.append(i)
            ref = i
    bounds.append(n)
    scenes = []
    for b0, b1 in zip(bounds, bounds[1:]):
        t0, t1 = times[b0], (times[b1] if b1 < n else times[-1] + (times[-1] - times[-2] if n > 1 else 1.0))
        parts = max(1, math.ceil((t1 - t0) / MAX_SCENE))
        idx = list(range(b0, b1))
        for p in range(parts):
            sub = idx[len(idx) * p // parts: len(idx) * (p + 1) // parts]
            if sub:
                scenes.append(sub)
    # normalise sharpness within the clip
    s_arr = np.array(sharp)
    s_norm = (s_arr - s_arr.min()) / (np.ptp(s_arr) + 1e-6)

    def score(i):
        b = bright[i]
        expo = 1.0 if 45 <= b <= 210 else max(0.0, 1 - min(abs(b - 45), abs(b - 210)) / 45)
        return 0.75 * s_norm[i] + 0.25 * expo

    out_scenes = []
    for sub in scenes:
        best = max(sub, key=score)
        third = max(1, len(sub) // 3)
        extra = []
        for part in (sub[:third], sub[-third:]):
            c = max(part, key=score)
            if c != best and c not in extra:
                extra.append(c)
        t_end = times[sub[-1] + 1] if sub[-1] + 1 < n else times[sub[-1]] + 0.5
        out_scenes.append({
            "s": round(times[sub[0]], 2), "e": round(t_end, 2),
            "key": files[best], "key_t": round(times[best], 2), "extra": [files[i] for i in extra],
            "sharp": round(float(s_norm[best]), 2), "bright": round(bright[best]),
            "motion": round(float(np.mean([motion[i] for i in sub])), 1),
            "vision": details(os.path.join(fdir, files[best]), eng, E),
        })
    res = {"frames": n, "fps": round(n / max(times[-1] - times[0], 1e-6), 2) if n > 1 else 0,
           "dark_share": round(float(np.mean(np.array(bright) < 35)), 2),
           "motion_mean": round(float(np.mean(motion)), 1), "scenes": out_scenes}
    res.update({"engine": fpe, "threshold": round(thr, 4), "engines": eng})   # клипы.json names them only when not Apple's
    json.dump(res, open(os.path.join(a.clipdir, "frames.json"), "w"), ensure_ascii=False)
    if a.sheet:
        keys = out_scenes if len(out_scenes) <= 16 else [out_scenes[round(i * (len(out_scenes) - 1) / 15)] for i in range(16)]
        tiles = []
        fnt = font(18)
        for sc in keys:
            im = Image.open(os.path.join(fdir, sc["key"])).convert("RGB")
            d = ImageDraw.Draw(im)
            t = sc["key_t"]
            lab = "%d:%02d" % (t // 60, t % 60)
            d.rectangle([0, 0, 12 + 11 * len(lab), 24], fill=(0, 0, 0))
            d.text((5, 2), lab, fill=(255, 220, 0), font=fnt)
            tiles.append(im)
        w, h = tiles[0].size
        cols = 4 if len(tiles) > 4 else len(tiles)
        rows = math.ceil(len(tiles) / cols)
        sheet = Image.new("RGB", (w * cols, h * rows), (25, 25, 25))
        for i, im in enumerate(tiles):
            sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
        os.makedirs(os.path.dirname(os.path.abspath(a.sheet)), exist_ok=True)
        sheet.save(a.sheet, quality=80)
    print("FRAMES_DONE %s: %d frames, %d scenes" % (os.path.basename(a.clipdir.rstrip("/")), n, len(out_scenes)))


if __name__ == "__main__":
    main()
