"""시험 공통 준비: 화면 시험은 창을 띄우지 않고 돌리고, 설정은 임시 폴더에 쓴다."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # PySide6를 불러오기 전에 정해야 한다


@pytest.fixture(scope="session")
def qapp() -> Iterator[object]:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # 화면 없는 방식에서는 클립보드에 무언가 담긴 채 끝나면 프로그램이 종료하며 죽는다(실제 Windows 화면 방식은 괜찮다).
    app.clipboard().clear()
    app.processEvents()


@pytest.fixture(autouse=True)
def isolated_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """시험이 실제 사용자 설정 파일을 건드리지 않게 한다."""
    monkeypatch.setenv("APPDATA", str(tmp_path_factory.mktemp("appdata")))
