"""화면이 "연결 켜기 / 끄기 / 보낼 것 올리기"만 부르면 되도록 암호 만들기, 주소 찾기, 서버 켜기를 묶는다.

켤 때마다 새 암호와 빈 "보낼 것 상자"를 만든다. 끄면 그 암호도, 올려 둔 것도 다시 쓸 수 없다.
화면 부품을 쓰지 않는다.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from hwik.core import netinfo
from hwik.core.errors import NoNetworkError, TransferError
from hwik.core.events import Listener
from hwik.core.outbox import Outbox
from hwik.core.server import ServerConfig, TransferServer
from hwik.core.session import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Connection:
    """켜진 연결. url에는 암호가 들어 있어 기록에 찍히지 않게 감춘다."""

    address: str
    port: int
    url: str = field(repr=False)


class TransferService:
    def __init__(self, listener: Listener | None = None) -> None:
        self._listener = listener
        self._server: TransferServer | None = None
        self._outbox: Outbox | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self, save_dir: Path) -> Connection:
        """서버를 켜고 휴대폰이 열 주소를 돌려준다. 이미 켜져 있으면 끄고 새 암호로 다시 켠다."""
        with self._lock:
            self._stop_locked()
            address = netinfo.lan_ip()
            if address is None:
                raise NoNetworkError(
                    "와이파이에 연결돼 있지 않습니다. 휴대폰과 같은 와이파이에 연결한 뒤 다시 시도해 주세요. "
                    "와이파이가 없으면 PC를 휴대폰 핫스팟에 연결해도 됩니다."
                )
            session, outbox = Session.new(), Outbox()
            server = TransferServer(
                session, ServerConfig(host=address, save_dir=save_dir), listener=self._listener, outbox=outbox
            )
            server.start()
            self._server, self._outbox = server, outbox
            return Connection(address=address, port=server.port, url=netinfo.phone_url(address, server.port, session))

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def offer_files(self, paths: Iterable[Path]) -> int:
        """휴대폰이 받아 갈 수 있게 파일을 올려 둔다. 올린 개수를 돌려준다(폴더처럼 못 올리는 것은 건너뛴다)."""
        outbox = self._require_outbox()
        count = 0
        for path in paths:
            try:
                outbox.add_file(path)
            except TransferError as err:
                logger.info("보낼 수 없는 항목을 건너뜁니다: %s", err)
                continue
            count += 1
        return count

    def offer_text(self, text: str) -> None:
        """휴대폰이 복사해 갈 수 있게 글자를 올려 둔다."""
        self._require_outbox().add_text(text)

    def _require_outbox(self) -> Outbox:
        outbox = self._outbox
        if outbox is None:
            raise TransferError("휴대폰과 연결돼 있지 않습니다. 창을 열어 QR을 먼저 띄워 주세요.")
        return outbox

    def _stop_locked(self) -> None:
        server, self._server, self._outbox = self._server, None, None
        if server is not None:
            server.stop()
