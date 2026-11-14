"""전송 중에 일어나는 일을 화면 쪽에 알리는 알림.

서버는 화면을 모른다. 화면(트레이·창)은 Listener 하나를 넘겨주고 이 알림들을 받는다.
Listener는 서버의 요청 스레드에서 불리므로, 받는 쪽이 자기 화면 스레드로 넘겨야 한다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class TransferStarted:
    transfer_id: str
    name: str
    size: int
    client: str
    upcoming_files: int = 0  # 휴대폰이 이 파일 뒤에 더 보내겠다고 알린 개수(화면 표시용, 믿을 값은 아님)
    upcoming_bytes: int = 0


@dataclass(frozen=True)
class TransferProgress:
    transfer_id: str
    received: int
    total: int


@dataclass(frozen=True)
class TransferFinished:
    transfer_id: str
    path: Path
    size: int


@dataclass(frozen=True)
class TransferFailed:
    transfer_id: str
    name: str
    message: str


@dataclass(frozen=True)
class FileSent:
    """PC가 내준 파일을 휴대폰이 끝까지 받아 갔다."""

    name: str
    size: int
    client: str


@dataclass(frozen=True)
class TextReceived:
    """휴대폰이 글자를 보냈다."""

    text: str = field(repr=False)  # 내용이 기록에 찍히지 않게
    client: str = ""


TransferEvent = Union[TransferStarted, TransferProgress, TransferFinished, TransferFailed, FileSent, TextReceived]
Listener = Callable[[TransferEvent], None]
