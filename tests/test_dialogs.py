"""안내·확인 창 시험: 단추가 영어(Yes/No/OK)가 아니라 우리말로 나오는지."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from hwik.ui import dialogs


def labels(box: QMessageBox) -> list[str]:
    return [button.text() for button in box.buttons()]


def test_notice_has_one_korean_button(qapp: object) -> None:
    box = dialogs.build_notice(None, "받는 곳으로 쓸 수 없습니다.", QMessageBox.Icon.Warning)

    assert labels(box) == ["확인"]
    assert box.text() == "받는 곳으로 쓸 수 없습니다."


def test_question_buttons_say_what_they_do(qapp: object) -> None:
    box, yes = dialogs.build_question(None, "Hwik을 제거할까요?", "제거")

    assert labels(box) == ["제거", "취소"]
    assert yes.text() == "제거"
    assert box.defaultButton().text() == "취소"  # 엔터를 잘못 눌러도 지워지지 않게
