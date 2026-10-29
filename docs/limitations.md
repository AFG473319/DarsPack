# Known Limitations (محدودیت‌های شناخته‌شده)

Honest list of what DarsPack v0.1 does **not** do. Stating flaws openly is deliberate: honest engineering earns trust.

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

10. **Search is SQL `LIKE`, not FTS.** Word order no longer matters (multi-token search: every word of the query must match somewhere), but a token also matches inside longer words («فصل یکم» contains «فصل یک»), and the note is matched as stored — typing-style differences (ي/ی، نیم‌فاصله) inside a note don't match until a `note_norm` column lands. Fine for thousands of files; a student's library of a few hundred files is nowhere near the limit, but it would not scale to tens of thousands — that is FTS5 + Persian tokenization, future work.
11. **SQLite, one writer at a time.** Concurrent imports from the desktop UI and the web server serialize with a 5-second busy timeout. For one user this is a non-issue; it is not a multi-user database.
12. **Hashing speed is CPU-bound.** Measured SHA-256 throughput on the target i5-2450M is **30–55 MB/s** in Python (a single core); a 500 MB video takes ~10–15 seconds — with a visible progress bar. An early draft of this document claimed 150–250 MB/s; the real number is lower and was corrected after a proper measurement (corrected after a proper measurement). Import reads each file twice (hash pass + copy pass); large media is the slow case.
13. **The exe is unsigned.** Windows SmartScreen shows a warning on first run ("More info → Run anyway"). Code-signing certificates cost money; the demo script covers this in one sentence.
14. **No *automatic* backups of the library.** The app has a one-click backup («پشتیبان‌گیری»): one ZIP holding the browsable package (manifest + files + index), the catalog snapshot (`catalog.db`) and a restore guide — but the user must press it; nothing schedules or runs on its own, and restoring is still the documented manual steps.
15. **The phone client's JavaScript is only lightly guarded.** pytest covers the server and a static wiring check (ids exist, script parses), but there is no browser-level automated test of the phone UI — real-phone testing is manual. (A silent JS failure hid a broken PIN button until a real user tried it.)
16. **Subject classification quality depends on filenames.** Files with unhelpful names («IMG_2026.pdf») start unclassified and rely on the user completing them via the review dialog / «بدون درس» filter. The app makes this visible rather than guessing.
17. **~~The second distinct phone upload in a share session fails~~ — FIXED (2026-10-26).** The server used to write the `web_upload` log row after the import transaction, on the request thread's own connection, and never commit it; the connection stayed alive in the server's registry, so the uncommitted write held SQLite's write lock for the whole session — the second upload with *new* content stalled ~5 s and failed. The server now commits the log row explicitly (regression tests: the row exists, and two distinct uploads in a row both land).
18. **~~Stopping the share server races an in-flight request's log write~~ — FIXED (2026-10-26).** Handler threads used to run as daemons, which `ThreadingMixIn` never tracks or joins, so `stop()` closed each request thread's SQLite connection while a request could still be inside its log write (a native access violation). Handler threads are now joinable, so `server_close()` waits for them before any connection is closed. The test suite's own workaround (`daemon_threads = False`) became the product fix.
19. **The test suite can exit non-zero even when every test passes (Qt offscreen teardown crash).** On this machine some Qt widget tests (notably `tests/test_classify.py`) occasionally crash the pytest process during interpreter shutdown — exit code 127 or 139 — after the summary line reports all tests passed. Reproduced on a pristine `HEAD` worktree, so it predates the 2026-10-29 icon work and is not caused by any app code; the tests themselves pass. On this machine treat the green summary line as the pass signal, and re-run any file that exits non-zero to confirm. Not yet fixed.

## Bugs found and fixed in real use (2026-10-24 dogfooding session)

Each was reported in real use via the in-app crash dialog, fixed, and covered by a regression test:

1. Import hung on «در حال وارد کردن» — one failing file killed the worker thread before the completion signal (silent in a windowed exe). Fixed: per-file error containment, guaranteed `done`, `error.log`, global crash dialog.
2. The metadata dialog crashed on files without a subject (missing `subject_name` column in its query). Fixed: JOIN subjects.
3. The phone PIN button did nothing (client JS referenced a non-existent implicit global). Fixed: explicit element lookups + inline errors + static wiring guards.
4. The feedback button crashed (Qt passes `checked` to plain-function slots). Fixed: lambda wiring + a wiring-guard test.

## Measured on the target laptop (i5-2450M, 8 GB RAM, Windows 11) — 2026-10-24; re-measured 2026-10-25 after the UI improvement round

| Metric | Value | How |
|---|---|---|
| Whole dev environment | 270 MB (venv incl. PySide6-Essentials, PyInstaller, qrcode) | `du -sh .venv` |
| Built app (onedir) | 104 MB folder; DarsPack.exe 2.5 MB (was 2.4 MB) | `du -sh dist/DarsPack` |
| Startup to app-ready | 700–1100 ms on an empty library (was 420 ms on 2026-10-24; the machine's background load differs between the two measurements — not directly comparable. The deferred-import work (F4) removed ~420–490 ms of module imports from source runs.) | process start → first settings write |
| Idle RAM | ~81 MB on an empty library (was 76 MB) | `tasklist` after 8 s idle |
| Test suite | 257/257 green, ~32 s | `pytest` |

Every number above is reproducible from this repository (`installer/build.bat`, `pytest`, `eval/`).
