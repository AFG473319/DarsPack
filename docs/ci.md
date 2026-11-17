# CI and releases

GitHub Actions runs four checks on every push to `main`, every pull request, and on demand (`.github/workflows/ci.yml`). Windows is the supported target platform, so the checks run on Windows runners; on a public repository those runners are free.

| Job | What it does |
|---|---|
| **tests** | The full pytest suite on both supported Python versions — 3.12 (the declared floor in `pyproject.toml`) and 3.14 (the development machine). Qt runs headless (`QT_QPA_PLATFORM=offscreen`, also set in `tests/conftest.py`). A `coverage.xml` report is published as an artifact so it is always visible which lines the tests execute. |
| **lint** | `ruff check .` with a deliberately gentle, bug-catching-only ruleset (`ruff.toml`): syntax errors, undefined names, unused imports/variables. No formatting rules — the codebase predates the linter, and a clean run must stay meaningful instead of drowning in style churn. |
| **build** | The real Windows build, proving packaging never breaks: creates the `.venv` that `installer/build.bat` expects, runs PyInstaller (onedir app + headless `DarsPackMcp.exe`) and the Inno Setup installer (preinstalled on the runner), zips the portable folder and uploads `DarsPack-windows.zip` + `DarsPack-Setup.exe` as downloadable artifacts (kept 14 days). |
| **hygiene** | A guard that fails if any file that must stay out of git is ever committed (working notes, respondent data, …). The list of guarded paths lives in the repo secret `GUARDED_PATHS` (newline-separated paths), so the workflow file itself reveals nothing about what is guarded. |

Node.js — preinstalled on the runners — covers the phone-client JavaScript syntax checks in `tests/test_web_client.py`; those tests skip gracefully when Node is absent (e.g. on a machine without it).

## Releases (`.github/workflows/release.yml`)

Releases are tag-driven and follow the standard GitHub two-channel convention:

- **Stable:** push tag `vX.Y.Z` (e.g. `v0.2.2`) → release named «DarsPack X.Y.Z», marked **Latest** by GitHub automatically.
- **Beta:** push tag `vX.Y.Z-beta.N` (e.g. `v0.2.2-beta.1`, counter from 1) → release named «DarsPack X.Y.Z-beta.1», published as a **Pre-release** — it never takes the Latest badge. (`-alpha.N` / `-rc.N` behave the same way.)

Every release pipeline run: full test suite → **version consistency gate** (`scripts/check_release_tag.py`: the tag, `__version__` in `src/darspack/__init__.py` and `AppVersion` in `installer/DarsPack.iss` must all agree, with the app displaying exactly what the tag says) → PyInstaller + Inno Setup build → `SHA256SUMS.txt` over both artifacts → GitHub Release with `DarsPack-Setup.exe`, `DarsPack-windows.zip` and `SHA256SUMS.txt` attached.

To cut a release:

1. Bump `__version__` (`src/darspack/__init__.py`) and `MyAppVersion` (`installer/DarsPack.iss`, numeric-only) in one commit; let CI go green.
2. `git tag v0.2.2-beta.1 && git push origin v0.2.2-beta.1` — the beta publishes as a Pre-release.
3. After the beta is confirmed, set `__version__` back to the plain number and tag `v0.2.2` — that release becomes Latest.

The pipeline can be rehearsed without publishing anything: run the Release workflow manually (Actions → Release → Run workflow) with **dry_run** enabled (the default) — it tests, builds and uploads artifacts but creates no release.
