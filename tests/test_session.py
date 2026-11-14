"""일회용 암호(세션)와 틀린 암호 횟수 제한 시험."""
from __future__ import annotations

import dataclasses

import pytest

from hwik.core.session import AttemptLimiter, Session

MIN_TOKEN_LENGTH = 22  # 128비트를 주소에 쓸 수 있는 글자로 바꾼 길이


def test_new_sessions_get_long_tokens_that_differ() -> None:
    first, second = Session.new(), Session.new()

    assert len(first.token) >= MIN_TOKEN_LENGTH
    assert first.token != second.token


def test_sub_path_returns_rest_of_path_when_token_matches() -> None:
    session = Session(token="abc123")

    assert session.sub_path("/t/abc123/") == ""
    assert session.sub_path("/t/abc123/up") == "up"
    assert session.sub_path("/t/abc123/files/a.png") == "files/a.png"


@pytest.mark.parametrize(
    "path",
    ["/t/wrong/", "/t/abc123", "/abc123/", "/", "", "/t//", "/x/abc123/", "/t/abc1234/", "/t/ABC123/"],
)
def test_sub_path_returns_none_when_token_is_missing_or_wrong(path: str) -> None:
    session = Session(token="abc123")

    assert session.sub_path(path) is None


def test_sub_path_handles_non_ascii_guess_without_error() -> None:
    session = Session(token="abc123")

    assert session.sub_path("/t/암호/") is None


def test_is_token_path_tells_guesses_from_other_requests() -> None:
    assert Session.is_token_path("/t/whatever/") is True
    assert Session.is_token_path("/favicon.ico") is False


def test_repr_does_not_reveal_token() -> None:
    session = Session(token="secret-value")

    assert "secret-value" not in repr(session)


def test_session_cannot_be_changed() -> None:
    session = Session(token="abc123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        session.token = "other"  # type: ignore[misc]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_client_after_too_many_failures() -> None:
    limiter = AttemptLimiter(max_failures=3, window_seconds=60, clock=FakeClock())

    for _ in range(3):
        assert limiter.is_blocked("10.0.0.5") is False
        limiter.record_failure("10.0.0.5")

    assert limiter.is_blocked("10.0.0.5") is True
    assert limiter.is_blocked("10.0.0.6") is False


def test_limiter_forgets_failures_after_window() -> None:
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=2, window_seconds=60, clock=clock)
    limiter.record_failure("10.0.0.5")
    limiter.record_failure("10.0.0.5")

    clock.now += 61

    assert limiter.is_blocked("10.0.0.5") is False


def test_limiter_does_not_grow_without_bound() -> None:
    limiter = AttemptLimiter(max_failures=3, window_seconds=60, clock=FakeClock(), max_clients=10)

    for index in range(50):
        limiter.record_failure(f"10.0.0.{index}")

    assert limiter.tracked_clients() <= 10
