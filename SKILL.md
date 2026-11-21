---
name: video-library
description: "Keeps raw camera footage on external drives (any number, any names) in one structure on macOS: sorts clips into Source Video/year/month/day place/Camera_Profile (05:00 day boundary, colour profile read from the file, names never change), migrates a messy drive (look → agree → rename-only moves → verify → delete after a yes), checks duplicates byte by byte, builds the all-drive catalog ВСЕ ДИСКИ (what was shot where, which clips are in which project, what can be freed), fixes CapCut paths after moves, archives finished projects, and builds and searches a video map (speech, scenes, best frames, ★◐○ ratings, a day summary). Use whenever the user says разложить / раскидать по папкам, новый диск, разбери диск, наведи порядок в видео, inbox, каталог всех дисков, что где снято, карта видео, найди момент где я…, что можно удалить, освободить место, дубликаты, архивируем, верни в работу — or sort my footage, organize my drives, find the clip where… Making the video itself is reel-studio's job."
---
# Video Library

You keep the user's raw footage on their external drives in one structure, know what every clip contains, and say what can be freed — without ever losing a clip. Making a reel or vlog is reel-studio's job; this skill is the library around it: where sources live, how new footage and new drives get in, how finished projects leave for the archive, how to find a moment.

Talk to the user in their language; on-drive names (folders, `ВСЕ ДИСКИ`, `_карта`, `день.md`) are Russian and stay as they are — they are the library's format. `$S` below is this skill's `scripts/` folder.

## 0. Start
- **Platform.** `python3 -I $S/deps.py` — macOS (Apple Silicon: everything; Intel: no scene descriptions) or not (Linux / Windows: only `sort_inbox.py` with explicit paths and `verify_dups.py`; say so and stop for the rest). Missing tools → `deps.py --install`; the video map needs `--with map` (installs reel-studio and its environments) — ask before anything large downloads.
- **Drives.** `ls /Volumes`, `diskutil list external` (attached but not mounted → `diskutil mount diskNsM`). Drives can have any name, including a trailing space: always quote paths, never rename a volume (projects and CapCut drafts hold absolute paths to it). A drive belongs to the library when it has `Source Video/_catalog.csv`.
- Read `<drive>/CLAUDE.md` first when it exists: it is the drive's entry point and holds drive-specific facts (cameras, folders not to touch, the user's decisions).
- `python3 -I -B $S/selfcheck.py` — read-only: is the skill intact, which drives have outdated or missing tools, the platform report.
- **Where the tools run.** Every library drive carries the same tool set in `Source Video/_tools/`; this skill's `scripts/drive_tools/` is the master copy, deployed by `$S/install_to_drive.py`. Run the drive's copy: `python3 -I "/Volumes/<drive>/Source Video/_tools/<tool>"`. `video_map.py`, `vm_brief.py`, `vm_search.py`, `vm_annotate.py` find `_карта` next to themselves and must run from a drive; `sort_inbox.py` from anywhere else only with explicit `--root` and `--inbox`. The others take paths or scan `/Volumes` and work from anywhere.

## 1. The structure (identical on every drive)
```
<Drive>/
├ CLAUDE.md, ВСЕ ДИСКИ.md, ВСЕ ДИСКИ — каталог.csv     (the library part of the root)
├ _docs/ (КАК ВЕСТИ ПРОЕКТЫ.md …) └ история/ (finished migration plans)
├ Source Video/ ├ _inbox/ (Разложить.command, КАК ПОЛЬЗОВАТЬСЯ.txt) ├ _tools/ ├ _logs/ ├ _карта/ ├ _catalog.csv
│               └ 2026/2026-07 июль/2026-07-14 Лиссабон — старый город/Pocket4P_D-Log/DJI_….MP4
├ Video Production/ГГГГ-ММ название/        projects in work
└ Video Archive/ГГГГ-ММ название/{final, project, sources.txt}
```
- Year → month → **shooting day**; the place (and event) goes into the day folder's name. **A day starts at 05:00** — a night party stays in its evening.
- Inside a day **one folder per camera + profile = one LUT** (`Pocket4P_D-Log`, `Action5Pro_D-Log-M`, `iPhone_HDR`, `Screen`, `Other`…). The profile is read from the file (DJI `djmd` codes 0 Normal, 2 D-Log, 9 HLG, 19 D-Log M, 22 D-Log2; iPhone colour tags), never guessed by eye. Folder table and codes: `references/formats.md` §1.
- **File names never change.** Source Video holds camera files only — no `NOTES.md`, `assets/`, `work/` there, even if the session was opened in a day folder. Screens, FIT files, music go into a project's `assets/`.
- Projects live in `Video Production/ГГГГ-ММ название` (reel-studio creates them there when the material is on a library drive) and take clips by path, never by copy.
- Other top-level folders (films, photos, a podcast) are not touched; the drive's `CLAUDE.md` lists them.

## 2. Safety rules — why they exist
- **Only renames inside one drive.** Instant, no space needed, `._*` follow by themselves, every step goes into a journal in `Source Video/_logs/` that `--undo` can replay. A move between drives is a copy + delete: never do it as a "move".
- **Show the plan, wait for a yes** before renaming day or camera folders or moving any source. The user decides day places, which projects are finished, which camera gets which LUT.
- **Deleting is a separate, explicit yes**, always with full absolute paths (Claude's safety check reads relative `rm` paths against the drive root and blocks `rm` of top-level drive folders — leave an empty top-level shell to the user: Finder → Trash or `rm -rf "/Volumes/…"`). `node_modules` and other regenerable things need their own confirmation. Log every deletion (`_logs/cleanup_<date>.tsv`: size, path, how to get it back).
- **Same-drive duplicates only.** A copy on another drive is a backup, not waste. Before deleting `_дубликаты` re-run `verify_dups.py`; delete only when every copy matched and none is without an original.
- **Clips used in a project are never deletion candidates** — they rebuild the video.
- **Before editing any text file** (paths in projects, drafts, docs) copy it to `Source Video/_logs/<что>_<дата>_backup/`. Render logs are history: never rewrite them.
- **`._*` on exFAT is normal**: never count, move or delete them. Count files without `._*` and `node_modules`.
- **Do not recompress or shrink footage** unless the user brings it up: the options in `ВСЕ ДИСКИ.md` are a menu, not a plan.
- Every heavy local model runs under `mem_guard.py` (section 6).

## 3. A new drive: look → agree → move → verify → delete
Follow `references/process.md` §2; the traps are in `references/pitfalls.md`.
1. **Look (read-only).** Size, free space, file system; folders with sizes and `node_modules` separately; cameras and profiles; undated files; projects (Remotion, CapCut, Filmora); symlinks and absolute paths in project files; **references to this drive from other drives and the computer** (grep `/Volumes/<drive>/` in the CapCut drafts and other drives' projects). Dry-run the sorter on every old folder — the only write allowed here is an empty `<drive>/Source Video` the sorter needs (say so):
   `python3 -I $S/drive_tools/sort_inbox.py --root "/Volumes/<drive>/Source Video" --inbox "/Volumes/<drive>/<old folder>" --dry-run --plan-out "<scratchpad>/план_<folder>.tsv"`
   Look for `Other`, `*_10bit-unknown`, `*_CodeNN`, «нет даты». Day places: camera time zone, phone geotags, old folder names, one frame per day; ask about the doubtful ones.
2. **Agree.** Day places, projects in work vs finished, new cameras and LUTs, same-drive copies (candidate = same name + size, then the whole file byte by byte). Write `_docs/ПЛАН ПЕРЕЕЗДА.md` + `_docs/ПЛАН ПЕРЕЕЗДА — список файлов.tsv` (every file «откуда → куда»). Nothing moves before a yes.
3. **Move (renames only).**
   - `python3 -I $S/install_to_drive.py "/Volumes/<drive>"` (dry run) → `--apply`: skeleton, tools, `Разложить.command`, `КАК ПОЛЬЗОВАТЬСЯ.txt`, and `CLAUDE.md` / `_docs/КАК ВЕСТИ ПРОЕКТЫ.md` from templates where none exist. Then add drive-specific facts to that `CLAUDE.md`.
   - Sorter from the drive's own `_tools`, **per subfolder that holds clips** (it removes inbox folders it empties), with `--labels <file>` (`ГГГГ-ММ-ДД<TAB>место`) and date-hint subfolders for undated clips.
   - Projects: finished → `Video Archive/ГГГГ-ММ имя/{final, project, sources.txt}` + NOTES «Архив»; in work → `Video Production/`.
   - Rewrite symlinks and absolute paths (backup first, apply the path map until nothing changes), then `fix_capcut_paths.py` dry → `--apply` with CapCut closed and all drives connected.
   - Steps the tools do not cover: a one-off script with plan / `--apply` / `--undo` / journal (`references/process.md` §6).
4. **Verify.** Counts before/after match; every JSON parses; no old paths outside logs; no new broken links; `_inbox/_проверить` empty or explained; `catalog_all.py` rebuilt. Report numbers.
5. **Delete** — only after a separate yes, per section 2. Then move the plan to `_docs/история/` with a status line and rebuild the catalog.

## 4. New footage (inbox)
The user drops a card / phone export into `Source Video/_inbox` and double-clicks `Разложить.command` (it shows the plan and asks). From Claude: `python3 -I "/Volumes/<drive>/Source Video/_tools/sort_inbox.py" --dry-run`, then without it (`--yes` when there is no TTY). Afterwards: check `_inbox/_проверить/ПРИЧИНЫ.txt` and any `Other` / `*_10bit-unknown` / `*_CodeNN` folder (resolve the profile before editing — it decides the LUT); propose a place for new day folders (renaming = yes); rebuild the catalog; offer the map for the new days. Undo a run: `sort_inbox.py --undo "<drive>/Source Video/_logs/sort_….tsv"`. Undated clips: subfolder `ГГГГ-ММ-ДД место` in the inbox.

## 5. The all-drive catalog and "what can be freed"
- Rebuild after any change: `python3 -I "/Volumes/<drive>/Source Video/_tools/catalog_all.py"` → `ВСЕ ДИСКИ.md` + `ВСЕ ДИСКИ — каталог.csv` in every connected library drive root; offline drives keep their rows from the previous CSV. `--out <folder>` writes elsewhere.
- «Что где снято / в каких роликах клип» → `ВСЕ ДИСКИ.md` sections, then filter the CSV (`место`, `день`, `использован в`). Columns: `references/formats.md` §4.
- Usage comes from `sources.txt`, project texts and links, and CapCut drafts: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` plus any folders in `VIDEO_LIBRARY_CAPCUT_DRAFTS` (`:`-separated). With a drive offline, usage by its projects comes from the previous build — still glance at the drafts before calling a clip unused.
- «Что можно удалить / освободить место» → the sections of «Что можно освободить»: regenerable first (CapCut cache, `node_modules`, `work/tmp`, `out/prev`, `reel/public/…`), then same-drive duplicates, then — only as information — long unused clips and the map's ○ clips. Present sizes and paths, get a yes, delete by absolute path, log it, rebuild the catalog.

## 6. The video map
What every clip contains, kept on the drive in `Source Video/_карта/<day folder>/` (`клипы.json`, `листы/`, `день.md`) plus `_карта/поиск.sqlite`; work files on the computer in `~/.cache/video-map/work`. It must outlive the sources. Layers (each looks only at what the previous one picked): camera keyframes with LUT → Vision scenes and the sharpest frame per scene → Vision labels / OCR / faces → Silero VAD + GigaAM v3 speech → SoundAnalysis sounds → Qwen3-VL-8B chunk descriptions → **Claude** writes the day. Why each choice: `references/research.md`; schemas and the `день.md` template: `references/formats.md` §7.
- **Needs** macOS, reel-studio (https://github.com/tofuurem/reel-studio-skill; `$REEL_STUDIO_SKILL`, default `~/.claude/skills/reel-studio`) with its environments in `~/.cache/reel-studio` (`venv`, `gigvenv`, `vlmvenv` + `models/qwen3-vl-8b-4bit` ≈ 5.4 GB on Apple Silicon), Xcode command line tools (`swiftc` builds the sound detector on first use). `deps.py --install --with map [--with descriptions]` sets it up; `video_map.py` checks the stages it is asked for and names what is missing. Say before anything downloads.
- **Build days** (from the drive's `_tools`, in the background; roughly 10–15 min of machine time per hour of footage):
  `cd "/Volumes/<drive>/Source Video/_tools" && python3 -I video_map.py 2026-07-14 2026-07-15` (stages `--only extract,frames,speech,sounds,vlm,assemble`; finished work is skipped, so a stopped run resumes; `--index` rebuilds search only).
- **Memory guard, always.** `video_map.py` wraps speech (`--max-gb 4 --min-free-gb 3`) and Qwen (`--max-gb 11 --min-free-gb 4`) in `mem_guard.py`; any other heavy run goes through `python3 -I mem_guard.py --max-gb N --min-free-gb 4 -- <cmd>`. Exit 137 = the guard stopped it (often another app is using memory): wait and re-run the stage. Never lower the limits; with less than 16 GB of memory skip `vlm`.
- **Describe the day (Claude).** `python3 -I vm_brief.py <day> --speech 0`, look at the sheets in `листы/` (Read the jpg), check `ВСЕ ДИСКИ — каталог.csv` for «использован в». Write `пометки.json` (per clip `summary`, `tags`, `rating` ★ брать / ◐ запас / ○ можно удалить, `moments [{t, what}]`, `note`; `_day {label, summary}`) → `python3 -I vm_annotate.py <day> пометки.json` (writes `клипы.json`, rebuilds search) → write `_карта/<day folder>/день.md` from the template. Qwen errs in details: trust the transcript and the frames. Rate with the user's taste in mind (the drive's `CLAUDE.md`). For a whole drive, split the days among background agents with `references/day-annotation-brief.md` (`references/process.md` §5). Suggest a place for unlabeled or wrongly named day folders (renaming = yes; do it with `rename_days.py`, then `rename_days_projects.py` — `references/pitfalls.md`, Video map).
- **Find a moment** («найди, где я говорю про цену билета»): `python3 -I "/Volumes/<drive>/Source Video/_tools/vm_search.py" "билет* цен*" [--kind речь|кадры|в кадре|описание|момент] [--day 2026-07-14] [--disk <name>] [--path]` — words are AND-ed, `OR` between alternatives, `*` for word endings. It searches **all drives at once** (connected ones live, offline ones from the copy in `~/.cache/video-map/поиск/`) and prints drive, day, file, time, kind and the matching text; `--path` adds the clip's absolute path. Answer with drive, day, clip, timecode and path, and show the sheet. For material for a video, combine search with `день.md` ★ clips and moments, then hand over to reel-studio.
- **Roll out to another drive:** `install_to_drive.py` copies the map tools; then build day by day. Delete the work files only when the user wants the space (`~/.cache/video-map/work`).

## 7. Projects: «архивируем» and «верни в работу»
Finished project (render accepted, cover chosen, published): create `Video Archive/ГГГГ-ММ название/`; renders and chosen covers → `final/`; everything else as it was → `project/`; `sources.txt` (clips from Source Video by path from the drive root, `#` comments on top); move by rename inside the drive; count files before (without `._*`, `node_modules`) and after; rewrite absolute paths in working files (backup first, render logs untouched); check JSON and links; append «Архив» to `project/NOTES.md` (what went where, which paths were rewritten, what can be freed). Back to work: `project/` → `Video Production/…`, `final/` renders → `out/`, paths back, reinstall dependencies if they were deleted. Format: `references/formats.md` §6.

## 8. Keeping tools and docs in sync
- `scripts/drive_tools/` is the master set. `selfcheck.py` shows drift; `install_to_drive.py` replaces an older drive copy (old one backed up to `_logs/tools_<stamp>_backup/`) and refuses to overwrite a newer one. If a drive copy was improved on purpose, `cp -p` it into `scripts/drive_tools/` first, run `selfcheck.py`, then install to the other drives.
- `mem_guard.py` ships in reel-studio too: keep the newer copy in both. `vlm_describe.py` here is the standalone drive version (reel-studio's imports its own `common.py`).
- Drive docs: `assets/templates/CLAUDE.md` and `КАК ВЕСТИ ПРОЕКТЫ.md` (placeholders `{{DISK}}`, `{{ROOT}}`, `{{DATE}}`); `assets/inbox/КАК ПОЛЬЗОВАТЬСЯ.txt`. New general rules go into the template and the drives' `CLAUDE.md`; new traps into `references/pitfalls.md`.

## References
- `references/process.md` — the agreed rules, a new drive step by step, projects, docs on the drive, the map on a whole drive, one-off migration scripts, the phase table.
- `references/formats.md` — layout and folder names, inbox hints and labels, `_catalog.csv`, `ВСЕ ДИСКИ` CSV/MD, logs and reports, archive project + `sources.txt` + NOTES «Архив», the map (`клипы.json`, `пометки.json`, `день.md` template, search).
- `references/pitfalls.md` — file systems and volume names, sorting and moving, CapCut, tool drift, map traps, decisions that are always the user's.
- `references/research.md` — why GigaAM + VAD, keyframes + scenes + sharpest frame, Qwen3-VL locally, what was ruled out, the memory guard, speed.
- `references/day-annotation-brief.md` — the brief for background agents that annotate days.
