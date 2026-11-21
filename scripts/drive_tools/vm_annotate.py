#!/usr/bin/env python3
"""Manual annotations of the map (Claude writes them after reviewing a day): clip summary, tags, rating, moments.

    python3 -I vm_annotate.py YYYY-MM-DD пометки.json

пометки.json: {"_day": {"label": "<place> — <what happened>", "summary": "…"},
               "DJI_…0012_D.MP4": {"summary": "…", "tags": [...], "rating": "★", "moments": [{"t": 54, "what": "…"}], "note": "…"}}
Ratings: ★ — use (story, best shots), ◐ — reserve (cutaways, may come in handy), ○ — can be deleted (faulty, empty, duplicate).
Writes into _карта/<day>/клипы.json (video_map.py keeps these fields on rebuild) and rebuilds the search index.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(os.path.dirname(HERE), "_карта")


def main(day, path):
    d = next((x for x in sorted(os.listdir(MAP)) if x.startswith(day)), None)
    cj = os.path.join(MAP, d, "клипы.json")
    doc = json.load(open(cj, encoding="utf-8"))
    ann = json.load(open(path, encoding="utf-8"))
    if "_day" in ann:
        doc["day_note"] = ann["_day"]
    n = 0
    for c in doc["clips"]:
        a = ann.get(c["file"])
        if a:
            c.update({k: v for k, v in a.items() if k in ("summary", "tags", "rating", "moments", "note")})
            n += 1
    missing = [k for k in ann if k != "_day" and k not in {c["file"] for c in doc["clips"]}]
    tmp = cj + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, cj)
    print("annotations: %d%s" % (n, ("; no such clips: %s" % missing) if missing else ""))
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "video_map.py"), "--index"])


if __name__ == "__main__":
    main(*sys.argv[1:3])
