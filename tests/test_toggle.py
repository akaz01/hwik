"""켜고 끄는 스위치 부품 시험."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from hwik.ui.toggle import SWITCH_HEIGHT, Toggle


def test_clicking_anywhere_on_the_row_flips_the_switch(qapp: object) -> None:
    toggle = Toggle("받으면 바로 복사")
    toggle.resize(260, toggle.sizeHint().height())
    toggle.show()
    QGuiApplication.processEvents()
    changes: list[bool] = []
    toggle.toggled.connect(changes.append)

    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))  # 글자 쪽
    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton, pos=QPoint(250, 10))  # 스위치 쪽

    assert changes == [True, False]
    toggle.close()


def test_space_key_flips_the_switch(qapp: object) -> None:
    toggle = Toggle("받으면 바로 복사")
    toggle.show()
    toggle.setFocus()

    QTest.keyClick(toggle, Qt.Key.Key_Space)

    assert toggle.isChecked()
    toggle.close()


def test_row_is_tall_enough_for_switch_and_draws_in_both_states(qapp: object) -> None:
    toggle = Toggle("받으면 바로 복사")
    toggle.resize(260, toggle.sizeHint().height())

    off = toggle.grab().toImage()
    toggle.setChecked(True)
    on = toggle.grab().toImage()

    assert toggle.sizeHint().height() >= SWITCH_HEIGHT
    assert off != on  # 켜짐과 꺼짐이 눈으로 구별된다
