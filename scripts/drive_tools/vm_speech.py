#!/usr/bin/env python3
"""Video map, stage "speech": Silero VAD separates speech, GigaAM v3 (the best open model for Russian) recognises it.

    python3 -I mem_guard.py --max-gb 4 --min-free-gb 3 -- \\
        ~/.cache/reel-studio/gigvenv/bin/python -I vm_speech.py <work/clip1> [<work/clip2> …]

Reads <clip>/audio.wav (16 kHz mono), writes <clip>/speech.json:
  {"model": …, "speech_sec": N, "segments": [{"s": 12.3, "e": 17.8, "text": "…"}]}
Only what the VAD took for speech is recognised: on wind, engine noise and silence the model does not invent text.
Models load once for the whole list. Finished speech.json files are skipped.
"""
import json
import os
import sys
import time

MODEL = "gigaam-v3-e2e-rnnt"     # with punctuation and normalisation (numbers as digits)


def main(dirs):
    import onnx_asr
    todo = [d for d in dirs if os.path.exists(os.path.join(d, "audio.wav")) and not os.path.exists(os.path.join(d, "speech.json"))]
    if not todo:
        print("SPEECH_DONE (nothing to do)")
        return
    t0 = time.time()
    cpu = ["CPUExecutionProvider"]          # CoreML fails on part of the GigaAM graph
    vad = onnx_asr.load_vad("silero", providers=cpu)
    model = onnx_asr.load_model(MODEL, providers=cpu).with_vad(vad, min_silence_duration_ms=500, max_speech_duration_s=25)
    print("models loaded in %.1f s" % (time.time() - t0), flush=True)
    for n, d in enumerate(todo, 1):
        t = time.time()
        segs = []
        for r in model.recognize(os.path.join(d, "audio.wav"), language="ru"):
            text = (r.text or "").strip()
            if text:
                segs.append({"s": round(float(r.start), 2), "e": round(float(r.end), 2), "text": text})
        out = {"model": MODEL + " + silero-vad", "speech_sec": round(sum(x["e"] - x["s"] for x in segs), 1), "segments": segs}
        tmp = os.path.join(d, "speech.json.tmp")
        json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "speech.json"))
        print("%d/%d %s: speech %.0f s, %d segments, %.1f s" % (n, len(todo), os.path.basename(d.rstrip("/")),
                                                             out["speech_sec"], len(segs), time.time() - t), flush=True)
    print("SPEECH_DONE")


if __name__ == "__main__":
    main(sys.argv[1:])
