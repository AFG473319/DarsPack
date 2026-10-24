# Known Limitations (محدودیت‌های شناخته‌شده)

Honest list of what DarsPack v0.1 does **not** do. Stating flaws openly is part of the project's defense.

## Product scope

1. **Search covers names and metadata only** — not the text *inside* PDFs or Office files. Windows itself does not index PDF content by default either. Full-text search (FTS5 + Persian tokenization) is future work.
2. **Duplicates and conflicts are flagged, never resolved.** The app will not delete, merge or overwrite anything — the user decides. This is deliberate, not missing functionality.
3. **No filesystem auto-discovery.** Files enter the library only by manual import (file picker or phone upload). A watched-folder mode is future work.
4. **Filename-based metadata suggestions are heuristics.** They work on common Persian school patterns («نمونه سوال ریاضی نهم فصل 3»); unusual names get no suggestions and remain unclassified until the user edits them. There is no AI/OCR.
5. **Package verification detects, it does not repair.** A corrupt package is reported precisely but never auto-fixed.

## Platform and environment

6. **The phone client needs a running desktop "hub".** A phone-only classmate can browse/search/upload only while some PC on the Wi-Fi runs DarsPack with sharing enabled. A standalone mobile app is a v2 goal, not part of this version.
7. **The LAN share is plain HTTP on the local network** — no TLS. Threat model: classmates on the same Wi-Fi, protected by the per-session PIN and lockout. Not intended for hostile networks.
8. **School Wi-Fi may isolate clients.** If devices cannot see each other, the phone hotspot (laptop joins the phone's hotspot) is the reliable demo fallback.
9. **Windows only** for the desktop app. The web client works in any browser, but the hub is Windows (PyInstaller build).

## Engineering

10. **Search is SQL `LIKE`, not FTS.** Fine for thousands of files; a student's library of a few hundred files is nowhere near the limit, but it would not scale to tens of thousands.
11. **SQLite, one writer at a time.** Concurrent imports from the desktop UI and the web server serialize with a 5-second busy timeout. For one user this is a non-issue; it is not a multi-user database.
12. **Hashing speed is CPU-bound.** SHA-256 on the target i5-2450M runs ~150–250 MB/s in Python; a 500 MB video takes seconds with a visible progress bar. Test set files are small PDFs; large media is the slow case.
13. **The exe is unsigned.** Windows SmartScreen shows a warning on first run ("More info → Run anyway"). Code-signing certificates cost money; the demo script covers this in one sentence.
14. **No automatic backups of the library.** The library is one folder (`catalog.db` + `files/`) that can be copied for backup, but the app does not back it up itself.

## Measured on the target laptop (i5-2450M, 8 GB RAM, Windows 11) — 2026-10-24

| Metric | Value | How |
|---|---|---|
| Whole dev environment | 270 MB (venv incl. PySide6-Essentials, PyInstaller) | `du -sh .venv` |
| Built app (onedir) | 104 MB folder; DarsPack.exe 2.4 MB | `du -sh dist/DarsPack` |
| Startup to app-ready | 420 ms | time from process start to first settings write, `installer` measurement script |
| Idle RAM | 76 MB | `tasklist` after 3 s idle |
| Test suite | 50/50 green | `pytest` |

Every number above is reproducible from this repository (`installer/build.bat`, `pytest`, `eval/`).
