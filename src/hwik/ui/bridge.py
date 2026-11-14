"""서버 스레드에서 온 전송 알림을 화면 스레드로 넘긴다."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from hwik.core.events import TransferEvent


class EventBridge(QObject):
    """서버에 Listener로 넘기는 물건. 불리면 신호를 보내고, Qt가 화면 스레드에서 받게 해 준다.

    알림에는 "몇 번째 연결에서 온 것인지"(generation)를 붙인다. 창을 닫았다 다시 열면 번호가 바뀌므로,
    지난 연결에서 늦게 도착한 알림을 받는 쪽이 가려낼 수 있다.
    """

    received = Signal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.generation = 0

    def __call__(self, event: TransferEvent) -> None:
        self.received.emit(self.generation, event)
