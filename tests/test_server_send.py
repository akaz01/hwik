"""PC → 휴대폰 파일 내려받기와 글자 주고받기 시험."""
from __future__ import annotations

import http.client
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

import pytest

from hwik.core.events import FileSent, TextReceived, TransferEvent
from hwik.core.outbox import Outbox
from hwik.core.server import MAX_TEXT_BYTES, ServerConfig, TransferServer
from hwik.core.session import Session

TOKEN = "test-token-0123456789"
LOOPBACK = "127.0.0.1"


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))


class Recorder:
    def __init__(self) -> None:
        self.events: list[TransferEvent] = []

    def __call__(self, event: TransferEvent) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[Any]:
        return [event for event in self.events if isinstance(event, kind)]


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def box() -> Outbox:
    return Outbox()


@pytest.fixture
def server(tmp_path: Path, recorder: Recorder, box: Outbox) -> Iterator[TransferServer]:
    running = TransferServer(
        Session(token=TOKEN),
        ServerConfig(host=LOOPBACK, save_dir=tmp_path / "received"),
        listener=recorder,
        outbox=box,
    )
    running.start()
    yield running
    running.stop()


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "보낼 것" / "여행 사진.png"
    path.parent.mkdir()
    path.write_bytes(b"picture-bytes")
    return path


def send(
    server: TransferServer,
    method: str,
    sub_path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    token: str = TOKEN,
) -> Reply:
    connection = http.client.HTTPConnection(LOOPBACK, server.port, timeout=5)
    try:
        connection.putrequest(method, f"/t/{token}/{sub_path}")
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        reply_headers = {name.lower(): value for name, value in response.getheaders()}
        return Reply(response.status, reply_headers, response.read())
    finally:
        connection.close()


def post_text(server: TransferServer, body: bytes, **extra: str) -> Reply:
    return send(server, "POST", "text", body, {"Content-Length": str(len(body)), **extra})


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 3
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("기다린 일이 일어나지 않았다")
        time.sleep(0.02)


# ── 보낼 것 목록 ──


def test_state_is_empty_at_first(server: TransferServer) -> None:
    reply = send(server, "GET", "state")

    assert reply.status == 200
    assert reply.json() == {"ok": True, "version": 0, "items": []}


def test_state_lists_offered_files_and_texts_without_revealing_pc_paths(
    server: TransferServer, box: Outbox, photo: Path
) -> None:
    file_offer = box.add_file(photo)
    text_offer = box.add_text("붙여넣을 글자")

    reply = send(server, "GET", "state")

    assert reply.json() == {
        "ok": True,
        "version": 2,
        "items": [
            {"id": file_offer.item_id, "kind": "file", "name": "여행 사진.png", "size": 13},
            {"id": text_offer.item_id, "kind": "text", "text": "붙여넣을 글자"},
        ],
    }
    assert "보낼 것" not in reply.body.decode("utf-8")


def test_state_needs_the_password(server: TransferServer) -> None:
    assert send(server, "GET", "state", token="guess").status == 403


# ── 내려받기 ──


def test_download_gives_file_bytes_as_attachment(server: TransferServer, box: Outbox, photo: Path) -> None:
    offer = box.add_file(photo)

    reply = send(server, "GET", f"dl/{offer.item_id}")

    assert reply.status == 200
    assert reply.body == b"picture-bytes"
    assert reply.headers["content-length"] == "13"
    assert reply.headers["content-type"] == "application/octet-stream"
    assert reply.headers["x-content-type-options"] == "nosniff"
    disposition = reply.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"filename*=UTF-8''{quote('여행 사진.png')}" in disposition


def test_download_file_name_cannot_break_out_of_the_header(server: TransferServer, box: Outbox, tmp_path: Path) -> None:
    tricky = tmp_path / "a;b'c%d.txt"
    tricky.write_bytes(b"x")
    offer = box.add_file(tricky)

    disposition = send(server, "GET", f"dl/{offer.item_id}").headers["content-disposition"]

    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2
    assert f"filename*=UTF-8''{quote(tricky.name, safe='')}" in disposition


def test_download_tells_listener_the_file_was_sent(
    server: TransferServer, box: Outbox, photo: Path, recorder: Recorder
) -> None:
    offer = box.add_file(photo)

    send(server, "GET", f"dl/{offer.item_id}")

    wait_until(lambda: bool(recorder.of(FileSent)))
    sent = recorder.of(FileSent)[0]
    assert (sent.name, sent.size, sent.client) == ("여행 사진.png", 13, LOOPBACK)


def test_large_download_arrives_intact(server: TransferServer, box: Outbox, tmp_path: Path) -> None:
    data = bytes(range(256)) * 12_000  # 약 3MB
    big = tmp_path / "big.bin"
    big.write_bytes(data)
    offer = box.add_file(big)

    assert send(server, "GET", f"dl/{offer.item_id}").body == data


@pytest.mark.parametrize("sub_path", ["dl/unknown", "dl/", "dl", "dl/../state", "dl/a/b"])
def test_download_of_unknown_item_is_not_found(server: TransferServer, sub_path: str) -> None:
    assert send(server, "GET", sub_path).status == 404


def test_text_item_cannot_be_downloaded_as_file(server: TransferServer, box: Outbox) -> None:
    offer = box.add_text("글자")

    assert send(server, "GET", f"dl/{offer.item_id}").status == 404


def test_download_needs_the_password(server: TransferServer, box: Outbox, photo: Path) -> None:
    offer = box.add_file(photo)

    assert send(server, "GET", f"dl/{offer.item_id}", token="guess").status == 403


def test_download_of_removed_item_is_not_found(server: TransferServer, box: Outbox, photo: Path) -> None:
    offer = box.add_file(photo)
    box.remove(offer.item_id)

    assert send(server, "GET", f"dl/{offer.item_id}").status == 404


def test_download_of_file_deleted_on_pc_gives_readable_message(
    server: TransferServer, box: Outbox, photo: Path, recorder: Recorder
) -> None:
    offer = box.add_file(photo)
    photo.unlink()

    reply = send(server, "GET", f"dl/{offer.item_id}")

    assert reply.status == 404
    assert reply.json()["ok"] is False
    assert recorder.of(FileSent) == []


# ── 글자 보내기(휴대폰 → PC) ──


def test_text_from_phone_reaches_listener(server: TransferServer, recorder: Recorder) -> None:
    reply = post_text(server, "PC에 붙여넣을 글자\n둘째 줄".encode())

    assert reply.status == 200
    assert reply.json() == {"ok": True}
    received = recorder.of(TextReceived)[0]
    assert (received.text, received.client) == ("PC에 붙여넣을 글자\n둘째 줄", LOOPBACK)


def test_text_event_repr_does_not_show_the_text(server: TransferServer, recorder: Recorder) -> None:
    post_text(server, "비밀번호 1234".encode())

    assert "1234" not in repr(recorder.of(TextReceived)[0])


@pytest.mark.parametrize("body", [b"", b"   \n", b"\xff\xfe broken"])
def test_blank_or_broken_text_is_refused(server: TransferServer, recorder: Recorder, body: bytes) -> None:
    assert post_text(server, body).status == 400
    assert recorder.of(TextReceived) == []


def test_text_over_limit_is_refused(server: TransferServer, recorder: Recorder) -> None:
    reply = send(server, "POST", "text", b"", {"Content-Length": str(MAX_TEXT_BYTES + 1)})

    assert reply.status == 413
    assert recorder.of(TextReceived) == []


def test_text_without_length_is_refused(server: TransferServer) -> None:
    assert send(server, "POST", "text").status == 411


def test_text_from_another_site_is_refused(server: TransferServer, recorder: Recorder) -> None:
    assert post_text(server, b"hello", Origin="http://evil.example").status == 403
    assert recorder.of(TextReceived) == []


def test_text_with_wrong_password_is_refused(server: TransferServer, recorder: Recorder) -> None:
    reply = send(server, "POST", "text", b"hello", {"Content-Length": "5"}, token="guess")

    assert reply.status == 403
    assert recorder.of(TextReceived) == []


def test_text_cut_off_midway_is_dropped_not_delivered_short(server: TransferServer, recorder: Recorder) -> None:
    import socket

    with socket.create_connection((LOOPBACK, server.port), timeout=5) as phone:
        head = f"POST /t/{TOKEN}/text HTTP/1.1\r\nHost: {LOOPBACK}:{server.port}\r\nContent-Length: 100\r\n\r\n"
        phone.sendall(head.encode() + b"hello, world")  # 100바이트라고 하고 12바이트만 보낸 뒤 끊는다
        phone.shutdown(socket.SHUT_WR)
        phone.settimeout(5)
        try:
            while phone.recv(4096):
                pass
        except OSError:
            pass

    time.sleep(0.2)
    assert recorder.of(TextReceived) == []


def test_state_skips_the_list_when_phone_already_has_this_version(server: TransferServer, box: Outbox) -> None:
    box.add_text("PC에서 복사한 글자")
    first = send(server, "GET", "state").json()

    again = send(server, "GET", "state", headers={"X-Seen": str(first["version"])}).json()
    stale = send(server, "GET", "state", headers={"X-Seen": "0"}).json()

    assert again == {"ok": True, "version": first["version"]}  # 같은 글자를 1~2초마다 다시 흘리지 않는다
    assert stale["items"][0]["text"] == "PC에서 복사한 글자"


def test_too_many_texts_in_a_row_are_refused(server: TransferServer, recorder: Recorder) -> None:
    replies = [post_text(server, f"글자 {n}".encode()).status for n in range(8)]

    assert replies[:5] == [200] * 5
    assert 429 in replies[5:]
    assert len(recorder.of(TextReceived)) == 5


def test_connection_that_dribbles_its_headers_is_cut_off(
    server: TransferServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    from hwik.core import server as server_module

    monkeypatch.setattr(server_module, "HEADER_DEADLINE_SECONDS", 0.3)
    with socket.create_connection((LOOPBACK, server.port), timeout=5) as slow:
        slow.sendall(b"GET /t/")  # 요청을 끝내지 않고 붙잡고만 있는다
        slow.settimeout(3)
        started = time.monotonic()
        try:
            closed = slow.recv(4096) == b""
        except OSError:
            closed = True

    assert closed and time.monotonic() - started < 2.5


def test_header_deadline_does_not_cut_a_slow_body(
    server: TransferServer, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    from hwik.core import server as server_module

    monkeypatch.setattr(server_module, "HEADER_DEADLINE_SECONDS", 0.3)
    with socket.create_connection((LOOPBACK, server.port), timeout=5) as phone:
        head = f"POST /t/{TOKEN}/text HTTP/1.1\r\nHost: {LOOPBACK}:{server.port}\r\nContent-Length: 10\r\n\r\n"
        phone.sendall(head.encode() + b"hello")
        time.sleep(0.7)  # 머리글 기한보다 오래 걸리는 본문
        phone.sendall(b"world")
        reply = phone.recv(4096)

    assert b" 200 " in reply.split(b"\r\n", 1)[0]
    assert [event.text for event in recorder.of(TextReceived)] == ["helloworld"]
