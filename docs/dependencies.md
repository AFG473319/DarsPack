# Dependency Register

Project rule: every dependency is registered here **before** installation — what it does, why it is needed, its licence, and its measured size. Numbers below are measured on the development laptop (Python 3.14.6, Windows 11), 2026-10-24.

| Package | What it does | Why DarsPack needs it | Licence | Installed size | Status |
|---|---|---|---|---|---|
| PySide6-Essentials 6.12.0 | Qt 6 bindings (QtCore/QtGui/QtWidgets only) | Desktop UI with native Persian/RTL support; worker threads keep the UI responsive | LGPL-3.0 | part of the 250 MB venv below | installed |
| jdatetime 6.1.1 | Jalali (Shamsi) date handling | School years and date display; leap-Esfand/year-boundary tested | MIT (verified on PyPI) | part of the 250 MB venv below | installed |
| qrcode 8.2 | Generates QR codes as pure-Python SVG (no Pillow needed) | The share dialog shows a QR of the phone URL — scanning it beats typing `http://192.168.x.y:port/` on a phone keyboard, especially on demo day | BSD (verified on PyPI and `pip show`) | 455 kB installed + 208 kB for its one dependency `colorama` (measured on the dev laptop, 2026-10-25) | installed 2026-10-25 |
| pytest 9.1.1 | Test runner | Automated tests for every critical algorithm | MIT | part of the 250 MB venv below | installed (dev only) |
| pytest-cov 7.1.0 | Statement coverage reporting on top of pytest | CI publishes a coverage report so it is visible which lines the tests execute — especially useful during the review month, to confirm a rewritten module is still fully covered | MIT; its engine `coverage` 7.17.3 is Apache-2.0 (verified on PyPI) | 147 kB installed + 1.87 MB for `coverage` (measured 2026-11-17) | installed 2026-11-17 (dev/CI only) |
| ruff 0.17.5 | Fast Python linter (static analysis, one self-contained tool) | CI and local linting with a deliberately gentle, bug-catching-only ruleset (`ruff.toml`: syntax errors, undefined names, unused imports/variables) — no style rules, so a clean run stays meaningful | MIT (verified on PyPI) | ~490 kB installed (measured 2026-11-17) | installed 2026-11-17 (dev/CI only) |
| PyInstaller 6.22.3 | Bundles Python + app into an executable (onedir) | End users must not need Python installed; the same tool builds the Linux binary from `installer/darspack-linux.spec` | GPLv2 with bootloader exception (built app unrestricted) | part of the 270 MB venv below | installed (dev only) |
| Inno Setup 6.7.3 (dev/machine tool, Windows only) | Builds `dist\DarsPack-Setup.exe` from `installer\DarsPack.iss` | Official per-user setup.exe for classmates (Start Menu, optional desktop icon, Add/Remove entry) wrapping the onedir folder; no admin needed | Inno Setup License (free for commercial use, `license.txt` in the installed folder) | 34 MB installed, 122 files (measured 2026-11-09) | installed 2026-11-09 (dev only) |

### Bundled UI assets (not Python packages)

| Asset | What it does | Why DarsPack needs it | Licence | Measured size | Status |
|---|---|---|---|---|---|
| Vazirmatn 33.003, static weights Regular/Medium/SemiBold/Bold | Persian-first typeface | The UI's default font: proper Persian shaping and a consistent, modern look. Bundled so target PCs do not need it installed; falls back to Segoe UI if a file ever fails to load. | SIL OFL-1.1 (`assets/fonts/OFL.txt`) | 482 kB for four TTFs + 4.3 kB licence (2026-10-29) | bundled 2026-10-29 |
| Lucide 0.468.0, 38 SVG icons | Consistent line icons for the toolbar, menus and file rows | One visual language instead of text-only buttons; 20 px SVGs are crisp on every DPI. No icon font and no pip package. | ISC (`assets/icons/LICENSE`) | 15 kB for 38 SVGs + 3.2 kB licence (measured 2026-11-12) | bundled 2026-10-29; +8 icons 2026-11-09; +6 icons 2026-11-12 |

**Whole development environment: 270 MB** (`.venv/` including all of the above). Built output: 105 MB app folder, `DarsPack.exe` 2.65 MB **plus a second headless `DarsPackMcp.exe` 2.26 MB** for the MCP server, both sharing the same `_internal` folder (measured 2026-11-14) — see `docs/limitations.md` for measured numbers. The MCP server and the `--selftest` / `--print-config` flags add **no new packages**: only the standard library (`argparse`, `json`, `sys`, `pathlib`, `sqlite3`). The full `PySide6` distribution is intentionally NOT installed — its Addons half (WebEngine, 3D, multimedia, …) would add hundreds of megabytes DarsPack never uses; `PySide6-Essentials` ships exactly the widgets we need.

Everything else is the Python standard library: `sqlite3`, `hashlib`, `zipfile`, `http.server`, `json`, `threading`, `hmac`, `tempfile`. No other third-party packages are planned for v1; adding one requires an entry here first and a size check.

Dev-machine tools (not app dependencies): Node.js is used only by the test suite to syntax-check the phone client's JavaScript (`node --check` in `tests/test_web_client.py`); the app itself never touches it.

### Linux system libraries (not pip packages)

The PySide6 wheel does not bundle Qt's system libraries, so the Linux GUI (and the Qt parts of the test suite) need them from the distro. On Debian/Ubuntu:

```
sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3
```

If the app or a test fails at `from PySide6.QtGui import ...` with `libEGL.so.1: cannot open shared object file`, those packages are the missing piece. The Linux build (`installer/build-linux.sh`) and per-user install (`installer/install-linux.sh`, desktop file `installer/darspack.desktop`) need no installer tool — there is no Linux equivalent of Inno Setup in this project; the install script copies the onedir folder to `~/.local/share/DarsPack` and registers the app-menu entry. The Linux library default is `~/Documents/DarsPackLibrary` when a documents folder exists, otherwise `$XDG_DATA_HOME/DarsPackLibrary` (`~/.local/share/DarsPackLibrary`) — see `src/darspack/paths.py`.
