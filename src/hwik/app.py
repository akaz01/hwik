"""프로그램 시작: 창과 시계 옆 아이콘을 만들고 서로 잇는다."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from hwik import APP_NAME, DISPLAY_NAME, TASKBAR_ID, settings, single_instance
from hwik.tray import Tray
from hwik.ui.main_window import MainWindow

LOG_BYTES = 1_000_000 # 기록 파일 하나의 크기 한도(넘으면 하나만 남기고 새로 쓴다)


def _setup_log() -> None:
    """다른 PC에서 생긴 문제를 찾을 수 있게 경고 이상을 %LOCALAPPDATA%\\<앱>\\app.log 에 남긴다."""
    folder = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            folder / "app.log", maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8"
        )
    except OSError:
        return  # 기록을 못 남겨도 프로그램은 실행한다
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    # 창 없이 도는 프로그램이라, 처리하지 못한 오류가 흔적 없이 사라지지 않게 기록에 남긴다.
    sys.excepthook = lambda kind, value, trace: logging.getLogger(APP_NAME).error(
        "처리하지 못한 오류", exc_info=(kind, value, trace)
    )


def _use_own_taskbar_identity() -> None:
    """작업 표시줄이 이 프로그램을 python.exe가 아니라 따로 된 앱으로 보게 한다(그래야 우리 아이콘이 나온다)."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(TASKBAR_ID)
    except (AttributeError, OSError) as err:
        logging.getLogger(__name__).warning("작업 표시줄 식별값을 정하지 못했습니다: %s", type(err).__name__)


def _show(window: MainWindow) -> None:
    window.showNormal()
    window.raise_()
    window.activateWindow()


def main() -> int:
    if sys.platform != "win32":
        sys.stderr.write(f"{DISPLAY_NAME}은(는) Windows 전용입니다.\n")
        return 1
    _setup_log()
    _use_own_taskbar_identity()  # 창을 만들기 전에 해야 한다
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    # 창을 닫아도 시계 옆 아이콘은 남는다. 아이콘을 띄울 수 없는 환경에서는 창을 닫으면 끝낸다.
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    if single_instance.already_running():
        single_instance.ask_running_instance_to_show()
        return 0

    window = MainWindow(settings.load())
    tray = Tray()
    app.setWindowIcon(tray.icon())
    window.setWindowIcon(tray.icon())
    show_channel = single_instance.listen_for_show_requests(lambda: _show(window))

    def notify_if_hidden(summary: str) -> None:
        if not window.isActiveWindow():
            tray.notify(summary)

    def quit_app() -> None:
        window.disconnect_phone()
        tray.hide()
        show_channel.close()
        app.quit()

    window.batch_settled.connect(notify_if_hidden)
    tray.open_requested.connect(lambda: _show(window))
    tray.folder_requested.connect(window.open_save_folder)
    tray.quit_requested.connect(quit_app)
    app.aboutToQuit.connect(window.disconnect_phone)
    tray.show()
    _show(window)
    return app.exec()
