"""Tests for the i18n dictionaries (دوزبانه — a scored requirement).

The whole mechanism is two plain dicts and one lookup; what must never
break is fa/en parity (a key added to one language but not the other
would show raw English text in the Persian UI, or vice versa) and the
language switch restoring cleanly — the dialogs read the module-global
language, so a test that leaves it on English would silently turn every
later dialog test English too.
"""
from darspack import i18n


def test_fa_and_en_have_exactly_the_same_keys():
    assert set(i18n.STRINGS["fa"]) == set(i18n.STRINGS["en"])


def test_every_string_is_nonempty_text():
    for lang, strings in i18n.STRINGS.items():
        for key, value in strings.items():
            assert isinstance(value, str) and value.strip(), f"{lang}:{key}"


def test_tr_switches_to_english_and_back():
    i18n.set_language("en")
    try:
        assert i18n.tr("app_title") == "DarsPack"
    finally:
        i18n.set_language("fa")      # restore: later tests must stay Persian
    assert i18n.tr("app_title") == "درس‌پک"


def test_unknown_key_falls_back_to_the_key_itself():
    assert i18n.tr("no_such_key") == "no_such_key"


def test_num_formats_digits_for_the_active_language():
    """i18n.num() is the one place UI numbers become Persian digits —
    English stays Latin, Persian uses ۰-۹."""
    assert i18n.num(3) == "۳"
    assert i18n.num("1405-1406") == "۱۴۰۵-۱۴۰۶"
    i18n.set_language("en")
    try:
        assert i18n.num(3) == "3"
    finally:
        i18n.set_language("fa")
    assert i18n.num(3) == "۳"


def test_invalid_language_code_stays_persian():
    i18n.set_language("xx")
    try:
        assert i18n.language() == "fa"
        assert i18n.tr("app_title") == "درس‌پک"
    finally:
        i18n.set_language("fa")
