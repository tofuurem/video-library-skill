# Formats

Everything a drive holds, field by field. User-facing names are Russian and stay as they are.

## Contents
1. Drive layout and folder names
2. Inbox hints and the labels file
3. `Source Video/_catalog.csv` (per drive)
4. `ВСЕ ДИСКИ — каталог.csv` and `ВСЕ ДИСКИ.md` (all drives)
5. Logs, backups, reports
6. Video Archive project: `final/`, `project/`, `sources.txt`, NOTES.md «Архив»
7. Video map: `клипы.json`, `пометки.json`, `день.md`, `листы/`, `поиск.sqlite`, work files

---

## 1. Drive layout and folder names

```
<Диск>/
├ CLAUDE.md                      entry point for Claude (template: assets/templates/CLAUDE.md)
├ ВСЕ ДИСКИ.md, ВСЕ ДИСКИ — каталог.csv    written by catalog_all.py to every connected drive
├ _docs/                         guides for the user: КАК ВЕСТИ ПРОЕКТЫ.md, КАРТА ВИДЕО.md (both from templates),
│ │                              ИНВЕНТАРИЗАЦИЯ.md (the look step), ИДЕИ РОЛИКОВ.md (ideas from the map),
│ │                              (ПЛАН ПЕРЕЕЗДА.md while a migration runs)
│ └ история/                     finished migration plans: ПЛАН ПЕРЕЕЗДА.md + ПЛАН ПЕРЕЕЗДА — список файлов.tsv
├ Source Video/
│ ├ _inbox/                      new footage goes here → Разложить.command; КАК ПОЛЬЗОВАТЬСЯ.txt
│ │ └ _проверить/                what the sorter could not place + ПРИЧИНЫ.txt
│ ├ _tools/                      the tools (same copy on every drive) + reference/migrate_*.py
│ ├ _logs/                       journals, backups, reports — undo goes through them
│ ├ _дубликаты/                  verified same-drive copies waiting for deletion (exists only during a cleanup)
│ ├ _карта/                      video map (section 7)
│ ├ _catalog.csv                 per-drive catalog (section 3)
│ └ ГГГГ/ГГГГ-ММ месяц/ГГГГ-ММ-ДД место/Камера_Профиль/<original file name>
├ Video Production/ГГГГ-ММ название/     projects in work (reel-studio creates them here)
└ Video Archive/ГГГГ-ММ название/{final, project, sources.txt}
```

The library part of the root is only `CLAUDE.md` and `ВСЕ ДИСКИ.*`. Other top-level folders that are not video (films, a podcast, a photo library) stay untouched; list them in the drive's `CLAUDE.md` as «не трогать».

- **Year** `2026`; **month** `2026-11 ноябрь` (lowercase Russian month: январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь); **day** `2026-11-09` or `2026-11-09 Лиссабон — старый город` (place, optionally ` — событие`). The sorter creates new days without a place unless a hint or `--labels` gives one; a place is added later by renaming (needs the user's yes).
- Day boundary 05:00: a clip shot at 02:30 belongs to the previous evening.
- Undated material that cannot be placed: `ГГГГ-ММ месяц/_без даты — <место>/…`.
- **Camera_Profile** = one LUT. Names produced by `sort_inbox.py`:

| Folder | Meaning |
|---|---|
| `Pocket4P_D-Log`, `Pocket4P_HLG`, `Pocket4P_Normal`, `Pocket4P_D-Log2` | Osmo Pocket 4P; D-Log2 = code 22 (rare, check the LUT) |
| `Action5Pro_D-Log-M`, `Action5Pro_HLG`, `Action5Pro_Normal` | Osmo Action 5 Pro; Normal is always 8-bit |
| `Pocket4_Normal` | Osmo Pocket 4 (10-bit but code 0; an unset clock gives year 2000) |
| `Action4_Normal` | Osmo Action 4 (`dvtm_ac203.proto`, empty profile field = Normal) |
| `Neo_Normal` | DJI Neo drone, always 8-bit |
| `Pocket3_10bit-unknown` | Osmo Pocket 3: no profile field in djmd |
| `<Cam>_10bit-unknown` | DJI 10-bit BT.709 without a readable profile — resolve before editing |
| `<Cam>_CodeNN` | unknown djmd code NN — add it to `DJI_COLOR_CODES` |
| `iPhone_Normal`, `iPhone_HDR`, `iPhone_Apple-Log` | by transfer/primaries tags (HLG/PQ → HDR, primaries 9 / BT.2020 → Apple Log); exiftool first, ffprobe `color_transfer` / `color_primaries` when exiftool sees no transfer tag |
| `<Cam>_Photo`, `Other_Photo`, `iPhone_Photo` | photos; iPhone Live Photo videos (≤ 4.5 s) sit next to their photo |
| `Screen` | screen recordings and screenshots (by file name) |
| `Other` | unknown camera (re-encoded / messenger videos) |

**10-bit BT.709 without djmd** (a re-encoded DJI file): `TEN_BIT_709_PROFILE` maps the camera to a profile — by default `Action5Pro` → `D-Log-M` (Action 5 Pro records Normal in 8-bit only); other DJI cameras go to `<Cam>_10bit-unknown`. Override per run with `sort_inbox.py --ten-bit-709 "Action5Pro=HLG"` (comma-separated `Камера=Профиль`; an empty value `--ten-bit-709=` turns the fallback off, so such clips land in `*_10bit-unknown`), or for every run from a shell with the env var `VIDEO_LIBRARY_TEN_BIT_709` (same syntax; the option wins). `Разложить.command` uses the default unless the variable is set in the environment it runs in. The run prints the mapping when it is not the default.

DJI profile codes (djmd track, first record): **0 Normal, 2 D-Log, 9 HLG, 19 D-Log M, 22 D-Log2**. Field per firmware (`DJI_COLOR_FIELD` in sort_inbox.py): `dvtm_ac204.proto` (Action 5 Pro) 2.4.1, `dvtm_ac203.proto` (Action 4) 2.4.1, `dvtm_osmo_pocket_4.proto` (Pocket 4/4P) 2.2.3.1. Pocket 4P also writes the text tag `DjiCameraColorGammaSxS` (D-Log / Rec.709 / Rec.2100 HLG / D-Log2), which wins when present. Camera name from `Encoder` (`DJI OsmoPocket4P`, `DJI OsmoAction5 Pro`, `DJI OsmoPocket4`, `DJI NEO`…) or `Model`.

## 2. Inbox hints and the labels file

- **Date hint subfolder** in `_inbox`: `ГГГГ-ММ-ДД название/…` (any depth below). Files without a trustworthy date (camera clock in year 2000, messenger videos) get that date; a new day folder gets the name as its place. A dated file whose shooting day equals the hint day also gives the hint's name to its new day (`2026-12-03 Порту/DCIM/…`).
- **Labels file** for `--labels`: one line per day, `ГГГГ-ММ-ДД<TAB>метка`, e.g. `2026-07-31	Порту`. Applies to day folders the run creates. Kept as `Source Video/_logs/labels_<drive>_<date>.tsv`.
- Messenger videos named with 13 digits (`1769011772279.MOV`) — Unix milliseconds of the save time, matches QuickTime `CreateDate` (UTC): a day hint, not a shooting time.

## 3. `Source Video/_catalog.csv` (per drive, written by sort_inbox.py)

UTF-8 with BOM. One row per file under `ГГГГ/…`; rewritten after every sorter run (rows of files that are no longer present are dropped; key = file name + size).

| Column | Content |
|---|---|
| `day` | shooting day `ГГГГ-ММ-ДД` (05:00 boundary); empty for `_без даты` |
| `time` | local time `ЧЧ:ММ:СС` |
| `folder` | Camera_Profile folder |
| `kind` | `video`, `photo`, `live`, `screen` |
| `file` | original file name |
| `duration_s`, `resolution` (`3840x2160`, rotation applied), `orientation` (`вертикальное`/`горизонтальное`), `fps`, `size_mb` | from exiftool |
| `path` | path relative to `Source Video` |
| `origin` | where the file came from (old folder / inbox path); `a | b` if it arrived twice |

`catalog_all.py` and `fix_capcut_paths.py` find a drive by this file: a drive without `_catalog.csv` is invisible to them.

## 4. All-drive catalog (written by catalog_all.py into every connected drive root)

`ВСЕ ДИСКИ — каталог.csv` (UTF-8 BOM), one row per clip/photo of every drive:
`диск, день, место, папка, тип, файл, длительность мин, разрешение, ориентация, fps, размер ГБ, битрейт Мбит/с, использован в, копия на дисках, путь`
- `место` — the day folder's label; `путь` — from the drive root (`Source Video/…`).
- `использован в` — projects joined with ` | `. Sources: `sources.txt` in Video Archive / Video Production of every drive (exact list: such projects are not scanned further); otherwise symlinks and `DJI_…` names in project texts (`.json .md .txt .ts .tsx .py .csv .tsv`); CapCut drafts (`draft_info.json`) in `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` and in every folder listed in `VIDEO_LIBRARY_CAPCUT_DRAFTS` (shown as `CapCut: <draft>`).
- `копия на дисках` — other drives holding the same name + size.
- Drives not connected keep their rows from the previous CSV.

`ВСЕ ДИСКИ.md` sections: **Главное** (totals, free space, whether backups exist) · **Диски** (size, free, Source Video / Archive / Production, other folders) · **Что где снято** (consecutive days with one place merged; clips, hours, GB, «использовано N из M») · **Проекты и сколько клипов в них вошло** · **Что можно освободить**: 1) regenerable (CapCut cache, `node_modules`, `work/tmp`, `out/prev`, `reel/public/…`), 2) same clip on several drives (= backups), 3) long unused clips ≥ 10 min with options **А** HEVC 10-bit ~40 Mbit/s (4K; 30 for ≥2K, 15 below; keeps LOG/HLG, frees ~40 %), **Б** 1080p ~12 Mbit/s «на память» (frees ~80 %), **В** delete, 4) all unused videos.

## 5. Logs, backups, reports (all in `Source Video/_logs/`)

| File | Format / meaning |
|---|---|
| `sort_<ГГГГ-ММ-ДД_ЧЧММСС>[_N].tsv` | sorter journal: `action src dst reason`; actions `move`, `dup` (→ `_дубликаты`, reason `уже есть: <path>`), `check` (→ `_inbox/_проверить`), `sidecar` (.aae/.xmp/.thm follow their file). `sort_inbox.py --undo <file>` renames everything back. `_N` suffix when two runs start in the same second |
| `migration_<drive>_<date>.tsv` | one-off migration journal, same 4 columns (compatible with `--undo`) |
| `<что>_<дата>_backup/` | copies of text files before rewriting paths, mirroring absolute paths (`backup + original path`) |
| `<что>_<дата>_count.txt` | file counts before/after a move |
| `labels_<drive>_<date>.tsv` | day labels used |
| `дубликаты_проверка_<date>.tsv` | `verify_dups.py` report: `status size_bytes copy original` (paths from the drive root), status `OK` / `NO_ORIGINAL`; exit 0 only if every copy has a byte-identical original |
| `cleanup_<date>.tsv` | deletions: `#` header with the user's words and free space before/after, then `ГБ  путь  как вернуть` |
| `capcut_paths_<stamp>_backup/` | `fix_capcut_paths.py --apply` backups (in the `_logs` of the drive the tool runs from; outside a drive `~/.cache/video-library/logs`); `--undo <folder>` restores |
| `install_<stamp>.tsv`, `tools_<stamp>_backup/` | `install_to_drive.py --apply` journal and replaced tool versions |
| `docs_<date>.tsv`, `docs_<date>_backup/` | moves/edits of the drive docs |

`_inbox/_проверить/ПРИЧИНЫ.txt`: `# <stamp>` then `relative path<TAB>reason` per file (appended each run).

## 6. Video Archive project

```
Video Archive/2026-07 Лиссабон — рилс/
├ final/        final renders and chosen covers
├ project/      everything else exactly as it was (NOTES.md, assets/, work/, reel/, covers/, out/ with prev versions)
└ sources.txt
```
The folder name is `ГГГГ-ММ название` (month of the shoot, the user's words). Moved by rename inside the drive.

**sources.txt** — Source Video clips the project used, paths from the drive root, `#` comment lines on top:
```
# Клипы из Source Video, которые использованы в проекте «2026-07 Лиссабон — рилс» (28)
# В проекте клипы названы своими номерами (последние 4 цифры имени DJI).
# 0059 в монтаж не вошёл: из него взят только звук.
# Не из Source Video (лежат в project/assets): музыка (assets/music), скрины (assets/screens).
Source Video/2026/2026-07 июль/2026-07-14 Лиссабон — старый город/Pocket4P_D-Log/DJI_20260714061350_0001_D.MP4
…
```
Clips that live on another drive are listed in a comment: `# Не на этом диске (13): /Volumes/<другой диск>/…`. For Filmora projects the list comes from the `.wfp` (a zip: `ProjectFolder/Medias/*/media.json`, field `file_name`); for CapCut from `draft_info.json` paths; for Remotion projects from `assets/camera` links and `DJI_…` names in the project texts.

**NOTES.md «Архив»** (appended to `project/NOTES.md`), bullets: what went to `final/` and `project/`; how many clips in `sources.txt`; which absolute paths were rewritten, in which files, where the backups are (logs of renders are history, not rewritten); file counts before/after, no broken links; what was freed or can be freed and how to rebuild it.

Back to work («верни в работу»): `project/` → `Video Production/ГГГГ-ММ название/`, renders from `final/` → `out/`, paths rewritten back; reinstall dependencies if they were deleted (commands in NOTES.md).

## 7. Video map

### Where
- `Source Video/_карта/<day folder name>/клипы.json` — everything about every clip of the day.
- `Source Video/_карта/<day folder name>/листы/<clip>.jpg` — up to 16 best frames (4 per row) with timecodes, LUT applied.
- `Source Video/_карта/<day folder name>/день.md` — the day description, written by Claude.
- `Source Video/_карта/поиск.sqlite` — full-text search over all days of the drive.
- Work files on the computer: `~/.cache/video-map/work/<day>/<clip>/` (`frames/*.jpg` + `frames/times.json`, `audio.wav`, `extract.json`, `frames.json`, `speech.json`, `sounds.json`), `~/.cache/video-map/work/<day>/vlm_jobs.json` and `vlm_out.jsonl`. Safe to delete; the map does not depend on them (but a re-run then redoes every stage).

### `клипы.json`
```json
{
 "day": "2026-07-14",
 "folder": "2026/2026-07 июль/2026-07-14 Лиссабон — старый город",
 "built": "2026-07-20 21:52",
 "day_note": {"label": "Лиссабон — старый город", "summary": "Утром трамвай 28 до Алфамы, …"},
 "clips": [{
   "file": "DJI_20260714130244_0012_D.MP4",
   "path": "2026/2026-07 июль/2026-07-14 Лиссабон — старый город/Pocket4P_D-Log/DJI_20260714130244_0012_D.MP4",
   "camera": "Pocket4P_D-Log", "time": "13:02:44", "duration": 538.2, "size_gb": 8.56,
   "resolution": "3840x2160", "fps": "59.94",
   "lut": "DJI OSMO Pocket 4P D-Log to Rec.709 V2.0 size33.cube",
   "speech_sec": 460.9,
   "speech": [{"s": 1.03, "e": 3.23, "text": "Итак, мы в Алфаме."}],
   "sounds": [{"s": 0, "e": 3, "label": "speech"}],
   "wind_sec": 0, "dark_share": 0.0, "motion": 2.8,
   "scenes": [{"s": 0.0, "e": 37.04, "key": "00050.jpg", "key_t": 24.52, "sharp": 0.6, "bright": 120, "motion": 5.0,
               "vision": {"labels": [["adult", 0.93], ["people", 0.93], ["street", 0.41]], "text": [], "people": 1, "faces": 1, "face_size": 0.2,
                          "aesthetic": 0.44, "utility": false}}],
   "described": [{"s": 0.0, "e": 134.6, "что": "Мужчина на узкой улице говорит в камеру, за ним трамвай, …",
                  "где": "улица", "кадр": "селфи", "теги": ["трамвай"], "годится": "да"}],
   "sheet": "листы/DJI_20260714130244_0012_D.jpg",
   "summary": "Прогулка по Алфаме с рассказом в камеру, 9 минут, несколько дублей …",
   "tags": ["Алфама", "трамвай"], "rating": "★",
   "moments": [{"t": 54, "what": "чистый старт: «Итак, мы в Алфаме — самом старом районе.»"}],
   "note": "Фразы «склейка заново» и «Да ладно, заново» — пометки для монтажа, брать следующий дубль."
 }]
}
```
(Lists shortened.)

Machine fields (video_map.py): `file, path` (from Source Video), `camera, time, duration` (s), `size_gb, resolution, fps` (from `_catalog.csv`), `lut` (cube name or null), `speech_sec`, `speech[]` (GigaAM segments, s/e in seconds), `sounds[]` (runs of the same top SoundAnalysis class, 3-s windows; `wind*` labels sum into `wind_sec`), `dark_share` (share of frames with mean brightness < 35), `motion` (mean frame difference), `scenes[]` (`key` = best frame file in the work folder, `key_t` its time, `sharp` 0–1 within the clip, `bright` 0–255, `vision`: labels with confidence ≥ 0.3, OCR text ru/en ≥ 3 chars, people, faces, `face_size` = tallest face as a share of frame height (> 0.3 ≈ talking head / selfie), `aesthetic`/`utility` when macOS provides them), `described[]` (Qwen3-VL per chunk ≤ 150 s: `что, где, кадр, теги, годится`; a non-JSON answer lands in `что`), `sheet`, `engines` (only when a clip was built with engines other than Apple's: `{capability: engine}` for feature_print, labels, ocr, people, faces, aesthetics, sound_events — scenes and labels of different engines are not comparable). `frames.json` in the work folder always records `engine` (feature prints), `threshold` and `engines`.

Claude fields (kept across rebuilds): `summary`, `tags`, `rating`, `moments[{t, what}]`, `note`; day level `day_note{label, summary}` (written by vm_annotate.py — a later `assemble` does not carry it over, see pitfalls).

Ratings: **★ брать** (story, best shots) · **◐ запас** (cutaways, may come in handy) · **○ можно удалить** (broken, empty, duplicate take).

### `пометки.json` (input of `vm_annotate.py <day> пометки.json`)
```json
{"_day": {"label": "Лиссабон — старый город", "summary": "…"},
 "DJI_20260714131332_0013_D.MP4": {"summary": "Закат на смотровой площадке", "tags": ["закат", "смотровая"],
                                   "rating": "★", "moments": [{"t": 12, "what": "солнце садится за мост, панорама"}],
                                   "note": ""}}
```
Only `summary, tags, rating, moments, note` are taken per clip; unknown file names are reported. The script rebuilds `поиск.sqlite` afterwards.

### `день.md` template
Russian, plain, for the user. Fill from `vm_brief.py <day> --speech 0`, the sheets in `листы/` and `ВСЕ ДИСКИ — каталог.csv` (column «использован в»).
```markdown
# <14 июля 2026> — <место, событие>

Карта собрана <дата> (`Source Video/_tools/video_map.py`), описание и оценки — Claude по расшифровке, описаниям сцен и листам кадров.
Данные по каждому клипу: `клипы.json`; листы лучших кадров: `листы/`.

**Итог дня.** <3–5 предложений: что произошло по порядку.>

<N клипов <камера (профиль)>, <M> минут, из них <K> минут речи.>

## Хронология

Оценки: ★ брать · ◐ запас · ○ можно удалить.

| Время | Клип | Длина | Оценка | Что |
|---|---|---|---|---|
| 13:02 | `…0012` | 8:58 | ★ | <что в клипе, одной строкой> |

## Лучшие моменты

| Клип | Время | Что |
|---|---|---|
| `0012` | 0:54 | <цитата «…» или что видно> |

<Пометки для монтажа: например, фразы «склейка заново» — брать следующий дубль.>

## Уже использовано

**«<проект>»** (<в архиве / в работе>): `0019`, `0020` (<что>), …

## Удалено

- `<файл>` (<что было>) удалён <дата> <кем, почему>.

## Что можно удалить

<Клипы «○» с причиной и объёмом — или «Ничего: в дне нет клипов «○».»>
```
Time and length columns come from `клипы.json`; clip ids are the last four digits of the DJI name. Quotes are the speaker's words from the transcript (fix obvious ASR slips only when sure).

### `поиск.sqlite`
SQLite FTS5 table `t(day, file, s, e, kind, text, path)`, tokenizer `unicode61`. `kind`: `речь` (speech segments), `кадры` (Qwen descriptions), `в кадре` (Vision labels + OCR per scene), `описание` (Claude's summary + tags), `момент` (Claude's moments). Query syntax is FTS5: words are AND-ed, `OR` between alternatives, `слово*` for any ending (Russian needs it: `трамва*` finds «трамвай», «трамваем»). Opened read-only with `immutable=1`, so it works on exFAT; it is built on the computer and copied (SQLite cannot write on exFAT).
