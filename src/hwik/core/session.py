"""일회용 암호와 틀린 암호 횟수 제한.

휴대폰 주소는 ``/t/<암호>/...`` 꼴이다. 암호는 프로그램을 켤 때마다 새로 만들고 어디에도 저장하지 않는다.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

TOKEN_BYTES = 16  # 128비트. 주소에 쓸 수 있는 글자로 바꾸면 22자
TOKEN_PATH_PREFIX = "/t/"
DEFAULT_MAX_FAILURES = 20
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MAX_CLIENTS = 1000


@dataclass(frozen=True)
class Session:
    """한 번 켜져 있는 동안만 쓰는 암호."""

    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("암호가 비어 있습니다.")

    @classmethod
    def new(cls) -> Session:
        return cls(token=secrets.token_urlsafe(TOKEN_BYTES))

    @staticmethod
    def is_token_path(url_path: str) -> bool:
        """암호를 넣어 보려는 주소인지(맞는지는 따지지 않는다)."""
        return url_path.startswith(TOKEN_PATH_PREFIX)

    def sub_path(self, url_path: str) -> str | None:
        """암호가 맞으면 그 뒤 경로를, 아니면 None을 돌려준다."""
        if not self.is_token_path(url_path):
            return None
        candidate, slash, rest = url_path[len(TOKEN_PATH_PREFIX):].partition("/")
        if not slash:
            return None
        # 글자 수와 관계없이 같은 시간이 걸리게 비교한다(시간 차이로 암호를 추측하지 못하게).
        if not secrets.compare_digest(candidate.encode("utf-8"), self.token.encode("utf-8")):
            return None
        return rest


class AttemptLimiter:
    """같은 기기가 짧은 시간에 틀린 암호를 너무 많이 넣는지 센다."""

    def __init__(
        self,
        max_failures: int = DEFAULT_MAX_FAILURES,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._clock = clock
        self._max_clients = max_clients
        self._failures: dict[str, tuple[float, ...]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, client: str) -> bool:
        with self._lock:
            return len(self._recent(client, self._clock())) >= self._max_failures

    def record_failure(self, client: str) -> None:
        with self._lock:
            now = self._clock()
            recent = (*self._recent(client, now), now)[-self._max_failures:]
            if client not in self._failures:
                self._make_room(now)
            self._failures[client] = recent

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._failures)

    def _recent(self, client: str, now: float) -> tuple[float, ...]:
        oldest_allowed = now - self._window_seconds
        return tuple(moment for moment in self._failures.get(client, ()) if moment > oldest_allowed)

    def _make_room(self, now: float) -> None:
        """기억하는 기기 수가 끝없이 늘지 않게 지난 기록과 가장 오래된 기록을 버린다."""
        if len(self._failures) < self._max_clients:
            return
        self._failures = {
            client: recent for client in self._failures if (recent := self._recent(client, now))
        }
        while len(self._failures) >= self._max_clients:
            del self._failures[next(iter(self._failures))]
