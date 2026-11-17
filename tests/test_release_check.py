"""Tests for the release tag consistency gate (scripts/check_release_tag.py).

The gate runs right before a GitHub Release is published; these tests pin
its rules so a bad tag (or a forgotten version bump) can never slip through.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "check_release_tag", REPO / "scripts" / "check_release_tag.py")
rc = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("check_release_tag", rc)
_SPEC.loader.exec_module(rc)


# --- parse_tag: accepted shapes --------------------------------------------

def test_stable_tag_parses():
    assert rc.parse_tag("v0.2.1") == ("0.2.1", None)


def test_beta_tag_parses_with_suffix():
    assert rc.parse_tag("v0.2.2-beta.1") == ("0.2.2", "beta.1")
    assert rc.parse_tag("v1.0.0-rc.3") == ("1.0.0", "rc.3")
    assert rc.parse_tag("v1.0.0-alpha.12") == ("1.0.0", "alpha.12")


# --- parse_tag: rejected shapes --------------------------------------------

@pytest.mark.parametrize("bad", [
    "0.2.1",            # no v prefix
    "V0.2.1",           # uppercase V
    "v0.2",             # two-part version
    "v0.2.1.1",         # four-part version
    "v0.2.1-beta",      # suffix without a counter
    "v0.2.1-final",     # unknown suffix word
    "v0.2.1 - beta.1",  # spaces
])
def test_malformed_tags_are_rejected(bad):
    with pytest.raises(ValueError, match="not a release tag"):
        rc.parse_tag(bad)


def test_zero_pre_release_counter_is_rejected():
    # beta.0 parses as a tag shape but the counter must start at 1.
    with pytest.raises(ValueError, match="counter must start at 1"):
        rc.parse_tag("v0.2.1-beta.0")


# --- check: agreement rules --------------------------------------------------

def _iss(version):
    return f"#define MyAppVersion \"{version}\"\nAppVersion={version}\n"


def _iss_version(version):
    return rc.read_iss_app_version(_iss(version))


def test_iss_parser_resolves_the_preprocessor_define():
    assert _iss_version("0.2.1") == "0.2.1"


def test_consistent_stable_release_passes():
    assert rc.check("v0.2.1", "0.2.1", _iss_version("0.2.1")) == []


def test_consistent_beta_release_passes():
    # Beta tags pair with the full suffixed __version__ and the numeric
    # base in the Inno installer.
    assert rc.check("v0.2.2-beta.1", "0.2.2-beta.1", _iss_version("0.2.2")) == []


def test_forgotten_version_bump_is_caught():
    problems = rc.check("v0.2.2", "0.2.1", _iss_version("0.2.1"))
    assert any("__version__" in p for p in problems)
    assert any("AppVersion" in p for p in problems)


def test_beta_tag_with_numeric_version_mismatch_is_caught():
    problems = rc.check("v0.2.2-beta.1", "0.2.1", _iss_version("0.2.2"))
    assert any("__version__" in p for p in problems)


def test_iss_must_carry_numeric_base_only():
    # Inno's AppVersion must be numeric-only: a beta suffix there is wrong
    # even though it looks consistent with the tag.
    problems = rc.check("v0.2.2-beta.1", "0.2.2-beta.1",
                        _iss_version("0.2.2-beta.1"))
    assert any("AppVersion" in p for p in problems)


def test_stable_tag_rejected_while_version_still_has_suffix():
    # Cutting v0.2.2 while __version__ is still 0.2.2-beta.1 would publish
    # a "stable" whose app still displays the beta string.
    problems = rc.check("v0.2.2", "0.2.2-beta.1", _iss_version("0.2.2"))
    assert any("stable" in p for p in problems)


# --- the real files must pass with the real current version ------------------

def test_current_repo_state_is_releasable():
    """The check must pass for the version actually in the repo — this keeps
    the gate and the version sources in sync after any manual bump."""
    init_text = (REPO / "src" / "darspack" / "__init__.py").read_text(
        encoding="utf-8")
    iss_text = (REPO / "installer" / "DarsPack.iss").read_text(
        encoding="utf-8")
    version = rc.read_app_version(init_text)
    problems = rc.check(f"v{version}", version,
                        rc.read_iss_app_version(iss_text))
    assert problems == []
