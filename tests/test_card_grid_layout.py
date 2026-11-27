"""Regression: in grid view the subject/kind chips must stay small chips.

Bug (2026-11-27): with one or two files the QGridLayout gave all spare
height to the only row, so the card stretched to the viewport height and
the chip labels grew into two tall vertical bars.
"""
import pytest
from PySide6.QtWidgets import QFrame, QLabel

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.ui import main_window as mw_module


@pytest.mark.parametrize("meta", [
    {"subject": "ریاضی", "kind": "جزوه"},   # subject + kind chips
    {},                                       # unclassified file
], ids=["with_subject_and_kind", "no_subject"])
def test_grid_card_chips_stay_small(tmp_path, qapp, meta):
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه ریاضی فصل 1.pdf"
        src.write_bytes(b"grid card content")
        import_file(lib, src, meta=meta)
        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            win.resize(1100, 800)
            win.show()
            win._set_view_mode("cards")
            qapp.processEvents()

            cards = [w for w in win.card_container.findChildren(QFrame)
                     if w.objectName() == "FileCard"]
            chips = [w for w in win.card_container.findChildren(QLabel)
                     if w.objectName() in ("CardSubjChip", "CardKindChip")]
            assert len(cards) == 1
            assert chips, "the kind chip is always shown"
            for chip in chips:
                # one line of 8pt text plus padding, never a tall bar
                assert chip.height() <= chip.sizeHint().height() + 2
                assert chip.height() < 40
            # the card keeps its natural height instead of filling the view
            assert cards[0].height() < win.card_scroll.viewport().height() / 2
        finally:
            win.close()
            win.lib.close()
