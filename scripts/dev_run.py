"""개발용 실행 파일: PC 화면(3단계)이 생기기 전까지 서버를 켜고 QR을 브라우저에 띄운다.

쓰는 법: python scripts/dev_run.py <QR 화면을 쓸 폴더>
QR 화면 파일에는 암호가 든 주소가 들어가므로 프로젝트 밖 임시 폴더에 두고, 끝날 때 지운다.
"""
from __future__ import annotations

import logging
import sys
import time
import webbrowser
from pathlib import Path

import segno

from hwik.core import netinfo
from hwik.core.events import TransferEvent, TransferProgress
from hwik.core.server import ServerConfig, TransferServer
from hwik.core.session import Session

logger = logging.getLogger("dev_run")
SAVE_DIR = Path(__file__).resolve().parent.parent / "dev_received"
QR_PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>QR</title>
<body style="font-family:'Malgun Gothic',sans-serif;text-align:center;margin-top:48px">
<h1>휴대폰 카메라로 찍어 주세요</h1>{qr}<p>받은 파일 위치: {save_dir}</p></body></html>"""


def log_event(event: TransferEvent) -> None:
    if not isinstance(event, TransferProgress):
        logger.info("%s", event)


def main(qr_folder: Path) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stdout)
    address = netinfo.lan_ip()
    if address is None:
        logger.error("와이파이 주소를 찾지 못했습니다.")
        return 1
    session = Session.new()
    server = TransferServer(session, ServerConfig(host=address, save_dir=SAVE_DIR), listener=log_event)
    server.start()
    qr_file = qr_folder / "qr.html"
    qr = segno.make(netinfo.phone_url(address, server.port, session)).svg_inline(scale=9)
    qr_file.write_text(QR_PAGE.format(qr=qr, save_dir=SAVE_DIR), encoding="utf-8")
    webbrowser.open(qr_file.as_uri())
    logger.info("서버가 켜졌습니다. 끄려면 이 프로그램을 끝내세요.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        qr_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
