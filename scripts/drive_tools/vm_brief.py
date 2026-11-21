#!/usr/bin/env python3
"""A day's summary from the map — for reading (by a person, or by Claude before writing the day description).

    python3 -I vm_brief.py YYYY-MM-DD [--speech 400] [--clip DJI_…]

Per clip: time, camera, duration, speech/wind, segment descriptions (Qwen3-VL), transcript (cut to --speech characters
per clip; 0 — in full), path to the frame sheet. Writes nothing.
"""
import argparse
import json
import os

MAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_карта")


def mmss(t):
    t = float(t or 0)
    return "%d:%02d" % (t // 60, t % 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--speech", type=int, default=400)
    ap.add_argument("--clip")
    a = ap.parse_args()
    d = next((x for x in sorted(os.listdir(MAP)) if x.startswith(a.day)), None)
    if not d:
        raise SystemExit("no map for day " + a.day)
    doc = json.load(open(os.path.join(MAP, d, "клипы.json"), encoding="utf-8"))
    tot = sum(c["duration"] for c in doc["clips"])
    print("# %s — %d clips, %.0f min, speech %.0f min" % (d, len(doc["clips"]), tot / 60, sum(c["speech_sec"] for c in doc["clips"]) / 60))
    for c in doc["clips"]:
        if a.clip and a.clip not in c["file"]:
            continue
        print("\n## %s  %s  %s  %s, %.1f GB | speech %.0f s, wind %.0f s, dark %s | %d scenes | sheet: %s" % (
            c["time"], c["file"], c["camera"], mmss(c["duration"]), c["size_gb"], c["speech_sec"], c.get("wind_sec", 0),
            c.get("dark_share"), len(c["scenes"]), c.get("sheet")))
        for v in c.get("described", []):
            print("  [%s–%s] %s | %s | %s" % (mmss(v.get("s")), mmss(v.get("e")), v.get("что", ""), v.get("где", ""),
                                            ", ".join(v.get("теги", [])) if isinstance(v.get("теги"), list) else v.get("теги", "")))
        ocr = sorted({t for s in c["scenes"] for t in s["vision"].get("text", [])})
        if ocr:
            print("  text in frame:", "; ".join(ocr[:8]))
        text = " ".join("[%s] %s" % (mmss(x["s"]), x["text"]) for x in c["speech"])
        if text:
            print("  speech:", text if a.speech == 0 else text[: a.speech] + ("…" if len(text) > a.speech else ""))


if __name__ == "__main__":
    main()
