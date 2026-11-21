# Processes

How to bring a drive into the library and keep it there. Every step is reversible until the last one, and the last one (deleting) only happens after a separate yes.

## Contents
1. The agreed rules (say them to the user before the first drive)
2. A new drive: look → agree → move → verify → delete
3. Projects: where they live, archive, back to work
4. Docs on the drive
5. The video map on a whole drive
6. Writing a one-off migration script
7. The phases, distilled

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
1. `python3 -I <skill>/scripts/install_to_drive.py "/Volumes/<drive>"` (dry run) → `--apply`: skeleton, tools, `Разложить.command`, `КАК ПОЛЬЗОВАТЬСЯ.txt`, and `CLAUDE.md` / `_docs/КАК ВЕСТИ ПРОЕКТЫ.md` from templates where none exist. Add drive-specific facts to that `CLAUDE.md`: cameras and profiles, folders not to touch, old projects, encrypted CapCut drafts.
2. Sorter from the drive's own `_tools`, **per subfolder that holds clips** (it removes inbox folders it empties), with `--labels <file>` (`ГГГГ-ММ-ДД<TAB>место`) and date-hint subfolders for undated clips. Keep the labels file in `_logs/`.
3. Projects: finished → `Video Archive/ГГГГ-ММ имя/{final, project, sources.txt}` + NOTES «Архив»; in work → `Video Production/`. `sources.txt` comes from the project itself: Remotion links and texts, CapCut `draft_info.json`, Filmora `.wfp` (zip → `media.json` → `file_name`).
4. Same-drive copies → `Source Video/_дубликаты/` (renames), not deleted yet.
5. Rewrite symlinks and absolute paths (backup first; apply the path map until nothing changes), then `fix_capcut_paths.py` dry → `--apply` with CapCut closed and all drives connected.
6. Anything that does not fit the tools: a one-off script (section 6).

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
- Guides for the user in `_docs/` (`КАК ВЕСТИ ПРОЕКТЫ.md`), finished plans in `_docs/история/`.
- New general rules go into `assets/templates/CLAUDE.md` and into each drive's `CLAUDE.md`.

## 5. The video map on a whole drive
- Install the tools (`install_to_drive.py`), then run `video_map.py` for the drive's days in the background, under the memory guard (it is built in). Expect roughly 10–15 min of machine time per hour of footage on Apple Silicon (disk reads and Qwen dominate); a stopped run resumes.
- Claude annotates each day (`SKILL.md` §6). For a whole drive, split the days by trip among background agents with `day-annotation-brief.md`: write one sample day yourself first, start each agent once its days are built, apply `vm_annotate.py` only after the map run ends (it rebuilds the search).
- Collect place doubts from the agents into one rename list → the user's yes → `rename_days.py` + `rename_days_projects.py`.

## 6. Writing a one-off migration script
When a step does not fit the tools (moving camera folders between days, fixing a profile folder, a batch of project moves), write a script with the same contract as the tools:
- **plan by default**: prints every action and the checks; writes nothing;
- `--apply`: copies every text file it will edit to `Source Video/_logs/<what>_<stamp>_backup/<absolute path>`, then edits, then renames;
- a journal `Source Video/_logs/<what>_<stamp>.tsv` with columns `action src dst reason` (the sorter's format, so `sort_inbox.py --undo` understands plain renames);
- `--undo <journal>`: reverses renames and restores backups;
- checks at the end: counts, JSON parse, no old paths, no broken links;
- reads `_catalog.csv` / `клипы.json` / CapCut drafts as text, edits them with NFC/NFD and JSON `\/` / `\uXXXX` escapes in mind, and refuses to write a JSON that no longer parses.
Save it in the drive's `Source Video/_tools/reference/` with the date in the name, and mention it in the plan's history.

## 7. The phases, distilled
| Phase | What | Writes? |
|---|---|---|
| Look | sizes, FS, cameras, profiles, projects, links, abs paths, references from other drives; sorter `--dry-run --plan-out` per old folder | nothing (except an empty `Source Video` the sorter needs) |
| Agree | day places, projects in work vs archive, new cameras + LUTs, same-drive duplicates; plan file + full list | `_docs/ПЛАН ПЕРЕЕЗДА.md` + `.tsv` |
| Move | install tools / docs; sorter per subfolder with `--labels`; projects to Archive / Production with `sources.txt` + NOTES «Архив»; path rewrite with backups; `fix_capcut_paths.py` | renames + journals |
| Verify | counts before/after, JSON parse, old paths outside logs = 0, no new broken links, `_проверить` explained; `catalog_all.py` | reports |
| Delete | `verify_dups.py` again = N of N; full paths; regenerable separately; top-level shells to the user | only after a separate yes |
