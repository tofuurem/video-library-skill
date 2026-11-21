# Research behind the video map

Why each layer of the map is what it is. Numbers from outside benchmarks are as cited in the linked sources; local measurements are from a pilot on Apple Silicon (a 4K DJI library on an exFAT SSD) and are noted as such.

## Speech: GigaAM v3 + Silero VAD
- **Choice:** GigaAM v3 (Sber), model `gigaam-v3-e2e-rnnt` through `onnx-asr` (punctuation and normalisation: numbers as digits), CPU only. Silero VAD cuts speech out first; only speech is recognised.
- **Why GigaAM:** independent Russian benchmarks put it first among open models — about 3–4 % WER, Whisper large-v3 about 5 %, Parakeet about 10 % ([typewhisper-benchmark PR 5](https://github.com/TypeWhisper/typewhisper-benchmark/pull/5), [stt-ru-benchmark](https://github.com/vakovalskii/stt-ru-benchmark)). Local check: on 90 s of monologue GigaAM was noticeably more accurate than Parakeet. ≈ 20× realtime, ≈ 1.5 GB for GigaAM + VAD; pilot peak 2.6 GB.
- **Why VAD first:** Whisper invents text on stretches without speech — it loops a word in long pauses and writes subtitle credits on silent clips. A person who indexed 669 GB of GoPro footage named hallucinations on silence as the worst problem ([write-up](https://iliashaddad.com/blog/i-indexed-669-gb-of-my-gopro-videos-using-my-m1-max-computer)). Travel footage is full of wind and engine noise.
- **CoreML EP fails** on parts of GigaAM's graph → `CPUExecutionProvider`.
- Weights: GigaAM v3 ONNX (`istupakov/gigaam-v3-onnx`, ≈ 1 GB) and Silero VAD (≈ 2 MB) from Hugging Face on first use; official package: `salute-developers/GigaAM` on GitHub.

## Frames: camera keyframes, scenes, the sharpest frame
- **Not «one frame per second».** A fixed rate picks blurred frames; the common approach is dense small frames scored for sharpness, brightness and motion, a split into scenes, and the sharpest representative frame per scene ([sharp-frames-python](https://github.com/reflct/sharp-frames-python), [arXiv 2506.00667](https://arxiv.org/html/2506.00667v1)).
- **Keyframes only:** DJI writes 1–2 keyframes per second; `ffmpeg -skip_frame nokey` reads them in one pass without full decoding (full decoding is ~6× slower). 384 px wide, with the clip's LUT (LOG footage without a LUT is grey and models see it worse). Measured: an 8-min 4K clip (7.9 GB) in 24 s, bound by disk reads (~325 MB/s).
- **Scenes:** Apple Vision feature prints; a new scene when the print drifts from the scene's first frame by more than 0.95 (calibration: neighbouring frames inside a scene ~0.45, a change of place ~1.1–1.2), scenes ≥ 3 s, longer than 40 s split evenly (the describer needs different parts of a long take). Cut detectors like TransNetV2 are made for edited video; raw takes have no cuts.
- **Best frame:** 0.75 × normalised sharpness (variance of the Laplacian) + 0.25 × exposure (mean brightness 45–210 is fine), plus two spare frames from the start and end of the scene for the describer.
- **Vision on best frames:** labels (≥ 0.3), OCR ru/en, people, faces, aesthetics. Free and fast (~50 ms per frame for all requests), but the labels are coarse — for filters, not for the story.

## Sounds: Apple SoundAnalysis
Built-in classifier (303 classes), 3-s windows without overlap, compiled from `sound_events.swift`. Shows where wind ruined the microphone, engine, sea, music. 4 minutes of audio in 0.4 s.

## Scene descriptions: Qwen3-VL-8B, local
- **Choice:** Qwen3-VL-8B-Instruct, 4-bit, through `mlx-vlm` (model folder `~/.cache/reel-studio/models/qwen3-vl-8b-4bit`, ≈ 5.4 GB; `mlx-community/Qwen3-VL-8B-Instruct-4bit`). The most common recommendation for local video understanding on Apple Silicon ([mlx-vlm](https://github.com/Blaizzy/mlx-vlm)); free, nothing leaves the computer, answers in Russian.
- **Input:** chunks ≤ 150 s; 3–5 best frames of the chunk (448 px) + its transcript + OCR; strict JSON answer (`что, где, кадр, теги, годится`).
- **Cost:** pilot peak 7.5 GB, 5–6 s per chunk; MLX limits 10 GB memory / 1 GB cache inside, the guard's ceiling 11 GB outside.
- **Limits:** wrong in details (a motorbike ride becomes a cyclist). So the day — story, ratings, best moments, place — is Claude's job, reading transcripts, descriptions and sheets.

## Ruled out
- **Apple Foundation Models** (the on-device model can look at images): not available on every Mac, and no Russian.
- **Cloud (Gemini):** watches whole videos with sound, about $0.2–0.4 per hour of video ([estimate](https://mixpeek.com/guides/how-many-tokens-is-an-hour-of-video)), but means sending personal videos to a cloud — only if the user asks for it.
- **Ready-made tools:** [Edit Mind](https://www.producthunt.com/p/edit-mind-3/edit-mind-4) (open, local), Jumper, search in [Premiere](https://community.adobe.com/announcements-732/now-released-search-panel-finds-the-shot-faster-with-visual-search-311756) and DaVinci Resolve 21 find shots inside an editor. They leave no memory on the drive that survives deleting the sources and give no «what can be deleted» ratings; Edit Mind also samples a fixed frame per second and spends about 4.4 machine-hours per hour of video. Resolve's search may still help while editing.

## Memory guard
A Mac with unified memory can freeze when a model takes all of it. `mem_guard.py` polls every 0.5 s: the command's process-tree footprint (macOS `footprint`, includes GPU memory) and the Mac's available memory from `kern.memorystatus_level` (`vm_stat` free + inactive underestimates it several times while weights load, because the file cache is reclaimable). Above the ceiling or below the reserve it kills the process group and exits 137. Ceilings used: Qwen `--max-gb 11 --min-free-gb 4`, speech `--max-gb 4 --min-free-gb 3`. reel-studio ships the same file.

## Speed and size (pilot)
147 clips, ~5 h of video, 214 GB → ~30 min of machine time for all stages, bound by disk reads and Qwen. A 4 TB library (~2200 clips) is ~4–5 h of machine time; the map itself takes ~1–2 GB per TB of footage (data is grouped per day because every small file costs a whole cluster on exFAT).
