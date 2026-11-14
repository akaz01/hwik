"""python -m hwik 로 실행한다. 배포본에서는 `Hwik.exe -m hwik --uninstall`(제거)과 `--selftest`(점검)에도 쓴다."""
import sys


def _run() -> int:
    if "--uninstall" in sys.argv[1:]:
        from hwik.ui.setup_dialog import run_uninstall_dialog

        return run_uninstall_dialog()
    if "--selftest" in sys.argv[1:]:
        from hwik.selftest import run_selftest

        return run_selftest()
    from hwik.app import main

    return main()


sys.exit(_run())
