# Dependency Register

Project rule: every dependency is registered here **before** installation — what it does, why it is needed, its licence, and its measured size. Numbers below are measured on the development laptop (Python 3.14.6, Windows 11), 2026-10-24.

| Package | What it does | Why DarsPack needs it | Licence | Installed size | Status |
|---|---|---|---|---|---|
| PySide6-Essentials 6.12.0 | Qt 6 bindings (QtCore/QtGui/QtWidgets only) | Desktop UI with native Persian/RTL support; worker threads keep the UI responsive | LGPL-3.0 | part of the 250 MB venv below | installed |
| jdatetime 6.1.1 | Jalali (Shamsi) date handling | School years and date display; leap-Esfand/year-boundary tested | MIT (verified on PyPI) | part of the 250 MB venv below | installed |
| qrcode 8.2 | Generates QR codes as pure-Python SVG (no Pillow needed) | The share dialog shows a QR of the phone URL — scanning it beats typing `http://192.168.x.y:port/` on a phone keyboard, especially on demo day | BSD (verified on PyPI and `pip show`) | 455 kB installed + 208 kB for its one dependency `colorama` (measured on the dev laptop, 2026-10-25) | installed 2026-10-25 |
| pytest 9.1.1 | Test runner | Automated tests for every critical algorithm | MIT | part of the 250 MB venv below | installed (dev only) |
| PyInstaller 6.22.3 | Bundles Python + app into a Windows executable (onedir) | End users must not need Python installed | GPLv2 with bootloader exception (built app unrestricted) | part of the 270 MB venv below | installed (dev only) |
| Inno Setup 6.7.3 (dev/machine tool) | Builds `dist\DarsPack-Setup.exe` from `installer\DarsPack.iss` | Official per-user setup.exe for classmates (Start Menu, optional desktop icon, Add/Remove entry) wrapping the onedir folder; no admin needed | Inno Setup License (free for commercial use, `license.txt` in the installed folder) | 34 MB installed, 122 files (measured 2026-11-09) | installed 2026-11-09 (dev only) |

### Bundled UI assets (not Python packages)

| Asset | What it does | Why DarsPack needs it | Licence | Measured size | Status |
|---|---|---|---|---|---|
| Vazirmatn 33.003, static weights Regular/Medium/SemiBold/Bold | Persian-first typeface | The UI's default font: proper Persian shaping and a consistent, modern look. Bundled so target PCs do not need it installed; falls back to Segoe UI if a file ever fails to load. | SIL OFL-1.1 (`assets/fonts/OFL.txt`) | 482 kB for four TTFs + 4.3 kB licence (2026-10-29) | bundled 2026-10-29 |
| Lucide 0.468.0, 38 SVG icons | Consistent line icons for the toolbar, menus and file rows | One visual language instead of text-only buttons; 20 px SVGs are crisp on every DPI. No icon font and no pip package. | ISC (`assets/icons/LICENSE`) | 15 kB for 38 SVGs + 3.2 kB licence (measured 2026-11-12) | bundled 2026-10-29; +8 icons 2026-11-09; +6 icons 2026-11-12 |

**Whole development environment: 270 MB** (`.venv/` including all of the above). Built output: 105 MB app folder, `DarsPack.exe` 2.65 MB **plus a second headless `DarsPackMcp.exe` 2.26 MB** for the MCP server, both sharing the same `_internal` folder (measured 2026-11-14) — see `docs/limitations.md` for measured numbers. The MCP server and the `--selftest` / `--print-config` flags add **no new packages**: only the standard library (`argparse`, `json`, `sys`, `pathlib`, `sqlite3`). The full `PySide6` distribution is intentionally NOT installed — its Addons half (WebEngine, 3D, multimedia, …) would add hundreds of megabytes DarsPack never uses; `PySide6-Essentials` ships exactly the widgets we need.

Everything else is the Python standard library: `sqlite3`, `hashlib`, `zipfile`, `http.server`, `json`, `threading`, `hmac`, `tempfile`. No other third-party packages are planned for v1; adding one requires an entry here first and a size check.

Dev-machine tools (not app dependencies): Node.js is used only by the test suite to syntax-check the phone client's JavaScript (`node --check` in `tests/test_web_client.py`); the app itself never touches it.
