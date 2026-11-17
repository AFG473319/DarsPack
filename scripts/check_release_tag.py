"""Release consistency gate (دروازه‌ی سازگاری نسخه) — run before publishing.

Verifies that the git tag, the app version and the Inno installer version
all agree, so a release can never go out with mismatched numbers.

Usage (from a tag-push workflow or locally):
    python scripts/check_release_tag.py v0.2.2-beta.1

Rules enforced:
1. Tag format: vMAJOR.MINOR.PATCH, optionally followed by a pre-release
   suffix ``-alpha.N`` / ``-beta.N`` / ``-rc.N`` (N >= 1). The suffix is
   what makes GitHub publish the release as a Pre-release; a plain tag
   becomes the project's "Latest" release.
2. The version part must equal ``__version__`` in ``src/darspack/__init__.py``
   — the exact string the app displays.
3. The numeric base (version without the suffix) must equal ``AppVersion``
   in ``installer/DarsPack.iss`` — Inno Setup requires numeric-only
   versions there.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TAG_RE = re.compile(
    r"^v(?P<base>\d+\.\d+\.\d+)(?:-(?P<pre>alpha|beta|rc)\.(?P<num>\d+))?$"
)

ISS_APPVERSION_RE = re.compile(r'^AppVersion=(?P<value>\S+)\s*$', re.M)


def parse_tag(tag: str) -> tuple[str, str | None]:
    """Return (numeric_base, pre-release suffix or None); raise ValueError
    with a human-readable message if the tag is not a release tag."""
    m = TAG_RE.match(tag)
    if not m:
        raise ValueError(
            f"{tag!r} is not a release tag. Expected vMAJOR.MINOR.PATCH "
            f"optionally followed by -alpha.N / -beta.N / -rc.N (N >= 1), "
            f"e.g. v0.2.2 or v0.2.2-beta.1")
    base, pre, num = m.group("base"), m.group("pre"), m.group("num")
    if pre and int(num) < 1:
        raise ValueError(f"{tag!r}: the pre-release counter must start at 1, "
                         f"not {num!r}")
    return base, (f"{pre}.{num}" if pre else None)


def read_app_version(init_text: str) -> str:
    """Extract __version__ from src/darspack/__init__.py by regex — no
    import, because importing the package would pull in Qt, which a
    release check must not need."""
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.M)
    if not m:
        raise ValueError('__version__ = "..." not found in '
                         "src/darspack/__init__.py")
    return m.group(1)


def read_iss_app_version(iss_text: str) -> str:
    """Extract AppVersion from installer/DarsPack.iss (numeric-only),
    resolving an Inno preprocessor reference ({#MyAppVersion}) to its
    #define value."""
    m = ISS_APPVERSION_RE.search(iss_text)
    if not m:
        raise ValueError("AppVersion=... not found in installer/DarsPack.iss")
    value = m.group("value")
    ref = re.fullmatch(r"\{#(\w+)\}", value)
    if ref:
        define = re.search(
            rf'^#define\s+{ref.group(1)}\s+"([^"]*)"', iss_text, re.M)
        if not define:
            raise ValueError(
                f"{value} used in AppVersion but no #define "
                f"{ref.group(1)} found in installer/DarsPack.iss")
        value = define.group(1)
    return value


def check(tag: str, app_version: str, iss_version: str) -> list[str]:
    """Return a list of problems (empty list = release may be published)."""
    problems: list[str] = []
    base, pre = parse_tag(tag)

    if app_version != tag[1:]:
        # The app must show exactly what the tag says, so a beta tester can
        # read the version off the UI and know which build they run.
        problems.append(
            f"tag {tag} != __version__ {app_version!r} in "
            "src/darspack/__init__.py — bump __version__ first")

    if iss_version != base:
        problems.append(
            f"installer/DarsPack.iss AppVersion {iss_version!r} != "
            f"{base!r} (numeric base of the tag) — Inno needs the "
            "numeric-only version")

    if pre is None and app_version != base:
        problems.append(
            f"tag {tag} is stable (no pre-release suffix) but __version__ "
            f"{app_version!r} still carries a suffix — set __version__ to "
            f"{base!r} before tagging the stable release")

    return problems


def _force_utf8_output() -> None:
    """GitHub Actions Windows runners (and many real Windows consoles) use a
    legacy codepage (cp1252) for stdout. Without reconfiguring, printing the
    ↔ / — in our messages raises UnicodeEncodeError — which on run 44144483339
    killed this script AFTER the check had already passed. errors="replace"
    keeps a hostile console from ever crashing the gate."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _force_utf8_output()
    if len(argv) != 2:
        print("usage: python scripts/check_release_tag.py v0.2.2-beta.1",
              file=sys.stderr)
        return 2
    tag = argv[1]

    init_text = (ROOT / "src" / "darspack" / "__init__.py").read_text(
        encoding="utf-8")
    iss_text = (ROOT / "installer" / "DarsPack.iss").read_text(
        encoding="utf-8")

    try:
        problems = check(tag, read_app_version(init_text),
                         read_iss_app_version(iss_text))
    except ValueError as exc:
        print(f"release check FAILED: {exc}", file=sys.stderr)
        return 1

    if problems:
        print("release check FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    channel = "pre-release" if parse_tag(tag)[1] else "stable (Latest)"
    print(f"release check ok: {tag} ↔ __version__ ↔ installer AppVersion "
          f"agree — will publish as {channel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
