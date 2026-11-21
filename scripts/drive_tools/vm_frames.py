#!/usr/bin/env python3
"""Video map, stage "frames": the clip's scenes and the best frame of each scene (Apple Vision + numpy).

    ~/.cache/reel-studio/venv/bin/python -I vm_frames.py <clip folder in work> [--sheet sheet.jpg] [--calib]

Input: work/<clip>/frames/*.jpg (keyframes with the LUT, 384 px) and frames/times.json (time of every frame, s).
1. Every frame: sharpness (variance of the Laplacian), brightness, difference to the previous one (motion), Vision feature print.
2. Scenes: a new scene starts when the print drifts from the scene's start beyond the threshold and the scene lasts
   ≥ MIN_SCENE s; a scene longer than MAX_SCENE s is split evenly (the description model needs different parts of a long take).
3. In every scene the best frame: sharp and normally exposed (not dark, not blown out) + 2 spares from the start
   and the end of the scene — the description model gets them.
4. Vision on the best frames: labels (≥ 0.3), text (ru/en), people, faces, aesthetics.
→ work/<clip>/frames.json; --sheet: a sheet of up to 16 best frames with timecodes (on the drive, next to the map).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MIN_SCENE = 3.0
MAX_SCENE = 40.0
FP_THRESHOLD = 0.95      # calibrated with --calib: neighbouring frames within a scene ~0.45, a change of place ~1.1–1.2
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


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


def fp_dist(a, b):
    if a is None or b is None:
        return 0.0
    return float(np.linalg.norm(a - b))


def vision_details(path):
    import Vision
    from Foundation import NSURL
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
    cls = Vision.VNClassifyImageRequest.alloc().init()
    ocr = Vision.VNRecognizeTextRequest.alloc().init()
    ocr.setRecognitionLanguages_(["ru-RU", "en-US"])
    ocr.setRecognitionLevel_(0)
    hum = Vision.VNDetectHumanRectanglesRequest.alloc().init()
    face = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    reqs = [cls, ocr, hum, face]
    aes = Vision.VNCalculateImageAestheticsScoresRequest.alloc().init() if hasattr(Vision, "VNCalculateImageAestheticsScoresRequest") else None
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
    a = ap.parse_args()
    fdir = os.path.join(a.clipdir, "frames")
    times = json.load(open(os.path.join(fdir, "times.json")))
    files = sorted(f for f in os.listdir(fdir) if f.endswith(".jpg"))
    n = min(len(files), len(times))
    files, times = files[:n], times[:n]
    if n == 0:
        json.dump({"frames": 0, "scenes": []}, open(os.path.join(a.clipdir, "frames.json"), "w"))
        return
    sharp, bright, motion, prints = [], [], [], []
    prev = None
    for f in files:
        g = gray(os.path.join(fdir, f))
        sharp.append(sharpness(g))
        bright.append(float(g.mean()))
        motion.append(float(np.abs(g - prev).mean()) if prev is not None and prev.shape == g.shape else 0.0)
        prev = g
        prints.append(vision_print(os.path.join(fdir, f)))
    step = [fp_dist(prints[i - 1], prints[i]) for i in range(1, n)]
    if a.calib:
        q = np.percentile(step, [50, 75, 90, 95, 99]) if step else []
        print("neighbouring-frame step: median/75/90/95/99 %%:", [round(float(x), 3) for x in q])
        return
    # scenes
    bounds = [0]
    ref = 0
    for i in range(1, n):
        if times[i] - times[bounds[-1]] >= MIN_SCENE and fp_dist(prints[ref], prints[i]) > FP_THRESHOLD:
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
            "vision": vision_details(os.path.join(fdir, files[best])),
        })
    res = {"frames": n, "fps": round(n / max(times[-1] - times[0], 1e-6), 2) if n > 1 else 0,
           "dark_share": round(float(np.mean(np.array(bright) < 35)), 2),
           "motion_mean": round(float(np.mean(motion)), 1), "scenes": out_scenes}
    json.dump(res, open(os.path.join(a.clipdir, "frames.json"), "w"), ensure_ascii=False)
    if a.sheet:
        keys = out_scenes if len(out_scenes) <= 16 else [out_scenes[round(i * (len(out_scenes) - 1) / 15)] for i in range(16)]
        tiles = []
        font = ImageFont.truetype(FONT, 18)
        for sc in keys:
            im = Image.open(os.path.join(fdir, sc["key"])).convert("RGB")
            d = ImageDraw.Draw(im)
            t = sc["key_t"]
            lab = "%d:%02d" % (t // 60, t % 60)
            d.rectangle([0, 0, 12 + 11 * len(lab), 24], fill=(0, 0, 0))
            d.text((5, 2), lab, fill=(255, 220, 0), font=font)
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
