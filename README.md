<div align="center">

# درسپک · DarsPack

**All your school files in one place where you can find them. Offline, Persian-first, no account needed.**

همهی فایلهای درسی (جزوه، نمونهسوال، کاربرگ) در یک جای مرتب و قابل جستوجو. آفلاین، فارسی و بدون حساب کاربری.

[![CI](https://github.com/AFG473319/DarsPack/actions/workflows/ci.yml/badge.svg)](https://github.com/AFG473319/DarsPack/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/AFG473319/DarsPack)](https://github.com/AFG473319/DarsPack/releases/latest)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
![Platforms: Windows | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)

[**Download**](#download) · [Features](#features) · [Build from source](#build-from-source) · [Documentation](#documentation) · [فارسی](#فارسی)

![DarsPack main window: the Persian right-to-left library view](docs/screenshots/main-window.png)

</div>

DarsPack is a desktop app for Windows and Linux, made for Iranian middle-school students. It organizes class notes (جزوه), sample exams (نمونهسوال) and worksheets (کاربرگ) by subject, chapter and kind. It can also serve a phone-friendly web page over your home Wi-Fi, so you can open your library from your phone.

## Download

Get the latest version from the [**Releases page**](https://github.com/AFG473319/DarsPack/releases/latest).

| File | For |
|---|---|
| `DarsPack-Setup.exe` | Windows installer. Installs for your user only, no admin rights needed. |
| `DarsPack-windows.zip` | Windows portable version. Unzip it and run `DarsPack.exe`. |
| `DarsPack-linux.tar.gz` | Linux portable version. Extract it and run `DarsPack`. |
| `SHA256SUMS.txt` | Checksums. Use them to check your download before you run it. |

Versions marked **Latest** are stable. Versions marked **Pre-release** (`vX.Y.Z-beta.N`) are test builds and never replace the stable version.

> **Note:** Windows SmartScreen may warn you the first time you run the installer, because it is not code-signed. Known limitations are listed in [`docs/limitations.md`](docs/limitations.md).

## Features

**Organize**
- Add files by drag-and-drop or with the file/folder picker. Files are copied into a library the app manages, with a SHA-256 hash, and the copy survives a crash part-way through.
- After every import, a review dialog asks for each file's subject, chapter and kind. The app pre-fills a suggestion but never sets the subject without you.
- Tags, notes, school year (Jalali calendar), bulk editing, and a sortable table with keyboard shortcuts.

**Find**
- Persian-aware search: «فصل ۳» finds the same files as «فصل 3», and Arabic ي / ك match Persian ی / ک. Half-spaces (ZWNJ) are handled correctly.
- Filters for subject, chapter and kind, and a «بدون درس» (no subject) filter for files that are not classified yet.

**Stay safe**
- Duplicates (same content) and version conflicts (same name, different content) are **flagged, never deleted automatically**. You always decide.
- Deleted files go to the library's `.trash` folder and can be restored.
- No network access by default and no telemetry.

**Share**
- **Portable «درسپک» packages:** a ZIP with a JSON manifest, a SHA-256 hash for every file and an index page you can browse offline. A verify step reports exactly which files are missing or corrupt, even on a computer without DarsPack.
- **Phone access (optional):** turn on a PIN-protected web page for phones on the same Wi-Fi. From the phone you can search, view PDFs/images/text, download, and upload several files at once. Sharing is off until you turn it on, and it only works on your local network.
- **AI integration:** a built-in [MCP](docs/mcp.md) server (`DarsPackMcp.exe`) lets AI agents such as Claude Code, Cursor and OpenCode work with your library. It runs as a separate process with no window and no network. The in-app Help Center (F1) shows a ready-made setup prompt for each agent.

**Interface**
- Persian right-to-left dark theme with the Vazirmatn font, plus an English language option.
- Statistics, an activity history and an in-app feedback form ([online submission is optional](docs/feedback-setup.md)).

## Build from source

You need Python 3.12 or newer. The full list of dependencies (with sizes and licences) is in [`docs/dependencies.md`](docs/dependencies.md).

<details open>
<summary><b>Windows</b></summary>

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pip install -e .
.venv\Scripts\python -m darspack
```

Build a portable app folder (`dist\DarsPack\DarsPack.exe`):

```powershell
installer\build.bat
```

</details>

<details>
<summary><b>Linux</b></summary>

The PySide6 package does not include Qt's system libraries. On Debian/Ubuntu, install them first:

```bash
sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3
```

```bash
python3 -m venv .venv-linux
.venv-linux/bin/pip install -r requirements-dev.txt
.venv-linux/bin/pip install -e .
.venv-linux/bin/python -m darspack
```

Build a portable app folder (`dist/DarsPack/DarsPack`) and add it to your app menu (no sudo):

```bash
installer/build-linux.sh
installer/install-linux.sh            # remove it with: --uninstall
```

If the app fails with `libEGL.so.1: cannot open shared object file`, the system libraries above are missing.

</details>

**Library location:** by default the library is `Documents/DarsPackLibrary`. On Linux without a Documents folder, it is `~/.local/share/DarsPackLibrary`. You can move it from Settings.

### Tests

```bash
python -m pytest tests/
```

Qt runs offscreen during tests (`tests/conftest.py` sets this up), so no display is needed. CI runs the full suite on Windows and Linux with Python 3.12 and 3.14, along with `ruff` lint and the Windows and Linux builds.

### Screenshots of every screen

```bash
python scripts/capture_all_pages.py
```

This saves a PNG of the main window, every dialog, the welcome slides, the help tabs and the menus to `eval/screenshots/all_pages/`. It runs offscreen. For a shorter check that also tests the phone-sharing server, run `python scripts/app_harness.py screenshot --out-dir eval/screenshots`.

## Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Module map, SQLite schema, package format, LAN protocol, test strategy |
| [`docs/limitations.md`](docs/limitations.md) | Known limitations and measured performance |
| [`docs/mcp.md`](docs/mcp.md) | Setting up the MCP server for AI agents |
| [`docs/dependencies.md`](docs/dependencies.md) | Every dependency: what it is, why it's used, licence, size |
| [`docs/ci.md`](docs/ci.md) | CI checks and the tag-based release process |
| [`docs/feedback-setup.md`](docs/feedback-setup.md) | Optional online feedback endpoint |
| [`docs/releases/`](docs/releases/) | Release notes for each version |
| [`eval/benchmark-plan.md`](eval/benchmark-plan.md) | Benchmark plan: search time, duplicate/conflict detection, package verification |

## Feedback

Found a bug or have an idea? [Open an issue](https://github.com/AFG473319/DarsPack/issues) or use the feedback form inside the app. If DarsPack is useful to you, a ⭐ helps other students find it.

## License

DarsPack is released under the [GNU General Public License v3.0 or later](LICENSE).

The bundled assets have their own licences: the [Vazirmatn](src/darspack/assets/fonts/OFL.txt) font (SIL Open Font License 1.1) and the [Lucide](src/darspack/assets/icons/LICENSE) icons (ISC).

---

<div dir="rtl">

## فارسی

درسپک یک برنامهی ویندوزی و لینوکسی برای دانشآموزان دورهی متوسطه است. فایلهای درسی (جزوه، نمونهسوال و کاربرگ) را بر اساس درس، فصل و نوع مرتب میکند تا همیشه سریع پیدا شوند.

### دانلود

آخرین نسخه را از صفحهی [**Releases**](https://github.com/AFG473319/DarsPack/releases/latest) بگیرید:

- **ویندوز:** فایل `DarsPack-Setup.exe` را نصب کنید. به دسترسی مدیر (admin) نیازی نیست. نسخهی قابلحمل هم با نام `DarsPack-windows.zip` هست.
- **لینوکس:** فایل `DarsPack-linux.tar.gz` را باز کنید و `DarsPack` را اجرا کنید.
- با فایل `SHA256SUMS.txt` میتوانید سالم بودن فایل دانلودشده را بررسی کنید.

### امکانات

- **کاملاً آفلاین:** اینترنت لازم نیست و کتابخانه روی کامپیوتر خودتان است.
- **دستهبندی با تأیید شما:** بعد از هر بار افزودن فایل، درس و فصل و نوع هر فایل را بررسی و تأیید میکنید. برنامه فقط پیشنهاد میدهد.
- **جستوجوی فارسی واقعی:** «فصل ۳» و «فصل 3» یک نتیجه میدهند و حروف عربی و فارسی (ی/ي، ک/ك) و نیمفاصله درست شناخته میشوند.
- **بدون حذف خودکار:** فایلهای تکراری و نسخههای متفاوت فقط علامت میخورند و تصمیم با شماست. فایلهای حذفشده به سطل زباله میروند و برمیگردند.
- **بستهی قابلحمل:** از کتابخانه یک بستهی «درسپک» (ZIP) بسازید. روی هر کامپیوتری، حتی بدون نصب درسپک، میشود بررسی کرد که بسته کامل و سالم است.
- **دسترسی با گوشی (اختیاری):** با گوشی روی همان وایفای خانه به کتابخانه دسترسی دارید: جستوجو، دیدن، دانلود و آپلود فایل. این امکان با رمز (PIN) محافظت میشود و تا روشنش نکنید خاموش است.
- **رابط فارسی و راستچین** با فونت وزیرمتن و امکان تغییر زبان به انگلیسی.

اگر درسپک برایتان مفید بود، با یک ستاره ⭐ کمک کنید دانشآموزان دیگر هم پیدایش کنند.

</div>
