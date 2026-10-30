# DarsPack — درس‌پک

**An offline-first, Persian-first organizer for school materials.**

DarsPack (درس‌پک) helps Iranian middle-school students keep their class notes (جزوه), sample exams (نمونه‌سوال) and worksheets (کاربرگ) in one findable place. It is a Windows desktop app that also serves a phone-friendly web client over local Wi-Fi. Persian-first RTL interface with an English toggle.

> Status: **working v0.1** — core engine, RTL desktop UI, LAN phone client, and Windows build are implemented and covered by an automated test suite (250+ tests); see `docs/limitations.md` for known limitations.

## What works

- Import files/folders into an app-managed library (copy + SHA-256 + crash-safe), with a **classification review dialog** after every import — categorizing is the app's main job; the subject is never guessed behind your back.
- Normalized Persian search («فصل ۳» = «فصل 3», Arabic ي finds Persian ی), subject/chapter/kind filters, tags, notes.
- Duplicate detection (same content) and version-conflict detection (same name, different content) — **flagged, never auto-deleted**.
- **Manual delete and bulk actions** — Delete key, «حذف» button or right-click anywhere on a row; select several files (Ctrl/Shift) to remove them together (moved to the library's `.trash` folder, never erased) or reclassify them in one form.
- Portable «درس‌پک» packages: ZIP + JSON manifest + per-file hashes + offline RTL index; verify detects exactly which files are missing/corrupt.
- Optional LAN sharing: PIN-protected web client for phones on the same Wi-Fi (search, download, multi-file upload) with a web-app manifest for «Add to Home screen».
- Persian-first dark RTL UI with the bundled Vazirmatn typeface and one consistent icon set, Persian/English toggle, in-app feedback (star rating + topic, online submission optional — see `docs/feedback-setup.md`), activity log; one-command Windows build.

## Key ideas

- **Manual import into an app-managed library** — files are copied in, hashed (SHA-256) and cataloged by subject, chapter, lesson, kind and school year (Jalali calendar).
- **Duplicates and version conflicts are flagged, never auto-deleted** — the user always decides.
- **Portable «درس‌پک» packages** — a ZIP with a JSON manifest, per-file SHA-256 hashes and an offline browsable index; anyone can verify a package's completeness and integrity, even without DarsPack installed.
- **Fully offline by default** — the LAN share is opt-in per session and PIN-protected.
- Built for low-end hardware and Persian text: ی/ي and ك/ک normalization, Persian/Latin digits, half-space (ZWNJ) handling, Jalali dates.

## In this repository

| Path | Contents |
|---|---|
| `docs/architecture.md` | Module map, SQLite schema, package format, LAN protocol, test strategy |
| `docs/dependencies.md` | Dependency register (what / why / licence / size) |
| `docs/limitations.md` | Known limitations and measured performance on the target laptop |
***REMOVED***
| `eval/benchmark-plan.md` | Controlled benchmark: find-time, duplicate/conflict detection accuracy, package verification |
| `installer/` | PyInstaller spec + one-command build script (`build.bat`) |

## Run and build

From source (Python 3.12+, SQLite and the packages in `docs/dependencies.md`):

```
python -m venv .venv
.venv/Scripts/pip install PySide6-Essentials jdatetime pytest
.venv/Scripts/pip install -e .          # or add src/ to PYTHONPATH
.venv/Scripts/python -m darspack
```

Tests: `.venv/Scripts/python -m pytest tests/`

Windows build (produces `dist/DarsPack/DarsPack.exe`, a portable app folder):

```
installer\build.bat
```

## License

TBD.
