"""Resolve a launch command for the DarsPack MCP server that actually works.

Why this module exists
----------------------
The Help Center used to hand agents the literal command
``"<python>" -m darspack.mcp``.  That command failed in the two ways
DarsPack actually runs:

1. **Source checkout** - ``darspack`` lives in ``src/`` and is not
   installed, so Python answers ``ModuleNotFoundError: No module named
   'darspack'``.  The command needs ``src/`` on ``PYTHONPATH``.
2. **Packaged app** - ``sys.executable`` is ``DarsPack.exe``, so the
   "command" started the desktop GUI (Qt, a window, heavy) instead of a
   stdio server, and the agent never got a reply.

Both cases are resolved here, once, so the copied prompt, the JSON
snippets and the Help Center all describe the same working command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys

#: Console executable produced by ``installer/darspack.spec`` next to the
#: GUI exe.  It bundles only ``darspack.core`` + ``darspack.mcp`` (no Qt),
#: so an agent that starts it gets a small stdio process, never a window.
SERVER_EXE_NAME = "DarsPackMcp.exe"

#: Default location of the library, mirrors ``server.DEFAULT_LIBRARY_PATH``.
DEFAULT_LIBRARY_PATH = Path.home() / "Documents" / "DarsPackLibrary"


@dataclass(frozen=True)
class McpLaunch:
    """A ready-to-use ``command + args + env`` triple for an MCP client."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: ``"frozen"`` (bundled server exe), ``"python"`` (source/installed
    #: module) or ``"unavailable"`` (packaged app without the server exe).
    mode: str = "python"
    note: str = ""

    @property
    def available(self) -> bool:
        return self.mode != "unavailable"

    @property
    def argv(self) -> list[str]:
        return [self.command, *self.args]

    def command_line(self) -> str:
        """Single copy-pasteable line for a terminal (quoted for Windows)."""
        return " ".join(_quote(part) for part in self.argv)

    def selftest_line(self) -> str:
        """Copy-pasteable one-shot health check an agent can run first."""
        return f"{self.command_line()} --selftest"

    def to_mcp_server(self) -> dict:
        """Entry for the ``mcpServers`` block used by Claude/Cursor/VS Code."""
        entry: dict = {"command": self.command, "args": list(self.args)}
        if self.env:
            entry["env"] = dict(self.env)
        return entry

    def to_opencode_server(self) -> dict:
        """Entry for OpenCode v2, where ``command`` is one joined array."""
        entry: dict = {"type": "local", "command": self.argv}
        if self.env:
            entry["environment"] = _env_with_env_substitution(self.env)
        return entry


def _quote(part: str) -> str:
    """Quote a path for cmd/PowerShell only when it actually needs it."""
    if part and not any(ch.isspace() for ch in part) and '"' not in part:
        return part
    return f'"{part}"'


def _env_with_env_substitution(env: dict[str, str]) -> dict[str, str]:
    """Absolute paths only, so OpenCode's ``{env:...}`` syntax is not needed."""
    return dict(env)


def resolve_library_path(library_path: Path | str | None = None) -> Path:
    """Return the library the server must open, as an absolute path."""
    if library_path:
        return Path(library_path).expanduser().resolve()
    return DEFAULT_LIBRARY_PATH.resolve()


def _package_parent() -> Path | None:
    """Directory that must be on ``PYTHONPATH`` for ``import darspack``.

    In a source checkout that is ``<repo>/src``; for a ``pip install``ed
    copy it is ``site-packages``, which is harmless to add again.
    """
    try:
        import darspack  # imported lazily to keep this module import-light
    except Exception:
        return None
    try:
        return Path(darspack.__file__).resolve().parent.parent
    except Exception:
        return None


def _find_server_exe() -> Path | None:
    """Locate ``DarsPackMcp.exe`` inside a frozen (installed) build."""
    candidates: list[Path] = []
    exe = getattr(sys, "executable", "") or ""
    if exe:
        candidates.append(Path(exe).with_name(SERVER_EXE_NAME))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / SERVER_EXE_NAME)
    candidates.append(Path(sys.argv[0]).resolve().with_name(SERVER_EXE_NAME))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_launch(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> McpLaunch:
    """Build the working launch triple for the current install.

    ``python_path`` is only honoured in source/installed mode; it exists so
    tests and the Help Center can pin a specific interpreter.
    """
    library = resolve_library_path(library_path)
    tail = ["--library", str(library)]

    if getattr(sys, "frozen", False):
        server_exe = _find_server_exe()
        if server_exe is None:
            return McpLaunch(
                command="",
                mode="unavailable",
                note=(
                    f"{SERVER_EXE_NAME} is missing next to {Path(sys.executable).name}. "
                    "Rebuild or reinstall DarsPack so the MCP server ships with the app."
                ),
            )
        return McpLaunch(command=str(server_exe), args=tail, mode="frozen")

    python = python_path or sys.executable or "python"
    env: dict[str, str] = {}
    src = _package_parent()
    if src is not None:
        env["PYTHONPATH"] = str(src)
    return McpLaunch(
        command=python,
        args=["-m", "darspack.mcp", *tail],
        env=env,
        mode="python",
    )


def build_mcp_config(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> dict:
    """Standard ``mcpServers`` configuration for Claude/Cursor/VS Code."""
    launch = resolve_launch(library_path, python_path)
    return {"mcpServers": {"darspack": launch.to_mcp_server()}}


def build_opencode_config(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> dict:
    """OpenCode v2 configuration (``mcp.servers``, joined ``command`` array)."""
    launch = resolve_launch(library_path, python_path)
    return {"mcp": {"servers": {"darspack": launch.to_opencode_server()}}}


def build_selftest_command(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> str:
    """One-line verification an agent can run before registering anything."""
    return resolve_launch(library_path, python_path).selftest_line()


def config_json(config: dict) -> str:
    """Pretty JSON without escaping Persian text."""
    return json.dumps(config, indent=2, ensure_ascii=False)
