# DarsPack — درس‌پک

**An offline-first, Persian-first organizer for school materials.**

DarsPack (درس‌پک) helps Iranian middle-school students keep their class notes (جزوه), sample exams (نمونه‌سوال) and worksheets (کاربرگ) in one findable place. It is a Windows desktop app that also serves a phone-friendly web client over local Wi-Fi. Persian-first RTL interface with an English toggle.

> Status: **working v0.1** — core engine, brand RTL desktop UI, LAN phone client, and the Windows build are implemented and covered by 332 automated tests; see `docs/limitations.md` for known limitations.

## What works

- Drag-and-drop or file/folder picker import into an app-managed library (copy + SHA-256 + crash-safe), with a **classification review dialog** after every import — categorizing is the app's main job; the subject is never guessed behind your back.
- Normalized Persian search («فصل ۳» = «فصل 3», Arabic ي finds Persian ی), subject/chapter/kind filters, tags, notes.
- Duplicate detection (same content) and version-conflict detection (same name, different content) — **flagged, never auto-deleted**.
- **Manual delete, shortcuts and bulk actions** — Delete key, «حذف» button or right-click anywhere on a row; select several files (Ctrl/Shift) to remove them together (moved to the library's `.trash` folder, never erased) or reclassify them in one form. Keyboard shortcuts: Enter to open, Ctrl+E to edit metadata, Esc to clear search/selection, F5 to refresh; column header click-to-sort with visual indicators.
- Portable «درس‌پک» packages: ZIP + JSON manifest + per-file hashes + offline RTL index; verify detects exactly which files are missing/corrupt.
- Optional LAN sharing: PIN-protected web client for phones on the same Wi-Fi (search, inline viewing for PDFs/images/text, download, multi-file upload) with a web-app manifest for «Add to Home screen».
- **Built-in Model Context Protocol (MCP) server & 1-click AI integration**: Connect AI agents (Claude Code, OpenCode, Antigravity, Cursor, Hermes, OpenClaw) directly to the library. The server runs as a separate headless process (`DarsPackMcp.exe`) — no window, no network — and the in-app Help Center (F1) offers a 1-click prompt generator plus a `--selftest` health check.
- Persian-first dark RTL UI with the bundled Vazirmatn typeface, one consistent icon set, a compact app bar and toolbar, kind badges, Persian/English toggle, in-app feedback (star rating + topic, online submission optional — see `docs/feedback-setup.md`), activity log; one-command Windows build.

## Key ideas

- **Manual import into an app-managed library** — files are copied in, hashed (SHA-256) and cataloged by subject, chapter, lesson, kind and school year (Jalali calendar).
- **Duplicates and version conflicts are flagged, never auto-deleted** — the user always decides.
- **Portable «درس‌پک» packages** — a ZIP with a JSON manifest, per-file SHA-256 hashes and an offline browsable index; anyone can verify a package's completeness and integrity, even without DarsPack installed.
- **Fully offline by default** — the LAN share is opt-in per session and PIN-protected.
- Built for low-end hardware and Persian text: ی/ي and ک/ك normalization, Persian/Latin digits, half-space (ZWNJ) handling, Jalali dates.

## In this repository

| Path | Contents |
|---|---|
| `docs/architecture.md` | Module map, SQLite schema, package format, LAN protocol, test strategy |
| `docs/dependencies.md` | Dependency register (what / why / licence / size) |
| `docs/limitations.md` | Known limitations and measured performance on the target laptop |
| `docs/feedback-setup.md` | Optional online feedback endpoint setup |
| `docs/mcp.md` | Model Context Protocol (MCP) server configuration for AI agents |
***REMOVED***
| `eval/benchmark-plan.md` | Controlled benchmark: find-time, duplicate/conflict detection accuracy, package verification |
| `installer/` | PyInstaller spec + one-command build script (`build.bat`) |

## Run and build

From source (Python 3.12+, SQLite and the packages in `docs/dependencies.md`):

```
python -m venv .venv
.venv/Scripts/pip install PySide6-Essentials jdatetime qrcode pytest
.venv/Scripts/pip install -e .          # or add src/ to PYTHONPATH
.venv/Scripts/python -m darspack
```

Tests: `.venv/Scripts/python -m pytest tests/`

Windows build (produces `dist/DarsPack/DarsPack.exe`, a portable app folder):

```
installer\build.bat
```

## License

[GNU General Public License v3.0 or later (GPL-3.0-or-later)](LICENSE).

Bundled assets have their own permissive licenses:
- **Vazirmatn** font: [SIL Open Font License 1.1](src/darspack/assets/fonts/OFL.txt)
- **Lucide** icons: [ISC License](src/darspack/assets/icons/LICENSE)
