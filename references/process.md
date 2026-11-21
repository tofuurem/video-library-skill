# Processes

How to bring a drive into the library and keep it there. Every step is reversible until the last one, and the last one (deleting) only happens after a separate yes.

## Contents
1. The agreed rules (say them to the user before the first drive)
2. A new drive: look → agree → move → verify → delete
3. Projects: where they live, archive, back to work
4. Docs on the drive
5. The video map on a whole drive
6. Ideas and a content plan from the map
7. Writing a one-off migration script
8. The phases, distilled

---

## 1. The agreed rules
- Sources by **shooting day**, not by trip or event; the place (and event) goes into the day folder's name. Year → month → day.
- **Day boundary 05:00**: after-midnight clips stay in the evening's day.
- Inside a day, **one folder per camera + colour profile = one LUT** (`Pocket4P_D-Log`, `Action5Pro_HLG`, `iPhone_HDR`…). Profiles are read from the file, never guessed by eye.
- **File names never change.**
- Each drive gets `Source Video` (raw), `Video Production` (in work), `Video Archive` (finished: final renders + the project).
- Order: look → agree → move (renames only, with journals) → verify → delete (separately, after a yes).

Confirm the rules with the user on the first drive; their answers (place naming, what to leave alone) go into the drive's `CLAUDE.md`.

## 2. A new drive

### Look (read-only)
The written result of this step is the drive inventory `_docs/ИНВЕНТАРИЗАЦИЯ.md` (template `assets/templates/ИНВЕНТАРИЗАЦИЯ.md`; Claude fills it, `install_to_drive.py` does not write it): in short, the root folder by folder, sources by place and camera, finished and in-work projects, where the drive's clips are used, what was found (wrong places, clocks, unknown profiles, copies, references from elsewhere). It is the only file written here besides an empty `Source Video` for the sorter; update it after the move and after the map («Карта видео по дням»).
- `diskutil info`: file system (exFAT / APFS), size, free space. Top-level folders with sizes; `node_modules` sized separately (on exFAT they are huge on disk).
- Cameras and profiles: `exiftool` on a sample per folder, then the sorter's dry run (below) — it reads every file.
- Undated files (clock in year 2000), messenger videos (13-digit names), screen recordings.
- Projects: Remotion (`package.json` + `reel/`), CapCut (`com.lveditor.draft`, `draft_info.json`), Filmora (`.wfp`), plain folders with renders.
- Symlinks and absolute paths inside project files; **references to this drive from elsewhere**: grep `/Volumes/<drive>/` in the computer's CapCut drafts, other drives' projects, `Video Archive`, `Video Production`.
- Sorter dry run on every old folder that holds clips — the only write allowed here is an empty `<drive>/Source Video` the sorter needs (say so):
  `python3 -I <skill>/scripts/drive_tools/sort_inbox.py --root "/Volumes/<drive>/Source Video" --inbox "/Volumes/<drive>/<old folder>" --dry-run --plan-out "<scratchpad>/план_<folder>.tsv"`
- In the plan look for `Other`, `*_10bit-unknown`, `*_CodeNN`, «нет даты», and what would land in `_проверить`.
- Day places: old folder names, phone geotags, the camera's time zone, one frame per day. Mark guesses as guesses; the map later confirms or corrects them (`pitfalls.md`: places drift around flights).
- Same-drive copies: candidates = same name + size; then compare whole files byte by byte (`cmp`). Copies on another drive are backups — not candidates.

### Agree
Write `_docs/ПЛАН ПЕРЕЕЗДА.md` in Russian, plain:
- what is on the drive now (folders, sizes, cameras, projects, free space);
- how it will look (the tree, day list with places, camera folders, which LUT each needs);
- one section per step with numbers (files, GB), what gets deleted and how much it frees;
- open questions (doubtful places, unknown profiles, which projects are finished).

Plus `_docs/ПЛАН ПЕРЕЕЗДА — список файлов.tsv`: every file «откуда → куда». Nothing moves before the user's yes.

### Move (renames only)
1. `python3 -I <skill>/scripts/install_to_drive.py "/Volumes/<drive>"` (dry run) → `--apply`: skeleton, tools, `Разложить.command`, `КАК ПОЛЬЗОВАТЬСЯ.txt`, and `CLAUDE.md` / `_docs/КАК ВЕСТИ ПРОЕКТЫ.md` / `_docs/КАРТА ВИДЕО.md` from templates where none exist. Add drive-specific facts to that `CLAUDE.md`: cameras and profiles, folders not to touch, old projects, encrypted CapCut drafts.
2. Sorter from the drive's own `_tools`, **per subfolder that holds clips** (it removes inbox folders it empties), with `--labels <file>` (`ГГГГ-ММ-ДД<TAB>место`) and date-hint subfolders for undated clips. Keep the labels file in `_logs/`.
3. Projects: finished → `Video Archive/ГГГГ-ММ имя/{final, project, sources.txt}` + NOTES «Архив»; in work → `Video Production/`. `sources.txt` comes from the project itself: Remotion links and texts, CapCut `draft_info.json`, Filmora `.wfp` (zip → `media.json` → `file_name`).
4. Same-drive copies → `Source Video/_дубликаты/` (renames), not deleted yet.
5. Rewrite symlinks and absolute paths (backup first; apply the path map until nothing changes), then `fix_capcut_paths.py` dry → `--apply` with CapCut closed and all drives connected.
6. Anything that does not fit the tools: a one-off script (section 7).

### Verify
- File counts before and after match (without `._*` and `node_modules`).
- Every JSON parses; no new broken symlinks; no old paths outside logs (compare NFC-normalised — `pitfalls.md`).
- `_inbox/_проверить` is empty or every file in it is explained.
- `catalog_all.py` rebuilt. Report the numbers to the user.

### Delete
Only after a separate yes, per the safety rules in SKILL.md: `verify_dups.py` right before deleting `_дубликаты` (every copy matched, 0 without an original), absolute paths, `node_modules` and other regenerable things as their own question, empty top-level shells left to the user. Log every deletion in `_logs/cleanup_<date>.tsv`. Then move the plan to `_docs/история/` with a status line, rebuild the catalog, add new traps to `pitfalls.md`.

### Scale to expect
A 2 TB drive with ~1000 clips: the look and the plan take one session; the move itself is minutes (renames); the path rewrite and checks are where the time goes. The map of a drive like that is hours of machine time (section 5).

## 3. Projects
- Projects live in `Video Production/ГГГГ-ММ название` (month of the shoot, the user's words). reel-studio creates them there when the material is on a library drive; clips are used by path from `Source Video`, never copied. Source Video holds raw camera files only — even if a session was opened inside a day folder.
- Non-camera material (screenshots, music, FIT files) is copied into the project's `assets/`.
- **«архивируем»** (render accepted, cover chosen, published): `Video Archive/ГГГГ-ММ название/`; renders and chosen covers → `final/`; everything else as it was → `project/`; `sources.txt`; move by rename inside the drive; count files before and after; rewrite absolute paths in working files (backup first, render logs untouched); check JSON and links; append «Архив» to `project/NOTES.md`. Formats: `formats.md` §6.
- **«верни в работу»**: `project/` → `Video Production/…`, `final/` renders → `out/`, paths back, reinstall dependencies if they were deleted.

## 4. Docs on the drive
- The drive root keeps only `CLAUDE.md` (entry point: rules + a table of docs and tools) and `ВСЕ ДИСКИ.*`. Claude's memory is tied to the folder a session is opened in; a root `CLAUDE.md` is read by every session on the drive, wherever it is opened.
- Guides for the user in `_docs/`: `КАК ВЕСТИ ПРОЕКТЫ.md`, `КАРТА ВИДЕО.md` (both installed from templates), `ИНВЕНТАРИЗАЦИЯ.md` (the look step), `ИДЕИ РОЛИКОВ.md` (§6); finished plans in `_docs/история/`.
- `CLAUDE.md`, `КАК ВЕСТИ ПРОЕКТЫ.md`, `КАРТА ВИДЕО.md` share their general sections across drives and keep drive-specific parts (cameras, clocks, folders not to touch, map state): carry a general change into each drive by hand; `install_to_drive.py` never overwrites them.
- New general rules go into `assets/templates/CLAUDE.md` and into each drive's `CLAUDE.md`.

## 5. The video map on a whole drive
- Install the tools (`install_to_drive.py`), then run `video_map.py` for the drive's days in the background, under the memory guard (it is built in). Expect roughly 10–15 min of machine time per hour of footage on Apple Silicon (disk reads and Qwen dominate); a stopped run resumes.
- Claude annotates each day (`SKILL.md` §6). For a whole drive, split the days by trip among background agents with `day-annotation-brief.md`: write one sample day yourself first, start each agent once its days are built, apply `vm_annotate.py` only after the map run ends (it rebuilds the search).
- Collect place doubts from the agents into one rename list → the user's yes → `rename_days.py` + `rename_days_projects.py`.
- Fill «Особенности» and «Состояние» in the drive's `_docs/КАРТА ВИДЕО.md` (days, clips, hours, ratings ★ ◐ ○, what was left out and why, where the `пометки.json` inputs are kept) and the «Карта видео по дням» table in `_docs/ИНВЕНТАРИЗАЦИЯ.md`.

## 6. Ideas and a content plan from the map
The map exists so the user can make videos from what they shot. When they ask «что можно сделать из отснятого», «идеи рилсов», «контент-план»:
1. **Make sure the map is complete.** Every day built and described (`день.md`); describe missing days first (§5). Offline drives: their search copy works, their `день.md` do not — list them as not covered, or ask to connect them.
2. **Read every `день.md`** of the drives in scope: ★ clips, «Лучшие моменты», `note` lines with ideas, «Уже использовано».
3. **Know what is taken.** «использован в» in `ВСЕ ДИСКИ — каталог.csv`, `Video Archive` / `Video Production` of every drive, CapCut drafts. A story already told in a published video counts as used even when its clips are free; list such ideas under «Сделано ранее и исключено» with the reason.
4. **Verify every candidate in the source.** Read the full transcript around the piece with a minute of margin (`vm_brief.py <day> --clip NNNN`), look at the sheet in `листы/`, search related material on all drives (`vm_search.py "<слово>*" --path`). Timecodes are phrase bounds from the transcript (cut by ear: ASR errs in names); quotes are the speaker's words; profanity marked «[мат]»; note light, whether faces are visible, camera, profile and frame rate.
5. **Group** (structure of `assets/templates/ИДЕИ РОЛИКОВ.md`):
   - **talking pieces** — a monologue or conversation → a cut table (time → phrase), hook first; continuations of the same thought in other clips;
   - **short reels by branch** (themes the material falls into), each scored: hook, material, story 0–3; effort Л/С/Т; length; total ≈ (sum) × 10 / 9, −1 for Т, lower when the check found a repeat, strangers' faces or darkness; a status and the next step. A ТОП table on top;
   - **rubrics** — a recurring format, only with material for ≥ 2–3 episodes (otherwise a one-off);
   - **a visual format with ready shot sets** — e.g. calm «cinematic lo-fi» reels: 15–30 s, 5–8 shots of 2–4 s, no speech (no shots where the user talks), quiet live sound under music, one line of lowercase micro-text, one look across the series. Each set is a table of shots (clip, time range, what, strength) checked on the sheets; note which camera's frame rate allows a clean slow-down (50–60 fps → 2×; 30 fps only real speed), horizontal 4K that must be cropped to 9:16, copyrighted sound to replace; add how to shoot more for the format;
   - **needs reshooting** (a shot, a screen recording, a one-line voice-over) and whether the idea works without it;
   - **must not be shown without blur** (screens with chats, documents, client details), **not at all** (private moments, things the user asked to cut), **needs consent** (friends in frame);
   - **a release order** — what is ready and strongest first, branches alternating, date-bound themes at their date.
6. **Protect the material.** Clips an idea needs stop being deletion candidates, even when rated ○ (bloopers and broken takes are a rubric's material): say so in the ideas file and fix the clip's `note` / rating in `день.md` and `пометки.json` (re-run `vm_annotate.py`).
7. **Write `_docs/ИДЕИ РОЛИКОВ.md`** on the drive whose material it covers (an idea with clips on several drives sits with its main clips; other clips carry their drive). Russian, plain, addressed to the user. Show the ТОП to the user.
8. **Hand over to reel-studio** the ideas the user picks: the idea's paragraph is the brief (clip paths, timecodes, length, format, blur / consent / profanity notes, the user's taste). reel-studio creates `Video Production/ГГГГ-ММ название`. Update the idea's status after each step (в работе → v1 → в архиве with the path; отклонён with the user's reason) and add what the user liked or rejected to the drive's `CLAUDE.md`, so the next round is better aimed.

## 7. Writing a one-off migration script
When a step does not fit the tools (moving camera folders between days, fixing a profile folder, a batch of project moves), write a script with the same contract as the tools:
- **plan by default**: prints every action and the checks; writes nothing;
- `--apply`: copies every text file it will edit to `Source Video/_logs/<what>_<stamp>_backup/<absolute path>`, then edits, then renames;
- a journal `Source Video/_logs/<what>_<stamp>.tsv` with columns `action src dst reason` (the sorter's format, so `sort_inbox.py --undo` understands plain renames);
- `--undo <journal>`: reverses renames and restores backups;
- checks at the end: counts, JSON parse, no old paths, no broken links;
- reads `_catalog.csv` / `клипы.json` / CapCut drafts as text, edits them with NFC/NFD and JSON `\/` / `\uXXXX` escapes in mind, and refuses to write a JSON that no longer parses.
Save it in the drive's `Source Video/_tools/reference/` with the date in the name, and mention it in the plan's history.

## 8. The phases, distilled
| Phase | What | Writes? |
|---|---|---|
| Look | sizes, FS, cameras, profiles, projects, links, abs paths, references from other drives; sorter `--dry-run --plan-out` per old folder | `_docs/ИНВЕНТАРИЗАЦИЯ.md` (and an empty `Source Video` the sorter needs) |
| Agree | day places, projects in work vs archive, new cameras + LUTs, same-drive duplicates; plan file + full list | `_docs/ПЛАН ПЕРЕЕЗДА.md` + `.tsv` |
| Move | install tools / docs; sorter per subfolder with `--labels`; projects to Archive / Production with `sources.txt` + NOTES «Архив»; path rewrite with backups; `fix_capcut_paths.py` | renames + journals |
| Verify | counts before/after, JSON parse, old paths outside logs = 0, no new broken links, `_проверить` explained; `catalog_all.py` | reports |
| Delete | `verify_dups.py` again = N of N; full paths; regenerable separately; top-level shells to the user | only after a separate yes |
| Map | `video_map.py` per day under the guard; Claude writes `день.md`; fill «Особенности» / «Состояние» in `_docs/КАРТА ВИДЕО.md` | `_карта/`, `_docs/КАРТА ВИДЕО.md` |
| Ideas | every `день.md` + usage + transcripts and sheets → talking pieces, scored reels, rubrics, shot sets, reshoots, blur, release order; picked ideas → reel-studio | `_docs/ИДЕИ РОЛИКОВ.md` |
