"""서버 켜기·끄기를 화면 대신 맡아 주는 서비스 시험."""
from __future__ import annotations

import http.client
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hwik.core import netinfo
from hwik.core.errors import NoNetworkError, TransferError
from hwik.service import TransferService

LOOPBACK = "127.0.0.1"


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[TransferService]:
    monkeypatch.setattr(netinfo, "lan_ip", lambda: LOOPBACK)
    running = TransferService()
    yield running
    running.stop()


def status_of(url: str) -> int:
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=5)
    try:
        connection.request("GET", parts.path)
        return connection.getresponse().status
    finally:
        connection.close()


def test_start_returns_address_the_phone_can_open(service: TransferService, tmp_path: Path) -> None:
    connection = service.start(tmp_path)

    assert connection.url.startswith(f"http://{LOOPBACK}:{connection.port}/t/")
    assert status_of(connection.url) == 200
    assert service.is_running


def test_stop_closes_the_address(service: TransferService, tmp_path: Path) -> None:
    connection = service.start(tmp_path)

    service.stop()

    assert not service.is_running
    with pytest.raises(OSError):
        status_of(connection.url)


def test_every_start_uses_a_new_password(service: TransferService, tmp_path: Path) -> None:
    first = service.start(tmp_path)
    service.stop()
    second = service.start(tmp_path)

    assert urlsplit(first.url).path != urlsplit(second.url).path


def test_starting_again_while_running_replaces_the_old_address(service: TransferService, tmp_path: Path) -> None:
    first = service.start(tmp_path)

    second = service.start(tmp_path)

    assert status_of(second.url) == 200
    assert first.port != second.port or status_of(first.url) == 403


def test_start_without_wifi_gives_readable_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(netinfo, "lan_ip", lambda: None)
    service = TransferService()

    with pytest.raises(NoNetworkError, match="와이파이"):
        service.start(tmp_path)

    assert not service.is_running


def body_of(url: str, sub_path: str) -> bytes:
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=5)
    try:
        connection.request("GET", parts.path + sub_path)
        return connection.getresponse().read()
    finally:
        connection.close()


def test_offered_files_and_text_become_visible_to_the_phone(service: TransferService, tmp_path: Path) -> None:
    connection = service.start(tmp_path / "received")
    document = tmp_path / "보고서.pdf"
    document.write_bytes(b"%PDF")

    count = service.offer_files([document, tmp_path, tmp_path / "없는 파일.txt"])
    service.offer_text("붙여넣을 글자")

    state = body_of(connection.url, "state").decode("utf-8")
    assert count == 1
    assert "보고서.pdf" in state and "붙여넣을 글자" in state


def test_offering_without_connection_gives_readable_error(tmp_path: Path) -> None:
    idle = TransferService()

    with pytest.raises(TransferError, match="연결"):
        idle.offer_files([tmp_path])
    with pytest.raises(TransferError, match="연결"):
        idle.offer_text("글자")


def test_offers_do_not_survive_a_new_connection(service: TransferService, tmp_path: Path) -> None:
    service.start(tmp_path)
    service.offer_text("지난 연결의 글자")

    connection = service.start(tmp_path)

    assert "지난 연결의 글자" not in body_of(connection.url, "state").decode("utf-8")


def test_stop_before_start_is_safe() -> None:
    TransferService().stop()


def test_connection_repr_hides_password(service: TransferService, tmp_path: Path) -> None:
    connection = service.start(tmp_path)

    assert urlsplit(connection.url).path.split("/")[2] not in repr(connection)
