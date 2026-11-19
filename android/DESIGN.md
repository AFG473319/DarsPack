# DarsPack Android — shared design (read this first)

Flutter rebuild of the Windows DarsPack app (source of truth:
`~/workspace/darspack-review/repo`, main @ b9ae4e4). Persian-first, RTL,
offline-first, no accounts, free, GPL-3.0-or-later. Sideloaded APK for a
Samsung Galaxy S20 FE (Android 13). No Play Store, no phone/SMS
verification anywhere. **Never push anywhere — local commits only.**

## Who owns what (do not write into another agent's files)

| Agent | Owns |
|---|---|
| data | `lib/core/**`, `test/core/**` |
| ui | `lib/ui/**`, `lib/l10n/**`, `lib/app_state.dart`, `lib/main.dart` (UI wiring only), `test/ui/**` |
| lan | `lib/lan/**`, `assets/web/**`, `test/lan/**` |
| packaging | `android/**`, `pubspec.yaml` (deps only with coordinator's OK), icon, `flutter analyze/test/build`, final QA |

`lib/main.dart` is assembled by the coordinator from the pieces; the UI
agent writes it first, others only request changes through the coordinator.

## Packages (already in pubspec.yaml — do not add others without asking)

sqflite, path, path_provider, file_picker, http, shelf, shelf_router,
shared_preferences, crypto, archive, open_filex, network_info_plus,
qr_flutter, shamsi_date (Jalali dates only).

## Library layout on Android (mirrors Windows exactly)

```
<app documents>/DarsPackLibrary/
├── catalog.db            # SQLite, SAME schema as Windows core/db.py
├── files/000001.pdf …    # stored name = zero-padded id + original extension
└── files/.trash/         # deleted files moved here, never erased
```

## SQLite schema — port Windows `core/db.py` SCHEMA verbatim

Tables: subjects(id, name, normalized), teachers, files(id, stored_name,
original_name, name_norm, size_bytes, sha256, imported_at, subject_id,
teacher_id, chapter, lesson, school_year, kind CHECK IN
('جزوه','نمونه‌سوال','کاربرگ','تکلیف','سایر'), note, available),
tags, file_tags, activity_log, hint_rules, import_skips.
Indexes idx_files_sha, idx_files_name_norm. `PRAGMA user_version = 1`
(migration 1 added the `lesson` column). WAL mode, foreign keys ON.
Seed the 14 default subjects only when the subjects table is empty:
ریاضی، علوم تجربی، فارسی، عربی، دینی، انگلیسی، مطالعات اجتماعی، هنر،
کار و فناوری، تربیت بدنی، آمادگی دفاعی، سلامت و بهداشت،
تفکر و سبک زندگی، کارگاه.

## Core rules (Windows behaviour — do not "improve" these)

- **Normalize** (`core/normalize.py`): ي→ی، ك→ک، ە→ه، Persian/Arabic
  digits→Latin, ZWNJ→space for match keys, strip diacritics/tatweel,
  collapse whitespace, casefold. Display keeps the original text.
- **Suggest** (`core/suggest.py`): from filename stem — subject by
  longest-match-first over the subject list; chapter from «فصل N» or
  «فصل <word>» (یک…دوازده, longest word first so دوازده never reads as دو);
  lesson likewise from «درس»; kind from keyword hints
  (نمونه سوال/امتحان/آزمون/تست→نمونه‌سوال، جزوه/خلاصه/مرور/جمع بندی/فرمول→جزوه،
  کاربرگ/ورقه→کاربرگ، تکلیف/تمرین/پروژه/مشی→تکلیف); grade word نهم/هشتم/هفتم.
  **The subject is NEVER auto-applied** — suggestions only pre-fill the
  classify sheet; unclassified files stay in «بدون درس» until the user
  confirms. Chapter/lesson/kind hints ARE applied at import.
- **Import** (`core/importer.py`): SHA-256 the source → duplicate check by
  hash (duplicate = reported + skipped, naming the twin; `keepDuplicate`
  override) → copy to `tmp_<id><ext>` → atomic rename to
  `<id:06d><ext>` → one DB transaction. One bad file never aborts a batch.
- **Search** (`core/search.py`): normalize query, split into tokens,
  AND them; each token must match filename/subject/tags/note/kind, and a
  «فصل/درس N» phrase also matches the structured chapter/lesson columns.
  Rank: prefix match on first token first, then recency. Cap 8 tokens.
- **Backup** (`core/backup.py` + `core/manifest.py`): ZIP named
  `darspack-backup-<Jalali YYYY-MM-DD>.zip` containing `manifest.json`
  (`{"format":"darspack-package","version":1,"created":…,"files":[…]}`
  with per-file name/sha256/size/subject/chapter/lesson/school_year/kind/
  tags/path), `files/` with the catalog's STORED names, `index.html`
  (RTL browsable list), `catalog.db` (snapshot), `RESTORE-راهنما.txt`.
  Restore replaces catalog.db + files/ together (keep a safety copy of
  the current library first). Verify: re-hash every member vs manifest.
  A plain درس‌پک package export is the same ZIP without catalog.db.
  **Backups must be interchangeable with the Windows app.**
- **School year**: Jalali year starting 1 Mehr, e.g. «1405-1406».

## Theme (Windows `ui/theme.py` — dark, navy + saffron)

bg #14161b, surface #1a1d24, surface2 #22262f, surface3 #2a2f39,
header #1e222a, border #2e3440, text #e9e6df, muted #9aa0ab,
faint #6b7280, primary navy #2d3f6e, primaryHover #3a5290,
accent saffron #e0a83c (accent only — never large fills),
onAccent #1c1508, danger #d9736e, success #8fd08f.
Font: Vazirmatn (bundled in `assets/fonts/`, OFL). Kind badges:
جزوه / نمونه‌سوال / کاربرگ / تکلیف / سایر. Persian digits in display,
Latin digits accepted everywhere.

## Strings

Port `src/darspack/i18n.py` fa/en dicts into `lib/l10n/strings.dart`
(same keys, same Persian wording). App default language: fa. Data
values (subject names, kinds) are stored in Persian and shown as-is
in both languages.

## Screens (UI agent)

Home/library (subject chips incl. «همه» + «بدون درس» + unclassified
count, kind filter, search field, file list with type icon + kind badge
+ chapter/lesson, tap = open with system viewer, long-press = select),
classify sheet (after import, per file: subject/chapter/lesson/kind,
prefilled from suggestions), file detail/edit (rename note, tags,
reclassify, delete → trash), import (file picker, progress, results),
duplicates view, trash view (restore / empty), backup & restore,
packages (export/verify/import), settings (language fa/en, font size,
library location info, about), share screen (see LAN).

## LAN — both directions (LAN agent)

### Client (phone → Windows server)
`GET /api/search?q=&subject_id=&kind=&unclassified=`,
`GET /api/subjects`, `GET /api/manifest`, `GET /api/file/<id>`,
`POST /api/upload?name=&kind=&lesson=&subject=` with the raw file as
the body (NOT multipart). Every `/api/*` call carries `?pin=<6-digit>`.
Wrong PIN 5× → the server locks that IP out for 30 s (expect 403
`{"error":"pin"}` or `{"error":"lockout"}`). Max upload 200 MB.
Inline-viewable types: pdf/png/jpg/jpeg/gif/txt; everything else
downloads. Save server address + PIN in SharedPreferences after the
user enters them once.

### Server (phone hosts, laptop reads in a browser)
Embedded HTTP server (shelf) on a random port, bound to all interfaces,
**only while sharing is on**. Same endpoints as the Windows server
(see `src/darspack/web/server.py`): `GET /` (serve `assets/web/index.html`),
`GET /api/manifest`, `GET /api/subjects`, `GET /api/search`,
`GET /api/file/<id>`, `POST /api/upload` (raw body, staged to temp then
imported through the normal importer; kind/lesson stored, subject NEVER
stored — returns as `prefill`, file lands unclassified). PIN: random
6-digit per session, shown in the app with a QR code of the URL
(`http://<lan-ip>:<port>/?pin=…` — display the PIN separately in Latin
digits, exactly as typed). Same lockout rule. Same 200 MB cap. The web
UI in `assets/web/` is a simplified RTL port of the Windows
`web/client/index.html` (search, subject chips, list, open/download,
upload) — Persian-only is fine for v1.
Show the phone's LAN IP(s) (network_info_plus) and a stop button.

## Screenshot harness (mirrors the Windows `scripts/app_harness.py` + `scripts/capture_all_pages.py`)

The Windows app has a sandbox + driver + capture script that seeds a temp
library with 8 realistic sample files (جزوه ریاضی فصل ۳ نهم.pdf، نمونه سوال
ریاضی نهم فصل ۳.pdf، کاربرگ علوم تجربی درس ۵.pdf، جزوه فارسی درس ۲ هشتم.pdf،
نمونه سوال علوم نهم فصل ۴.pdf، تکلیف زبان انگلیسی درس ۳.pdf، عکس تخته تدریس
ریاضی فصل ۵.png، فایل بدون درس برای تست.pdf), plus activity-log rows,
hint rules and trash files with sidecars — then shows every page/dialog
and grabs a numbered PNG of each. The Flutter equivalent lives in
`integration_test/screenshots_test.dart` (UI agent owns it):

- Seeds the same 8 sample files into a temp library (same names, subjects,
  chapters, kinds, notes as the Windows sandbox), plus activity rows,
  hint rules and two trash entries — so every screen has real content.
- Walks every screen and dialog: home/library, search «ریاضی», classify
  sheet, file detail/edit, bulk edit, stats, activity, duplicates,
  trash, share (PIN + QR), settings, backup & restore, packages
  (export/verify), exam pack, welcome/onboarding, help, LAN client and
  LAN server screens. Opens each one with real taps (never by pumping a
  bare widget), waits for frames to settle (`pumpAndSettle`) BEFORE
  capturing — a dialog captured before it is shown renders blank
  (the Windows review's L16).
- Saves one numbered PNG per capture, e.g. `01_library.png`,
  `02_search.png`, `03_classify.png` … into a folder under the project.
- **One command:** `flutter test integration_test/screenshots_test.dart`
  (run from `~/workspace/darspack-android/`). The agent that builds it
  must verify the exact output folder for the installed Flutter version
  and write it into `integration_test/README.md` — the command must work
  from a clean checkout with no extra flags.
- The test also asserts every screenshot file is non-blank (size above a
  small threshold and not a single solid colour) so a blank render fails
  loudly instead of silently.

## Testing

- Data agent: unit tests for normalize/suggest/search/import/backup
  (port the Windows test expectations where they exist).
- LAN agent: tests for the server routes with shelf test client + a
  client test against a fake HTTP server.
- UI agent: widget tests for the main screens where sensible.
- Packaging agent: `flutter analyze`, `flutter test`, `flutter build apk --release`.

## Conventions

- Dart, `flutter_lints`. Small files, one concept each, Persian comments
  where the Windows code has them. No clever tricks.
- Never touch `~/workspace/darspack-review/repo` (read-only source).
- Commit in `~/workspace/darspack-android/` on the `main` branch with
  clear messages. Never push.
