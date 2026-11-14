"""Hwik.exe(이름만 바꾼 서명된 pythonw.exe)의 시작점: 설치 폴더 밖이면 설치 창, 안이면 앱.

installer/sitecustomize.py가 부른다. 돌려주는 값은 종료 코드.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import traceback

from hwik import DISPLAY_NAME

MIN_WINDOWS_BUILD = 17763  # Windows 10 1809: 화면 부품(Qt 6)이 요구한다
WARNING_ICON = 0x30
ERROR_ICON = 0x10


def _message(text: str, icon: int) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, DISPLAY_NAME, icon)


def _windows_too_old() -> bool:
    """Qt를 불러오기 전에 Windows 기본 안내 창으로 알린다(오래된 Windows에서는 Qt 6이 아예 뜨지 않는다)."""
    if sys.getwindowsversion().build >= MIN_WINDOWS_BUILD:
        return False
    _message(f"{DISPLAY_NAME}은 Windows 10(1809 이상) 또는 Windows 11에서 실행됩니다.", WARNING_ICON)
    return True


def run() -> int:
    if _windows_too_old():
        return 1
    try:
        from hwik import selfinstall

        if selfinstall.needs_install():  # 내려받아 푼 폴더에서 실행: 사용자 폴더에 설치(또는 업데이트)
            from hwik.ui.setup_dialog import run_setup_dialog

            return run_setup_dialog()
        from hwik.app import main

        return main()
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    except Exception:  # 창이 없는 프로그램이라, 시작하다 죽으면 아무 일도 안 일어난 것처럼 보인다
        logging.getLogger(__name__).exception("시작하지 못했습니다")
        last_line = traceback.format_exc().strip().splitlines()[-1]
        _message(f"{DISPLAY_NAME}을 시작하지 못했습니다.\n\n{last_line}", ERROR_ICON)
        return 1
    finally:
        logging.shutdown()  # 부르는 쪽이 os._exit로 끝내므로 기록을 여기서 비운다
