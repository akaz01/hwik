"""안내·확인 창. Qt의 기본 단추는 번역 파일이 없으면 영어(Yes/No/OK)로 나오므로, 단추 글자를 직접 정한다."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QMessageBox, QWidget

from hwik import DISPLAY_NAME

OK = "확인"
CANCEL = "취소"


def build_notice(parent: QWidget | None, text: str, icon: QMessageBox.Icon) -> QMessageBox:
    box = QMessageBox(icon, DISPLAY_NAME, text, QMessageBox.StandardButton.NoButton, parent)
    box.addButton(OK, QMessageBox.ButtonRole.AcceptRole)
    return box


def build_question(parent: QWidget | None, text: str, yes: str) -> tuple[QMessageBox, QAbstractButton]:
    """예 단추에는 하는 일을 적는다("제거" 등). 기본 단추는 취소다."""
    box = QMessageBox(QMessageBox.Icon.Question, DISPLAY_NAME, text, QMessageBox.StandardButton.NoButton, parent)
    yes_button = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    no_button = box.addButton(CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no_button)
    box.setEscapeButton(no_button)
    return box, yes_button


def inform(parent: QWidget | None, text: str) -> None:
    build_notice(parent, text, QMessageBox.Icon.Information).exec()


def warn(parent: QWidget | None, text: str) -> None:
    build_notice(parent, text, QMessageBox.Icon.Warning).exec()


def fail(parent: QWidget | None, text: str) -> None:
    build_notice(parent, text, QMessageBox.Icon.Critical).exec()


def ask(parent: QWidget | None, text: str, yes: str) -> bool:
    box, yes_button = build_question(parent, text, yes)
    box.exec()
    return box.clickedButton() is yes_button
