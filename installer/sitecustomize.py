"""배포본의 Hwik.exe(= Python 재단이 서명한 pythonw.exe를 이름만 바꾼 것)로 실행될 때 앱을 시작한다.

Windows의 스마트 앱 컨트롤은 서명도 평판도 없는 exe를 막는다. 직접 만든 exe 대신 서명된 pythonw.exe를
그대로 쓰되, 인자 없이(더블클릭·바로가기) 실행되면 Python이 할 일을 고르기 전에 여기서 앱(처음이면 설치 창)을
띄우고 끝낸다. `Hwik.exe -m hwik --uninstall`처럼 Python 옵션으로 시작하면 손대지 않는다.
build.ps1이 배포본의 app 폴더(sys.path에 있음)에 복사한다.
"""
import os
import sys


def _launch() -> None:
    if os.path.basename(sys.executable).lower() in ("python.exe", "pythonw.exe"):
        return  # 개발 환경 등: 평소의 Python으로 둔다
    args = sys.orig_argv[1:]
    if args and args[0].startswith("-"):
        return
    sys.argv = [sys.executable, *args]
    from hwik.launch import run

    os._exit(run())  # 여기서 끝내야 Python이 대화형으로 넘어가지 않는다


_launch()
