"""설치 창과 제거 창. 내려받아 푼 폴더에서 Hwik.exe를 처음 실행하면 설치 창이 뜬다."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from hwik import DISPLAY_NAME, TASKBAR_ID, __version__, selfinstall
from hwik.tray import draw_icon, make_icon
from hwik.ui import dialogs, theme
from hwik.ui.toggle import Toggle

logger = logging.getLogger(__name__)

DIALOG_WIDTH = 300
ICON_SIZE = 64
SETUP_STYLE = f"""
QDialog {{ background: {theme.PAPER}; }}
QLabel {{ color: {theme.INK}; }}
QLabel#note {{ color: {theme.MUTED}; }}
QPushButton#install {{
    padding: 10px; border: 2px solid transparent; border-radius: 11px;
    background: {theme.COBALT}; color: {theme.WHITE};
}}
QPushButton#install:hover {{ background: {theme.DEEP}; }}
QPushButton#install:focus {{ border-color: {theme.INK}; }}
QPushButton#install:disabled {{ background: {theme.DISABLED_TEXT}; }}
QProgressBar {{ border: none; border-radius: 3px; background: {theme.LINE}; max-height: 6px; }}
QProgressBar::chunk {{ border-radius: 3px; background: {theme.COBALT}; }}
"""


def _app() -> QApplication:
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(TASKBAR_ID)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(make_icon())
    return app  # type: ignore[return-value]


class SetupDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        updating = selfinstall.is_installed()
        self.setWindowTitle(f"{DISPLAY_NAME} 설치")
        self.setFixedWidth(DIALOG_WIDTH)
        self.setStyleSheet(SETUP_STYLE)
        self.installed: selfinstall.Installed | None = None

        icon = QLabel()
        sharp = draw_icon(ICON_SIZE * 2)  # 배율이 높은 화면에서도 또렷하게 두 배로 그려 넣는다
        sharp.setDevicePixelRatio(2)
        icon.setPixmap(sharp)
        title = QLabel(f"{DISPLAY_NAME} {__version__}")
        title.setFont(theme.font(20, QFont.Weight.Bold))
        note = QLabel("휴대폰과 PC 사이에 사진·파일·글자를 QR 하나로 주고받습니다.", objectName="note")
        note.setFont(theme.font(12))
        note.setWordWrap(True)
        self._desktop = Toggle("바탕 화면에 바로가기 만들기")
        self._desktop.setFont(theme.font(12, QFont.Weight.DemiBold))
        self._desktop.setChecked(True)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._button = QPushButton("업데이트" if updating else "설치", objectName="install")
        self._button.setFont(theme.font(13, QFont.Weight.Bold))
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self._install)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(0)
        layout.addWidget(icon)
        layout.addSpacing(12)
        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addWidget(note)
        layout.addSpacing(18)
        layout.addWidget(self._desktop)
        layout.addSpacing(16)
        layout.addWidget(self._progress)
        layout.addSpacing(8)
        layout.addWidget(self._button)

    def _on_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)
        QApplication.processEvents()  # 복사하는 동안에도 창이 멈춘 것처럼 보이지 않게

    def _install(self) -> None:
        self._button.setEnabled(False)
        self._button.setText("설치하는 중…")
        self._desktop.setEnabled(False)
        self._progress.setVisible(True)
        try:
            self.installed = selfinstall.install(self._desktop.isChecked(), self._on_progress)
        except (OSError, ValueError) as err:
            logger.error("설치하지 못했습니다: %s", err)
            dialogs.fail(self, f"설치하지 못했습니다.\n\n{err}")
            self._button.setEnabled(True)
            self._button.setText("다시 시도")
            self._desktop.setEnabled(True)
            self._progress.setVisible(False)
            return
        if self.installed.warnings:
            dialogs.warn(self, "\n".join(self.installed.warnings))
        self.accept()


def run_setup_dialog() -> int:
    """설치 창을 띄우고, 설치가 끝나면 설치된 Hwik을 켠다."""
    app = _app()
    dialog = SetupDialog()
    dialog.exec()
    if dialog.installed is None:
        return 1  # 설치하지 않고 닫음
    selfinstall.launch_installed(dialog.installed.folder)
    del app
    return 0


def run_uninstall_dialog() -> int:
    """Windows '설치된 앱'에서 제거를 누르면 뜬다."""
    app = _app()
    question = f"{DISPLAY_NAME}을 제거할까요?\n\n휴대폰에서 받은 파일은 그대로 남습니다."
    if not dialogs.ask(None, question, "제거"):
        return 1
    selfinstall.uninstall()
    dialogs.inform(None, f"{DISPLAY_NAME}을 제거했습니다.")
    selfinstall.remove_after_exit()
    del app
    return 0
