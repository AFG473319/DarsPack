# Dependency Register

Project rule: every dependency gets an entry here **before** it is installed — what it does, why it is needed, its licence, and its measured size. Sizes below marked *planned* are replaced with real numbers at install time.

| Package | What it does | Why DarsPack needs it | Licence | Size (installed) | Status |
|---|---|---|---|---|---|
| PySide6 | Qt 6 bindings for Python: widgets, RTL layout direction, QThreads | Desktop UI with native Persian/RTL support; hashing runs off the UI thread so the interface never freezes | LGPL-3.0 | *planned — measure at install (expect 150–300 MB)* | planned |
| jdatetime | Jalali (Shamsi) date conversion | School years and date display; tested for leap Esfand and year boundaries | MIT (verify at install) | *planned — tiny (<1 MB)* | planned |
| pytest | Test runner | Automated tests for every critical algorithm | MIT | dev-only | planned |
| PyInstaller | Bundles Python + app into a Windows executable | End users must not need Python installed | GPLv2 with bootloader exception (built app unrestricted) | dev-only | planned (M9) |

Everything else is the Python standard library: `sqlite3`, `hashlib`, `zipfile`, `http.server`, `json`, `threading`, `hmac`, `tempfile`. No other third-party packages are planned for v1; adding one requires an entry here first and a size check (target laptop has ~8.8 GB free).
