"""보낼 것 상자: PC 사용자가 휴대폰에 내주기로 고른 파일과 글자.

휴대폰은 여기 올라온 것만, 추측할 수 없는 번호로만 받아 갈 수 있다. PC의 경로로는 아무것도 꺼낼 수 없다.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from hwik.core.errors import TransferError

MAX_ITEMS = 50  # 넘으면 가장 오래된 것부터 내린다
MAX_TEXT_CHARS = 100_000
ID_BYTES = 16


@dataclass(frozen=True)
class FileOffer:
    item_id: str
    path: Path
    name: str
    size: int


@dataclass(frozen=True)
class TextOffer:
    item_id: str
    text: str = field(repr=False)  # 내용이 기록에 찍히지 않게


Offer = Union[FileOffer, TextOffer]


def _new_id() -> str:
    return secrets.token_urlsafe(ID_BYTES)


class Outbox:
    """여러 스레드(화면, 서버 요청)가 함께 쓴다. 내용이 바뀔 때마다 version이 1씩 오른다."""

    def __init__(self) -> None:
        self._items: tuple[Offer, ...] = ()
        self._version = 0
        self._lock = threading.Lock()

    def add_file(self, path: Path) -> FileOffer:
        try:
            if not path.is_file():
                raise TransferError("보낼 수 있는 파일이 아닙니다.")
            size = path.stat().st_size
        except OSError as err:
            raise TransferError("파일을 읽을 수 없습니다.") from err
        offer = FileOffer(item_id=_new_id(), path=path, name=path.name, size=size)
        self._append(offer)
        return offer

    def add_text(self, text: str) -> TextOffer:
        if not text.strip():
            raise TransferError("보낼 글자가 없습니다.")
        if len(text) > MAX_TEXT_CHARS:
            raise TransferError("글자가 너무 깁니다.")
        offer = TextOffer(item_id=_new_id(), text=text)
        self._append(offer)
        return offer

    def remove(self, item_id: str) -> None:
        with self._lock:
            remaining = tuple(item for item in self._items if item.item_id != item_id)
            if len(remaining) != len(self._items):
                self._items, self._version = remaining, self._version + 1

    def clear(self) -> None:
        with self._lock:
            if self._items:
                self._items, self._version = (), self._version + 1

    def find_file(self, item_id: str) -> FileOffer | None:
        with self._lock:
            for item in self._items:
                if isinstance(item, FileOffer) and secrets.compare_digest(
                    item.item_id.encode("utf-8"), item_id.encode("utf-8")
                ):
                    return item
        return None

    def snapshot(self) -> tuple[int, tuple[Offer, ...]]:
        with self._lock:
            return self._version, self._items

    def _append(self, offer: Offer) -> None:
        with self._lock:
            self._items = (*self._items, offer)[-MAX_ITEMS:]
            self._version += 1
