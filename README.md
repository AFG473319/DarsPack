# DarsPack — درس‌پک

**An offline-first, Persian-first organizer for school materials.**

DarsPack (درس‌پک) helps Iranian middle-school students keep their class notes (جزوه), sample exams (نمونه‌سوال) and worksheets (کاربرگ) in one findable place. It is a Windows desktop app that also serves a phone-friendly web client over local Wi-Fi. Persian-first RTL interface with an English toggle.

> Status: **early development** — architecture and evaluation plan are in place (see below); implementation is starting.

## Key ideas

- **Manual import into an app-managed library** — files are copied in, hashed (SHA-256) and cataloged by subject, chapter, teacher and school year (Jalali calendar).
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
