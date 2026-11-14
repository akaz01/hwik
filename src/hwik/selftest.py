"""배포본 점검: 빠진 부품이 다른 사람 PC가 아니라 만드는 자리에서 드러나게 한다.

`Hwik.exe -m hwik --selftest` 로 실행하고, 결과를 %TEMP%\\Hwik_selftest.txt 에 적는다. 종료 코드 0이면 통과.
"""
from __future__ import annotations

import importlib
import pkgutil
import secrets
import tempfile
import traceback
import urllib.request
from collections.abc import Callable
from pathlib import Path

import hwik
from hwik import APP_NAME

LOOPBACK = "127.0.0.1"
FETCH_SECONDS = 5


def _import_everything() -> str:
    names = [info.name for info in pkgutil.walk_packages(hwik.__path__, "hwik.") if info.name != "hwik.__main__"]
    for name in names:
        importlib.import_module(name)
    return f"모듈 {len(names)}개"


def _draw() -> str:
    from PySide6.QtWidgets import QApplication

    from hwik.tray import draw_icon
    from hwik.ui.stage import render_qr

    app = QApplication.instance() or QApplication([])
    icon = draw_icon(64)
    qr = render_qr(f"http://{LOOPBACK}:50000/t/{'a' * 22}/", 154, 1.0)
    if icon.isNull() or qr.isNull():
        raise RuntimeError("아이콘이나 QR을 그리지 못했습니다")
    del app
    return "아이콘·QR"


def _serve_phone_page() -> str:
    """서버를 실제로 켜고 휴대폰 화면을 받아 본다(화면 파일이 묶음에 들어 있는지까지 확인된다)."""
    from hwik.core.server import ServerConfig, TransferServer
    from hwik.core.session import AttemptLimiter, Session
    from hwik.core.transfer import ReceiveLimits

    token = secrets.token_urlsafe(16)
    with tempfile.TemporaryDirectory() as folder:
        config = ServerConfig(host=LOOPBACK, save_dir=Path(folder), limits=ReceiveLimits())
        server = TransferServer(
            Session(token=token), config, limiter=AttemptLimiter(max_failures=3, window_seconds=60), listener=None
        )
        server.start()
        try:
            sizes = []
            for name in ("", "app.css", "app.js"):
                url = f"http://{LOOPBACK}:{server.port}/t/{token}/{name}"
                with urllib.request.urlopen(url, timeout=FETCH_SECONDS) as reply:  # noqa: S310 - 자기 자신에게만
                    sizes.append(len(reply.read()))
        finally:
            server.stop()
    if min(sizes) == 0:
        raise RuntimeError("휴대폰 화면 파일이 비어 있습니다")
    return f"휴대폰 화면 {sum(sizes)}바이트"


def _heic_decoder() -> str:
    """아이폰 사진 해독 부품과 그 라이브러리(DLL)가 묶음에 들어 있는지."""
    import pi_heif

    return f"HEIC 해독 부품 {pi_heif.libheif_version()}"


def run_selftest() -> int:
    checks: list[Callable[[], str]] = [_import_everything, _draw, _serve_phone_page, _heic_decoder]
    lines = [f"{APP_NAME} {hwik.__version__} 점검"]
    failed = False
    for check in checks:
        try:
            lines.append(f"통과: {check()}")
        except Exception:  # 무엇이 빠졌는지 그대로 적어야 한다
            failed = True
            lines.append(f"실패: {check.__name__}\n{traceback.format_exc()}")
    report = Path(tempfile.gettempdir()) / f"{APP_NAME}_selftest.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
