# Dependency Register

Project rule: every dependency is registered here **before** installation — what it does, why it is needed, its licence, and its measured size. Numbers below are measured on the development laptop (Python 3.14.6, Windows 11), 2026-10-24.

| Package | What it does | Why DarsPack needs it | Licence | Installed size | Status |
|---|---|---|---|---|---|
| PySide6-Essentials 6.12.0 | Qt 6 bindings (QtCore/QtGui/QtWidgets only) | Desktop UI with native Persian/RTL support; worker threads keep the UI responsive | LGPL-3.0 | part of the 250 MB venv below | installed |
| jdatetime 6.1.1 | Jalali (Shamsi) date handling | School years and date display; leap-Esfand/year-boundary tested | MIT (verified on PyPI) | part of the 250 MB venv below | installed |
| qrcode 8.2 | Generates QR codes as pure-Python SVG (no Pillow needed) | The share dialog shows a QR of the phone URL — scanning it beats typing `http://192.168.x.y:port/` on a phone keyboard, especially on demo day | BSD (verified on PyPI and `pip show`) | 455 kB installed + 208 kB for its one dependency `colorama` (measured on the dev laptop, 2026-10-25) | installed 2026-10-25 |
| pytest 9.1.1 | Test runner | Automated tests for every critical algorithm | MIT | part of the 250 MB venv below | installed (dev only) |
| PyInstaller 6.22.3 | Bundles Python + app into a Windows executable (onedir) | End users must not need Python installed | GPLv2 with bootloader exception (built app unrestricted) | part of the 270 MB venv below | installed (dev only) |

**Whole development environment: 270 MB** (`.venv/` including all of the above). Built output: 104 MB app folder, 2.4 MB launcher exe — see `docs/limitations.md` for measured numbers. The full `PySide6` distribution is intentionally NOT installed — its Addons half (WebEngine, 3D, multimedia, …) would add hundreds of megabytes DarsPack never uses; `PySide6-Essentials` ships exactly the widgets we need.

Everything else is the Python standard library: `sqlite3`, `hashlib`, `zipfile`, `http.server`, `json`, `threading`, `hmac`, `tempfile`. No other third-party packages are planned for v1; adding one requires an entry here first and a size check.

Dev-machine tools (not app dependencies): Node.js is used only by the test suite to syntax-check the phone client's JavaScript (`node --check` in `tests/test_web_client.py`); the app itself never touches it.
