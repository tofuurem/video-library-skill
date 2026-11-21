#!/usr/bin/env python3
"""Scene descriptions with a local Qwen3-VL (MLX). Run ONLY under the memory guard:

    python3 -I mem_guard.py --max-gb 12 --min-free-gb 4 -- \\
        ~/.cache/reel-studio/vlmvenv/bin/python -I vlm_describe.py jobs.json answers.jsonl [--model DIR]

jobs.json: [{"id": "...", "images": ["frame1.jpg", ...], "context": "what is said in the scene, camera, time"}, ...]
answers.jsonl: one line per job {"id", "text", "sec", "peak_gb"}; finished ids are skipped (a run can be continued).
The model loads once. MLX limits: memory 10 GB, cache 1 GB; pictures are shrunk to 448 px on the long side.
"""
import argparse
import json
import os
import sys
import time

DEFAULT_MODEL = os.path.expanduser("~/.cache/reel-studio/models/qwen3-vl-8b-4bit")
PROMPT = (
    "Это кадры одной сцены из личного видео (влог автора), по порядку времени. "
    "{context}\n"
    "Опиши сцену по-русски для каталога видео. Ответь строго JSON без пояснений:\n"
    '{{"что": "1–2 предложения: что происходит, что делают люди", '
    '"где": "место коротко (улица, салон мотоциклов, лодка, кафе…)", '
    '"кадр": "крупность и ракурс: селфи / от первого лица / общий план / деталь", '
    '"теги": ["3–8 коротких тегов"], '
    '"годится": "да / нет — можно ли взять кадр в ролик (резкий, нормально видно)"}}'
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("out")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=260)
    ap.add_argument("--mem-gb", type=float, default=10.0)
    a = ap.parse_args()

    import mlx.core as mx
    mx.set_memory_limit(int(a.mem_gb * 2**30))
    mx.set_cache_limit(1 * 2**30)
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from PIL import Image

    jobs = json.load(open(a.jobs, encoding="utf-8"))
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                pass
    jobs = [j for j in jobs if j["id"] not in done]
    if not jobs:
        print("VLM_DONE (nothing to do)")
        return
    t0 = time.time()
    model, processor = load(a.model)
    print("model loaded in %.1f s, memory %.1f GB" % (time.time() - t0, mx.get_active_memory() / 2**30), flush=True)
    tmpdir = os.path.join(os.path.dirname(os.path.abspath(a.out)), ".vlm_tmp")
    os.makedirs(tmpdir, exist_ok=True)
    with open(a.out, "a", encoding="utf-8") as f:
        for n, j in enumerate(jobs, 1):
            imgs = []
            for k, p in enumerate(j["images"]):
                im = Image.open(p).convert("RGB")
                im.thumbnail((448, 448))
                q = os.path.join(tmpdir, "%d.jpg" % k)
                im.save(q, quality=90)
                imgs.append(q)
            prompt = apply_chat_template(processor, model.config, PROMPT.format(context=j.get("context", "")),
                                         num_images=len(imgs))
            mx.reset_peak_memory()
            t = time.time()
            r = generate(model, processor, prompt, imgs, max_tokens=a.max_tokens, temperature=0.0, verbose=False)
            text = getattr(r, "text", r)
            rec = {"id": j["id"], "text": text.strip(), "sec": round(time.time() - t, 1),
                   "peak_gb": round(mx.get_peak_memory() / 2**30, 2)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            mx.clear_cache()
            print("%d/%d %s — %.1f s, peak %.1f GB" % (n, len(jobs), j["id"], rec["sec"], rec["peak_gb"]), flush=True)
    print("VLM_DONE")


if __name__ == "__main__":
    main()
