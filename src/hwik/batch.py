"""한 번에 받은 파일 묶음: 진행 계산과 화면 문구.

휴대폰은 고른 파일을 하나씩 차례로 보낸다. PC는 잠깐 사이를 두고 이어서 온 파일을 한 묶음으로 본다.
화면 부품을 쓰지 않는 순수 계산이라 그대로 시험할 수 있다. 묶음은 바꾸지 않고 늘 새로 만든다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Literal

from hwik.core.events import (
    TransferEvent,
    TransferFailed,
    TransferFinished,
    TransferProgress,
    TransferStarted,
)

BATCH_GAP_SECONDS = 1.5  # 이만큼 조용하면 묶음이 끝난 것으로 본다
SPEED_SETTLE_SECONDS = 0.8  # 처음 잠깐은 속도가 들쭉날쭉해 보여 주지 않는다
KB = 1024
MB = KB * 1024
GB = MB * 1024
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".gif", ".bmp", ".avif", ".dng"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".3gp", ".m4v"})

Status = Literal["active", "done", "failed"]


@dataclass(frozen=True)
class Item:
    transfer_id: str
    name: str
    size: int
    received: int = 0
    status: Status = "active"
    path: Path | None = None
    message: str = ""


@dataclass(frozen=True)
class Batch:
    items: tuple[Item, ...] = ()
    started_at: float | None = None
    last_event_at: float | None = None
    upcoming_files: int = 0  # 가장 최근에 시작한 파일이 알려 준, 아직 오지 않은 파일 수와 크기
    upcoming_bytes: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def is_running(self) -> bool:
        return any(item.status == "active" for item in self.items)

    @property
    def total_bytes(self) -> int:
        # 받다 실패한 파일은 도착한 만큼만 센다: 그래야 나머지를 다 받았을 때 진행 표시가 끝까지 간다.
        return sum(item.received if item.status == "failed" else item.size for item in self.items)

    @property
    def received_bytes(self) -> int:
        return sum(item.received for item in self.items)

    @property
    def expected_bytes(self) -> int:
        """지금까지 온 파일에, 휴대폰이 더 보내겠다고 한 것까지 더한 크기."""
        return self.total_bytes + self.upcoming_bytes

    @property
    def expected_files(self) -> int:
        return len(self.items) + self.upcoming_files

    @property
    def progress(self) -> float:
        total = self.expected_bytes
        return min(self.received_bytes / total, 1.0) if total > 0 else 0.0

    @property
    def done_items(self) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.status == "done")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def saved_paths(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.done_items if item.path is not None)

    @property
    def last_failure_message(self) -> str:
        messages = [item.message for item in self.items if item.status == "failed"]
        return messages[-1] if messages else ""

    def is_settled(self, now: float) -> bool:
        """다 받고 나서 조용한 시간이 지나, 결과를 보여 줘도 되는지."""
        if self.is_empty or self.is_running or self.last_event_at is None:
            return False
        return now - self.last_event_at > BATCH_GAP_SECONDS

    def speed(self, now: float) -> float:
        """묶음이 시작된 뒤의 평균 속도(초당 바이트)."""
        if self.started_at is None or now <= self.started_at:
            return 0.0
        return self.received_bytes / (now - self.started_at)


def apply(batch: Batch, event: TransferEvent, now: float) -> Batch:
    """알림 하나를 반영한 새 묶음을 돌려준다."""
    if isinstance(event, TransferStarted):
        added = _add(batch, Item(event.transfer_id, event.name, event.size), now)
        return replace(added, upcoming_files=event.upcoming_files, upcoming_bytes=event.upcoming_bytes)
    if isinstance(event, TransferProgress):
        return _update(batch, event.transfer_id, now, received=event.received)
    if isinstance(event, TransferFinished):
        return _update(batch, event.transfer_id, now, received=event.size, status="done", path=event.path)
    if isinstance(event, TransferFailed):
        return _update(batch, event.transfer_id, now, status="failed", message=event.message)
    return batch


def _add(batch: Batch, item: Item, now: float) -> Batch:
    quiet_for = math.inf if batch.last_event_at is None else now - batch.last_event_at
    if not batch.is_running and quiet_for > BATCH_GAP_SECONDS:
        return Batch(items=(item,), started_at=now, last_event_at=now)
    return replace(batch, items=(*batch.items, item), last_event_at=now)


def _update(batch: Batch, transfer_id: str, now: float, **changes: object) -> Batch:
    if not any(item.transfer_id == transfer_id for item in batch.items):
        return batch
    items = tuple(
        replace(item, **changes) if item.transfer_id == transfer_id else item  # type: ignore[arg-type]
        for item in batch.items
    )
    return replace(batch, items=items, last_event_at=now)


def format_size(size: float) -> str:
    if size >= GB:
        return f"{size / GB:.1f}GB"
    if size >= MB:
        return f"{size / MB:.1f}MB"
    return f"{max(1, round(size / KB))}KB"


def format_remaining(seconds: float) -> str:
    if seconds < 5:
        return "곧 끝남"
    if seconds <= 55:
        return f"약 {math.ceil(seconds / 5) * 5}초 남음"
    return f"약 {math.ceil(seconds / 60)}분 남음"


def headline(batch: Batch) -> str:
    """상태판에 크게 보여 줄 글."""
    if batch.is_running:
        total = batch.expected_files
        return f"받는 중 {len(batch.items)} / {total}" if total > 1 else "받는 중"
    done = batch.done_items
    if not done:
        return "받지 못했습니다"
    if batch.failed_count:
        return f"{len(batch.items)}개 중 {len(done)}개만 받음"  # 한 줄에 들어가게 짧게
    return f"{_describe(done)} 받았습니다"


def _describe(items: tuple[Item, ...]) -> str:
    suffixes = {PurePath(item.name).suffix.lower() for item in items}
    if suffixes <= IMAGE_SUFFIXES:
        return f"사진 {len(items)}장"
    if suffixes <= VIDEO_SUFFIXES:
        return f"영상 {len(items)}개"
    return f"파일 {len(items)}개"


def detail(batch: Batch, now: float) -> str:
    """받는 동안 상태판 아래쪽에 보여 줄 글: 파일 이름, 속도, 남은 시간."""
    active = [item for item in batch.items if item.status == "active"]
    if not active:
        return ""
    lines = [active[-1].name]
    speed = batch.speed(now)
    if batch.started_at is not None and now - batch.started_at > SPEED_SETTLE_SECONDS and speed > 0:
        remaining = (batch.expected_bytes - batch.received_bytes) / speed
        lines.append(f"초당 {format_size(speed)} · {format_remaining(remaining)}")
    return "\n".join(lines)
